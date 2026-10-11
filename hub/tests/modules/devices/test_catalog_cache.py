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


def write_manifest(manifests, name: str) -> None:
    (manifests / f"{name}.json").write_text(
        json.dumps(
            {
                "name": name,
                "title": name.title(),
                "installer": "hub",
                "source": f"vendor/{name}",
            }
        )
    )


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


def test_a_module_listing_components_hands_the_catalog_their_recipe_form(box):
    manifests, published = box
    (manifests / "codeg.json").write_text(
        json.dumps(
            {
                "name": "codeg",
                "title": "Codeg",
                "installer": "hub",
                "source": "vendor/codeg",
                "license": "MIT",
                "corresponding_source": "https://github.com/vendor/codeg",
                "platforms": {
                    "linux-amd64": {
                        "components": [
                            {
                                "name": "node",
                                "url": "https://nodejs.org/dist/node.tar.gz",
                                "sha256": "b" * 64,
                                "package_kind": "tar",
                                "directory": "node",
                            }
                        ],
                        "verify": "true",
                        "uninstall": {
                            "packages": [],
                            "post_uninstall": [],
                            "is_data_kept": True,
                        },
                    }
                },
            }
        )
    )
    cache = DeviceCatalogCache(services=published)
    platform = {"os": "linux", "family": "debian", "arch": "amd64"}

    catalog, _ = cache.catalog(scope=link_scope("192.168.100.7"), platform=platform)

    assert catalog["modules"]["codeg"]["components"] == [
        {"name": "node", "package_kind": "tar", "directory": "node", "sha256": "b" * 64}
    ]


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
