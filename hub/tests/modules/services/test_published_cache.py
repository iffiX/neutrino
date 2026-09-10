"""The published-list cache: gathering, the fingerprint, and recomposing."""

import concurrent.futures
import threading

import pytest

from neutrino_hub.modules.devices.desired_state import DesiredStateStore
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


MAC = "aa:bb:cc:dd:ee:ff"


class StubSessions:
    """The live sockets as the cache reads them: the last report per device."""

    def __init__(self, reports=None):
        self._reports = dict(reports or {})

    def reports(self):
        return dict(self._reports)


def report(**modules) -> dict:
    return {
        "modules": {
            name: {"state": "installed", "code": "", "params": {}, "details": details}
            for name, details in modules.items()
        }
    }


def cache(
    units: StubUnits,
    *,
    sessions=None,
    addresses=None,
    on_fingerprint_change=None,
    executor=None,
) -> PublishedServiceCache:
    return PublishedServiceCache(
        declared_probe=StubProbe(),
        served_models=StubServedModels(),
        units=units,
        agent_sessions=sessions,
        device_addresses=addresses,
        desired_states=DesiredStateStore(),
        on_fingerprint_change=on_fingerprint_change,
        executor=executor,
    )


def hosting_samba() -> None:
    store = DesiredStateStore()
    store.set_enabled(MAC, "samba", True)
    store.write(
        MAC, "samba", {"shares": [{"name": "media", "path": "/srv"}], "users": []}
    )


def test_a_devices_samba_share_is_published_at_the_devices_address(box):
    hosting_samba()
    sessions = StubSessions({MAC: report(samba={"is_active": True})})

    entries, fingerprint = cache(
        StubUnits(), sessions=sessions, addresses={MAC: "192.168.100.7"}
    ).entries()

    assert [e["id"] for e in entries] == ["samba_aa-bb-cc-dd-ee-ff_media"]
    assert entries[0]["payload"]["host"] == "192.168.100.7"
    assert entries[0]["is_healthy"] is True
    assert len(fingerprint) == 16


def test_a_module_that_is_installed_but_switched_off_publishes_nothing(box):
    DesiredStateStore().write(
        MAC, "samba", {"shares": [{"name": "media", "path": "/srv"}], "users": []}
    )
    sessions = StubSessions({MAC: report(samba={"is_active": True})})

    entries, _ = cache(
        StubUnits(), sessions=sessions, addresses={MAC: "10.0.0.7"}
    ).entries()

    assert entries == []


def test_a_module_that_is_on_but_not_installed_publishes_nothing(box):
    hosting_samba()
    sessions = StubSessions(
        {MAC: {"modules": {"samba": {"state": "absent", "details": {}}}}}
    )

    entries, _ = cache(
        StubUnits(), sessions=sessions, addresses={MAC: "10.0.0.7"}
    ).entries()

    assert entries == []


def test_a_devices_gitea_and_containers_come_from_its_report(box, monkeypatch):
    store = DesiredStateStore()
    store.set_enabled(MAC, "gitea", True)
    store.set_enabled(MAC, "podman", True)
    monkeypatch.setattr(
        PublishedServiceCache, "_is_answering", lambda self, url: url.endswith(":3000/")
    )
    sessions = StubSessions(
        {
            MAC: report(
                gitea={"is_running": True, "url": "http://192.168.100.7:3000/"},
                podman={
                    "containers": [
                        {
                            "name": "web",
                            "image": "nginx",
                            "is_running": True,
                            "host_ports": [8080],
                        }
                    ]
                },
            )
        }
    )

    entries, _ = cache(
        StubUnits(), sessions=sessions, addresses={MAC: "192.168.100.7"}
    ).entries()

    by_id = {e["id"]: e for e in entries}
    assert by_id["gitea_aa-bb-cc-dd-ee-ff"]["is_healthy"] is True
    assert by_id["gitea_aa-bb-cc-dd-ee-ff"]["payload"] == {
        "url": "http://192.168.100.7:3000/"
    }
    assert by_id["podman_aa-bb-cc-dd-ee-ff_web_8080"]["payload"] == {
        "host": "192.168.100.7",
        "port": 8080,
    }


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
    """A module hosted on the hub box's own agent sits at a hub address."""
    hosting_samba()
    sessions = StubSessions({MAC: report(samba={"is_active": True})})

    resolved = cache(
        StubUnits(), sessions=sessions, addresses={MAC: "192.168.100.1"}
    ).entries_for("192.168.93.1")

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


class ChangeCounter:
    """Counts the times the cache said its list composes differently."""

    def __init__(self):
        self.count = 0

    def __call__(self) -> None:
        self.count += 1


def test_a_list_that_composes_differently_says_so_once(box, monkeypatch, tmp_path):
    binary = tmp_path / "cli-proxy-api"
    binary.write_text("")
    monkeypatch.setattr(published_module, "CLIPROXYAPI_BINARY_PATH", binary)
    changes = ChangeCounter()
    held = cache(StubUnits({"cliproxyapi": True}), on_fingerprint_change=changes)

    held.entries()
    assert changes.count == 1

    held.expire()
    held.entries()
    assert changes.count == 1

    write_config(
        "ai/providers.json",
        {
            "providers": [
                {"id": "p1", "name": "up", "kind": "anthropic", "secret_id": "s1"}
            ]
        },
    )
    held.expire()
    held.entries()

    assert changes.count == 2


# --- recomposing on the events that move the list ---


class GatedProbe:
    """A probe that holds a refresh open until the test lets it go.

    Attributes:
        calls: How many refreshes reached it.
        entered: Set once a refresh is inside.
        gate: What a refresh waits on.
    """

    def __init__(self):
        self.calls = 0
        self.entered = threading.Event()
        self.gate = threading.Event()

    def results(self, services):
        self.calls += 1
        self.entered.set()
        self.gate.wait(5.0)
        return []


def worker() -> concurrent.futures.ThreadPoolExecutor:
    return concurrent.futures.ThreadPoolExecutor(max_workers=1)


def test_a_scheduled_refresh_composes_the_list_with_nobody_reading_it(box):
    """A device's report changing what it hosts is on screen before a read."""
    hosting_samba()
    sessions = StubSessions({MAC: report(samba={"is_active": True})})
    changes = ChangeCounter()
    executor = worker()
    held = cache(
        StubUnits(),
        sessions=sessions,
        addresses={MAC: "192.168.100.7"},
        on_fingerprint_change=changes,
        executor=executor,
    )

    held.schedule_refresh()
    executor.shutdown(wait=True)

    assert changes.count == 1
    assert [entry["id"] for entry in held.entries()[0]] == [
        "samba_aa-bb-cc-dd-ee-ff_media"
    ]


def test_schedules_arriving_while_one_runs_are_answered_by_one_more(box):
    probe = GatedProbe()
    executor = worker()
    held = PublishedServiceCache(
        declared_probe=probe,
        served_models=StubServedModels(),
        units=StubUnits(),
        desired_states=DesiredStateStore(),
        executor=executor,
    )

    held.schedule_refresh()
    assert probe.entered.wait(5.0)
    held.schedule_refresh()
    held.schedule_refresh()
    probe.gate.set()
    executor.shutdown(wait=True)

    assert probe.calls == 2
