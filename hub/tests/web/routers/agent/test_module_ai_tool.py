"""A managed machine's AI tools: the Modules page's Global configuration.

What these pin: the view names every account with an instance in a module
not withdrawn, each with the modules it runs and its result as the machine
last reported it; turning the setting on is refused while the gateway
serves no model and for a machine that is offline, and otherwise mints the
device's key, stores the setting and pushes the state; turning it off
revokes the key and pushes; the tool choices are cleaned as the client
cleans them and pushed only while the setting is on.
"""

import json
from types import SimpleNamespace

import pytest

from neutrino_hub.modules.clients import ai_keys
from neutrino_hub.modules.cliproxyapi.ops import load_config
from neutrino_hub.web.routers.agent import module_ai_tool
from tests.conftest import unlock_vault
from tests.web.module_api_box import DEVICE, OFFLINE, module_box

BASE = "/api/agent/module/ai_tool"


class Gateway:
    """The names the gateway serves, as a test sets them."""

    def __init__(self):
        self.models = ["gw-model"]

    def __call__(self, served_models):
        return list(self.models)


@pytest.fixture
def api(monkeypatch, tmp_path):
    unlock_vault(monkeypatch, tmp_path)
    monkeypatch.setattr(ai_keys, "_apply", lambda **kwargs: None)
    gateway = Gateway()
    monkeypatch.setattr(module_ai_tool, "gateway_models", gateway)
    client, runtime = module_box(monkeypatch, tmp_path, module_ai_tool.router)
    runtime.served_models = None
    store = runtime.desired_states
    store.set_want(DEVICE, "vscode", "running")
    store.set_want(DEVICE, "code_server", "running")
    store.set_want(DEVICE, "cloudcli", "absent")
    store.write(DEVICE, "vscode", {"instances": [{"account": "alice", "port": 8001}]})
    store.write(
        DEVICE,
        "code_server",
        {"instances": [{"account": "alice", "port": 9001}, {"account": "bob"}]},
    )
    store.write(DEVICE, "cloudcli", {"instances": [{"account": "carol", "port": 3}]})
    with client:
        yield client, runtime, gateway, tmp_path


def stored(tmp_path) -> dict:
    return json.loads((tmp_path / "devices" / DEVICE / "ai_tools.json").read_text())


def test_the_view_names_each_account_and_what_the_machine_reported(api, monkeypatch):
    client, runtime, _gateway, _ = api
    reports = {
        DEVICE: {
            "ai_tools": {
                "accounts": [
                    {"account": "alice", "state": "switched"},
                    {
                        "account": "bob",
                        "state": "failed",
                        "code": "switch_failed",
                        "params": {"account": "bob", "detail": "no"},
                    },
                ]
            }
        }
    }
    monkeypatch.setattr(runtime.agent_sessions, "reports", lambda: reports)

    view = client.get(BASE, params={"device_id": DEVICE}).json()

    assert view["is_enabled"] is False
    assert view["is_gateway_serving"] is True
    assert view["models"] == ["gw-model"]
    assert view["accounts"] == [
        {
            "account": "alice",
            "modules": ["vscode", "code_server"],
            "state": "switched",
            "code": "",
            "params": {},
        },
        {
            "account": "bob",
            "modules": ["code_server"],
            "state": "failed",
            "code": "switch_failed",
            "params": {"account": "bob", "detail": "no"},
        },
    ]


def test_turning_it_on_is_refused_while_the_gateway_serves_nothing(api):
    client, runtime, gateway, tmp_path = api
    gateway.models = []

    answer = client.post(f"{BASE}/enable", json={"device_id": DEVICE})

    assert answer.status_code == 409
    assert answer.json()["detail"] == {"code": "gateway_not_serving", "params": {}}
    assert DEVICE not in load_config().device_keys
    assert runtime.agent_sessions.pushes == []
    assert not (tmp_path / "devices" / DEVICE / "ai_tools.json").exists()


def test_an_offline_machine_is_refused(api):
    client, _runtime, _gateway, _ = api

    answer = client.post(f"{BASE}/enable", json={"device_id": OFFLINE})

    assert (answer.status_code, answer.json()["detail"]["code"]) == (
        409,
        "agent_offline",
    )
    assert OFFLINE not in load_config().device_keys


def test_on_mints_the_key_and_pushes_and_off_revokes_it_and_pushes(api):
    client, runtime, _gateway, tmp_path = api

    on = client.post(f"{BASE}/enable", json={"device_id": DEVICE})
    key = load_config().device_keys[DEVICE]
    off = client.post(f"{BASE}/disable", json={"device_id": DEVICE})

    assert on.json()["is_enabled"] is True
    assert key.name == "device/box"
    assert off.json()["is_enabled"] is False
    assert DEVICE not in load_config().device_keys
    assert stored(tmp_path)["is_enabled"] is False
    assert [push[0] for push in runtime.agent_sessions.pushes] == [DEVICE, DEVICE]


def test_the_choices_are_cleaned_and_pushed_only_while_the_setting_is_on(api):
    client, runtime, _gateway, tmp_path = api
    choices = {
        "claude": {"opus": "big", "nonsense": "x"},
        "codex": {"model": "c", "model_reasoning_effort": "extreme"},
        "lisp": {"model": "y"},
    }

    off = client.post(
        f"{BASE}/set", json={"device_id": DEVICE, "tool_configs": choices}
    )
    pushed_while_off = len(runtime.agent_sessions.pushes)
    client.post(f"{BASE}/enable", json={"device_id": DEVICE})
    client.post(f"{BASE}/set", json={"device_id": DEVICE, "tool_configs": choices})

    assert off.json()["tool_configs"] == {
        "claude": {"opus": "big"},
        "codex": {"model": "c"},
        "gemini": {},
    }
    assert stored(tmp_path)["tool_configs"] == off.json()["tool_configs"]
    assert pushed_while_off == 0
    assert len(runtime.agent_sessions.pushes) == 2


def failed_report(runtime, monkeypatch, state: str = "failed"):
    reports = {
        DEVICE: {
            "ai_tools": {
                "accounts": [
                    {"account": "alice", "state": state, "code": "switch_failed"}
                ]
            }
        }
    }
    monkeypatch.setattr(runtime.agent_sessions, "reports", lambda: reports)


def test_on_again_while_an_account_failed_puts_a_retry_mark(api, monkeypatch):
    from neutrino_hub.modules.devices.retry_marks import DeviceRetryMarks

    client, runtime, _gateway, _ = api
    client.post(f"{BASE}/enable", json={"device_id": DEVICE})
    assert DeviceRetryMarks().marks(DEVICE) == {}
    failed_report(runtime, monkeypatch)

    client.post(f"{BASE}/enable", json={"device_id": DEVICE})

    assert set(DeviceRetryMarks().marks(DEVICE)) == {"ai_tools"}
    assert len(runtime.agent_sessions.pushes) == 2


def test_off_again_after_a_failed_switch_back_puts_a_retry_mark(api, monkeypatch):
    """The reported bug: cc-switch could not run for the switch back, was
    put right, and the second off did nothing, since only on wrote a mark."""
    from neutrino_hub.modules.devices.retry_marks import DeviceRetryMarks

    client, runtime, _gateway, _ = api
    client.post(f"{BASE}/enable", json={"device_id": DEVICE})
    client.post(f"{BASE}/disable", json={"device_id": DEVICE})
    assert DeviceRetryMarks().marks(DEVICE) == {}
    failed_report(runtime, monkeypatch)

    client.post(f"{BASE}/disable", json={"device_id": DEVICE})

    assert set(DeviceRetryMarks().marks(DEVICE)) == {"ai_tools"}
    assert len(runtime.agent_sessions.pushes) == 3


def test_off_from_on_with_a_failed_account_puts_no_mark(api, monkeypatch):
    """Turning off changes the state by itself; a failed switch on is not
    a switch back to retry."""
    from neutrino_hub.modules.devices.retry_marks import DeviceRetryMarks

    client, runtime, _gateway, _ = api
    client.post(f"{BASE}/enable", json={"device_id": DEVICE})
    failed_report(runtime, monkeypatch)

    client.post(f"{BASE}/disable", json={"device_id": DEVICE})

    assert DeviceRetryMarks().marks(DEVICE) == {}


def test_on_again_with_no_failed_account_puts_no_mark(api, monkeypatch):
    from neutrino_hub.modules.devices.retry_marks import DeviceRetryMarks

    client, runtime, _gateway, _ = api
    client.post(f"{BASE}/enable", json={"device_id": DEVICE})
    failed_report(runtime, monkeypatch, state="switched")

    client.post(f"{BASE}/enable", json={"device_id": DEVICE})

    assert DeviceRetryMarks().marks(DEVICE) == {}


def report_states(runtime, monkeypatch, states: dict) -> None:
    accounts = [{"account": name, "state": state} for name, state in states.items()]
    reports = {DEVICE: {"ai_tools": {"accounts": accounts}}}
    monkeypatch.setattr(runtime.agent_sessions, "reports", lambda: reports)


def in_use(client) -> bool:
    return client.get(BASE, params={"device_id": DEVICE}).json()["is_in_use"]


def test_off_with_a_switch_back_that_failed_is_still_in_use(api, monkeypatch):
    """The chip reads on, so its press sends disable and tries again."""
    client, runtime, _gateway, _ = api
    report_states(runtime, monkeypatch, {"alice": "switched_back", "bob": "failed"})

    assert in_use(client) is True


def test_off_with_every_account_back_is_not_in_use(api, monkeypatch):
    client, runtime, _gateway, _ = api
    report_states(runtime, monkeypatch, {"alice": "switched_back"})

    assert in_use(client) is False


def test_on_with_an_account_on_the_gateway_is_in_use(api, monkeypatch):
    client, runtime, _gateway, _ = api
    client.post(f"{BASE}/enable", json={"device_id": DEVICE})
    report_states(runtime, monkeypatch, {"alice": "switched", "bob": "failed"})

    assert in_use(client) is True


def test_on_with_every_switch_failed_is_not_in_use(api, monkeypatch):
    """The chip reads off, so its press sends enable and tries again."""
    client, runtime, _gateway, _ = api
    client.post(f"{BASE}/enable", json={"device_id": DEVICE})
    report_states(runtime, monkeypatch, {"alice": "failed", "bob": "failed"})

    assert in_use(client) is False


def test_on_with_an_account_not_yet_reported_is_in_use(api, monkeypatch):
    client, runtime, _gateway, _ = api
    client.post(f"{BASE}/enable", json={"device_id": DEVICE})
    report_states(runtime, monkeypatch, {"alice": "failed"})

    assert in_use(client) is True


def test_a_report_on_an_older_state_is_not_read(api, monkeypatch):
    """Right after a press the machine's last results answer the state before."""
    client, runtime, _gateway, _ = api
    client.post(f"{BASE}/enable", json={"device_id": DEVICE})
    report_states(
        runtime, monkeypatch, {"alice": "switched_back", "bob": "switched_back"}
    )
    session = SimpleNamespace(offered_hash="new", state_hash="old")
    monkeypatch.setattr(runtime.agent_sessions, "get", lambda key: session)

    assert in_use(client) is True
