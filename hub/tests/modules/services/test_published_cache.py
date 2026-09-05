"""The published-list cache: gathering, the fingerprint, and expiry."""

import pytest

from neutrino_hub.modules.services import published as published_module
from neutrino_hub.modules.services.config import DeclaredServiceRegistry
from neutrino_hub.modules.services.probe import DeclaredServiceHealth
from neutrino_hub.modules.services.published import PublishedServiceCache
from neutrino_hub.system.systemd_ctl import ServiceStatus
from neutrino_hub.utils.json_file import write_config
from tests.conftest import lan_entry


class StubProbe:
    def results(self, services):
        return [
            DeclaredServiceHealth(s.id, True, "2026-01-01T00:00:00+00:00", None)
            for s in services
        ]


class StubServedModels:
    def served(self, *, port, client_key):
        return True, ["claude-sonnet-4-5"]


class StubUnits:
    def __init__(self, active: dict[str, bool] | None = None):
        self.active = active or {}

    def status(self, name):
        is_active = self.active.get(name, False)
        return ServiceStatus(
            name=name,
            unit=f"{name}.service",
            is_installed=name in self.active,
            is_active=is_active,
            is_enabled=is_active,
        )


@pytest.fixture()
def box(monkeypatch, tmp_path):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr("neutrino_hub.utils.constants.UTILS_STATE_ROOT", state)
    monkeypatch.setattr(
        published_module, "CLIPROXYAPI_BINARY_PATH", tmp_path / "no-gateway"
    )
    write_config(
        "router/network.json",
        {
            "interfaces": [lan_entry("enp1s0", address="192.168.100.1")],
            "uplink_policy": "failover",
        },
    )
    return tmp_path


def cache(units: StubUnits) -> PublishedServiceCache:
    return PublishedServiceCache(
        declared_probe=StubProbe(), served_models=StubServedModels(), units=units
    )


def test_a_samba_module_share_is_published_with_the_unit_health(box):
    write_config(
        "samba/samba.json", {"shares": [{"name": "media", "path": "/srv"}], "users": []}
    )

    entries, fingerprint = cache(StubUnits({"samba": True})).entries()

    assert [e["id"] for e in entries] == ["samba_media"]
    assert entries[0]["payload"]["host"] == "192.168.100.1"
    assert entries[0]["is_healthy"] is True
    assert len(fingerprint) == 16


def test_a_declared_record_is_published_with_its_probe_health(box):
    DeclaredServiceRegistry().add(
        name="forge", kind="generic_tcp", host="10.0.0.5", port=9000
    )

    entries, _ = cache(StubUnits()).entries()

    assert len(entries) == 1
    assert entries[0]["type"] == "port"
    assert entries[0]["is_healthy"] is True


def test_the_composition_is_cached_until_expired(box):
    held = cache(StubUnits())
    _, before = held.entries()

    DeclaredServiceRegistry().add(
        name="forge", kind="generic_tcp", host="10.0.0.5", port=9000
    )
    assert held.entries()[0] == []

    held.expire()
    entries, after = held.entries()
    assert len(entries) == 1
    assert after != before


def test_entries_for_resolves_the_hub_hosts_for_one_caller(box):
    write_config(
        "samba/samba.json", {"shares": [{"name": "media", "path": "/srv"}], "users": []}
    )

    resolved = cache(StubUnits({"samba": True})).entries_for("192.168.93.1")

    assert resolved[0]["payload"]["host"] == "192.168.93.1"


def test_the_ai_entry_waits_for_a_fed_gateway(box, monkeypatch, tmp_path):
    binary = tmp_path / "cli-proxy-api"
    binary.write_text("")
    monkeypatch.setattr(published_module, "CLIPROXYAPI_BINARY_PATH", binary)

    held = cache(StubUnits({"cliproxyapi": True}))
    assert held.entries()[0] == []

    write_config(
        "ai/providers.json",
        {
            "providers": [
                {"id": "p1", "name": "up", "kind": "anthropic", "secret_id": "s1"}
            ]
        },
    )
    held.expire()
    entries, _ = held.entries()

    assert [e["id"] for e in entries] == ["ai"]
    # No client key on the box: the unit's own state is the health and the
    # model list stays empty.
    assert entries[0]["is_healthy"] is True
    assert entries[0]["payload"]["models"] == []
