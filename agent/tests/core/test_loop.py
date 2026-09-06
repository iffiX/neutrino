"""One agent, driven beat by beat with a scripted channel.

What these pin: every field the heartbeat payload carries and where each
comes from; every shape a reply may take — including shapes this build
cannot read, which become a typed ``last_error`` and never a dead process;
the rejection counter and the three-beat self-unbind; the wire-generation
reinstall and its once-per-target latch; the binding file shared with the
CLI; and the commands a reply queues. Nothing here talks to a network.
"""

import json
import os

import pytest

import neutrino_agent.core.channel as channel
import neutrino_agent.core.loop as loop_module
from neutrino_agent.constants import (
    AGENT_HEARTBEAT_INTERVAL_S,
    AGENT_HEARTBEAT_PATH,
    AGENT_RESULT_PATH,
    AGENT_WIRE_GENERATION,
)
from neutrino_agent.core import self_update
from neutrino_agent.core.commands import CommandOutcome
from neutrino_agent.core.loop import Agent
from neutrino_agent.core.metrics import HostMetrics
from neutrino_agent.platforms.base import AgentPlatform, PlatformUnsupportedError
from neutrino_agent.platforms.detect import platform_tuple
from tests.conftest import bind


def test_a_binding_written_by_another_process_is_adopted(config_path):
    agent = Agent(log=lambda message: None)
    assert agent._channel is None

    bind(config_path)
    agent._adopt_external_binding()

    assert agent._channel is not None


def test_a_binding_removed_by_another_process_is_let_go(config_path):
    bind(config_path)
    agent = Agent(log=lambda message: None)
    agent._pending = {"ai_tools": {"is_enabled": False}}

    config_path.write_text(json.dumps({"device_id": "kept"}))
    agent._adopt_external_binding()

    assert agent._channel is None
    assert agent._pending == {}


def test_an_untouched_file_reloads_nothing(config_path):
    bind(config_path)
    agent = Agent(log=lambda message: None)
    channel = agent._channel

    agent._adopt_external_binding()

    assert agent._channel is channel


def test_a_rewrite_of_the_same_binding_wipes_no_state(config_path):
    bind(config_path)
    agent = Agent(log=lambda message: None)
    agent._pending = {"ai_tools": {"is_enabled": True}}

    bind(config_path)
    agent._adopt_external_binding()

    assert agent._pending == {"ai_tools": {"is_enabled": True}}
    assert agent._channel is not None


def test_disconnect_leaves_the_service_unbound(config_path):
    bind(config_path)
    agent = Agent(log=lambda message: None)

    agent.disconnect()

    assert agent._channel is None
    stored = json.loads(config_path.read_text())
    assert "gateway_url" not in stored and "token" not in stored
    agent._adopt_external_binding()
    assert agent._channel is None


def test_repeated_refusals_unbind_the_machine(config_path, monkeypatch):
    bind(config_path)
    agent = Agent(log=lambda message: None)

    def refuse(path, payload):
        raise channel.GatewayRefused("gateway refused this machine's token (401)")

    monkeypatch.setattr(agent._channel, "post", refuse)
    delays = [agent.run_once() for _ in range(3)]

    assert agent._channel is None
    assert "gateway_url" not in json.loads(config_path.read_text())
    assert agent.last_error() == {
        "code": "self_unbound",
        "params": {"cause": "hub_refused"},
    }
    assert delays[-1] == 2


def test_a_single_refusal_keeps_the_binding(config_path, monkeypatch):
    bind(config_path)
    agent = Agent(log=lambda message: None)

    def refuse(path, payload):
        raise channel.GatewayRefused("gateway refused this machine's token (401)")

    monkeypatch.setattr(agent._channel, "post", refuse)
    agent.run_once()

    assert agent._channel is not None
    assert "gateway_url" in json.loads(config_path.read_text())


def answer_in_turn(agent, monkeypatch, answers):
    """Make the channel raise, or reply, one prepared answer per beat."""

    def answer(path, payload):
        outcome = answers.pop(0)
        if outcome is not None:
            raise outcome
        return {"module_orders": [], "catalog_hash": ""}

    monkeypatch.setattr(agent._channel, "post", answer)


def test_mixed_rejection_kinds_total_to_an_unbind(config_path, monkeypatch):
    bind(config_path)
    agent = Agent(log=lambda message: None)
    answer_in_turn(
        agent,
        monkeypatch,
        [
            channel.GatewayRefused("gateway refused this machine's token (401)"),
            channel.GatewayUntrusted(
                "the gateway's certificate does not match the pinned fingerprint"
            ),
            channel.GatewayVersionRefused(hub_version="0.1.0", agent_version="0.2.0"),
        ],
    )

    for _ in range(3):
        agent.run_once()

    assert agent._channel is None
    assert "gateway_url" not in json.loads(config_path.read_text())
    # The reason names the rejection that tipped the counter.
    assert agent.last_error() == {
        "code": "self_unbound",
        "params": {"cause": "agent_newer_than_hub"},
    }


def test_an_unreachable_beat_neither_counts_nor_resets(config_path, monkeypatch):
    """Only a successful beat resets the rejection counter; a broken wire in
    the middle of a run of rejections leaves the count standing."""
    bind(config_path)
    agent = Agent(log=lambda message: None)
    refused = "gateway refused this machine's token (401)"
    answer_in_turn(
        agent,
        monkeypatch,
        [
            channel.GatewayRefused(refused),
            channel.GatewayRefused(refused),
            channel.GatewayUnreachable("cannot reach gateway: timed out"),
            channel.GatewayRefused(refused),
        ],
    )

    for _ in range(3):
        agent.run_once()
    assert agent._channel is not None
    assert agent._refusals == 2

    agent.run_once()
    assert agent._channel is None
    assert "gateway_url" not in json.loads(config_path.read_text())


def test_a_successful_beat_resets_the_rejection_count(config_path, monkeypatch):
    bind(config_path)
    agent = Agent(log=lambda message: None)
    refused = "gateway refused this machine's token (401)"
    answer_in_turn(
        agent,
        monkeypatch,
        [
            channel.GatewayRefused(refused),
            channel.GatewayRefused(refused),
            None,
            channel.GatewayRefused(refused),
        ],
    )

    for _ in range(4):
        agent.run_once()

    assert agent._channel is not None
    assert agent._refusals == 1
    assert "gateway_url" in json.loads(config_path.read_text())


def test_an_adopted_binding_starts_with_a_clean_count(config_path, monkeypatch):
    bind(config_path)
    agent = Agent(log=lambda message: None)
    refused = "gateway refused this machine's token (401)"
    answer_in_turn(
        agent,
        monkeypatch,
        [
            channel.GatewayRefused(refused),
            channel.GatewayRefused(refused),
        ],
    )
    for _ in range(2):
        agent.run_once()

    bind(config_path, url="http://127.0.0.1:10")
    agent._adopt_external_binding()

    assert agent._refusals == 0


def test_the_heartbeat_carries_the_wire_contract(config_path, monkeypatch):
    """Up: accounts, modules, module_requests, ai_targets and a coded
    last_error; the pre-rename field names never appear."""
    bind(config_path)
    agent = Agent(log=lambda message: None)
    seen = {}

    def record(path, payload):
        seen.update(payload)
        return {"module_orders": [], "catalog_hash": ""}

    monkeypatch.setattr(agent._channel, "post", record)
    agent.run_once()

    for key in (
        "hostname",
        "client_version",
        "wire",
        "metrics",
        "platform",
        "accounts",
        "catalog_hash",
        "modules",
        "module_requests",
        "ai_targets",
        "last_error",
    ):
        assert key in seen
    assert "functions" not in seen and "function_requests" not in seen
    assert isinstance(seen["accounts"], list)
    assert isinstance(seen["ai_targets"], dict)
    assert seen["last_error"] is None


class _RaisingChannel:
    def __init__(self, error):
        self._error = error

    def post(self, path, payload):
        raise self._error


class _ReplyingChannel:
    def __init__(self, reply):
        self._reply = reply

    def post(self, path, payload):
        return self._reply


def test_a_stale_wire_answer_reinstalls_and_never_unbinds(config_path, monkeypatch):
    """The 409 about this build is not about the binding: no refusal is
    counted, the error is typed, and the reinstall runs once per target."""
    bind(config_path)
    agent = Agent(log=lambda message: None)
    installed = []
    monkeypatch.setattr(loop_module.self_update, "package_kind", lambda platform: "deb")
    monkeypatch.setattr(
        loop_module.self_update,
        "run_update",
        lambda posting, kind: installed.append(kind),
    )
    agent._channel = _RaisingChannel(channel.GatewayWireStale(hub_wire=2, agent_wire=1))

    for _ in range(4):
        agent.run_once()

    assert installed == ["deb"]
    assert agent.last_error() == {
        "code": "agent_wire_stale",
        "params": {"hub_wire": 2, "agent_wire": 1},
    }
    assert agent._refusals == 0
    assert agent._channel is not None


def test_three_version_refused_beats_unbind(config_path, monkeypatch):
    bind(config_path)
    agent = Agent(log=lambda message: None)

    def refuse(path, payload):
        raise channel.GatewayVersionRefused(hub_version="0.1.0", agent_version="0.2.0")

    monkeypatch.setattr(agent._channel, "post", refuse)
    delays = [agent.run_once() for _ in range(3)]

    assert agent._channel is None
    assert "gateway_url" not in json.loads(config_path.read_text())
    assert agent.last_error() == {
        "code": "self_unbound",
        "params": {"cause": "agent_newer_than_hub"},
    }
    # Counted beats wait one plain interval — no backoff, this is an answer,
    # not an outage — and the third drops to the unbound idle poll.
    assert delays == [5, 5, 2]


def test_two_version_refused_beats_keep_the_binding(config_path, monkeypatch):
    bind(config_path)
    agent = Agent(log=lambda message: None)

    def refuse(path, payload):
        raise channel.GatewayVersionRefused(hub_version="0.1.0", agent_version="0.2.0")

    monkeypatch.setattr(agent._channel, "post", refuse)
    for _ in range(2):
        agent.run_once()

    assert agent._channel is not None
    assert "gateway_url" in json.loads(config_path.read_text())
    assert agent.last_error()["code"] == "agent_newer_than_hub"


def test_a_reply_this_build_cannot_read_is_reported_not_fatal(config_path):
    """A hub speaking another shape must never take the process down."""
    bind(config_path)
    agent = Agent(log=lambda message: None)
    agent._channel = _ReplyingChannel(
        {
            "module_orders": [],
            # The pre-generation dict shape where a list is expected.
            "catalog": {"modules": {}, "services": {"ai": {"kind": "ai"}}},
            "catalog_hash": "x",
            "ai_accounts": {},
            "commands": [],
            "hub_version": "0.1.0",
        }
    )

    delay = agent.run_once()

    assert delay > 0
    assert agent._channel is not None


class _ScriptedChannel:
    """Answers each post from a prepared script and records every call."""

    def __init__(self, script=None):
        self.script = list(script or [])
        self.posts = []

    def post(self, path, payload):
        self.posts.append((path, payload))
        if not self.script:
            return {"module_orders": [], "catalog_hash": ""}
        outcome = self.script.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


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


class _FakeOperator:
    """Records what a command asked and answers a prepared outcome."""

    def __init__(self, outcome=None):
        self.calls = []
        self.outcome = outcome or CommandOutcome(exit_code=0, output="done\n")

    def run(self, action, args):
        self.calls.append((action, dict(args)))
        return self.outcome


def scripted_agent(config_path, script=None, *, platform=None):
    """A bound agent whose channel answers from a script, off the network."""
    bind(config_path)
    if platform is None:
        platform = _FakePlatform(metrics=HostMetrics(), accounts=["alice", "bob"])
    agent = Agent(log=lambda message: None, platform=platform)
    agent._channel = _ScriptedChannel(script)
    return agent


def test_the_stores_live_under_the_platforms_data_root():
    platform = _FakePlatform(metrics=HostMetrics(), accounts=[])
    agent = Agent(log=lambda message: None, platform=platform)

    root = platform.agent_data_dir()
    assert agent._store._path == os.path.join(root, "services.json")
    assert agent._services["file"]._credentials_dir == os.path.join(
        root, "mount_credentials"
    )


def test_heartbeat_payload_every_field_comes_from_its_source(config_path, monkeypatch):
    metrics = HostMetrics(cpu_percent=12.34, memory_percent=56.78, uptime_s=7)
    platform = _FakePlatform(metrics=metrics, accounts=["alice", "bob"])
    agent = scripted_agent(config_path, platform=platform)
    monkeypatch.setattr(loop_module, "hostname", lambda: "census-box")
    agent._store.set_ai_target("alice", is_activated=True)
    agent.request_module("openssh_server", is_enabled=True)

    agent.run_once()

    path, payload = agent._channel.posts[0]
    assert path == AGENT_HEARTBEAT_PATH
    # The census is closed: a new payload field lands with its test.
    assert set(payload) == {
        "hostname",
        "client_version",
        "wire",
        "metrics",
        "platform",
        "accounts",
        "catalog_hash",
        "modules",
        "module_requests",
        "module_results",
        "ai_targets",
        "rdp_share",
        "last_error",
    }
    assert payload["hostname"] == "census-box"
    assert payload["client_version"] == loop_module.AGENT_VERSION
    assert payload["wire"] == AGENT_WIRE_GENERATION
    assert payload["metrics"] == metrics.to_dict()
    assert payload["platform"] == platform_tuple()
    assert payload["accounts"] == ["alice", "bob"]
    assert payload["catalog_hash"] == ""
    assert payload["modules"] == agent.module_states()
    assert payload["module_requests"] == {"openssh_server": {"is_enabled": True}}
    # What is true and what the last order produced; the machine answers
    # for both and for nothing else about modules.
    assert payload["module_results"] == []
    assert payload["ai_targets"] == {"alice": True}
    assert payload["last_error"] is None


def test_heartbeat_metrics_platform_cannot_read_sends_the_empty_shape(config_path):
    agent = scripted_agent(config_path, platform=_FakePlatform(accounts=["alice"]))

    agent.run_once()

    _, payload = agent._channel.posts[0]
    assert payload["metrics"] == HostMetrics().to_dict()


def test_heartbeat_accounts_platform_cannot_enumerate_sends_an_empty_list(
    config_path,
):
    agent = scripted_agent(config_path, platform=_FakePlatform(metrics=HostMetrics()))

    agent.run_once()

    _, payload = agent._channel.posts[0]
    assert payload["accounts"] == []


def test_heartbeat_catalog_hash_after_a_catalog_lands_echoes_the_hubs(config_path):
    agent = scripted_agent(
        config_path,
        [
            {
                "module_orders": [],
                "catalog": {"modules": {}, "services": []},
                "catalog_hash": "h1",
            }
        ],
    )

    agent.run_once()
    agent.run_once()

    _, second = agent._channel.posts[1]
    assert second["catalog_hash"] == "h1"
    assert agent.catalog() == {"modules": {}, "services": []}


def test_heartbeat_module_requests_accepted_beat_drops_them(config_path):
    agent = scripted_agent(config_path)
    agent.request_module("openssh_server", is_enabled=True)

    agent.run_once()
    agent.run_once()

    _, first = agent._channel.posts[0]
    _, second = agent._channel.posts[1]
    assert first["module_requests"] == {"openssh_server": {"is_enabled": True}}
    assert second["module_requests"] == {}


def test_heartbeat_last_error_after_a_failed_beat_rides_the_next_payload(config_path):
    agent = scripted_agent(
        config_path,
        [channel.GatewayUnreachable("cannot reach gateway: timed out")],
    )

    agent.run_once()
    agent.run_once()

    _, second = agent._channel.posts[1]
    assert second["last_error"] == {
        "code": "hub_unreachable",
        "params": {"detail": "cannot reach gateway: timed out"},
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("module_orders", 5),
        ("module_orders", {"broken": 1}),
        ("catalog", 5),
        ("catalog", ["broken"]),
        ("ai_accounts", 5),
        ("ai_accounts", ["alice"]),
        ("commands", 5),
        ("commands", ["reboot"]),
        ("commands", None),
    ],
)
def test_reply_field_of_the_wrong_type_is_typed_and_never_fatal(
    config_path, field, value
):
    reply = {"module_orders": [], "catalog_hash": ""}
    reply[field] = value
    agent = scripted_agent(config_path, [reply])

    delay = agent.run_once()

    assert delay == AGENT_HEARTBEAT_INTERVAL_S
    assert agent.last_error()["code"] == "hub_reply_unreadable"
    assert agent._channel is not None
    assert agent._refusals == 0


def test_reply_with_every_field_missing_applies_as_empty_truth(config_path):
    agent = scripted_agent(config_path, [{}])
    agent._pending = {"openssh_server": {"is_enabled": True}}

    delay = agent.run_once()

    assert delay == AGENT_HEARTBEAT_INTERVAL_S
    assert agent.last_error() is None
    assert agent._engine.report() == {}


def test_reply_fields_of_none_read_as_absent(config_path):
    agent = scripted_agent(
        config_path,
        [
            {
                "module_orders": None,
                "catalog": None,
                "ai_accounts": None,
                "hub_version": None,
            }
        ],
    )

    delay = agent.run_once()

    assert delay == AGENT_HEARTBEAT_INTERVAL_S
    assert agent.last_error() is None
    assert agent._engine.report() == {}


def test_reply_that_is_not_an_object_is_typed_and_never_fatal(config_path):
    agent = scripted_agent(config_path, [["not", "an", "object"]])

    delay = agent.run_once()

    assert delay == AGENT_HEARTBEAT_INTERVAL_S
    assert agent.last_error()["code"] == "hub_reply_unreadable"
    assert agent._channel is not None


def test_reply_coercible_fields_of_the_wrong_type_are_stringified(
    config_path, monkeypatch
):
    """``catalog_hash`` and ``hub_version`` are read through ``str``, so a
    number lands as its text and drives the same paths."""
    monkeypatch.setattr(loop_module, "AGENT_VERSION", "1.0.0")
    installed = []
    monkeypatch.setattr(loop_module.self_update, "package_kind", lambda platform: "deb")
    monkeypatch.setattr(
        loop_module.self_update,
        "run_update",
        lambda posting, kind: installed.append(kind),
    )
    agent = scripted_agent(
        config_path,
        [
            {
                "module_orders": [],
                "catalog": {"modules": {}, "services": []},
                "catalog_hash": 123,
                "hub_version": 999,
            }
        ],
    )

    agent.run_once()
    agent.run_once()

    _, second = agent._channel.posts[1]
    assert second["catalog_hash"] == "123"
    assert installed == ["deb"]
    assert agent.last_error() is None


def test_reply_unreadable_keeps_the_state_a_good_beat_applied(config_path):
    agent = scripted_agent(
        config_path,
        [
            {
                "module_orders": [],
                "catalog": {"modules": {}, "services": []},
                "catalog_hash": "h1",
            },
            {"module_orders": "broken", "catalog_hash": "h2"},
        ],
    )

    agent.run_once()
    delay = agent.run_once()

    assert delay == AGENT_HEARTBEAT_INTERVAL_S
    assert agent.last_error()["code"] == "hub_reply_unreadable"
    assert agent.catalog() == {"modules": {}, "services": []}
    assert agent._engine.catalog_hash == "h1"


def test_reply_catalog_unreadable_never_claims_the_replys_hash(config_path):
    """Reporting the hash of a catalog this build could not keep would stop
    the hub ever re-sending it."""
    agent = scripted_agent(
        config_path,
        [{"module_orders": [], "catalog": 5, "catalog_hash": "h9"}],
    )

    delay = agent.run_once()

    assert delay == AGENT_HEARTBEAT_INTERVAL_S
    assert agent.last_error()["code"] == "hub_reply_unreadable"
    assert agent.catalog() == {}

    agent.run_once()
    _, second = agent._channel.posts[1]
    assert second["catalog_hash"] == ""


def test_reply_unreadable_beats_never_count_toward_unbinding(config_path):
    agent = scripted_agent(config_path, [{"commands": None}] * 3)

    for _ in range(3):
        agent.run_once()

    assert agent._channel is not None
    assert agent._refusals == 0
    assert "gateway_url" in json.loads(config_path.read_text())


def test_reply_readable_again_clears_the_typed_error(config_path):
    agent = scripted_agent(config_path, [{"commands": None}])

    agent.run_once()
    assert agent.last_error()["code"] == "hub_reply_unreadable"

    agent.run_once()
    assert agent.last_error() is None


def test_wire_stale_a_new_generation_target_relaunches_the_reinstall(
    config_path, monkeypatch
):
    agent = scripted_agent(
        config_path,
        [
            channel.GatewayWireStale(hub_wire=2, agent_wire=1),
            channel.GatewayWireStale(hub_wire=2, agent_wire=1),
            channel.GatewayWireStale(hub_wire=3, agent_wire=1),
        ],
    )
    installed = []
    monkeypatch.setattr(loop_module.self_update, "package_kind", lambda platform: "deb")
    monkeypatch.setattr(
        loop_module.self_update,
        "run_update",
        lambda posting, kind: installed.append(kind),
    )

    for _ in range(3):
        agent.run_once()

    assert installed == ["deb", "deb"]


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
    agent = scripted_agent(
        config_path,
        [
            channel.GatewayWireStale(hub_wire=2, agent_wire=1),
            channel.GatewayWireStale(hub_wire=2, agent_wire=1),
        ],
    )
    attempts = []

    def fail(posting, kind):
        attempts.append(kind)
        raise error

    monkeypatch.setattr(loop_module.self_update, "package_kind", lambda platform: "deb")
    monkeypatch.setattr(loop_module.self_update, "run_update", fail)

    agent.run_once()
    agent.run_once()

    assert attempts == ["deb"]
    assert agent._update_error == {"code": code, "params": {"target": "wire-2"}}
    assert agent.last_error()["code"] == "agent_wire_stale"


def test_wire_stale_platform_without_a_package_installs_nothing(
    config_path, monkeypatch
):
    agent = scripted_agent(
        config_path,
        [
            channel.GatewayWireStale(hub_wire=2, agent_wire=1),
            channel.GatewayWireStale(hub_wire=2, agent_wire=1),
        ],
    )
    monkeypatch.setattr(loop_module.self_update, "package_kind", lambda platform: "")
    installed = []
    monkeypatch.setattr(
        loop_module.self_update,
        "run_update",
        lambda posting, kind: installed.append(kind),
    )

    delays = [agent.run_once() for _ in range(2)]

    assert installed == []
    assert delays == [AGENT_HEARTBEAT_INTERVAL_S] * 2
    assert agent.last_error() == {
        "code": "agent_wire_stale",
        "params": {"hub_wire": 2, "agent_wire": 1},
    }
    assert agent._channel is not None


def test_adopt_binding_a_changed_url_swaps_the_channel_and_clears_state(config_path):
    bind(config_path)
    agent = Agent(log=lambda message: None)
    agent._pending = {"openssh_server": {"is_enabled": False}}
    agent._update_target = "9.9.9"
    agent._update_error = {"code": "agent_update_launch_failed", "params": {}}

    bind(config_path, url="http://127.0.0.1:10")
    agent._adopt_external_binding()

    assert agent._binding[0] == "http://127.0.0.1:10"
    assert agent._channel is not None
    assert agent._pending == {}
    assert agent._update_target == ""
    assert agent.last_error() is None


def test_reply_command_runs_and_its_report_is_posted_in_the_same_beat(config_path):
    agent = scripted_agent(
        config_path,
        [
            {
                "module_orders": [],
                "catalog_hash": "",
                "commands": [{"id": "c1", "action": "reboot", "args": {"when": "now"}}],
            },
            {},
        ],
    )
    operator = _FakeOperator(CommandOutcome(exit_code=3, output="denied\n"))
    agent._operator = operator

    delay = agent.run_once()

    assert operator.calls == [("reboot", {"when": "now"})]
    result_path, result = agent._channel.posts[1]
    assert result_path == AGENT_RESULT_PATH
    assert result == {"id": "c1", "exit_code": 3, "output": "denied\n"}
    assert delay == AGENT_HEARTBEAT_INTERVAL_S
    assert agent.last_error() is None


def test_reply_command_without_an_id_reports_under_its_action_name(config_path):
    agent = scripted_agent(
        config_path,
        [
            {
                "module_orders": [],
                "catalog_hash": "",
                "commands": [{"action": "shutdown", "args": {}}],
            },
            {},
        ],
    )
    agent._operator = _FakeOperator()

    agent.run_once()

    _, result = agent._channel.posts[1]
    assert result["id"] == "shutdown"


def test_reply_command_report_post_failure_leaves_the_beat_healthy(config_path):
    agent = scripted_agent(
        config_path,
        [
            {
                "module_orders": [],
                "catalog_hash": "",
                "commands": [{"id": "c1", "action": "reboot", "args": {}}],
            },
            channel.GatewayUnreachable("cannot reach gateway: gone"),
        ],
    )
    agent._operator = _FakeOperator()

    delay = agent.run_once()

    assert delay == AGENT_HEARTBEAT_INTERVAL_S
    assert agent.last_error() is None
    assert agent._channel is not None


def test_the_replys_operation_is_the_pages_and_follows_the_hub(config_path):
    operation = {
        "kind": "order",
        "action": "install",
        "title": "FakeDesk",
        "state": "installing",
        "output": "fakedesk: installing",
    }
    agent = scripted_agent(
        config_path,
        [
            {"module_orders": [], "catalog_hash": "", "operation": operation},
            {"module_orders": [], "catalog_hash": "", "operation": None},
        ],
    )

    agent.run_once()
    # The hub holds the one stream; this machine renders its copy.
    assert agent.operation() == operation

    agent.run_once()
    assert agent.operation() is None


def test_an_operation_that_is_not_an_object_reads_as_none(config_path):
    agent = scripted_agent(
        config_path,
        [{"module_orders": [], "catalog_hash": "", "operation": "busy"}],
    )

    agent.run_once()

    assert agent.operation() is None


def test_disconnecting_forgets_the_hubs_operation(config_path):
    operation = {
        "kind": "bootstrap",
        "action": "install",
        "title": "",
        "state": "done",
        "output": "",
    }
    agent = scripted_agent(
        config_path,
        [{"module_orders": [], "catalog_hash": "", "operation": operation}],
    )
    agent.run_once()
    assert agent.operation() is not None

    agent.disconnect()

    assert agent.operation() is None
