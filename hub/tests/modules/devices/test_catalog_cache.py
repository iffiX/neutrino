"""The device catalog: two halves, hashed per scope."""

import json

import pytest

from neutrino_hub.modules.devices.catalog import DeviceCatalogCache
from neutrino_hub.modules.services.collector import hub_self_addresses, resolve_entries
from neutrino_hub.modules.services.host_scope import link_scope


class StubPublished:
    """A published-list cache answering from a fixed list."""

    def __init__(self):
        self.entries_list: list[dict] = []
        self.fingerprint = "fp1"

    def entries(self):
        return list(self.entries_list), self.fingerprint

    def entries_for(self, scope):
        return resolve_entries(
            self.entries_list,
            device_hosts={},
            hub_addresses=hub_self_addresses(["192.168.100.1"]),
            hub_host=scope.hub_address,
        )


def port_entry() -> dict:
    return {
        "id": "podman_web_8080",
        "type": "port",
        "title": "web",
        "payload": {"host": "192.168.100.1", "port": 8080},
        "is_healthy": True,
        "source": "module",
        "description": "published by container web (nginx)",
        "description_code": "container",
        "description_params": {"image": "nginx"},
        "modules": [],
        "record_id": None,
    }


@pytest.fixture()
def box(monkeypatch, tmp_path):
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    monkeypatch.setattr(
        "neutrino_hub.modules.devices.manifests.MANIFESTS_DIR", manifests
    )
    return manifests, StubPublished()


AGENT_ENTRY = {"install": {"method": "agent", "params": {}}}


def write_manifest(manifests, name: str, platforms: "dict | None" = None, **top):
    """One manifest of the loader's shape; an agent entry on Linux by default."""
    manifest = {
        "name": name,
        "title": name.title(),
        "description": f"The {name} module",
        "publisher": f"vendor/{name}",
        "platforms": platforms or {"linux": {"runner": name, **AGENT_ENTRY}},
        **top,
    }
    (manifests / f"{name}.json").write_text(json.dumps(manifest))


def test_the_catalog_has_two_halves_under_one_hash(box):
    manifests, published = box
    write_manifest(manifests, "forge")
    published.entries_list = [port_entry()]
    cache = DeviceCatalogCache(services=published)

    catalog, digest = cache.catalog(scope=link_scope("192.168.100.7"))

    assert set(catalog) == {"modules", "services"}
    assert catalog["modules"]["forge"]["title"] == "Forge"
    assert len(digest) == 16
    entry = catalog["services"][0]
    # Resolved for the asking device, and stripped to the wire fields.
    assert entry["payload"]["host"] == "192.168.100.7"
    assert "record_id" not in entry


def test_each_platform_gets_the_entry_its_platform_resolves_to(box):
    """A system entry on Linux and a hub entry on Windows: the row's runner,
    method, version and recipe follow the entry, and only the hub entry
    shows the licence and the source address, its version filled in."""
    manifests, published = box
    write_manifest(
        manifests,
        "engine",
        {
            "linux-debian": {
                "runner": "engine",
                "install": {
                    "method": "system",
                    "params": {
                        "version": "system",
                        "packages": ["engine"],
                        "verify": "engine --version",
                        "uninstall": {"packages": ["engine"], "post_uninstall": []},
                    },
                },
            },
            "windows-amd64": {
                "runner": "engine_machine",
                "install": {
                    "method": "hub",
                    "params": {
                        "version": "6.1.4",
                        "releases": [
                            {
                                "kind": "github",
                                "sources": ["https://api.example"],
                                "repository": "vendor/engine",
                                "tag": "v{version}",
                            }
                        ],
                        "artifacts": [
                            {
                                "name": "engine",
                                "kind": "msi",
                                "directory": "engine",
                                "file": "engine-{version}.msi",
                                "digest": "sha256:" + "c" * 64,
                                "sources": ["https://vendor.example/{file}"],
                            }
                        ],
                        "verify": "engine --version",
                        "uninstall": {"post_uninstall": [], "is_data_kept": True},
                    },
                },
            },
        },
        license="Apache-2.0",
        corresponding_source="https://github.com/vendor/engine/tree/v{version}",
    )
    cache = DeviceCatalogCache(services=published)
    scope = link_scope("192.168.100.7")
    fields = ("runner", "method", "version", "license", "corresponding_source")

    linux, _ = cache.catalog(
        scope=scope, platform={"os": "linux", "family": "debian", "arch": "amd64"}
    )
    windows, _ = cache.catalog(
        scope=scope, platform={"os": "windows", "family": "", "arch": "amd64"}
    )

    assert tuple(linux["modules"]["engine"][field] for field in fields) == (
        "engine",
        "system",
        "system",
        "",
        "",
    )
    assert tuple(windows["modules"]["engine"][field] for field in fields) == (
        "engine_machine",
        "hub",
        "6.1.4",
        "Apache-2.0",
        "https://github.com/vendor/engine/tree/v6.1.4",
    )
    assert windows["modules"]["engine"]["recipe"]["params"]["artifacts"] == [
        {
            "name": "engine",
            "kind": "msi",
            "digest": "sha256:" + "c" * 64,
            "directory": "engine",
        }
    ]
    assert windows["modules"]["engine"]["publisher"] == "vendor/engine"


def test_a_platform_the_manifest_names_no_entry_for_gets_no_recipe(box):
    manifests, published = box
    write_manifest(manifests, "forge")
    cache = DeviceCatalogCache(services=published)

    catalog, _ = cache.catalog(
        scope=link_scope("192.168.100.7"),
        platform={"os": "windows", "family": "", "arch": "amd64"},
    )

    row = catalog["modules"]["forge"]
    assert (row["runner"], row["method"], row["recipe"]) == ("", "", {})


def test_two_hosts_get_two_catalogs_with_two_hashes(box):
    _, published = box
    published.entries_list = [port_entry()]
    cache = DeviceCatalogCache(services=published)

    first, first_hash = cache.catalog(scope=link_scope("192.168.100.7"))
    second, second_hash = cache.catalog(scope=link_scope("192.168.93.5"))

    assert first["services"][0]["payload"]["host"] == "192.168.100.7"
    assert second["services"][0]["payload"]["host"] == "192.168.93.5"
    assert first_hash != second_hash


def test_the_composition_is_cached_per_host(box, monkeypatch):
    _, published = box
    cache = DeviceCatalogCache(services=published)
    first, first_hash = cache.catalog(scope=link_scope("192.168.100.7"))

    composed = []
    monkeypatch.setattr(
        StubPublished,
        "entries_for",
        lambda self, target_host: composed.append(target_host) or [],
    )
    again, again_hash = cache.catalog(scope=link_scope("192.168.100.7"))

    assert composed == []
    assert (again, again_hash) == (first, first_hash)


def test_a_moved_fingerprint_recomposes_for_every_host(box):
    _, published = box
    cache = DeviceCatalogCache(services=published)
    _, before = cache.catalog(scope=link_scope("192.168.100.7"))

    published.entries_list = [port_entry()]
    published.fingerprint = "fp2"
    catalog, after = cache.catalog(scope=link_scope("192.168.100.7"))

    assert after != before
    assert catalog["services"][0]["id"] == "podman_web_8080"
