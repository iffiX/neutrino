"""One agent, driven connection by connection with scripted sockets.

What these pin: the identity card the hello carries and the five sections
of the report, with ``error`` the most recent of its three sources; what
each refusal does to the binding, at the door and on a live socket alike,
with only ``binding_unknown`` deleting it and a replaced socket waiting for
a person; the binding file
shared with the CLI; the connection round over every address the hub
answers on, the name first, the one that answered written back and a whole
round failing being what backs off; the state's ``urls`` kept on disk; a
network change under the machine starting a round at once and moving a
live socket to the name's address; the self-update a welcome's
``software`` triggers and its once-per-target latch; ``sync`` sending a
report now and what ``probe`` does; and the wake flag cleared before a
turn rather than after it. Nothing here talks to a network.
"""

import json
import os
import threading
import time

import pytest

import neutrino_agent.core.enrollment as enrollment_module
import neutrino_agent.core.loop as loop_module
from neutrino_agent import AGENT_VERSION
from neutrino_agent.constants import (
    AGENT_BACKOFF_MAX_S,
    AGENT_BACKOFF_MIN_S,
    AGENT_REINSTALL_RESULT_NAME,
    AGENT_REPORT_INTERVAL_S,
    AGENT_ROLE,
    AGENT_SOFTWARE_PREFIX,
    AGENT_WS_PATH,
    PROTOCOL,
)
from neutrino_agent.core.loop import IDLE_POLL_INTERVAL_S, Agent
from neutrino_agent.core.metrics import HostMetrics
from neutrino_agent.exceptions import (
    GatewayUnreachable,
    GatewayUntrusted,
    PlatformUnsupportedError,
    SocketClosed,
)
from neutrino_agent.platforms.base import AgentPlatform
from tests.conftest import BINDING_ID, BINDING_TOKEN, bind
from tests.core.test_session import ScriptedClient

WELCOME = {
    "type": "welcome",
    "protocol": 1,
    "role": "hub",
    "id": "hub-1",
    "name": "hub",
    "software": "neutrino_hub/0.0.1",
}
HUNG_UP = GatewayUnreachable("hung up")
# A script entry: the hub hangs up once the first report has gone up.
DROP_AFTER_REPORT = object()


class _FakePlatform(AgentPlatform):
    """A platform with prepared metrics, accounts and interfaces; the rest
    refuses."""

    os_name = "linux"

    def __init__(self, *, metrics=None, accounts=None, interfaces=None):
        self._metrics = metrics
        self._accounts = accounts
        self._interfaces = interfaces

    def read_host_metrics(self):
        if self._metrics is None:
            raise PlatformUnsupportedError("no metrics here")
        return self._metrics

    def human_accounts(self):
        if self._accounts is None:
            raise PlatformUnsupportedError("cannot enumerate accounts here")
        return list(self._accounts)

    def read_network_interfaces(self):
        if self._interfaces is None:
            raise PlatformUnsupportedError("no interfaces to read here")
        return list(self._interfaces)


INTERFACES = [
    {
        "name": "eth0",
        "mac": "02:00:00:00:00:01",
        "addresses": ["192.0.2.10", "fe80::ff:fe00:1"],
    },
    {"name": "wlan0", "mac": "02:00:00:00:00:02", "addresses": ["10.0.0.5"]},
]


class ClientScript:
    """Hands the loop one scripted client per connection, in order.

    Attributes:
        local_address: What every client built names as the socket's own
            address.
        client_class: What each connection's client is built from.
    """

    def __init__(self, scripts, default=None):
        self.scripts = list(scripts)
        self.default = default if default is not None else [HUNG_UP]
        self.clients: list = []
        self.built: list = []
        self.local_address = ""
        self.client_class = ScriptedClient

    def __call__(self, **kwargs):
        self.built.append(kwargs)
        client = self.client_class()
        client.local_address = self.local_address
        script = self.scripts.pop(0) if self.scripts else self.default
        if isinstance(script, Exception):
            client.connect_error = script
        else:
            for item in script:
                if item is DROP_AFTER_REPORT:
                    client.drop_after_report = True
                else:
                    client.feed(item)
        self.clients.append(client)
        return client


def scripted_agent(config_path, monkeypatch, scripts=None, *, platform=None):
    """A bound agent whose sockets answer from scripts, off the network."""
    bind(config_path)
    if platform is None:
        platform = _FakePlatform(metrics=HostMetrics(), accounts=["alice", "bob"])
    script = ClientScript(scripts or [])
    monkeypatch.setattr(loop_module, "WebSocketClient", script)
    agent = Agent(log=lambda message: None, platform=platform)
    return agent, script


def welcomed_then_dropped():
    return [WELCOME, DROP_AFTER_REPORT]


# --- the binding file shared with the CLI ---


def test_a_binding_written_by_another_process_is_adopted(config_path):
    agent = Agent(log=lambda message: None)
    assert agent._operator is None

    bind(config_path)
    agent._adopt_external_binding()

    assert agent._operator is not None


def test_a_binding_removed_by_another_process_is_let_go(config_path):
    bind(config_path)
    agent = Agent(log=lambda message: None)
    agent._last_error = {"code": "hub_unreachable", "params": {}}

    config_path.unlink()
    agent._adopt_external_binding()

    assert agent._operator is None
    assert agent.last_error() is None


def test_an_untouched_file_reloads_nothing(config_path):
    bind(config_path)
    agent = Agent(log=lambda message: None)
    made = agent._operator

    agent._adopt_external_binding()

    assert agent._operator is made


def test_a_rewrite_of_the_same_binding_wipes_no_state(config_path):
    bind(config_path)
    agent = Agent(log=lambda message: None)
    agent._last_error = {"code": "hub_unreachable", "params": {}}

    bind(config_path)
    agent._adopt_external_binding()

    assert agent.last_error() == {"code": "hub_unreachable", "params": {}}


def test_adopt_binding_a_changed_url_swaps_the_operator_and_clears_state(config_path):
    bind(config_path)
    agent = Agent(log=lambda message: None)
    agent._update_target = "9.9.9"
    agent._update_error = {"code": "agent_update_launch_failed", "params": {}}

    bind(config_path, url="http://127.0.0.1:10")
    agent._adopt_external_binding()

    assert agent._binding["gateway_url"] == "http://127.0.0.1:10"
    assert agent._operator is not None
    assert agent._update_target == ""
    assert agent.last_error() is None


def test_a_changed_binding_closes_the_live_socket(config_path, monkeypatch):
    agent, script = scripted_agent(config_path, monkeypatch, [[WELCOME]])
    session = agent._open_session()
    session.connect()
    agent._session = session

    config_path.unlink()
    agent._adopt_external_binding()

    assert script.clients[0].is_closed
    assert agent._session is None


def test_leave_gives_the_binding_back_and_leaves_the_service_unbound(
    config_path, monkeypatch
):
    agent, script = scripted_agent(config_path, monkeypatch, [[WELCOME]])
    left: list = []
    monkeypatch.setattr(
        enrollment_module.BindingHttpClient,
        "leave",
        lambda self, binding_id, token: left.append((binding_id, token)),
    )
    session = agent._open_session()
    session.connect()
    agent._session = session

    agent.leave()

    assert left == [(BINDING_ID, BINDING_TOKEN)]
    assert agent._operator is None
    assert script.clients[0].is_closed
    assert not config_path.exists()


def test_leave_does_not_wait_on_a_hub_that_cannot_be_told(config_path, monkeypatch):
    agent, _ = scripted_agent(config_path, monkeypatch)
    lines: list = []
    agent._log = lines.append

    def refuse(self, binding_id, token):
        raise GatewayUnreachable("gone")

    monkeypatch.setattr(enrollment_module.BindingHttpClient, "leave", refuse)

    agent.leave()

    assert agent._operator is None
    assert not config_path.exists()
    assert "could not tell the hub we are leaving: hub_unreachable" in lines


def test_the_store_lives_under_the_platforms_data_root():
    platform = _FakePlatform(metrics=HostMetrics(), accounts=[])
    agent = Agent(log=lambda message: None, platform=platform)

    root = platform.agent_data_dir()
    assert agent._store._path == os.path.join(root, "state.json")
    assert agent._rdp._credentials_dir == os.path.join(root, "credentials")


# --- the hello and the report ---


def test_the_socket_is_opened_on_the_bindings_host_port_and_pin(
    config_path, monkeypatch
):
    bind(config_path, url="https://hub.lan:8443", fingerprint="ab" * 32)
    script = ClientScript([welcomed_then_dropped()])
    monkeypatch.setattr(loop_module, "WebSocketClient", script)
    platform = _FakePlatform(metrics=HostMetrics(), accounts=[])
    agent = Agent(log=lambda message: None, platform=platform)

    agent.run_once()

    (built,) = script.built
    assert built == {
        "host": "hub.lan",
        "port": 8443,
        "path": AGENT_WS_PATH,
        "fingerprint": "ab" * 32,
    }


def test_the_hello_is_the_identity_card(config_path, monkeypatch):
    agent, script = scripted_agent(config_path, monkeypatch, [welcomed_then_dropped()])
    monkeypatch.setattr(loop_module, "hostname", lambda: "box")

    agent.run_once()

    (hello,) = script.clients[0].frames("hello")
    assert hello == {
        "type": "hello",
        "protocol": PROTOCOL,
        "role": AGENT_ROLE,
        "id": BINDING_ID,
        "name": "box",
        "software": f"{AGENT_SOFTWARE_PREFIX}{AGENT_VERSION}",
        "token": BINDING_TOKEN,
    }
    assert hello["protocol"] == 1
    assert hello["role"] == "agent"
    assert hello["software"].startswith("neutrino_hub/") is False


def test_the_report_carries_every_field_from_its_source(config_path, monkeypatch):
    metrics = HostMetrics(cpu_percent=12.3, memory_percent=56.7, uptime_s=7)
    platform = _FakePlatform(
        metrics=metrics, accounts=["alice", "bob"], interfaces=INTERFACES
    )
    agent, script = scripted_agent(
        config_path, monkeypatch, [welcomed_then_dropped()], platform=platform
    )
    monkeypatch.setattr(loop_module, "hostname", lambda: "box")
    script.local_address = "10.0.0.5"
    # The runners' first observation runs on the reconcile thread; read them
    # now so the report and the states it is compared with are one reading.
    agent._engine.refresh_now()

    agent.run_once()

    (report,) = script.clients[0].frames("report")
    assert set(report) == {
        "type",
        "state_hash",
        "machine",
        "network",
        "modules",
        "desktop",
        "error",
    }
    assert report["type"] == "report"
    assert report["state_hash"] == ""
    assert set(report["machine"]) == {"hostname", "platform", "accounts", "metrics"}
    assert report["machine"]["hostname"] == "box"
    assert report["machine"]["platform"] == agent.platform()
    assert report["machine"]["accounts"] == ["alice", "bob"]
    assert report["machine"]["metrics"]["cpu_percent"] == 12.3
    assert report["machine"]["metrics"]["uptime_s"] == 7
    assert report["network"] == {
        "link": {
            "interface": "wlan0",
            "mac": "02:00:00:00:00:02",
            "address": "10.0.0.5",
        },
        "interfaces": INTERFACES,
    }
    assert report["modules"] == agent.module_states()
    for row in report["modules"].values():
        assert set(row) == {"state", "is_active", "code", "params", "details"}
    assert set(report["desktop"]) == {
        "is_shared",
        "account",
        "connected_count",
        "share_id",
        "port",
        "attention",
    }
    assert report["desktop"]["is_shared"] is False
    assert report["error"] is None


def test_report_metrics_platform_cannot_read_sends_the_empty_shape(
    config_path, monkeypatch
):
    platform = _FakePlatform(metrics=None, accounts=[])
    agent, script = scripted_agent(
        config_path, monkeypatch, [welcomed_then_dropped()], platform=platform
    )

    agent.run_once()

    (report,) = script.clients[0].frames("report")
    assert report["machine"]["metrics"] == HostMetrics().to_dict()


def test_report_accounts_platform_cannot_enumerate_sends_an_empty_list(
    config_path, monkeypatch
):
    platform = _FakePlatform(metrics=HostMetrics(), accounts=None)
    agent, script = scripted_agent(
        config_path, monkeypatch, [welcomed_then_dropped()], platform=platform
    )

    agent.run_once()

    (report,) = script.clients[0].frames("report")
    assert report["machine"]["accounts"] == []


def test_report_interfaces_platform_cannot_read_sends_the_link_alone(
    config_path, monkeypatch
):
    platform = _FakePlatform(metrics=HostMetrics(), accounts=[])
    agent, script = scripted_agent(
        config_path, monkeypatch, [welcomed_then_dropped()], platform=platform
    )
    script.local_address = "192.0.2.10"

    agent.run_once()

    (report,) = script.clients[0].frames("report")
    assert report["network"] == {
        "link": {"interface": "", "mac": "", "address": "192.0.2.10"},
        "interfaces": [],
    }


REINSTALL_RESULT = {
    "package": "neutrino-agent_0.1.0_amd64.deb",
    "kind": "deb",
    "started_at": "2026-09-10T10:00:00Z",
    "finished_at": "2026-09-10T10:00:12Z",
    "exit_code": 0,
    "output": "Setting up neutrino-agent\n",
}
FAILED_REINSTALL = dict(REINSTALL_RESULT, exit_code=100, output="dpkg: error\n")
REINSTALL_ERROR = {
    "code": "reinstall_failed",
    "params": {"exit_code": 100, "finished_at": "2026-09-10T10:00:12Z"},
}


def test_a_failed_reinstall_is_the_reports_error(tmp_path, config_path, monkeypatch):
    (tmp_path / AGENT_REINSTALL_RESULT_NAME).write_text(json.dumps(FAILED_REINSTALL))
    agent, script = scripted_agent(config_path, monkeypatch, [welcomed_then_dropped()])

    agent.run_once()

    (hello,) = script.clients[0].frames("hello")
    (report,) = script.clients[0].frames("report")
    assert "error" not in hello
    assert report["error"] == REINSTALL_ERROR
    # The package manager's own output stays on the machine.
    assert "dpkg" not in json.dumps(report)


def test_a_reinstall_that_went_through_is_no_error(tmp_path, config_path, monkeypatch):
    (tmp_path / AGENT_REINSTALL_RESULT_NAME).write_text(json.dumps(REINSTALL_RESULT))
    agent, script = scripted_agent(config_path, monkeypatch, [welcomed_then_dropped()])

    agent.run_once()

    (report,) = script.clients[0].frames("report")
    assert report["error"] is None


def test_a_reinstall_record_written_mid_run_rides_the_next_report(
    tmp_path, config_path, monkeypatch
):
    """The install writes its result after the new agent is already up."""
    agent, script = scripted_agent(
        config_path, monkeypatch, [welcomed_then_dropped(), welcomed_then_dropped()]
    )
    agent.run_once()
    (first,) = script.clients[0].frames("report")

    (tmp_path / AGENT_REINSTALL_RESULT_NAME).write_text(json.dumps(FAILED_REINSTALL))
    agent.run_once()

    (second,) = script.clients[1].frames("report")
    assert first["error"] is None
    assert second["error"] == REINSTALL_ERROR


def test_a_reinstall_record_that_cannot_be_read_rides_up_as_nothing(
    tmp_path, config_path, monkeypatch
):
    (tmp_path / AGENT_REINSTALL_RESULT_NAME).write_text("not json at all")
    agent, script = scripted_agent(config_path, monkeypatch, [welcomed_then_dropped()])

    agent.run_once()

    (report,) = script.clients[0].frames("report")
    assert report["error"] is None


def test_the_last_error_rides_the_next_connections_report(config_path, monkeypatch):
    agent, script = scripted_agent(
        config_path,
        monkeypatch,
        [GatewayUnreachable("gone"), welcomed_then_dropped()],
    )

    agent.run_once()
    assert agent.last_error()["code"] == "hub_unreachable"
    agent.run_once()

    # A welcome clears it: the report that follows carries none.
    (report,) = script.clients[1].frames("report")
    assert report["error"] is None


def test_the_error_is_the_most_recent_of_its_three_sources(
    tmp_path, config_path, monkeypatch
):
    """Each source is stamped when its value changes; the newest is shown,
    and a source that clears hands the section to the next newest."""
    agent, _ = scripted_agent(config_path, monkeypatch)
    update_error = {"code": "agent_update_launch_failed", "params": {"target": "9"}}
    state_error = {"code": "apply_failed", "params": {"module": "samba"}}
    assert agent._report_payload()["error"] is None

    agent._update_error = dict(update_error)
    assert agent._report_payload()["error"] == update_error

    agent._desired._state_error = dict(state_error)
    assert agent._report_payload()["error"] == state_error

    agent._update_error = dict(update_error, params={"target": "10"})
    assert agent._report_payload()["error"] == {
        "code": "agent_update_launch_failed",
        "params": {"target": "10"},
    }

    agent._update_error = None
    assert agent._report_payload()["error"] == state_error

    (tmp_path / AGENT_REINSTALL_RESULT_NAME).write_text(json.dumps(FAILED_REINSTALL))
    assert agent._report_payload()["error"] == REINSTALL_ERROR

    agent._desired._state_error = None
    assert agent._report_payload()["error"] == REINSTALL_ERROR
    (tmp_path / AGENT_REINSTALL_RESULT_NAME).write_text(json.dumps(REINSTALL_RESULT))
    assert agent._report_payload()["error"] is None


# --- refusals, and what each does to the binding ---


def refused(code: str, params=None) -> list:
    """A hub that answers the hello with ``refused`` and closes 4000."""
    return [
        {"type": "refused", "code": code, "params": dict(params or {})},
        SocketClosed(4000, code),
    ]


@pytest.mark.parametrize(
    "script, code, params",
    [
        (
            refused("protocol_too_old", {"peer": 1, "hub": 3, "min": 2}),
            "protocol_too_old",
            {"peer": 1, "hub": 3, "min": 2},
        ),
        (
            refused("protocol_too_new", {"peer": 2, "hub": 1, "min": 1}),
            "protocol_too_new",
            {"peer": 2, "hub": 1, "min": 1},
        ),
        (GatewayUntrusted("wrong pin"), "hub_untrusted", {}),
        (refused("ticket_spent"), "ticket_spent", {}),
        (refused("role_mismatch"), "role_mismatch", {}),
        (refused("somebody_new"), "somebody_new", {}),
        ([SocketClosed(4000, "binding_unknown")], "channel_refused", {}),
    ],
)
def test_a_refusal_keeps_the_binding_and_asks_again_later(
    config_path, monkeypatch, script, code, params
):
    """Every refusal but ``binding_unknown`` leaves the binding where it
    is: the hub has not forgotten this machine, it has said no for now."""
    agent, _ = scripted_agent(config_path, monkeypatch, [script] * 3)

    delays = [agent.run_once() for _ in range(3)]

    assert delays == [AGENT_BACKOFF_MAX_S] * 3
    assert agent._operator is not None
    assert enrollment_module.is_bound()
    assert agent.last_error() == {"code": code, "params": params}


def test_binding_unknown_deletes_the_binding_and_waits_for_a_link(
    config_path, monkeypatch
):
    """Only the hub holding the pinned certificate can say it has no such
    binding; the agent takes its word and keeps the reason for status."""
    agent, script = scripted_agent(
        config_path, monkeypatch, [refused("binding_unknown")]
    )

    assert agent.run_once() == IDLE_POLL_INTERVAL_S

    assert not config_path.exists()
    assert not enrollment_module.is_bound()
    assert agent._operator is None
    assert agent.last_error() == {"code": "binding_unknown", "params": {}}

    assert agent.run_once() == IDLE_POLL_INTERVAL_S
    assert len(script.clients) == 1
    assert agent.last_error() == {"code": "binding_unknown", "params": {}}


def test_binding_unknown_posts_no_leave(config_path, monkeypatch):
    agent, _ = scripted_agent(config_path, monkeypatch, [refused("binding_unknown")])
    left: list = []
    monkeypatch.setattr(
        enrollment_module.BindingHttpClient,
        "leave",
        lambda self, binding_id, token: left.append(binding_id),
    )

    agent.run_once()

    assert left == []


def test_a_replaced_socket_stops_reconnecting_until_a_person_acts(
    config_path, monkeypatch
):
    agent, script = scripted_agent(
        config_path, monkeypatch, [[WELCOME, SocketClosed(4010, "replaced")]]
    )

    assert agent.run_once() == IDLE_POLL_INTERVAL_S
    assert agent.run_once() == IDLE_POLL_INTERVAL_S
    assert agent.run_once() == IDLE_POLL_INTERVAL_S

    assert len(script.clients) == 1
    assert agent._operator is not None
    assert enrollment_module.is_bound()
    assert agent.last_error() == {"code": "replaced", "params": {}}


def test_a_new_binding_wakes_a_replaced_agent(config_path, monkeypatch):
    agent, script = scripted_agent(
        config_path,
        monkeypatch,
        [[WELCOME, SocketClosed(4010, "replaced")], welcomed_then_dropped()],
    )
    agent.run_once()
    assert len(script.clients) == 1

    bind(config_path, url="http://127.0.0.1:10")
    agent.run_once()

    assert len(script.clients) == 2
    assert script.clients[1].frames("hello")
    assert agent._is_replaced is False


def test_a_join_wakes_a_replaced_agent(config_path, monkeypatch):
    agent, script = scripted_agent(
        config_path,
        monkeypatch,
        [[WELCOME, SocketClosed(4010, "replaced")], welcomed_then_dropped()],
    )
    agent.run_once()
    monkeypatch.setattr(
        enrollment_module, "enroll", lambda link, platform=None: bind(config_path)
    )

    agent.join("neutrino://enroll/x")
    agent.run_once()

    assert len(script.clients) == 2
    assert agent._is_replaced is False


def test_a_refusal_after_the_welcome_keeps_the_binding(config_path, monkeypatch):
    """A 4000 on a live socket is a refusal like any other: the next hello
    hears the code, and the binding stays until the hub says it has none."""
    agent, _ = scripted_agent(
        config_path, monkeypatch, [[WELCOME, SocketClosed(4000, "binding_unknown")]]
    )

    delay = agent.run_once()

    assert delay == AGENT_BACKOFF_MAX_S
    assert agent._operator is not None
    assert enrollment_module.is_bound()
    assert agent.last_error()["code"] == "channel_refused"


def live_refusal(code: str, params=None) -> list:
    """A hub that welcomes, then refuses on the live socket and closes 4000."""
    return [
        WELCOME,
        {"type": "refused", "code": code, "params": dict(params or {})},
        SocketClosed(4000, code),
    ]


def test_binding_unknown_on_a_live_socket_unbinds_without_waiting(
    config_path, monkeypatch
):
    """The panel forgot this device while its socket was up: the refusal
    is read where it arrives, not at the next hello a minute later."""
    agent, script = scripted_agent(
        config_path, monkeypatch, [live_refusal("binding_unknown", {"id": BINDING_ID})]
    )

    assert agent.run_once() == IDLE_POLL_INTERVAL_S

    assert not config_path.exists()
    assert not enrollment_module.is_bound()
    assert agent._operator is None
    assert agent.last_error() == {
        "code": "binding_unknown",
        "params": {"id": BINDING_ID},
    }

    assert agent.run_once() == IDLE_POLL_INTERVAL_S
    assert len(script.clients) == 1


@pytest.mark.parametrize(
    "code, params",
    [
        ("protocol_too_new", {"peer": 2, "hub": 1, "min": 1}),
        ("somebody_new", {}),
    ],
)
def test_a_refusal_on_a_live_socket_keeps_the_binding_and_records_its_code(
    config_path, monkeypatch, code, params
):
    """The close 4000 behind the frame is the end of a refusal already
    recorded, so the code stays the hub's own."""
    agent, _ = scripted_agent(config_path, monkeypatch, [live_refusal(code, params)])

    delay = agent.run_once()

    assert delay == AGENT_BACKOFF_MAX_S
    assert agent._operator is not None
    assert enrollment_module.is_bound()
    assert agent.last_error() == {"code": code, "params": params}


def test_an_unreachable_hub_backs_off_and_a_welcome_resets_it(config_path, monkeypatch):
    agent, _ = scripted_agent(
        config_path,
        monkeypatch,
        [
            GatewayUnreachable("gone"),
            GatewayUnreachable("gone"),
            refused("protocol_too_new"),
            welcomed_then_dropped(),
            GatewayUnreachable("gone"),
        ],
    )

    delays = [agent.run_once() for _ in range(5)]

    # The welcome put the backoff back to its floor: the drop that ended
    # that connection waits the minimum, and the next failure doubles it.
    assert delays == [
        AGENT_BACKOFF_MIN_S,
        AGENT_BACKOFF_MIN_S * 2,
        AGENT_BACKOFF_MAX_S,
        AGENT_BACKOFF_MIN_S,
        AGENT_BACKOFF_MIN_S * 2,
    ]
    assert agent._operator is not None


def test_an_adopted_binding_starts_clean(config_path, monkeypatch):
    agent, _ = scripted_agent(config_path, monkeypatch, [refused("protocol_too_new")])
    agent.run_once()
    assert agent.last_error()["code"] == "protocol_too_new"

    bind(config_path, url="http://127.0.0.1:10")
    agent._adopt_external_binding()

    assert agent.last_error() is None
    assert agent._backoff_s == AGENT_BACKOFF_MIN_S


# --- the addresses the hub answers on ---


LAN_URL = "http://192.0.2.1:9"
WAN_URL = "http://198.51.100.1:9"
OVERLAY_URL = "http://100.64.0.1:9"
NAME_ADDRESS = "192.0.2.1"
STATE_WITH_URLS = {
    "type": "state",
    "hash": "h1",
    "urls": [LAN_URL, OVERLAY_URL],
    "modules": {},
}


def hosts_tried(script) -> list:
    return [built["host"] for built in script.built]


def stored() -> dict:
    return enrollment_module.load_binding()


def test_the_next_address_is_tried_when_one_stops_answering(config_path, monkeypatch):
    """Two addresses fail, the third answers: it is written back as the one
    that answered, and the next round opens there first."""
    agent, script = scripted_agent(
        config_path,
        monkeypatch,
        [HUNG_UP, HUNG_UP, welcomed_then_dropped(), welcomed_then_dropped()],
    )
    bind(config_path, url=LAN_URL, urls=[LAN_URL, WAN_URL, OVERLAY_URL])

    delay = agent.run_once()

    assert hosts_tried(script) == ["192.0.2.1", "198.51.100.1", "100.64.0.1"]
    assert delay == AGENT_BACKOFF_MIN_S
    assert stored()["gateway_url"] == OVERLAY_URL
    assert stored()["gateway_urls"] == [LAN_URL, WAN_URL, OVERLAY_URL]
    assert script.clients[2].frames("report")[0]["error"] is None

    agent.run_once()

    assert hosts_tried(script)[3] == "100.64.0.1"
    assert agent._operator is not None


def test_a_whole_round_failing_is_what_backs_off(config_path, monkeypatch):
    agent, script = scripted_agent(config_path, monkeypatch, [])
    bind(config_path, url=LAN_URL, urls=[LAN_URL, OVERLAY_URL])

    delays = [agent.run_once() for _ in range(3)]

    assert delays == [
        AGENT_BACKOFF_MIN_S,
        AGENT_BACKOFF_MIN_S * 2,
        AGENT_BACKOFF_MIN_S * 4,
    ]
    assert hosts_tried(script) == ["192.0.2.1", "100.64.0.1"] * 3
    assert agent.last_error()["code"] == "hub_unreachable"
    assert stored()["gateway_url"] == LAN_URL


def test_the_round_waits_the_rotate_delay_between_addresses(config_path, monkeypatch):
    agent, _ = scripted_agent(config_path, monkeypatch, [])
    bind(config_path, url=LAN_URL, urls=[LAN_URL, OVERLAY_URL])
    monkeypatch.setattr(loop_module, "AGENT_ROTATE_DELAY_S", 0.2)
    started = time.monotonic()

    agent.run_once()

    assert 0.2 <= time.monotonic() - started < 5


def test_the_states_urls_are_written_to_disk_and_adopt_nothing(
    config_path, monkeypatch
):
    agent, script = scripted_agent(
        config_path, monkeypatch, [[WELCOME, STATE_WITH_URLS, DROP_AFTER_REPORT]]
    )
    made = agent._operator

    agent.run_once()

    assert stored()["gateway_urls"] == [LAN_URL, OVERLAY_URL]
    assert stored()["gateway_url"] == "http://127.0.0.1:9"
    assert agent._binding["gateway_urls"] == [LAN_URL, OVERLAY_URL]
    agent._adopt_external_binding()
    assert agent._operator is made


def test_a_state_naming_the_same_urls_writes_nothing(config_path, monkeypatch):
    agent, _ = scripted_agent(
        config_path, monkeypatch, [[WELCOME, STATE_WITH_URLS, DROP_AFTER_REPORT]]
    )
    bind(config_path, urls=[LAN_URL, OVERLAY_URL])
    agent._adopt_external_binding()
    before = config_path.stat().st_mtime_ns

    agent.run_once()

    assert config_path.stat().st_mtime_ns == before


def test_a_state_without_urls_keeps_the_list(config_path, monkeypatch):
    agent, _ = scripted_agent(
        config_path,
        monkeypatch,
        [[WELCOME, {"type": "state", "hash": "h1", "modules": {}}, DROP_AFTER_REPORT]],
    )
    bind(config_path, urls=[LAN_URL])

    agent.run_once()

    assert stored()["gateway_urls"] == [LAN_URL]


def test_an_old_binding_without_the_list_still_connects(config_path, monkeypatch):
    agent, script = scripted_agent(config_path, monkeypatch, [welcomed_then_dropped()])

    agent.run_once()

    assert hosts_tried(script) == ["127.0.0.1"]
    assert script.clients[0].frames("report")
    assert stored()["gateway_url"] == "http://127.0.0.1:9"


def test_the_name_is_tried_first_and_written_back(config_path, monkeypatch):
    agent, script = scripted_agent(config_path, monkeypatch, [welcomed_then_dropped()])
    bind(config_path, url=OVERLAY_URL, urls=[LAN_URL, OVERLAY_URL])
    monkeypatch.setattr(enrollment_module, "resolve_hub_address", lambda: NAME_ADDRESS)

    agent.run_once()

    assert hosts_tried(script) == [NAME_ADDRESS]
    assert script.built[0]["port"] == 9
    assert stored()["gateway_url"] == LAN_URL


def test_the_names_fingerprint_mismatch_is_skipped_without_alarm(
    config_path, monkeypatch
):
    """A foreign network resolving the name to its own portal is not this
    hub: the round goes on to the stored addresses and records no error."""
    agent, script = scripted_agent(
        config_path,
        monkeypatch,
        [GatewayUntrusted("wrong pin"), welcomed_then_dropped()],
    )
    lines: list = []
    agent._log = lines.append
    monkeypatch.setattr(enrollment_module, "resolve_hub_address", lambda: "10.9.9.9")

    delay = agent.run_once()

    assert hosts_tried(script) == ["10.9.9.9", "127.0.0.1"]
    assert delay == AGENT_BACKOFF_MIN_S
    # The drop after the report is the only error recorded: no alarm.
    assert agent.last_error() == {
        "code": "hub_unreachable",
        "params": {"detail": "hung up"},
    }
    assert "http://10.9.9.9:9 answers to the hub's name and is not this hub" in lines


def test_a_stored_address_off_the_pin_is_logged_and_the_round_goes_on(
    config_path, monkeypatch
):
    agent, script = scripted_agent(
        config_path,
        monkeypatch,
        [GatewayUntrusted("wrong pin"), welcomed_then_dropped()],
    )
    lines: list = []
    agent._log = lines.append
    bind(config_path, url=LAN_URL, urls=[LAN_URL, OVERLAY_URL])

    delay = agent.run_once()

    assert hosts_tried(script) == ["192.0.2.1", "100.64.0.1"]
    assert delay == AGENT_BACKOFF_MIN_S
    assert agent.last_error()["code"] == "hub_unreachable"
    assert f"{LAN_URL} presented a certificate that is not the hub's" in lines
    assert stored()["gateway_url"] == OVERLAY_URL


def test_a_stored_address_off_the_pin_alarms_when_no_address_answers(
    config_path, monkeypatch
):
    agent, script = scripted_agent(
        config_path, monkeypatch, [GatewayUntrusted("wrong pin"), HUNG_UP]
    )
    bind(config_path, url=LAN_URL, urls=[LAN_URL, OVERLAY_URL])

    delay = agent.run_once()

    assert hosts_tried(script) == ["192.0.2.1", "100.64.0.1"]
    assert delay == AGENT_BACKOFF_MAX_S
    assert agent.last_error() == {"code": "hub_untrusted", "params": {}}
    assert enrollment_module.is_bound()


def test_a_refusal_ends_the_round(config_path, monkeypatch):
    agent, script = scripted_agent(config_path, monkeypatch, [refused("ticket_spent")])
    bind(config_path, url=LAN_URL, urls=[LAN_URL, OVERLAY_URL])

    delay = agent.run_once()

    assert hosts_tried(script) == ["192.0.2.1"]
    assert delay == AGENT_BACKOFF_MAX_S
    assert agent.last_error()["code"] == "ticket_spent"


def test_probe_walks_the_round_too(config_path, monkeypatch):
    agent, script = scripted_agent(config_path, monkeypatch, [HUNG_UP, [WELCOME]])
    bind(config_path, url=LAN_URL, urls=[LAN_URL, OVERLAY_URL])

    agent.probe()

    assert hosts_tried(script) == ["192.0.2.1", "100.64.0.1"]
    assert agent.last_error() is None
    assert script.clients[1].is_closed


def sources(monkeypatch, *addresses) -> list:
    """The route probe answering each address in turn, the last one after."""
    pending = list(addresses)
    asked: list = []

    def probe(urls):
        asked.append(list(urls))
        return pending.pop(0) if len(pending) > 1 else pending[0]

    monkeypatch.setattr(enrollment_module, "default_source_address", probe)
    return asked


def test_a_changed_source_address_ends_the_wait_and_resets_the_backoff(
    config_path, monkeypatch
):
    agent, _ = scripted_agent(config_path, monkeypatch, [])
    bind(config_path, url=OVERLAY_URL, urls=[LAN_URL, OVERLAY_URL])
    agent._adopt_external_binding()
    agent._backoff_s = AGENT_BACKOFF_MAX_S
    asked = sources(monkeypatch, "10.0.0.5", "192.0.2.20")
    monkeypatch.setattr(loop_module, "AGENT_REPORT_INTERVAL_S", 0.01)
    # The engine's first observation sets the wake flag from its own thread;
    # a flag of the test's own keeps that out of the wait.
    agent._news = threading.Event()
    started = time.monotonic()

    agent._wait_out(AGENT_BACKOFF_MAX_S)

    assert time.monotonic() - started < 5
    assert agent._backoff_s == AGENT_BACKOFF_MIN_S
    assert agent._source_address == "192.0.2.20"
    # The route is looked at toward the hub's own order of addresses.
    assert asked[0] == [LAN_URL, OVERLAY_URL]


def test_the_first_look_and_an_unchanged_address_wait_the_delay_out(
    config_path, monkeypatch
):
    agent, _ = scripted_agent(config_path, monkeypatch, [])
    sources(monkeypatch, "10.0.0.5")
    monkeypatch.setattr(loop_module, "AGENT_REPORT_INTERVAL_S", 0.01)
    agent._news = threading.Event()
    started = time.monotonic()

    agent._wait_out(0.1)

    assert 0.1 <= time.monotonic() - started < 5
    assert agent._source_address == "10.0.0.5"


def test_news_ends_the_wait_before_the_network_is_looked_at(config_path, monkeypatch):
    agent, _ = scripted_agent(config_path, monkeypatch, [])
    asked = sources(monkeypatch, "10.0.0.5")
    agent.report_soon()

    agent._wait_out(AGENT_BACKOFF_MAX_S)

    assert asked == []


def test_a_live_socket_follows_the_name_to_a_stored_address(config_path, monkeypatch):
    """Connected over the overlay, the machine comes home: the name resolves
    to the LAN address the binding holds, and the socket is moved there."""
    agent, script = scripted_agent(config_path, monkeypatch, [[WELCOME]])
    lines: list = []
    agent._log = lines.append
    bind(config_path, url=OVERLAY_URL, urls=[LAN_URL, OVERLAY_URL])
    agent._adopt_external_binding()
    session = agent._connect_round()
    agent._session = session
    sources(monkeypatch, "10.0.0.5", "192.0.2.20")
    agent._tick()
    monkeypatch.setattr(enrollment_module, "resolve_hub_address", lambda: NAME_ADDRESS)

    agent._tick()

    assert script.clients[0].is_closed
    assert session.serve() is None
    assert f"moving to {LAN_URL}" in lines
    assert agent._news.is_set()


@pytest.mark.parametrize("resolved", ["", "10.9.9.9", "100.64.0.1"])
def test_a_live_socket_stays_when_the_name_is_elsewhere(
    config_path, monkeypatch, resolved
):
    """No name, a name off the stored list, or the address in use: nothing
    moves."""
    agent, script = scripted_agent(config_path, monkeypatch, [[WELCOME]])
    bind(config_path, url=OVERLAY_URL, urls=[LAN_URL, OVERLAY_URL])
    agent._adopt_external_binding()
    agent._session = agent._connect_round()
    sources(monkeypatch, "10.0.0.5", "192.0.2.20")
    agent._tick()
    monkeypatch.setattr(enrollment_module, "resolve_hub_address", lambda: resolved)

    agent._tick()

    assert not script.clients[0].is_closed
    agent._session.close()


# --- the welcome's software ---


PACKAGE_OPEN = {"type": "open", "stream": 1, "kind": "package"}


def installer(monkeypatch) -> list:
    """The self-update replaced at its two seams: the bytes come from a
    stub, and what it was asked to install is recorded."""
    installed: list = []
    monkeypatch.setattr(loop_module.self_update, "package_kind", lambda platform: "deb")
    monkeypatch.setattr(
        loop_module.self_update,
        "receive_package",
        lambda channel, directory: f"{directory}/agent.deb",
    )
    monkeypatch.setattr(
        loop_module.self_update,
        "run_update",
        lambda path, kind, data_dir: installed.append((path, kind)),
    )
    return installed


def welcomed_by(software: str) -> list:
    return [dict(WELCOME, software=software), DROP_AFTER_REPORT]


def test_a_newer_hub_opens_a_package_stream_and_launches_the_install_once_per_target(
    config_path, monkeypatch, tmp_path
):
    monkeypatch.setattr(loop_module, "AGENT_VERSION", "1.0.0")
    agent, script = scripted_agent(
        config_path, monkeypatch, [welcomed_by("neutrino_hub/9.9.9")] * 2
    )
    installed = installer(monkeypatch)

    agent.run_once()
    agent.run_once()

    assert installed == [(f"{tmp_path / 'packages'}/agent.deb", "deb")]
    assert script.clients[0].frames("open") == [PACKAGE_OPEN]
    assert script.clients[1].frames("open") == []


@pytest.mark.parametrize(
    "agent_version, software",
    [
        ("1.0.0", "neutrino_hub/9.9.9+dev"),
        ("1.0.0+dev", "neutrino_hub/9.9.9"),
        ("1.0.0", "neutrino_hub/1.0.0"),
        ("1.0.0", "neutrino_hub/0.9.9"),
        ("1.0.0", "neutrino_hub/wat"),
        ("1.0.0", "something_else/9.9.9"),
        ("1.0.0", ""),
    ],
)
def test_a_dev_older_equal_or_foreign_software_updates_nothing(
    config_path, monkeypatch, agent_version, software
):
    monkeypatch.setattr(loop_module, "AGENT_VERSION", agent_version)
    agent, script = scripted_agent(config_path, monkeypatch, [welcomed_by(software)])
    installed = installer(monkeypatch)

    agent.run_once()

    assert installed == []
    assert script.clients[0].frames("open") == []
    assert agent._update_error is None


# --- commands and the reinstall verb ---


def test_a_reinstall_command_opens_the_same_package_stream(config_path, monkeypatch):
    agent, script = scripted_agent(config_path, monkeypatch, [[WELCOME]])
    installed = installer(monkeypatch)
    session = agent._open_session()
    session.connect()
    agent._session = session

    outcome = agent._run_command("agent", "reinstall", {})

    assert [kind for _, kind in installed] == ["deb"]
    assert script.clients[0].frames("open") == [PACKAGE_OPEN]
    assert outcome == {
        "exit_code": 0,
        "code": "",
        "params": {},
        "output": "reinstall launched\n",
    }
    session.close()


def test_a_reinstall_command_with_no_socket_is_typed(config_path, monkeypatch):
    agent, _ = scripted_agent(config_path, monkeypatch)
    installed = installer(monkeypatch)

    outcome = agent._run_command("agent", "reinstall", {})

    assert installed == []
    assert outcome["code"] == "hub_unreachable"
    assert agent._update_target == ""


def test_a_command_with_no_binding_is_typed(config_path, monkeypatch):
    agent, _ = scripted_agent(config_path, monkeypatch)
    agent._operator = None

    outcome = agent._run_command("agent", "reboot", {})

    assert outcome["code"] == "hub_unreachable"
    assert outcome["exit_code"] == 1


def test_a_resize_command_reaches_the_live_sessions_stream(config_path, monkeypatch):
    agent, script = scripted_agent(config_path, monkeypatch, [[WELCOME]])
    session = agent._open_session()
    session.connect()
    agent._session = session
    resized: list = []
    monkeypatch.setattr(
        session,
        "resize_stream",
        lambda stream_id, cols, rows: resized.append((stream_id, cols, rows)) or True,
    )

    outcome = agent._run_command(
        "agent", "resize", {"shell": 2, "cols": 100, "rows": 30}
    )

    assert outcome["exit_code"] == 0
    assert resized == [(2, 100, 30)]
    session.close()


def test_a_stream_is_opened_on_the_live_socket_and_refused_without_one(
    config_path, monkeypatch
):
    agent, script = scripted_agent(config_path, monkeypatch, [[WELCOME]])
    with pytest.raises(GatewayUnreachable):
        agent._open_stream("log", module="samba")

    session = agent._open_session()
    session.connect()
    agent._session = session
    channel = agent._open_stream("log", module="samba")

    assert channel.id == 1
    assert script.clients[0].frames("open") == [
        {"type": "open", "stream": 1, "kind": "log", "module": "samba"}
    ]
    session.close()


# --- sync and probe ---


def test_sync_with_no_socket_is_typed(config_path, monkeypatch):
    agent, _ = scripted_agent(config_path, monkeypatch)

    assert agent.sync() == {"code": "hub_unreachable", "params": {}}


def test_sync_sends_a_report_now_on_the_live_socket(config_path, monkeypatch):
    """The interval is seconds long; a second report inside it is the one
    sync asked for, and no other word goes up."""
    agent, script = scripted_agent(config_path, monkeypatch, [[WELCOME]])
    session = agent._open_session()
    session.connect()
    agent._session = session
    thread = threading.Thread(target=session.serve, daemon=True)
    thread.start()
    script.clients[0].wait_for("report", count=1)

    assert agent.sync() == {}

    script.clients[0].wait_for("report", count=2, timeout_s=2)
    assert script.clients[0].frames("state_request") == []
    session.close()
    thread.join(timeout=2)


def test_probe_connects_once_and_closes(config_path, monkeypatch):
    agent, script = scripted_agent(config_path, monkeypatch, [[WELCOME]])

    agent.probe()

    assert agent.last_error() is None
    assert script.clients[0].frames("hello")
    assert script.clients[0].frames("report") == []
    assert script.clients[0].is_closed


def test_probe_reports_a_refusal_and_touches_nothing(config_path, monkeypatch):
    agent, _ = scripted_agent(config_path, monkeypatch, [refused("binding_unknown")])

    agent.probe()

    assert agent.last_error()["code"] == "binding_unknown"
    assert agent._operator is not None
    assert enrollment_module.is_bound()


def test_probe_while_unbound_does_nothing(config_path, monkeypatch):
    agent = Agent(log=lambda message: None)

    agent.probe()

    assert agent.last_error() is None


def test_an_unbound_agent_idles(config_path, monkeypatch):
    agent = Agent(log=lambda message: None)

    assert agent.run_once() == IDLE_POLL_INTERVAL_S


def test_a_module_command_that_took_is_reported_at_once(config_path, monkeypatch):
    """The hub answers the command's route from the report behind it, so
    the report goes up whether or not the read found anything new."""
    agent, _ = scripted_agent(config_path, monkeypatch, [[WELCOME]])
    refreshed: list = []
    monkeypatch.setattr(agent._engine, "refresh_now", lambda: refreshed.append(True))
    agent._news.clear()

    agent._operator._on_module_changed("zfs")

    assert refreshed == [True]
    assert agent._news.is_set()


# --- the wake flag ---


class _Stop(Exception):
    """Ends ``run_forever`` from a scripted turn."""


class _WatchedEvent(threading.Event):
    """An event whose waits return at once, recording whether it was set."""

    def __init__(self):
        super().__init__()
        self.waits: list = []

    def wait(self, timeout=None):
        self.waits.append(self.is_set())
        return True


def test_news_during_a_turn_starts_the_next_turn_without_waiting(
    config_path, monkeypatch
):
    """A stop or a ``nagent sync`` that lands while a turn runs is still
    standing when the wait begins, so the backoff is not waited out."""
    agent, _ = scripted_agent(config_path, monkeypatch)
    monkeypatch.setattr(agent._rdp, "apply_baseline", lambda: None)
    agent._news = _WatchedEvent()
    turns: list = []

    def turn():
        turns.append(True)
        if len(turns) == 2:
            raise _Stop()
        agent.report_soon()
        return AGENT_BACKOFF_MAX_S

    monkeypatch.setattr(agent, "run_once", turn)

    with pytest.raises(_Stop):
        agent.run_forever()

    assert agent._news.waits == [True]


def test_a_start_sweeps_the_package_the_last_process_left(
    config_path, monkeypatch, tmp_path
):
    agent, _ = scripted_agent(config_path, monkeypatch)
    monkeypatch.setattr(agent._rdp, "apply_baseline", lambda: None)
    packages = tmp_path / "packages"
    packages.mkdir()
    (packages / ".package.abc.part").write_bytes(b"the package that installed me")

    def stop():
        raise _Stop()

    monkeypatch.setattr(agent, "run_once", stop)

    with pytest.raises(_Stop):
        agent.run_forever()

    assert os.listdir(packages) == []
