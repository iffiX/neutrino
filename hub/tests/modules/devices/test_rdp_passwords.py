"""The seat password a machine's desktop is shared behind.

The hub makes it: nobody types it and nobody is shown it. A machine
reporting the remote desktop host installed is given one, sealed under the
vault's data key in ``config/devices/<dir>/rdp.json``, and the composed
desired state is the only place it opens again. A locked vault seals
nothing and leaves the machine for its next report.
"""

import json
import string

import pytest

from neutrino_hub.modules.credentials.vault import seal_bytes
from neutrino_hub.modules.devices import agent_reports
from neutrino_hub.modules.devices import desired_state as desired_state_module
from neutrino_hub.modules.devices.agent_module_controller import AgentModuleController
from neutrino_hub.modules.devices.agent_sessions import AgentSessionRegistry
from neutrino_hub.modules.devices.desired_state import DesiredStateStore
from neutrino_hub.modules.devices.install_lock import DeviceInstallLocks
from neutrino_hub.modules.devices.registry import ManagedDevice
from neutrino_hub.modules.services.device_shares import DeviceShareRegistry
from tests.conftest import unlock_vault

MAC = "aa:bb:cc:dd:ee:ff"
RDP_PATH = "devices/aa-bb-cc-dd-ee-ff/rdp.json"
PLATFORM = {"os": "linux", "family": "debian", "arch": "amd64"}


class StubPublishedServices:
    def expire(self):
        return None


class ReportingRuntime:
    """The report path, with a real store under a temporary config root."""

    def __init__(self):
        self.client_metrics: dict = {}
        self.client_modules: dict = {}
        self.client_platform: dict = {}
        self.client_hostname: dict = {}
        self.client_accounts: dict = {}
        self.client_address: dict = {}
        self.client_last_error: dict = {}
        self.device_shares = DeviceShareRegistry()
        self.published_services = StubPublishedServices()
        self.agent_module_orders = AgentModuleController(
            cache=None, locks=DeviceInstallLocks()
        )
        self.agent_sessions = AgentSessionRegistry()
        self.desired_states = DesiredStateStore()


@pytest.fixture
def config(monkeypatch, tmp_path):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(desired_state_module, "UTILS_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(desired_state_module, "resolved_modules", lambda platform: {})
    return tmp_path


@pytest.fixture
def locked(monkeypatch, tmp_path):
    """A box with no data key: nothing seals until somebody unlocks it."""
    empty = tmp_path / "no_state"
    empty.mkdir()
    monkeypatch.setattr("neutrino_hub.utils.constants.UTILS_STATE_ROOT", empty)


def report(**fields) -> dict:
    body = {
        "type": "report",
        "metrics": {},
        "modules": {"rustdesk": {"state": "installed"}},
        "addresses": [],
        "accounts": [],
        "rdp": {"is_shared": False},
        "last_error": None,
    }
    body.update(fields)
    return body


def beat(runtime, **fields) -> None:
    agent_reports.record_report(
        runtime, ManagedDevice(mac_address=MAC, name="testbox"), report(**fields)
    )


def stored(config) -> dict:
    return json.loads((config / RDP_PATH).read_text())


def test_the_first_installed_report_generates_one(config, monkeypatch, tmp_path):
    unlock_vault(monkeypatch, tmp_path)
    runtime = ReportingRuntime()

    beat(runtime)

    password = runtime.desired_states.seat_password(MAC)
    assert len(password) == 22
    assert set(password) <= set(string.ascii_letters + string.digits)


def test_a_later_report_keeps_the_password_the_machine_already_has(
    config, monkeypatch, tmp_path
):
    unlock_vault(monkeypatch, tmp_path)
    runtime = ReportingRuntime()
    beat(runtime)
    first = runtime.desired_states.seat_password(MAC)

    beat(runtime)
    beat(runtime)

    assert runtime.desired_states.seat_password(MAC) == first


def test_a_machine_whose_package_lacks_the_host_is_given_none(
    config, monkeypatch, tmp_path
):
    unlock_vault(monkeypatch, tmp_path)
    runtime = ReportingRuntime()

    beat(runtime, modules={"rustdesk": {"state": "absent"}})

    assert not (config / RDP_PATH).exists()
    assert runtime.desired_states.seat_password(MAC) == ""


def test_a_locked_vault_leaves_it_for_the_next_report(
    config, locked, monkeypatch, tmp_path
):
    runtime = ReportingRuntime()

    beat(runtime)

    assert not (config / RDP_PATH).exists()
    assert runtime.desired_states.seat_password(MAC) == ""

    unlock_vault(monkeypatch, tmp_path)
    beat(runtime)

    assert runtime.desired_states.seat_password(MAC) != ""


def test_what_lands_under_config_is_sealed_and_nowhere_in_plain_text(
    config, monkeypatch, tmp_path
):
    unlock_vault(monkeypatch, tmp_path)
    store = DesiredStateStore()
    store.ensure_seat_password(MAC)

    password = store.seat_password(MAC)

    assert set(stored(config)) == {"seat_password_sealed"}
    assert set(stored(config)["seat_password_sealed"]) == {"nonce", "data"}
    written = [path for path in config.rglob("*") if path.is_file()]
    assert written
    for path in written:
        assert password not in path.read_text()


def test_compose_hands_the_machine_the_opened_password(config, monkeypatch, tmp_path):
    unlock_vault(monkeypatch, tmp_path)
    store = DesiredStateStore()
    store.ensure_seat_password(MAC)

    desired, _ = store.compose(MAC, PLATFORM)

    assert desired["rdp"] == {"seat_password": store.seat_password(MAC)}
    assert desired["rdp"]["seat_password"] != ""


def test_a_seal_this_box_cannot_open_composes_empty(config, monkeypatch, tmp_path):
    """A beat degrades rather than failing: the machine is handed no password
    and the next state it is pushed carries whatever this box can open."""
    unlock_vault(monkeypatch, tmp_path)
    store = DesiredStateStore()
    (config / "devices/aa-bb-cc-dd-ee-ff").mkdir(parents=True)
    (config / RDP_PATH).write_text(
        json.dumps({"seat_password_sealed": seal_bytes(b"other", b"wrong")})
    )

    desired, _ = store.compose(MAC, PLATFORM)

    assert desired["rdp"] == {"seat_password": ""}


def test_a_reset_replaces_the_password(config, monkeypatch, tmp_path):
    unlock_vault(monkeypatch, tmp_path)
    store = DesiredStateStore()
    store.ensure_seat_password(MAC)
    first = store.seat_password(MAC)

    store.reset_seat_password(MAC)

    assert store.seat_password(MAC) != first
    assert set(stored(config)) == {"seat_password_sealed"}
