"""One agent, driven connection by connection with scripted sockets.

What these pin: every field the hello and the report carry and where each
comes from; the rejection counter and the three-refusal self-unbind, with a
replaced socket and a broken wire counting for nothing; the wire-generation
reinstall and its once-per-target latch; the binding file shared with the
CLI; the self-update a welcome triggers; and what ``sync`` and ``probe`` do.
Nothing here talks to a network.
"""

import json
import os

import pytest

import neutrino_agent.core.channel as channel
import neutrino_agent.core.loop as loop_module
from neutrino_agent import AGENT_VERSION
from neutrino_agent.constants import (
    AGENT_BACKOFF_MIN_S,
    AGENT_HEARTBEAT_INTERVAL_S,
    AGENT_WIRE_GENERATION,
    AGENT_WS_PATH,
)
from neutrino_agent.core import self_update
from neutrino_agent.core.loop import IDLE_POLL_INTERVAL_S, Agent
from neutrino_agent.core.metrics import HostMetrics
from neutrino_agent.core.ws_client import SocketClosed
from neutrino_agent.platforms.base import AgentPlatform, PlatformUnsupportedError
from tests.conftest import bind
from tests.core.test_session import ScriptedClient

WELCOME = {"type": "welcome", "hub_version": "0.0.1", "device_id": "d"}
HUNG_UP = channel.GatewayUnreachable("hung up")
# A script entry: the hub hangs up once the first report has gone up.
DROP_AFTER_REPORT = object()


class _FakePlatform(AgentPlatform):
    """A platform with prepared metrics and accounts; the rest refuses."""

    os_name = "linux"

    def __init__(self, *, metrics=None, accounts=None):
        self._metrics = metrics
        self._accounts = accounts

    def read_host_metrics(self):
        if self._metrics is None:
            raise PlatformUnsupportedError("no metrics here")
        return self._metrics

    def human_accounts(self):
        if self._accounts is None:
            raise PlatformUnsupportedError("cannot enumerate accounts here")
        return list(self._accounts)


class ClientScript:
    """Hands the loop one scripted client per connection, in order."""

    def __init__(self, scripts, default=None):
        self.scripts = list(scripts)
        self.default = default if default is not None else [HUNG_UP]
        self.clients: list = []
        self.built: list = []

    def __call__(self, **kwargs):
        self.built.append(kwargs)
        client = ScriptedClient()
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
    assert agent._channel is None

    bind(config_path)
    agent._adopt_external_binding()

    assert agent._channel is not None


def test_a_binding_removed_by_another_process_is_let_go(config_path):
    bind(config_path)
    agent = Agent(log=lambda message: None)
    agent._last_error = {"code": "hub_unreachable", "params": {}}

    config_path.write_text(json.dumps({"device_id": "kept"}))
    agent._adopt_external_binding()

    assert agent._channel is None
    assert agent.last_error() is None


def test_an_untouched_file_reloads_nothing(config_path):
    bind(config_path)
    agent = Agent(log=lambda message: None)
    made = agent._channel

    agent._adopt_external_binding()

    assert agent._channel is made


def test_a_rewrite_of_the_same_binding_wipes_no_state(config_path):
    bind(config_path)
    agent = Agent(log=lambda message: None)
    agent._refusals = 2

    bind(config_path)
    agent._adopt_external_binding()

    assert agent._refusals == 2


def test_adopt_binding_a_changed_url_swaps_the_channel_and_clears_state(config_path):
    bind(config_path)
    agent = Agent(log=lambda message: None)
    agent._update_target = "9.9.9"
    agent._update_error = {"code": "agent_update_launch_failed", "params": {}}

    bind(config_path, url="http://127.0.0.1:10")
    agent._adopt_external_binding()

    assert agent._binding[0] == "http://127.0.0.1:10"
    assert agent._channel is not None
    assert agent._update_target == ""
    assert agent.last_error() is None


def test_a_changed_binding_closes_the_live_socket(config_path, monkeypatch):
    agent, script = scripted_agent(config_path, monkeypatch, [[WELCOME]])
    session = agent._open_session()
    session.connect()
    agent._session = session

    config_path.write_text(json.dumps({"device_id": "kept"}))
    agent._adopt_external_binding()

    assert script.clients[0].is_closed
    assert agent._session is None


def test_disconnect_leaves_the_service_unbound(config_path, monkeypatch):
    agent, script = scripted_agent(config_path, monkeypatch, [[WELCOME]])
    left: list = []
    agent._channel.post = lambda path, payload: left.append(path) or {}
    session = agent._open_session()
    session.connect()
    agent._session = session

    agent.disconnect()

    assert left == ["/api/agent/leave"]
    assert agent._channel is None
    assert script.clients[0].is_closed
    assert "gateway_url" not in json.loads(config_path.read_text())


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
    config_path.write_text(
        json.dumps(
            {
                "gateway_url": "https://hub.lan:8443",
                "token": "tok",
                "fingerprint": "ab" * 32,
            }
        )
    )
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


def test_the_hello_carries_the_wire_contract(config_path, monkeypatch):
    platform = _FakePlatform(metrics=HostMetrics(), accounts=["alice", "bob"])
    agent, script = scripted_agent(
        config_path, monkeypatch, [welcomed_then_dropped()], platform=platform
    )
    monkeypatch.setattr(loop_module, "hostname", lambda: "box")
    monkeypatch.setattr(
        loop_module.enrollment,
        "machine_addresses",
        lambda: [{"mac": "aa:bb:cc:dd:ee:ff", "address": "192.168.100.7"}],
    )

    agent.run_once()

    (hello,) = script.clients[0].frames("hello")
    assert hello == {
        "type": "hello",
        "token": "tok",
        "client_version": AGENT_VERSION,
        "wire": AGENT_WIRE_GENERATION,
        "hostname": "box",
        "platform": agent.platform(),
        "addresses": [{"mac": "aa:bb:cc:dd:ee:ff", "address": "192.168.100.7"}],
        "accounts": ["alice", "bob"],
        "state_hash": "",
    }


def test_the_report_carries_every_field_from_its_source(config_path, monkeypatch):
    metrics = HostMetrics(cpu_percent=12.3, memory_percent=56.7, uptime_s=7)
    platform = _FakePlatform(metrics=metrics, accounts=["alice", "bob"])
    agent, script = scripted_agent(
        config_path, monkeypatch, [welcomed_then_dropped()], platform=platform
    )
    monkeypatch.setattr(loop_module.enrollment, "machine_addresses", lambda: [])

    agent.run_once()

    (report,) = script.clients[0].frames("report")
    assert report["type"] == "report"
    assert report["metrics"]["cpu_percent"] == 12.3
    assert report["metrics"]["uptime_s"] == 7
    assert report["platform"] == agent.platform()
    assert report["addresses"] == []
    assert report["accounts"] == ["alice", "bob"]
    assert report["modules"] == agent.module_states()
    assert report["state_hash"] == ""
    assert report["state_error"] is None
    assert set(report["rdp"]) == {
        "is_shared",
        "account",
        "share_id",
        "port",
        "attention",
    }
    assert report["rdp"]["is_shared"] is False
    assert report["last_error"] is None


def test_report_metrics_platform_cannot_read_sends_the_empty_shape(
    config_path, monkeypatch
):
    platform = _FakePlatform(metrics=None, accounts=[])
    agent, script = scripted_agent(
        config_path, monkeypatch, [welcomed_then_dropped()], platform=platform
    )

    agent.run_once()

    (report,) = script.clients[0].frames("report")
    assert report["metrics"] == HostMetrics().to_dict()


def test_report_accounts_platform_cannot_enumerate_sends_an_empty_list(
    config_path, monkeypatch
):
    platform = _FakePlatform(metrics=HostMetrics(), accounts=None)
    agent, script = scripted_agent(
        config_path, monkeypatch, [welcomed_then_dropped()], platform=platform
    )

    agent.run_once()

    (hello,) = script.clients[0].frames("hello")
    assert hello["accounts"] == []


def test_the_last_error_rides_the_next_connections_report(config_path, monkeypatch):
    agent, script = scripted_agent(
        config_path,
        monkeypatch,
        [channel.GatewayUnreachable("gone"), welcomed_then_dropped()],
    )

    agent.run_once()
    assert agent.last_error()["code"] == "hub_unreachable"
    agent.run_once()

    # A welcome clears it: the report that follows carries none.
    (report,) = script.clients[1].frames("report")
    assert report["last_error"] is None


# --- rejections, and the three-refusal unbind ---


def refused(code: int, reason: str) -> list:
    return [SocketClosed(code, reason)]


def test_repeated_refusals_unbind_the_machine(config_path, monkeypatch):
    agent, _ = scripted_agent(
        config_path, monkeypatch, [refused(4401, "unknown_token")] * 3
    )

    delays = [agent.run_once() for _ in range(3)]

    assert delays[:2] == [AGENT_HEARTBEAT_INTERVAL_S] * 2
    assert delays[2] == IDLE_POLL_INTERVAL_S
    assert agent._channel is None
    assert "gateway_url" not in json.loads(config_path.read_text())
    assert agent.last_error() == {
        "code": "self_unbound",
        "params": {"cause": "hub_refused"},
    }


def test_a_single_refusal_keeps_the_binding(config_path, monkeypatch):
    agent, _ = scripted_agent(config_path, monkeypatch, [refused(4401, "x")])

    agent.run_once()

    assert agent._channel is not None
    assert agent.last_error()["code"] == "hub_refused"


def test_mixed_rejection_kinds_total_to_an_unbind(config_path, monkeypatch):
    agent, _ = scripted_agent(
        config_path,
        monkeypatch,
        [
            channel.GatewayUntrusted("wrong pin"),
            refused(4409, "agent_newer_than_hub"),
            refused(4401, "unknown_token"),
        ],
    )

    for _ in range(3):
        agent.run_once()

    assert agent._channel is None
    assert agent.last_error()["params"]["cause"] == "hub_refused"


def test_an_unreachable_connect_neither_counts_nor_resets(config_path, monkeypatch):
    agent, _ = scripted_agent(
        config_path,
        monkeypatch,
        [
            refused(4401, "x"),
            channel.GatewayUnreachable("gone"),
            channel.GatewayUnreachable("gone"),
            refused(4401, "x"),
        ],
    )

    delays = [agent.run_once() for _ in range(4)]

    assert delays[1:3] == [AGENT_BACKOFF_MIN_S, AGENT_BACKOFF_MIN_S * 2]
    assert agent._refusals == 2
    assert agent._channel is not None


def test_a_welcome_resets_the_rejection_count_and_the_backoff(config_path, monkeypatch):
    agent, _ = scripted_agent(
        config_path,
        monkeypatch,
        [
            refused(4401, "x"),
            channel.GatewayUnreachable("gone"),
            welcomed_then_dropped(),
            refused(4401, "x"),
            refused(4401, "x"),
        ],
    )

    for _ in range(5):
        agent.run_once()

    assert agent._refusals == 2
    assert agent._channel is not None


def test_a_replaced_socket_counts_for_nothing_and_backs_off(config_path, monkeypatch):
    agent, _ = scripted_agent(
        config_path,
        monkeypatch,
        [[WELCOME, SocketClosed(4410, "replaced")]] * 3,
    )

    delays = [agent.run_once() for _ in range(3)]

    assert delays == [AGENT_BACKOFF_MIN_S, AGENT_BACKOFF_MIN_S, AGENT_BACKOFF_MIN_S]
    assert agent._refusals == 0
    assert agent._channel is not None
    assert agent.last_error()["code"] == "hub_unreachable"


def test_a_refusal_after_the_welcome_counts_toward_the_unbind(config_path, monkeypatch):
    """A hub that forgets the device closes its live socket with 4401; the
    reconnects are refused before any welcome, and the three add up."""
    agent, _ = scripted_agent(
        config_path,
        monkeypatch,
        [[WELCOME, SocketClosed(4401, "unknown_token")]] + [refused(4401, "x")] * 2,
    )

    delays = [agent.run_once() for _ in range(3)]

    assert delays[0] == AGENT_HEARTBEAT_INTERVAL_S
    assert agent._channel is None


def test_an_adopted_binding_starts_with_a_clean_count(config_path, monkeypatch):
    agent, _ = scripted_agent(config_path, monkeypatch, [refused(4401, "x")] * 2)
    agent.run_once()
    agent.run_once()
    assert agent._refusals == 2

    bind(config_path, url="http://127.0.0.1:10")
    agent._adopt_external_binding()

    assert agent._refusals == 0


# --- the wire generation ---


def test_a_stale_wire_answer_reinstalls_and_never_unbinds(config_path, monkeypatch):
    agent, _ = scripted_agent(
        config_path, monkeypatch, [refused(4409, "agent_wire_stale")] * 4
    )
    installed = []
    monkeypatch.setattr(loop_module.self_update, "package_kind", lambda platform: "deb")
    monkeypatch.setattr(
        loop_module.self_update,
        "run_update",
        lambda posting, kind, architecture: installed.append(kind),
    )

    delays = [agent.run_once() for _ in range(4)]

    assert delays == [AGENT_HEARTBEAT_INTERVAL_S] * 4
    # Once per target: the same answer again relaunches nothing.
    assert installed == ["deb"]
    assert agent._channel is not None
    assert agent.last_error()["code"] == "agent_wire_stale"


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (
            self_update.SelfUpdateError("agent_package_digest_mismatch"),
            "agent_package_digest_mismatch",
        ),
        (
            channel.GatewayUnreachable("cannot reach gateway: gone"),
            "agent_update_fetch_failed",
        ),
    ],
)
def test_wire_stale_a_failed_reinstall_is_coded_and_not_retried(
    config_path, monkeypatch, error, code
):
    agent, _ = scripted_agent(
        config_path, monkeypatch, [refused(4409, "agent_wire_stale")] * 2
    )
    attempts = []

    def fail(posting, kind, architecture):
        attempts.append(kind)
        raise error

    monkeypatch.setattr(loop_module.self_update, "package_kind", lambda platform: "deb")
    monkeypatch.setattr(loop_module.self_update, "run_update", fail)

    agent.run_once()
    agent.run_once()

    assert attempts == ["deb"]
    assert agent._update_error == {"code": code, "params": {"target": "wire-0"}}
    assert agent.last_error()["code"] == "agent_wire_stale"


def test_wire_stale_platform_without_a_package_installs_nothing(
    config_path, monkeypatch
):
    agent, _ = scripted_agent(
        config_path, monkeypatch, [refused(4409, "agent_wire_stale")]
    )
    monkeypatch.setattr(loop_module.self_update, "package_kind", lambda platform: "")
    installed = []
    monkeypatch.setattr(
        loop_module.self_update,
        "run_update",
        lambda posting, kind, architecture: installed.append(kind),
    )

    agent.run_once()

    assert installed == []
    assert agent._channel is not None
    assert agent._update_error["code"] == "agent_package_missing"


# --- the welcome's hub version ---


def test_a_newer_hub_launches_the_self_update_once_per_target(config_path, monkeypatch):
    newer = dict(WELCOME, hub_version="99.0.0")
    agent, _ = scripted_agent(
        config_path, monkeypatch, [[newer, DROP_AFTER_REPORT]] * 2
    )
    installed = []
    monkeypatch.setattr(loop_module.self_update, "package_kind", lambda platform: "deb")
    monkeypatch.setattr(
        loop_module.self_update,
        "run_update",
        lambda posting, kind, architecture: installed.append(kind),
    )

    agent.run_once()
    agent.run_once()

    assert installed == ["deb"]


def test_an_older_or_equal_hub_updates_nothing(config_path, monkeypatch):
    agent, _ = scripted_agent(config_path, monkeypatch, [welcomed_then_dropped()])
    installed = []
    monkeypatch.setattr(loop_module.self_update, "package_kind", lambda platform: "deb")
    monkeypatch.setattr(
        loop_module.self_update,
        "run_update",
        lambda posting, kind, architecture: installed.append(kind),
    )

    agent.run_once()

    assert installed == []


# --- commands and the reinstall order ---


def test_a_reinstall_command_forces_the_self_update(config_path, monkeypatch):
    agent, _ = scripted_agent(config_path, monkeypatch)
    installed = []
    monkeypatch.setattr(loop_module.self_update, "package_kind", lambda platform: "deb")
    monkeypatch.setattr(
        loop_module.self_update,
        "run_update",
        lambda posting, kind, architecture: installed.append(kind),
    )

    outcome = agent._run_command("reinstall", {})

    assert installed == ["deb"]
    assert outcome == {
        "exit_code": 0,
        "code": "",
        "params": {},
        "output": "reinstall launched\n",
    }


def test_a_command_with_no_binding_is_typed(config_path, monkeypatch):
    agent, _ = scripted_agent(config_path, monkeypatch)
    agent._operator = None

    outcome = agent._run_command("reboot", {})

    assert outcome["code"] == "hub_unreachable"
    assert outcome["exit_code"] == 1


# --- sync and probe ---


def test_sync_with_no_socket_is_typed(config_path, monkeypatch):
    agent, _ = scripted_agent(config_path, monkeypatch)

    assert agent.sync() == {"code": "hub_unreachable", "params": {}}


def test_sync_sends_a_state_request_on_the_live_socket(config_path, monkeypatch):
    agent, script = scripted_agent(config_path, monkeypatch, [[WELCOME]])
    session = agent._open_session()
    session.connect()
    agent._session = session

    assert agent.sync() == {}

    assert script.clients[0].frames("state_request") == [{"type": "state_request"}]
    session.close()


def test_probe_connects_once_and_closes(config_path, monkeypatch):
    agent, script = scripted_agent(config_path, monkeypatch, [[WELCOME]])

    agent.probe()

    assert agent.last_error() is None
    assert script.clients[0].frames("hello")
    assert script.clients[0].frames("report") == []
    assert script.clients[0].is_closed


def test_probe_reports_a_refusal_without_counting_it(config_path, monkeypatch):
    agent, _ = scripted_agent(config_path, monkeypatch, [refused(4401, "x")])

    agent.probe()

    assert agent.last_error()["code"] == "hub_refused"
    assert agent._refusals == 0
    assert agent._channel is not None


def test_probe_while_unbound_does_nothing(config_path, monkeypatch):
    agent = Agent(log=lambda message: None)

    agent.probe()

    assert agent.last_error() is None


def test_an_unbound_agent_idles(config_path, monkeypatch):
    agent = Agent(log=lambda message: None)

    assert agent.run_once() == IDLE_POLL_INTERVAL_S
