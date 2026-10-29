"""One agent, driven turn by turn against a transport a test plays.

What these pin: the transport started as the agent's child and started
again when it ends, a transport that will not start backing off; the
``dial`` sent once per binding with the binding's keys, the token's psk and
the addresses in order, the hub's name first, and sent again only when the
addresses change while no session is up; ``hello`` written on each
``session_open``, the identity card with no token; the report's sections,
``account_details`` among them, the link the session's own address; the
welcome's time setting the hub clock's offset and its address written back
as the binding's; the state's ``urls`` kept on disk; what each refusal does
to the binding, ``binding_unknown`` deleting it, switching the AI tools
back and turning the desktop share off, ``replaced`` dialling no more until
a person acts, and every other code kept while the transport dials again; a
frame this build cannot read the typed error; the ``port`` question
answered from the report and the last state; the AI gateway forward asked
of the transport while the state says ``is_forwarded``; the streams this
side opens on its own connections; the self-update a newer hub's
``software`` triggers once the first report has gone out; a leave, a join,
``sync`` and the status ``probe``; a binding of 0.5 taking the hub's key;
and the relays run with the loop. Nothing here talks to a network beyond
a Unix socket in a temporary directory.
"""

import hashlib
import json
import os
import threading
import time

import pytest

import neutrino_agent.core.enrollment as enrollment_module
import neutrino_agent.core.loop as loop_module
import neutrino_agent.modules.shared.hub_clock as hub_clock_module
from neutrino_agent import AGENT_VERSION
from neutrino_agent.constants import (
    AGENT_BACKOFF_MAX_S,
    AGENT_BACKOFF_MIN_S,
    AGENT_REINSTALL_RESULT_NAME,
    AGENT_REPORT_INTERVAL_S,
    AGENT_SOFTWARE_PREFIX,
    PROTOCOL,
)
from neutrino_agent.core.loop import IDLE_POLL_INTERVAL_S, Agent, link_address
from neutrino_agent.core.metrics import HostMetrics
from neutrino_agent.exceptions import GatewayUnreachable, PlatformUnsupportedError
from neutrino_agent.modules.podman.constants import PODMAN_BINARY
from neutrino_agent.modules.podman.machine_runner import PodmanMachineModuleRunner
from neutrino_agent.modules.shared.hub_clock import HubClock, hub_time
from neutrino_agent.platforms.base import AgentPlatform
from neutrino_agent.streams.shell_session import ShellSession
from tests.conftest import (
    BINDING_ID,
    BINDING_TOKEN,
    HUB_KEY,
    MACHINE_ID,
    PRIVATE_KEY,
    bind,
)
from tests.transport.fake_transport import FakeTransport, one_shot_for, starter_for

LAN_URL = "tcp://192.0.2.1:8443"
OVERLAY_URL = "tcp://100.64.0.1:8443"
NAME_URL = "tcp://hub.neutrino.internal:8443"
MACHINE_URL = "ssh://root@127.0.0.1:50743/run/podman/podman.sock"
AI_ON = {"hash": "h", "ai_tools": {"is_enabled": True, "is_forwarded": True}}
AI_OFF = {"hash": "h", "ai_tools": {"is_enabled": False, "is_forwarded": False}}
INTERFACES = [
    {
        "name": "eth0",
        "mac": "02:00:00:00:00:01",
        "addresses": ["192.0.2.10", "fe80::ff:fe00:1"],
    },
    {"name": "wlan0", "mac": "02:00:00:00:00:02", "addresses": ["10.0.0.5"]},
]


class _FakePlatform(AgentPlatform):
    """A platform with prepared metrics, accounts and interfaces; the rest
    refuses."""

    os_name = "linux"

    def __init__(self, *, metrics=None, accounts=None, interfaces=None, details=None):
        self._metrics = metrics
        self._accounts = accounts
        self._interfaces = interfaces
        self._details = details

    def read_host_metrics(self):
        if self._metrics is None:
            raise PlatformUnsupportedError("no metrics here")
        return self._metrics

    def human_accounts(self):
        if self._accounts is None:
            raise PlatformUnsupportedError("cannot enumerate accounts here")
        return list(self._accounts)

    def account_details(self):
        if self._details is None:
            return super().account_details()
        return list(self._details)

    def account_home(self, account):
        return f"/home/{account}"

    def read_network_interfaces(self):
        if self._interfaces is None:
            raise PlatformUnsupportedError("no interfaces to read here")
        return list(self._interfaces)


def default_platform():
    return _FakePlatform(metrics=HostMetrics(), accounts=["alice", "bob"])


@pytest.fixture
def fake():
    transport = FakeTransport()
    yield transport
    transport.close()


def agent_on(fake, *, config, platform=None, url=LAN_URL, urls=None, is_bound=True):
    """An agent whose transport is the fake, its binding written."""
    if is_bound:
        bind(config, url=url, urls=urls)
    return Agent(
        log=lambda message: None,
        platform=platform or default_platform(),
        transport_starter=starter_for(fake),
        one_shot=one_shot_for(fake),
    )


def live(agent, fake, **welcome):
    """The agent's transport up, a session opened and welcomed."""
    agent.run_once()
    fake.welcome(**welcome)
    fake.wait_for(agent.is_online)
    return agent


def until(check, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not check():
        assert time.monotonic() < deadline, "the condition never held"
        time.sleep(0.01)


def commands_named(fake, name) -> list:
    return [line for line in fake.commands if line["command"] == name]


# --- the transport and the dial ---


def test_the_first_turn_starts_the_transport_and_dials_the_binding(fake, config_path):
    agent = agent_on(fake, config=config_path, urls=[LAN_URL, OVERLAY_URL])

    delay = agent.run_once()

    assert delay == IDLE_POLL_INTERVAL_S
    assert fake.starts == 1
    (dial,) = commands_named(fake, "dial")
    assert {key: value for key, value in dial.items() if key != "id"} == {
        "command": "dial",
        "hub_key": HUB_KEY,
        "private_key": PRIVATE_KEY,
        "psk": hashlib.sha256(BINDING_TOKEN.encode()).hexdigest(),
        "role": "agent",
        "protocol": PROTOCOL,
        "addresses": [NAME_URL, LAN_URL, OVERLAY_URL],
    }


def test_the_last_answered_address_follows_the_list_and_other_schemes_are_left_out(
    fake, config_path
):
    agent = agent_on(
        fake,
        config=config_path,
        url="tcp://198.51.100.9:8443",
        urls=["https://192.0.2.1:8443", LAN_URL],
    )

    agent.run_once()

    assert fake.wait_command("dial")["addresses"] == [
        NAME_URL,
        LAN_URL,
        "tcp://198.51.100.9:8443",
    ]


def test_a_binding_is_dialled_once_and_again_when_its_addresses_change_unwelcomed(
    fake, config_path
):
    agent = agent_on(fake, config=config_path, urls=[LAN_URL])
    agent.run_once()
    agent.run_once()
    assert len(commands_named(fake, "dial")) == 1

    agent._note_urls([OVERLAY_URL, LAN_URL])
    agent.run_once()

    dials = commands_named(fake, "dial")
    assert len(dials) == 2
    assert dials[1]["addresses"] == [NAME_URL, OVERLAY_URL, LAN_URL]


def test_a_states_urls_are_written_down_and_dial_nothing_while_a_session_is_up(
    fake, config_path
):
    agent = live(agent_on(fake, config=config_path, urls=[LAN_URL]), fake)

    fake.send_frame({"type": "state", "hash": "h2", "urls": [OVERLAY_URL, LAN_URL]})
    until(lambda: enrollment_module.load_binding()["gateway_urls"][0] == OVERLAY_URL)
    agent.run_once()

    assert len(commands_named(fake, "dial")) == 1


def test_a_transport_that_will_not_start_backs_off_and_says_why(config_path):
    bind(config_path)

    def refuse(platform, log):
        raise OSError("no such program")

    agent = Agent(
        log=lambda m: None, platform=default_platform(), transport_starter=refuse
    )

    delays = [agent.run_once() for _ in range(3)]

    assert delays == [
        AGENT_BACKOFF_MIN_S,
        AGENT_BACKOFF_MIN_S * 2,
        AGENT_BACKOFF_MIN_S * 4,
    ]
    assert agent.last_error()["code"] == "transport_unavailable"


def test_a_transport_that_ends_is_started_again_and_dialled_again(fake, config_path):
    agent = live(agent_on(fake, config=config_path), fake)

    fake.drop_control()
    until(lambda: not agent.is_online())
    agent.run_once()

    assert fake.starts == 2
    assert len(commands_named(fake, "dial")) == 2


def test_an_unbound_agent_starts_no_transport(fake, config_path):
    agent = agent_on(fake, config=config_path, is_bound=False)

    assert agent.run_once() == IDLE_POLL_INTERVAL_S
    assert fake.starts == 0


def test_a_binding_written_by_another_process_is_dialled(fake, config_path):
    agent = agent_on(fake, config=config_path, is_bound=False)
    agent.run_once()

    bind(config_path)
    agent.run_once()

    assert fake.wait_command("dial")["hub_key"] == HUB_KEY


def test_a_binding_removed_by_another_process_is_undialled(fake, config_path):
    agent = live(agent_on(fake, config=config_path), fake)

    config_path.unlink()
    agent.run_once()

    fake.wait_command("undial")
    assert not agent.is_online()
    assert agent._operator is None


def test_a_rewrite_of_the_same_binding_wipes_no_state(fake, config_path):
    agent = agent_on(fake, config=config_path)
    agent._last_error = {"code": "hub_unreachable", "params": {}}

    bind(config_path, url=LAN_URL)
    agent._adopt_external_binding()

    assert agent.last_error() == {"code": "hub_unreachable", "params": {}}


# --- the session ---


def test_hello_is_the_identity_card_written_at_each_session_open(
    fake, config_path, monkeypatch
):
    monkeypatch.setattr(loop_module, "hostname", lambda: "box")
    agent = agent_on(fake, config=config_path)
    agent.run_once()

    fake.send_event("session_open", address=LAN_URL, local_address="10.0.0.5:5000")
    hello = fake.wait_frame("hello")

    assert hello == {
        "type": "hello",
        "protocol": PROTOCOL,
        "role": "agent",
        "id": BINDING_ID,
        "name": "box",
        "software": f"{AGENT_SOFTWARE_PREFIX}{AGENT_VERSION}",
    }


def test_the_report_carries_every_section_from_its_source(
    fake, config_path, monkeypatch
):
    metrics = HostMetrics(cpu_percent=12.3, memory_percent=56.7, uptime_s=7)
    platform = _FakePlatform(
        metrics=metrics,
        accounts=["alice", "bob"],
        interfaces=INTERFACES,
        details=[{"account": "alice", "home": "/home/alice", "shell": "/bin/zsh"}],
    )
    monkeypatch.setattr(loop_module, "hostname", lambda: "box")
    agent = agent_on(fake, config=config_path, platform=platform)
    agent._engine.refresh_now()
    live(agent, fake, local="10.0.0.5:51000")

    assert agent.run_once() == AGENT_REPORT_INTERVAL_S

    report = fake.wait_frame("report")
    assert set(report) == {
        "type",
        "state_hash",
        "machine",
        "network",
        "modules",
        "desktop",
        "ai_tools",
        "error",
    }
    assert set(report["machine"]) == {
        "hostname",
        "platform",
        "accounts",
        "account_details",
        "metrics",
        "sessions",
    }
    assert report["machine"]["hostname"] == "box"
    assert report["machine"]["accounts"] == ["alice", "bob"]
    assert report["machine"]["account_details"] == [
        {"account": "alice", "home": "/home/alice", "shell": "/bin/zsh"}
    ]
    assert report["machine"]["metrics"]["cpu_percent"] == 12.3
    assert report["network"]["link"] == {
        "interface": "wlan0",
        "mac": "02:00:00:00:00:02",
        "address": "10.0.0.5",
    }
    assert report["modules"] == agent.module_states()
    assert report["ai_tools"] == {"accounts": []}
    assert report["error"] is None


def test_a_platform_that_cannot_read_sends_the_empty_shapes(fake, config_path):
    platform = _FakePlatform(metrics=None, accounts=None)
    agent = live(agent_on(fake, config=config_path, platform=platform), fake)

    agent.run_once()

    report = fake.wait_frame("report")
    assert report["machine"]["metrics"] == HostMetrics().to_dict()
    assert report["machine"]["accounts"] == []
    assert report["machine"]["account_details"] == []
    assert report["network"]["interfaces"] == []


@pytest.mark.parametrize(
    "local, address",
    [
        ("10.0.0.5:51000", "10.0.0.5"),
        ("[fe80::1]:51000", "fe80::1"),
        ("10.0.0.5", "10.0.0.5"),
        ("", ""),
    ],
)
def test_the_link_is_the_sessions_own_address_without_its_port(local, address):
    assert link_address(local) == address


def test_the_welcomes_time_sets_the_hub_clocks_offset_and_its_address_is_kept(
    fake, config_path, monkeypatch
):
    clock = HubClock(clock=lambda: 1000.0, monotonic=lambda: 50.0)
    monkeypatch.setattr(hub_clock_module, "_HUB_CLOCK", clock)
    agent = agent_on(fake, config=config_path, url=LAN_URL, urls=[LAN_URL, OVERLAY_URL])
    live(agent, fake, address="100.64.0.1:8443", time=1300.0)

    agent.run_once()

    assert hub_time() == 1300.0
    assert enrollment_module.load_binding()["gateway_url"] == OVERLAY_URL


def test_a_welcome_without_time_leaves_the_offset_at_zero(
    fake, config_path, monkeypatch
):
    clock = HubClock(clock=lambda: 1000.0, monotonic=lambda: 50.0)
    clock.take(1500.0)
    monkeypatch.setattr(hub_clock_module, "_HUB_CLOCK", clock)
    agent = agent_on(fake, config=config_path)
    agent.run_once()
    fake.send_event("session_open", address=LAN_URL, local_address="")
    fake.wait_frame("hello")
    fake.send_frame({"type": "welcome", "role": "hub", "software": "neutrino_hub/x"})
    fake.wait_for(agent.is_online)

    agent.run_once()

    assert hub_time() == 1000.0


def test_a_state_frame_reaches_the_applier(fake, config_path):
    agent = live(agent_on(fake, config=config_path), fake)

    fake.send_frame({"type": "state", "hash": "h9", "modules": {}})

    until(lambda: agent._desired.latest().get("hash") == "h9")


def test_a_frame_this_build_cannot_read_is_the_reports_error(fake, config_path):
    agent = live(agent_on(fake, config=config_path), fake)
    agent.run_once()

    fake.send_frame({"type": "from_the_future", "x": 1})
    until(lambda: agent.last_error() is not None)
    agent.run_once()

    assert agent.is_online()
    assert fake.wait_frame("report", 2)["error"] == {
        "code": "frame_unreadable",
        "params": {"type": "from_the_future"},
    }


def test_persist_from_the_hub_is_answered_with_a_reply(fake, config_path):
    agent = live(agent_on(fake, config=config_path), fake)

    fake.send_frame({"type": "persist", "request": "r1", "session_id": "nobody"})

    assert fake.wait_frame("reply") == {
        "type": "reply",
        "request": "r1",
        "code": "session_unknown",
        "params": {"session_id": "nobody"},
    }
    assert agent.is_online()


def test_every_session_opens_shells_in_the_one_registry_the_report_lists(
    fake, config_path
):
    agent = live(agent_on(fake, config=config_path), fake)

    kinds = agent._stream_kinds()
    agent._shells.take(
        "tab-1",
        is_resumed=False,
        make=lambda on_change, on_end: ShellSession(
            session_id="tab-1", terminal=None, account="root", title="bash"
        ),
    )

    assert kinds["shell"].keywords["sessions"] is agent._shells
    assert kinds["exec"].keywords == {
        "terminal": agent._terminal_settings,
        "platform": agent._platform,
    }
    (listed,) = agent._report_payload()["machine"]["sessions"]
    assert listed["session_id"] == "tab-1"


class MachineRunner(PodmanMachineModuleRunner):
    """The Windows and macOS runner, reduced to the read's command."""

    def __init__(self):
        pass

    def read_command(self):
        return ("podman.exe", "--url", MACHINE_URL, "--identity", "key")


def test_a_containers_shell_runs_through_the_machines_read_command_where_it_runs(
    fake, config_path, monkeypatch
):
    agent = agent_on(fake, config=config_path)
    shell = agent._stream_kinds()["shell"]

    on_linux = shell.keywords["container_podman"]()
    monkeypatch.setitem(agent._engine._module_runners, "podman", MachineRunner())
    on_a_machine = shell.keywords["container_podman"]()

    assert on_linux == (PODMAN_BINARY,)
    assert on_a_machine[2] == MACHINE_URL


def test_a_stream_the_hub_opens_is_attached_and_a_kind_unknown_closed(
    fake, config_path
):
    live(agent_on(fake, config=config_path), fake)

    fake.send_event("stream", stream="s4", open={"kind": "teleport"})
    far = fake.wait_attached("s4")

    assert far.first["op"] == "attach"
    kind, payload = far.read_record()
    assert (kind, json.loads(payload)) == (
        8,
        {"code": "kind_unknown", "params": {"kind": "teleport"}},
    )


def test_a_command_stream_runs_through_the_operator(fake, config_path):
    live(agent_on(fake, config=config_path), fake)

    fake.send_event(
        "stream",
        stream="s6",
        open={"kind": "command", "module": "nobody", "verb": "x"},
    )
    far = fake.wait_attached("s6")

    assert far.read_record() == (2, b"")
    kind, payload = far.read_record()
    assert kind == 8
    assert json.loads(payload)["code"] == "verb_unknown"


# --- refusals ---


@pytest.mark.parametrize(
    "code, params",
    [
        ("protocol_too_old", {"peer": 3, "hub": 4, "min": 4}),
        ("protocol_too_new", {"peer": 5, "hub": 4, "min": 4}),
        ("channel_full", {"limit": 1}),
        ("somebody_new", {}),
    ],
)
def test_a_refusal_keeps_the_binding_while_the_transport_dials_again(
    fake, config_path, code, params
):
    agent = live(agent_on(fake, config=config_path), fake)

    fake.send_frame({"type": "refused", "code": code, "params": params})
    fake.send_event("session_end", code=code, params=params)
    until(lambda: not agent.is_online())
    agent.run_once()

    assert agent.last_error() == {"code": code, "params": params}
    assert enrollment_module.is_bound()
    assert commands_named(fake, "undial") == []


def test_a_refused_knock_with_no_session_is_recorded_too(fake, config_path):
    agent = agent_on(fake, config=config_path)
    agent.run_once()

    fake.send_event("session_end", code="protocol_too_old", params={"min": 4})
    until(lambda: agent.last_error() is not None)

    assert agent.last_error()["code"] == "protocol_too_old"


@pytest.mark.parametrize(
    "code, params",
    [
        ("hub_unreachable", {"detail": "dial tcp 192.0.2.1:8443: i/o timeout"}),
        ("hub_untrusted", {}),
        ("protocol_too_old", {"peer": 4, "hub": 5, "min": 5}),
    ],
)
def test_a_round_that_found_no_session_says_why(fake, config_path, code, params):
    agent = agent_on(fake, config=config_path)
    agent.run_once()

    fake.send_event("round_end", code=code, params=params, next_round_s=5)
    until(lambda: agent.last_error() is not None)

    assert agent.last_error() == {"code": code, "params": params}
    assert enrollment_module.is_bound()


def test_a_round_ended_by_binding_unknown_unbinds(fake, config_path):
    agent = agent_on(fake, config=config_path)
    agent._rdp = RecordedDesktop()
    agent.run_once()

    fake.send_event("round_end", code="binding_unknown", params={}, next_round_s=0)
    until(lambda: not enrollment_module.is_bound())

    assert agent.last_error()["code"] == "binding_unknown"


def test_a_binding_unknown_about_a_binding_written_over_since_keeps_the_new_one(
    fake, config_path
):
    agent = agent_on(fake, config=config_path)
    agent.run_once()

    bind(config_path, url=OVERLAY_URL)
    fake.send_event("round_end", code="binding_unknown", params={}, next_round_s=0)
    fake.send_event("round_end", code="hub_unreachable", params={}, next_round_s=5)
    until(lambda: (agent.last_error() or {}).get("code") == "hub_unreachable")

    assert json.loads(config_path.read_text())["gateway_url"] == OVERLAY_URL


def test_a_line_from_a_transport_ended_since_is_dropped(fake, config_path):
    agent = agent_on(fake, config=config_path)
    agent.run_once()
    ended = agent._generation

    agent._stop_transport()
    agent._on_event_of(ended, {"event": "round_end", "code": "binding_unknown"})

    assert enrollment_module.is_bound()
    assert agent.last_error() is None


def test_a_binding_written_over_starts_the_transport_afresh(fake, config_path):
    agent = live(agent_on(fake, config=config_path), fake)

    bind(config_path, url=OVERLAY_URL)
    agent.run_once()

    assert fake.starts == 2
    assert fake.wait_command("dial", count=2)["addresses"] == [NAME_URL, OVERLAY_URL]


def test_a_session_that_drops_is_hub_unreachable_and_keeps_the_binding(
    fake, config_path
):
    agent = live(agent_on(fake, config=config_path), fake)

    fake.send_event("session_end", code="", params={})
    until(lambda: not agent.is_online())
    agent.run_once()

    assert agent.last_error()["code"] == "hub_unreachable"
    assert enrollment_module.is_bound()


class RecordedAiTools:
    """The AI tools as the loop reaches them."""

    def __init__(self):
        self.is_bound_at_switch_back: list = []

    def switch_back_all(self):
        self.is_bound_at_switch_back.append(enrollment_module.is_bound())
        return []

    def report(self):
        return {"accounts": []}


class RecordedDesktop:
    """The desktop host as leaving reaches it."""

    def __init__(self):
        self.left = 0
        self.repaired = 0

    def leave_hub(self):
        self.left += 1

    def declaration(self):
        return {"is_shared": False}

    def settle_at_start(self):
        """Nothing to settle."""

    def repair_password(self):
        self.repaired += 1


def test_binding_unknown_unbinds_switches_back_cuts_the_share_and_undials(
    fake, config_path
):
    agent = live(agent_on(fake, config=config_path), fake)
    tools, desktop = RecordedAiTools(), RecordedDesktop()
    agent._ai_tools, agent._rdp = tools, desktop

    fake.send_frame({"type": "refused", "code": "binding_unknown", "params": {}})
    until(lambda: not agent.is_online())
    agent.run_once()

    assert not config_path.exists()
    assert tools.is_bound_at_switch_back == [False]
    assert desktop.left == 1
    fake.wait_command("undial")
    assert agent.last_error()["code"] == "binding_unknown"
    assert agent.run_once() == IDLE_POLL_INTERVAL_S


def test_replaced_dials_no_more_until_a_new_binding(fake, config_path):
    agent = live(agent_on(fake, config=config_path), fake)

    fake.send_frame({"type": "refused", "code": "replaced", "params": {}})
    until(lambda: not agent.is_online())
    agent.run_once()
    agent.run_once()

    fake.wait_command("undial")
    assert len(commands_named(fake, "dial")) == 1
    assert enrollment_module.is_bound()

    bind(config_path, url=OVERLAY_URL)
    agent.run_once()

    assert len(commands_named(fake, "dial")) == 2


# --- the port question ---


PUBLISHING_REPORT = {
    "samba": {"state": "running", "details": {"shares": [{}]}},
    "vscode": {
        "state": "running",
        "details": {"instances": [{"account": "ann", "port": 8000}]},
    },
    "gitea": {
        "state": "running",
        "details": {
            "url": "http://127.0.0.1:3000/",
            "port": 3000,
            "ssh_listen_port": 2222,
        },
    },
    "hermes_webui": {"state": "running", "details": {"port": 8787}},
    "ssh_server": {
        "state": "running",
        "details": {
            "instances": [
                {"account": "ann", "port": 22000, "is_running": True},
                {"account": "bob", "port": 22001, "is_running": False},
            ]
        },
    },
    "podman": {
        "state": "running",
        "details": {
            "containers": [
                {
                    "name": "dns",
                    "is_running": True,
                    "host_bindings": [
                        {"address": "", "port": 5353, "protocol": "udp"},
                        {"address": "192.0.2.10", "port": 9000},
                    ],
                }
            ]
        },
    },
}


def test_the_port_question_is_answered_from_the_report_and_the_state(
    fake, config_path, monkeypatch
):
    agent = live(agent_on(fake, config=config_path), fake)
    monkeypatch.setattr(agent._engine, "report", lambda: PUBLISHING_REPORT)
    monkeypatch.setattr(
        agent, "rdp_declaration", lambda: {"is_shared": True, "port": 21118}
    )

    answers = {
        port: fake.ask("port", port=port, protocol="tcp")
        for port in (445, 21118, 8000, 3000, 2222, 8787, 22000, 22001, 9000, 5353)
    }
    udp = fake.ask("port", port=5353, protocol="udp")

    for port in (445, 21118, 8000, 3000, 2222, 8787, 22000):
        assert answers[port]["address"] == "127.0.0.1", port
    assert answers[9000]["address"] == "192.0.2.10"
    for port in (22001, 5353):
        assert answers[port]["code"] == "port_not_published"
        assert answers[port]["params"] == {"port": port}
    assert udp["address"] == "127.0.0.1"


def test_a_question_this_build_does_not_know_is_control_unavailable(fake, config_path):
    live(agent_on(fake, config=config_path), fake)

    assert fake.ask("mystery")["code"] == "control_unavailable"


# --- the AI gateway forward ---


def test_a_state_with_the_forward_on_asks_the_transport_and_off_gives_it_back(
    fake, config_path
):
    agent = live(agent_on(fake, config=config_path), fake)
    fake.answers["forward_start"] = lambda line: {"listen": "127.0.0.1:41000"}

    fake.send_frame(dict(AI_ON, type="state"))
    start = fake.wait_command("forward_start")
    until(lambda: agent._ai_forward.local_port == 41000)
    fake.send_frame(dict(AI_OFF, type="state"))
    stop = fake.wait_command("forward_stop")

    assert (start["listen"], start["protocol"], start["open"]) == (
        "127.0.0.1:0",
        "tcp",
        {"kind": "connect", "id": "ai"},
    )
    assert (stop["listen"], stop["protocol"]) == ("127.0.0.1:41000", "tcp")
    assert agent._ai_forward.local_port == 0


def test_the_hubs_own_agent_asks_for_no_forward(fake, config_path):
    agent = live(agent_on(fake, config=config_path), fake)

    agent._take_state(dict(AI_ON, ai_tools={"is_enabled": True, "is_forwarded": False}))

    assert commands_named(fake, "forward_start") == []


def test_a_forward_the_transport_refused_is_asked_for_again_at_the_tick(
    fake, config_path
):
    agent = live(agent_on(fake, config=config_path), fake)
    fake.answers["forward_start"] = {"code": "port_taken", "params": {"port": 8317}}
    agent._take_state(AI_ON)
    assert agent._ai_forward.local_port == 0

    fake.answers["forward_start"] = lambda line: {"listen": "127.0.0.1:8317"}
    agent._tick()

    assert agent._ai_forward.local_port == 8317
    assert len(commands_named(fake, "forward_start")) == 2


def test_a_new_transport_is_asked_for_the_forward_the_kept_state_wants(
    fake, config_path
):
    agent = agent_on(fake, config=config_path)
    agent._desired._store.write(AI_ON)
    fake.answers["forward_start"] = lambda line: {"listen": "127.0.0.1:8317"}

    agent.run_once()

    fake.wait_command("forward_start")
    assert agent._ai_forward.local_port == 8317


def test_leave_gives_the_binding_back_and_closes_everything(fake, config_path):
    agent = live(agent_on(fake, config=config_path), fake)
    fake.answers["forward_start"] = lambda line: {"listen": "127.0.0.1:8317"}
    agent._take_state(AI_ON)
    tools, desktop = RecordedAiTools(), RecordedDesktop()
    agent._ai_tools, agent._rdp = tools, desktop

    agent.leave()

    leave = fake.wait_command("leave")
    assert leave["psk"] == hashlib.sha256(BINDING_TOKEN.encode()).hexdigest()
    assert leave["hub_key"] == HUB_KEY
    fake.wait_command("undial")
    fake.wait_command("forward_stop")
    assert not config_path.exists()
    assert tools.is_bound_at_switch_back == [False]
    assert desktop.left == 1
    assert agent._operator is None


def test_leave_does_not_wait_on_a_hub_that_cannot_be_told(fake, config_path):
    agent = agent_on(fake, config=config_path)
    agent._rdp = RecordedDesktop()
    lines: list = []
    agent._log = lines.append
    fake.answers["leave"] = {"code": "hub_unreachable", "params": {"detail": "x"}}

    agent.leave()

    assert not config_path.exists()
    assert "could not tell the hub we are leaving: hub_unreachable" in lines


# --- the streams this side opens ---


def test_a_stream_this_side_opens_rides_its_own_connection(fake, config_path):
    agent = live(agent_on(fake, config=config_path), fake)

    channel = agent._open_stream("log", module="samba")
    channel.send_line("installing")
    channel.close("", {"state": "installed"})

    opened = fake.wait_opened()
    assert opened.first["open"] == {"kind": "log", "module": "samba"}
    assert opened.read_record() == (3, b"installing\n")
    kind, payload = opened.read_record()
    assert (kind, json.loads(payload)) == (
        8,
        {"code": "", "params": {"state": "installed"}},
    )


def test_a_stream_with_no_session_is_refused(fake, config_path):
    agent = agent_on(fake, config=config_path)

    with pytest.raises(GatewayUnreachable):
        agent._open_stream("log", module="samba")


def installer(monkeypatch) -> list:
    """The self-update replaced at its two seams."""
    installed: list = []
    monkeypatch.setattr(loop_module, "AGENT_REINSTALL_WAIT_S", 0)
    monkeypatch.setattr(loop_module.self_update, "package_kind", lambda platform: "deb")

    def receive(channel, directory, kind):
        channel.close()
        return f"{directory}/neutrino_agent.{kind}"

    monkeypatch.setattr(loop_module.self_update, "receive_package", receive)

    def run_update(path, kind, state_dir, version, is_reinstall):
        installed.append((path, kind, version, is_reinstall))

    monkeypatch.setattr(loop_module.self_update, "run_update", run_update)
    return installed


def test_a_newer_hub_opens_the_package_stream_after_the_first_report_once(
    fake, config_path, monkeypatch, tmp_path
):
    monkeypatch.setattr(loop_module, "AGENT_VERSION", "1.0.0")
    installed = installer(monkeypatch)
    agent = live(
        agent_on(fake, config=config_path), fake, software="neutrino_hub/9.9.9"
    )

    agent.run_once()
    agent.run_once()

    assert installed == [
        (f"{tmp_path / 'packages'}/neutrino_agent.deb", "deb", "9.9.9", False)
    ]
    assert fake.wait_opened().first["open"] == {"kind": "package"}
    assert len(fake.opened) == 1


@pytest.mark.parametrize(
    "agent_version, software",
    [
        ("1.0.0", "neutrino_hub/9.9.9+dev"),
        ("1.0.0+dev", "neutrino_hub/9.9.9"),
        ("1.0.0", "neutrino_hub/1.0.0"),
        ("1.0.0", "neutrino_hub/0.9.9"),
        ("1.0.0", "something_else/9.9.9"),
    ],
)
def test_a_dev_older_equal_or_foreign_software_updates_nothing(
    fake, config_path, monkeypatch, agent_version, software
):
    monkeypatch.setattr(loop_module, "AGENT_VERSION", agent_version)
    installed = installer(monkeypatch)
    agent = live(agent_on(fake, config=config_path), fake, software=software)

    agent.run_once()

    assert installed == []
    assert fake.opened == []


def test_a_reinstall_command_opens_the_same_package_stream(
    fake, config_path, monkeypatch
):
    installed = installer(monkeypatch)
    agent = live(agent_on(fake, config=config_path), fake)

    outcome = agent._run_command("agent", "reinstall", {})

    assert [kind for _, kind, _, _ in installed] == ["deb"]
    assert outcome["output"] == "reinstall launched\n"


def test_a_command_with_no_binding_is_typed(fake, config_path):
    agent = agent_on(fake, config=config_path, is_bound=False)

    assert agent._run_command("agent", "reboot", {})["code"] == "hub_unreachable"


# --- sync, probe, join ---


def test_sync_with_no_session_is_typed_and_with_one_sends_now(fake, config_path):
    agent = agent_on(fake, config=config_path)
    assert agent.sync() == {"code": "hub_unreachable", "params": {}}

    live(agent, fake)
    agent._news.clear()

    assert agent.sync() == {}
    assert agent._news.is_set()


def answer_the_probe(fake, frame):
    """A transport that opens a session at the dial and answers the hello."""

    def on_dial(line):
        def later():
            fake.send_event("session_open", address=LAN_URL, local_address="")
            fake.wait_frame("hello")
            fake.send_frame(frame)

        threading.Thread(target=later, daemon=True).start()
        return {}

    fake.answers["dial"] = on_dial


def test_probe_dials_once_takes_the_welcome_and_undials(fake, config_path):
    agent = agent_on(fake, config=config_path)
    answer_the_probe(fake, {"type": "welcome", "role": "hub"})

    agent.probe()

    assert agent.last_error() is None
    fake.wait_command("undial")
    assert fake.wait_frame("hello")["id"] == BINDING_ID


def test_probe_reports_a_refusal(fake, config_path):
    agent = agent_on(fake, config=config_path)
    answer_the_probe(fake, {"type": "refused", "code": "protocol_too_old"})

    agent.probe()

    assert agent.last_error() == {"code": "protocol_too_old", "params": {}}


def test_probe_while_unbound_does_nothing(fake, config_path):
    agent = agent_on(fake, config=config_path, is_bound=False)

    agent.probe()

    assert fake.starts == 0


def test_a_join_runs_on_the_services_transport_while_it_runs(
    fake, config_path, monkeypatch
):
    agent = live(agent_on(fake, config=config_path), fake)
    joined: list = []

    def enroll(link, platform, transport):
        with transport() as control:
            joined.append(control is agent._control)
        bind(config_path, url=OVERLAY_URL)

    monkeypatch.setattr(enrollment_module, "enroll", enroll)

    agent.join("neutrino://enroll/x")

    assert joined == [True]
    assert agent._binding["gateway_url"] == OVERLAY_URL
    fake.wait_command("undial")


# --- a binding of 0.5 ---


def legacy_binding(path) -> None:
    path.write_text(
        json.dumps(
            {
                "gateway_url": "https://192.0.2.1:8443",
                "id": BINDING_ID,
                "token": BINDING_TOKEN,
                "fingerprint": "ff" * 32,
                "machine_id": MACHINE_ID,
            }
        )
    )


def test_a_binding_of_0_5_says_hub_key_missing_and_dials_nothing(fake, config_path):
    legacy_binding(config_path)
    lines: list = []
    agent = Agent(
        log=lines.append,
        platform=default_platform(),
        transport_starter=starter_for(fake),
        one_shot=one_shot_for(fake),
    )

    agent.run_once()
    agent.run_once()

    assert agent.last_error() == {"code": "hub_key_missing", "params": {}}
    assert fake.starts == 0
    assert fake.commands == []
    assert len([line for line in lines if "no hub key" in line]) == 1


# --- the report's error ---


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
    "params": {
        "exit_code": 100,
        "finished_at": "2026-09-10T10:00:12Z",
        "output": "dpkg: error\n",
    },
}


def test_a_failed_reinstall_is_the_reports_error(fake, tmp_path, config_path):
    (tmp_path / AGENT_REINSTALL_RESULT_NAME).write_text(json.dumps(FAILED_REINSTALL))
    agent = live(agent_on(fake, config=config_path), fake)

    agent.run_once()

    assert "error" not in fake.wait_frame("hello")
    assert fake.wait_frame("report")["error"] == REINSTALL_ERROR


@pytest.mark.parametrize("exit_code", [0, 3010])
def test_a_reinstall_that_went_through_is_no_error(
    fake, tmp_path, config_path, exit_code
):
    (tmp_path / AGENT_REINSTALL_RESULT_NAME).write_text(
        json.dumps(dict(REINSTALL_RESULT, exit_code=exit_code))
    )
    agent = agent_on(fake, config=config_path)

    assert agent._report_payload()["error"] is None


def test_the_error_is_the_most_recent_of_its_three_sources(fake, tmp_path, config_path):
    agent = agent_on(fake, config=config_path)
    update_error = {"code": "agent_update_launch_failed", "params": {"target": "9"}}
    state_error = {"code": "apply_failed", "params": {"module": "samba"}}
    assert agent._report_payload()["error"] is None

    agent._update_error = dict(update_error)
    assert agent._report_payload()["error"] == update_error

    agent._desired._state_error = dict(state_error)
    assert agent._report_payload()["error"] == state_error

    agent._update_error = None
    assert agent._report_payload()["error"] == state_error

    (tmp_path / AGENT_REINSTALL_RESULT_NAME).write_text(json.dumps(FAILED_REINSTALL))
    assert agent._report_payload()["error"] == REINSTALL_ERROR


def test_a_welcome_clears_the_last_error(fake, config_path):
    agent = agent_on(fake, config=config_path)
    agent._last_error = {"code": "hub_unreachable", "params": {}}
    live(agent, fake)

    agent.run_once()

    assert agent.last_error() is None
    assert fake.wait_frame("report")["error"] is None


# --- the loop's own life ---


def test_the_store_lives_under_the_platforms_data_root(fake, config_path):
    platform = default_platform()
    agent = agent_on(fake, config=config_path, platform=platform)

    root = platform.agent_data_dir()
    assert agent._store._path == os.path.join(root, "state.json")
    assert agent._rdp._credentials_dir == os.path.join(root, "credentials")


class RecordedRelays:
    def __init__(self):
        self.events: list = []

    def start(self):
        self.events.append("start")

    def stop(self):
        self.events.append("stop")


class ForwardingRunner:
    def __init__(self, ports):
        self._ports = tuple(ports)

    def forwarder_ports(self):
        return self._ports


def test_the_loop_runs_the_relays_and_its_end_closes_them_and_the_transport(
    fake, config_path, monkeypatch
):
    agent = agent_on(fake, config=config_path)
    monkeypatch.setattr(agent._rdp, "settle_at_start", lambda: None)
    agent._relays = RecordedRelays()
    run_once = agent.run_once

    def turn():
        delay = run_once()
        agent.stop()
        return delay

    monkeypatch.setattr(agent, "run_once", turn)

    agent.run_forever()

    assert agent._relays.events == ["start", "stop"]
    assert fake.starts == 1 and not fake.is_running()


def test_the_relays_carry_the_forward_and_every_forwarder(fake, config_path):
    agent = live(agent_on(fake, config=config_path), fake)
    fake.answers["forward_start"] = lambda line: {"listen": "127.0.0.1:8317"}
    agent._engine._module_runners = {
        "cloudcli": ForwardingRunner([3101]),
        "codeg": ForwardingRunner([3102, 3103]),
    }
    agent._take_state(AI_ON)

    assert agent._relayed_ports() == {8317, 3101, 3102, 3103}


def test_the_hubs_own_agent_relays_the_gateways_own_port(fake, config_path):
    agent = agent_on(fake, config=config_path)
    agent._engine._module_runners = {}
    agent._desired._store.write(
        dict(AI_ON, ai_tools={"is_forwarded": False, "gateway_port": 8317})
    )

    assert agent._relayed_ports() == {8317}


def test_each_tick_reads_the_hub_clock_and_checks_the_seat_password(
    fake, config_path, monkeypatch
):
    readings: list = []

    class RecordingClock(HubClock):
        def now(self) -> float:
            readings.append(True)
            return super().now()

    monkeypatch.setattr(hub_clock_module, "_HUB_CLOCK", RecordingClock())
    agent = agent_on(fake, config=config_path)
    desktop = RecordedDesktop()
    agent._rdp = desktop

    agent._tick()
    agent._tick()

    assert len(readings) == 2
    assert desktop.repaired == 2


def test_a_join_from_another_process_ends_the_wait_and_resets_the_backoff(
    config_path,
):
    agent = Agent(log=lambda m: None, platform=default_platform())
    agent._backoff_s = AGENT_BACKOFF_MAX_S
    started = time.monotonic()

    def later():
        time.sleep(0.2)
        bind(config_path)

    threading.Thread(target=later, daemon=True).start()
    agent._wait_out(AGENT_BACKOFF_MAX_S)

    assert time.monotonic() - started < AGENT_BACKOFF_MAX_S / 2
    assert agent._backoff_s == AGENT_BACKOFF_MIN_S
