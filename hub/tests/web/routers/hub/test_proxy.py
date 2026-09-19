"""The Proxy page's own routes, and the databases the split runs on.

A scan asks the two repositories what they publish and answers with that
beside what the box holds; an update is a job, because fetching two files and
restarting xray is longer than a request. Neither reaches the network here:
the fetcher is fed from a table and the databases land in a temporary
directory.
"""

import asyncio
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.modules.xray import geodata
from neutrino_hub.modules.xray.constants import (
    XRAY_GEODATA_SOURCE_PACKAGE,
    XRAY_GEODATA_SOURCE_RELEASE,
)
from neutrino_hub.modules.xray.node_config import XrayNodeList
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.routers.hub import proxy as proxy_router
from tests.conftest import unlock_vault
from tests.modules.xray.test_geodata import NEW, fake_release_fetcher

ROUTING = {
    "is_proxy_enabled": True,
    "is_overlay_proxy_enabled": False,
    "is_direct_fallback_enabled": False,
    "is_geoip_split_enabled": True,
    "direct_domains": [],
    "direct_ips": [],
    "is_local_proxy_enabled": False,
    "socks_ports": [],
    "remote_dns": {"address": "1.1.1.1", "port": 53},
    "direct_dns": {"address": "223.5.5.5", "port": 53},
}
NODES = {
    "nodes": [
        {
            "id": "hk1",
            "name": "Tokyo",
            "address": "203.0.113.10",
            "is_enabled": True,
            "protocol": "shadowsocks",
            "secret_id": "0" * 32,
            "shadowsocks": {"port": 5800, "method": "aes-256-gcm"},
        }
    ],
    "balancer": {
        "probe_url": "https://www.gstatic.com/generate_204",
        "probe_interval_s": 60,
    },
}


class FakeStream:
    def __init__(self, label: str):
        self.id = "task0001"
        self.label = label


class FakeTasks:
    """The registry, without an event loop under it."""

    def __init__(self):
        self.started = []
        self.running_stream = None

    def start(self, *, label, source):
        self.started.append((label, source))
        return FakeStream(label)

    def running(self, label: str):
        return self.running_stream


class FakeRuntime:
    """What these routes reach for, held in memory."""

    def __init__(self):
        self.files = {
            "xray/nodes.json": dict(NODES),
            "xray/routing.json": dict(ROUTING),
        }
        self.is_config_dirty = False
        self.listening_ports = _HeldPorts()
        self.tasks = FakeTasks()
        self.exit_controller = _ExitController()
        # What the next Apply raises, for the paths that have to survive one.
        self.apply_failure: "Exception | None" = None

    def node_list(self) -> XrayNodeList:
        return XrayNodeList.from_dict(self.files["xray/nodes.json"])

    def routing(self) -> dict:
        return dict(self.files["xray/routing.json"])

    async def apply_all(self) -> str:
        if self.apply_failure is not None:
            raise self.apply_failure
        return "applied 1 nodes"


class _HeldPorts:
    def ports(self, *, ignoring: str = "") -> set:
        return set()


class _ExitController:
    """The exit rounds as the Apply route reaches them."""

    def __init__(self):
        self.reassert_count = 0
        self.wake_count = 0

    def reassert(self) -> bool:
        self.reassert_count += 1
        return True

    def wake(self) -> None:
        self.wake_count += 1


class FakeApplier:
    """An xray that restarts without a machine under it."""

    calls = []

    def restart(self) -> None:
        FakeApplier.calls.append("restart")

    def confirm_running(self) -> None:
        FakeApplier.calls.append("confirm_running")


@pytest.fixture
def geodata_paths(monkeypatch, tmp_path):
    """The databases and the version file, in a temporary directory."""
    directory = tmp_path / "geodata"
    directory.mkdir()
    for name in ("geoip.dat", "geosite.dat"):
        (directory / name).write_bytes(b"carried by the package")
    version_path = directory / "version.json"
    bodies = {
        source.asset: f"{source.file_name} payload".encode("utf-8")
        for source in geodata.sources()
    }
    installed, fetch = geodata.installed, geodata.fetch
    monkeypatch.setattr(geodata, "_read", fake_release_fetcher(bodies))
    monkeypatch.setattr(
        geodata, "installed", lambda: installed(version_path=version_path)
    )
    monkeypatch.setattr(
        geodata,
        "fetch",
        lambda releases: fetch(
            releases, directory=directory, version_path=version_path
        ),
    )
    return directory, version_path


@pytest.fixture
def client(monkeypatch, tmp_path, geodata_paths):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    unlock_vault(monkeypatch, tmp_path)
    runtime = FakeRuntime()
    monkeypatch.setattr(
        proxy_router,
        "write_config",
        lambda name, data: runtime.files.__setitem__(name, data),
    )
    FakeApplier.calls = []
    monkeypatch.setattr(proxy_router, "XrayConfigApplier", FakeApplier)
    app = FastAPI()
    app.include_router(proxy_router.router)
    app.dependency_overrides[require_session] = lambda: None
    app.dependency_overrides[get_runtime] = lambda: runtime
    with TestClient(app) as opened:
        yield opened, runtime


def test_the_page_names_the_release_each_database_is(client):
    opened, _ = client

    view = opened.get("/api/hub/proxy").json()

    assert view["geodata"]["source"] == XRAY_GEODATA_SOURCE_PACKAGE
    assert view["geodata"]["geoip_version"] == geodata.baseline().releases["geoip.dat"]
    assert view["geodata"]["latest"] is None
    assert view["is_geoip_split_enabled"]


def test_saving_the_settings_answers_with_the_same_view(client):
    """The page replaces its state with what a write returns, so a write that
    left the databases out would blank the panel that names them."""
    opened, _ = client

    saved = opened.post("/api/hub/proxy/set", json=ROUTING).json()

    assert saved["geodata"] == opened.get("/api/hub/proxy").json()["geodata"]


def test_an_apply_pins_the_stored_exit_again(client):
    """A restart drops the override, and the unit reports the restart before
    xray's API inbound is listening. Waiting for the next round would leave
    the box on the balancer's own choice for up to an interval."""
    opened, runtime = client

    response = opened.post("/api/hub/proxy/apply")

    assert response.json()["is_applied"]
    assert runtime.exit_controller.reassert_count == 1
    assert runtime.exit_controller.wake_count == 1


def test_an_apply_that_was_refused_leaves_the_exit_alone(client):
    """xray is running what it was running before, its override included."""
    opened, runtime = client
    runtime.apply_failure = RuntimeError("xray rejected the rendered config")

    response = opened.post("/api/hub/proxy/apply")

    assert not response.json()["is_applied"]
    assert runtime.exit_controller.reassert_count == 0
    assert runtime.exit_controller.wake_count == 0


def test_a_scan_answers_with_what_is_held_and_what_is_published(client):
    opened, _ = client

    scanned = opened.post("/api/hub/proxy/geodata/scan").json()

    assert scanned["geoip_version"] == geodata.baseline().releases["geoip.dat"]
    assert scanned["latest"] == {
        "geoip_version": NEW["geoip.dat"],
        "geosite_version": NEW["geosite.dat"],
    }


def test_a_scan_that_cannot_reach_the_repositories_is_refused(client, monkeypatch):
    opened, _ = client

    def unreachable(url: str) -> bytes:
        raise OSError("no route to host")

    monkeypatch.setattr(geodata, "_read", unreachable)

    response = opened.post("/api/hub/proxy/geodata/scan")

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "geodata_unreachable"


def test_an_update_answers_with_the_job_that_does_it(client):
    opened, runtime = client

    started = opened.post("/api/hub/proxy/geodata/update").json()

    assert started == {"task_id": "task0001"}
    assert [label for label, _ in runtime.tasks.started] == [
        proxy_router.GEODATA_TASK_LABEL
    ]


def test_an_update_already_running_is_the_one_handed_back(client):
    """Both jobs write the same two files, so there is only ever one."""
    opened, runtime = client
    runtime.tasks.running_stream = FakeStream(proxy_router.GEODATA_TASK_LABEL)

    started = opened.post("/api/hub/proxy/geodata/update").json()

    assert started == {"task_id": "task0001"}
    assert runtime.tasks.started == []


def test_the_update_takes_both_files_and_restarts_xray_onto_them(client, geodata_paths):
    """xray reads its databases at start, so the files on the disk are not what
    the box splits on until the service has been restarted."""
    directory, version_path = geodata_paths

    lines = asyncio.run(_drained(proxy_router._geodata_update_source()))

    assert json.loads(version_path.read_text(encoding="utf-8"))["releases"] == NEW
    assert (directory / "geoip.dat").read_bytes() == b"geoip.dat payload"
    assert FakeApplier.calls == ["restart", "confirm_running"]
    assert geodata.installed().source == XRAY_GEODATA_SOURCE_RELEASE
    assert any(NEW["geoip.dat"] in line for line in lines)


async def _drained(source) -> list:
    """Every line a task source produces.

    Args:
        source: The async generator the task registry would drain.

    Returns:
        The lines, in order.
    """
    return [line async for line in source]
