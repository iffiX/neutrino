"""The device catalog: two halves, one hash, rebuilt only on a moved stamp."""

import json
import os

import pytest

from neutrino_hub.modules.devices import catalog as catalog_module
from neutrino_hub.modules.devices.catalog import DeviceCatalogCache
from neutrino_hub.utils.json_file import write_config
from tests.conftest import lan_entry


class StubDockerCache:
    def __init__(self):
        self.batch = {}
        self.generation = 0

    def results(self, services):
        return dict(self.batch)


@pytest.fixture()
def box(monkeypatch, tmp_path):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr("neutrino_hub.utils.constants.UTILS_STATE_ROOT", state)
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    monkeypatch.setattr(
        "neutrino_hub.modules.functions.manifests.MANIFESTS_DIR", manifests
    )
    monkeypatch.setattr(catalog_module, "GITEA_BINARY_PATH", tmp_path / "no-gitea")
    monkeypatch.setattr(
        catalog_module, "CLIPROXYAPI_BINARY_PATH", tmp_path / "no-cli-proxy-api"
    )
    write_config(
        "router/network.json",
        {
            "interfaces": [lan_entry("enp1s0", address="192.168.100.1")],
            "uplink_policy": "failover",
        },
    )
    return tmp_path, manifests, StubDockerCache()


def write_manifest(manifests, name: str) -> None:
    (manifests / f"{name}.json").write_text(
        json.dumps({"name": name, "title": name.title()})
    )


def test_the_catalog_has_two_halves_under_one_hash(box):
    tmp_path, manifests, docker = box
    write_manifest(manifests, "anydesk")
    write_config(
        "samba/samba.json", {"shares": [{"name": "media", "path": "/srv"}], "users": []}
    )
    cache = DeviceCatalogCache(docker_cache=docker)

    catalog, digest = cache.catalog()

    assert set(catalog) == {"functions", "services"}
    assert catalog["functions"]["anydesk"]["title"] == "Anydesk"
    assert catalog["services"]["hub_share_media"]["host"] == "192.168.100.1"
    assert len(digest) == 16


def test_the_composition_is_cached_between_calls(box, monkeypatch):
    _, manifests, docker = box
    write_manifest(manifests, "anydesk")
    cache = DeviceCatalogCache(docker_cache=docker)
    cache.catalog()
    composed = []
    original = DeviceCatalogCache._compose
    monkeypatch.setattr(
        DeviceCatalogCache,
        "_compose",
        lambda self, declared: composed.append(True) or original(self, declared),
    )

    cache.catalog()

    assert composed == []


def test_an_edited_manifest_moves_the_hash(box):
    _, manifests, docker = box
    write_manifest(manifests, "anydesk")
    cache = DeviceCatalogCache(docker_cache=docker)
    _, before = cache.catalog()

    write_manifest(manifests, "todesk")
    _touch_apart(manifests / "todesk.json")
    catalog, after = cache.catalog()

    assert after != before
    assert "todesk" in catalog["functions"]


def test_a_changed_samba_config_moves_the_hash(box):
    tmp_path, _, docker = box
    cache = DeviceCatalogCache(docker_cache=docker)
    _, before = cache.catalog()

    write_config(
        "samba/samba.json", {"shares": [{"name": "media", "path": "/srv"}], "users": []}
    )
    _touch_apart(tmp_path / "samba/samba.json")
    catalog, after = cache.catalog()

    assert after != before
    assert "hub_share_media" in catalog["services"]


def test_a_moved_docker_generation_recomposes(box):
    _, _, docker = box
    cache = DeviceCatalogCache(docker_cache=docker)
    _, before = cache.catalog()

    from neutrino_hub.modules.services.docker import DockerContainer

    docker.batch = {
        "hub_podman": [
            DockerContainer(
                id="web",
                name="web",
                image="nginx",
                state="running",
                is_running=True,
                host_ports=[8080],
            )
        ]
    }
    docker.generation += 1
    catalog, after = cache.catalog()

    assert after != before
    assert "hub_podman_web_8080" in catalog["services"]


def test_the_ai_offer_waits_for_a_serving_gateway(box, monkeypatch, tmp_path):
    _, _, docker = box
    cache = DeviceCatalogCache(docker_cache=docker)

    catalog, _ = cache.catalog()
    assert "ai" not in catalog["services"]

    # The binary alone is not serving: it needs a provider or an account.
    binary = tmp_path / "cli-proxy-api"
    binary.write_text("")
    monkeypatch.setattr(catalog_module, "CLIPROXYAPI_BINARY_PATH", binary)
    catalog, _ = cache.catalog()
    assert "ai" not in catalog["services"]

    write_config(
        "ai/providers.json",
        {
            "providers": [
                {"id": "p1", "name": "up", "kind": "anthropic", "secret_id": "s1"}
            ]
        },
    )
    catalog, _ = cache.catalog()
    assert catalog["services"]["ai"]["kind"] == "ai"


def test_a_signed_in_account_also_counts_as_serving(box, monkeypatch, tmp_path):
    _, _, docker = box
    binary = tmp_path / "cli-proxy-api"
    binary.write_text("")
    monkeypatch.setattr(catalog_module, "CLIPROXYAPI_BINARY_PATH", binary)
    cache = DeviceCatalogCache(docker_cache=docker)
    catalog, _ = cache.catalog()
    assert "ai" not in catalog["services"]

    auth = tmp_path / "state/cliproxyapi/auth"
    auth.mkdir(parents=True)
    (auth / "claude-someone.json").write_text("{}")
    catalog, _ = cache.catalog()

    assert "ai" in catalog["services"]


def _touch_apart(path) -> None:
    """Move a file's mtime forward past filesystem timestamp granularity."""
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
