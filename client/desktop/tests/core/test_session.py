"""One hub's session through the transport, against a scripted transport.

The real local channel runs over a Unix socket to a fake transport the test
scripts: the test reads the commands and frames the client wrote and
emits the events and frames the transport would. What is pinned: the
``dial`` with the binding's keys, the token's digest as the psk and every
candidate with its path; the ``hello`` on every session the transport
opens, a move's included; the welcome written onto the binding and
answered with a report; a state that replaces what is held, reaches the
resident, is answered with a report and, when it names other addresses,
gives the transport its candidates again with a round; the disabled switch
told once; the round trip a ``pong`` sets; each question frame answered by
its ``reply``; every code a round, a session or a refused frame ends in, as
the Hubs table words it, with the transport's next round as the countdown;
the one refusal that unbinds; another client's ``replaced`` and a
Reconnect; a pending join spent through the transport with the pending id
as its label, the binding's id taken from the answer, and each refusal
waited by its code; a 0.5 binding waiting on ``hub_key_missing`` with
nothing dialled; a refresh and a network change as a ``round``; a transport that ends and comes back;
the open records of a shell and an exec naming their account; and a stop
that undials.
"""

import hashlib
import queue
import threading
import time

import pytest

from neutrino_client import CLIENT_VERSION
from neutrino_client.constants import (
    CLIENT_BACKOFF_MAX_S,
    CLIENT_ROLE,
    CLIENT_SOFTWARE_PREFIX,
    PROTOCOL,
)
from neutrino_client.core import enrollment
from neutrino_client.core.session import (
    CONNECTION_CONNECTED,
    CONNECTION_CONNECTING,
    CONNECTION_DISABLED,
    CONNECTION_REPLACED,
    CONNECTION_WAITING,
    ClientHubSession,
    clean_terminals,
    is_offline,
    is_on_local_network,
)
from neutrino_client.core.transport import ClientTransportChannel
from neutrino_client.exceptions import GatewayRefusedDetail, GatewayUnreachable
from tests.conftest import BINDING, HUB_KEY, HUB_SERVICES, PRIVATE_KEY, bind
from tests.fake_transport import RECORD_DATA, FakeTransport, unix_connect

WAIT_S = 5
WELCOME = {
    "type": "welcome",
    "protocol": PROTOCOL,
    "role": "hub",
    "id": "h1",
    "name": "home",
    "software": "neutrino_hub/0.6.0",
    "time": 1.0,
}
STATE = {"type": "state", "hash": "s1", "is_disabled": False, "services": HUB_SERVICES}
PLATFORM = {"os": "linux", "family": "debian", "arch": "amd64"}
HUB_URL = "tcp://192.168.1.2:8443"


def wait_for(condition, timeout_s: float = WAIT_S) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return False


class Harness:
    """A session on a real local channel to a fake transport, and what it told."""

    def __init__(self, binding: dict, *, answers=None, **kwargs):
        self.transport = FakeTransport()
        # Set before the session starts. Its thread sends a pending join at once.
        self.transport.answers.update(answers or {})
        self.channel = ClientTransportChannel(
            connect=unix_connect,
            listen=self.transport.listen,
            secret=self.transport.secret,
            log=lambda line: None,
            restart_min_s=0.05,
        )
        self.services = queue.Queue()
        self.disabled = []
        self.unbound = []
        self.welcomed = []
        self.lines = []
        kwargs.setdefault("local_networks", lambda: ["192.168.1.0/24"])
        self.session = ClientHubSession(
            binding=binding,
            transport=self.channel,
            hostname="box",
            platform_tuple=PLATFORM,
            os_machine_id="machine-1",
            log=self.lines.append,
            on_services=self.services.put,
            on_disabled=self.disabled.append,
            on_unbound=self.unbound.append,
            on_welcomed=lambda session, hub_id: self.welcomed.append(hub_id),
            **kwargs,
        )
        self.channel.on_ready(self.session.transport_ready)
        self.channel.on_lost(self.session.transport_lost)
        self.channel.start()
        assert self.channel.wait_ready(WAIT_S)
        self.session.start()

    def connect(self, label: str = "c1") -> dict:
        """Take the dial, open a session, answer the hello with a welcome."""
        dial = self.transport.next_command("dial")
        self.transport.emit(
            {
                "event": "session_open",
                "binding": label,
                "address": HUB_URL,
                "path": "lan",
                "handshake_ms": 3,
            }
        )
        self.transport.next_frame("hello")
        self.transport.frame(label, WELCOME)
        assert wait_for(lambda: self.session.connection() == CONNECTION_CONNECTED)
        self.transport.next_frame("report")
        return dial

    def close(self) -> None:
        self.session.stop()
        self.channel.stop()
        self.transport.close()


@pytest.fixture
def harness(config_path):
    bind(config_path, url=HUB_URL)
    made = Harness(dict(BINDING, gateway_url=HUB_URL))
    yield made
    made.close()


def replying(harness, frame_type: str, reply: dict) -> queue.Queue:
    """Answer the next question frame of a type with a reply; the question comes back."""
    asked_frames = queue.Queue()

    def answer():
        asked = harness.transport.next_frame(frame_type)["frame"]
        asked_frames.put(asked)
        harness.transport.frame(
            "c1", dict(reply, type="reply", request=asked["request"])
        )

    threading.Thread(target=answer, daemon=True).start()
    return asked_frames


# --- the pure helpers ---


def test_an_address_inside_this_machines_network_is_local():
    assert is_on_local_network("192.168.1.9", ["192.168.1.0/24"])
    assert not is_on_local_network("10.0.0.1", ["192.168.1.0/24"])
    assert not is_on_local_network("hub.lan", ["192.168.1.0/24"])


def test_only_loopback_and_link_local_networks_are_no_network():
    assert is_offline(["127.0.0.0/8", "fe80::/64"])
    assert not is_offline(["127.0.0.0/8", "192.168.1.0/24"])
    assert not is_offline([])


def test_a_terminals_machine_keeps_its_enabled_accounts_in_order():
    held = clean_terminals(
        [
            {
                "device_id": "d1",
                "name": "lab",
                "is_online": True,
                "accounts": ["iffi", {"account": "lab"}, "iffi", ""],
                "sessions": [{"session_id": "s1", "account": "iffi"}],
            }
        ]
    )
    assert held["machines"] == [
        {
            "device_id": "d1",
            "name": "lab",
            "is_online": True,
            "accounts": ["iffi", "lab"],
        }
    ]
    assert held["sessions"][0]["device_id"] == "d1"


# --- the dial and the hello ---


def test_the_dial_names_the_bindings_keys_the_tokens_digest_and_every_candidate(
    harness,
):
    dial = harness.transport.next_command("dial")
    assert dial["binding"] == "c1"
    assert dial["hub_key"] == HUB_KEY
    assert dial["private_key"] == PRIVATE_KEY
    assert dial["psk"] == hashlib.sha256(b"tok").hexdigest()
    assert dial["role"] == CLIENT_ROLE
    assert dial["protocol"] == PROTOCOL
    assert dial["candidates"] == [
        {"address": "tcp://hub.neutrino.internal:8443", "path": "lan"},
        {"address": HUB_URL, "path": "lan"},
    ]


def test_a_candidate_outside_this_machines_networks_is_direct(config_path):
    bind(config_path, url="tcp://203.0.113.9:8443")
    made = Harness(dict(BINDING, gateway_url="tcp://203.0.113.9:8443"))
    try:
        dial = made.transport.next_command("dial")
        assert {"address": "tcp://203.0.113.9:8443", "path": "direct"} in dial[
            "candidates"
        ]
    finally:
        made.close()


def test_an_address_of_another_scheme_is_not_dialled(config_path):
    binding = dict(
        BINDING,
        gateway_url=HUB_URL,
        gateway_urls=[HUB_URL, "quic://192.168.1.2:8443"],
    )
    bind(config_path, bindings=[binding])
    made = Harness(binding)
    try:
        dial = made.transport.next_command("dial")
        assert all(item["address"].startswith("tcp://") for item in dial["candidates"])
    finally:
        made.close()


def test_every_session_the_transport_opens_is_greeted_with_a_hello(harness):
    harness.transport.next_command("dial")
    harness.transport.emit(
        {"event": "session_open", "binding": "c1", "address": HUB_URL}
    )
    assert harness.transport.next_frame("hello") == {
        "frame": {
            "type": "hello",
            "protocol": PROTOCOL,
            "role": CLIENT_ROLE,
            "id": "c1",
            "name": "box",
            "software": f"{CLIENT_SOFTWARE_PREFIX}{CLIENT_VERSION}",
        },
        "binding": "c1",
    }
    assert harness.session.connection() == CONNECTION_CONNECTING


def test_the_welcome_opens_the_channel_and_is_answered_with_a_report(harness):
    harness.transport.next_command("dial")
    harness.transport.emit(
        {"event": "session_open", "binding": "c1", "address": HUB_URL}
    )
    harness.transport.next_frame("hello")
    harness.transport.frame("c1", WELCOME)
    report = harness.transport.next_frame("report")["frame"]
    assert report == {
        "type": "report",
        "state_hash": "",
        "machine": {
            "hostname": "box",
            "platform": PLATFORM,
            "os_machine_id": "machine-1",
        },
    }
    assert harness.session.connection() == CONNECTION_CONNECTED
    assert harness.session.hub_software() == "neutrino_hub/0.6.0"
    assert harness.welcomed == ["h1"]
    assert harness.session.wait_channel(0)


def test_a_welcome_of_another_role_opens_nothing(harness):
    harness.transport.next_command("dial")
    harness.transport.frame("c1", dict(WELCOME, role="agent"))
    time.sleep(0.2)
    assert harness.session.connection() == CONNECTION_CONNECTING


def test_a_move_is_greeted_again_and_the_channel_stays_connected(harness):
    harness.connect()
    harness.transport.emit(
        {
            "event": "session_open",
            "binding": "c1",
            "address": "tcp://10.0.0.1:8443",
            "path": "netbird",
        }
    )
    assert harness.transport.next_frame("hello")["frame"]["id"] == "c1"
    assert harness.session.connection() == CONNECTION_CONNECTED
    harness.transport.frame("c1", WELCOME)
    harness.transport.next_frame("report")
    assert wait_for(lambda: harness.session.gateway_url() == "tcp://10.0.0.1:8443")


# --- the state ---


def test_a_state_replaces_what_is_held_and_is_answered_with_its_hash(harness):
    harness.connect()
    apps = [{"id": "gitea_d1", "title": "Gitea", "source": "module", "local_name": "g"}]
    terminals = [
        {"device_id": "d1", "name": "lab", "is_online": True, "accounts": ["a"]}
    ]
    harness.transport.frame(
        "c1", dict(STATE, apps=apps, terminals=terminals, reached_through="lan")
    )
    assert harness.services.get(timeout=WAIT_S) is harness.session
    assert harness.transport.next_frame("report")["frame"]["state_hash"] == "s1"
    assert [entry["id"] for entry in harness.session.service_entries()] == [
        entry["id"] for entry in HUB_SERVICES
    ]
    assert harness.session.app_entries()[0]["id"] == "gitea_d1"
    assert harness.session.terminal_entries()[0]["accounts"] == ["a"]
    assert harness.session.reached_through() == "lan"


def test_a_state_naming_other_addresses_dials_again_with_a_round(harness):
    harness.connect()
    harness.transport.frame("c1", dict(STATE, urls=[HUB_URL, "tcp://203.0.113.9:8443"]))
    dial = harness.transport.next_command("dial")
    assert {"address": "tcp://203.0.113.9:8443", "path": "direct"} in dial["candidates"]
    assert harness.transport.next_command("round")["binding"] == "c1"
    kept = enrollment.load_config()["bindings"][0]
    assert kept["gateway_urls"] == [HUB_URL, "tcp://203.0.113.9:8443"]


def test_a_relay_address_is_ranked_as_the_relays_path(harness):
    harness.connect()
    harness.transport.frame(
        "c1",
        dict(
            STATE,
            urls=[HUB_URL, "tcp://relay.example:9443"],
            ssh_relay_url="tcp://relay.example:9443",
        ),
    )
    dial = harness.transport.next_command("dial")
    assert {"address": "tcp://relay.example:9443", "path": "ssh_relay"} in dial[
        "candidates"
    ]


def test_the_hub_switching_the_client_off_is_told_once(harness):
    harness.connect()
    harness.transport.frame("c1", dict(STATE, is_disabled=True))
    harness.transport.frame("c1", dict(STATE, is_disabled=True, hash="s2"))
    assert wait_for(lambda: harness.session.connection() == CONNECTION_DISABLED)
    time.sleep(0.1)
    assert harness.disabled == [harness.session]


# --- the round trip and the questions ---


def test_a_pong_with_the_last_pings_nonce_sets_the_round_trip(harness):
    harness.connect()
    ping = harness.transport.next_frame("ping")["frame"]
    harness.transport.frame("c1", {"type": "pong", "nonce": "other"})
    time.sleep(0.1)
    assert harness.session.rtt_ms() is None
    harness.transport.frame("c1", {"type": "pong", "nonce": ping["nonce"]})
    assert wait_for(lambda: harness.session.rtt_ms() is not None)


def test_a_service_frame_is_answered_by_its_reply(harness):
    harness.connect()
    asked = replying(harness, "service", {"params": {"password": "p"}})  # scan: allow
    assert harness.session.ask_service("rdp_s9") == {"password": "p"}  # scan: allow
    assert asked.get(timeout=WAIT_S)["id"] == "rdp_s9"


def test_a_reply_with_a_code_is_the_hubs_refusal(harness):
    harness.connect()
    asked = replying(
        harness, "service", {"code": "permission_denied", "params": {"kind": "panel"}}
    )
    with pytest.raises(GatewayRefusedDetail) as refused:
        harness.session.ask_panel_service()
    assert refused.value.code == "permission_denied"
    assert asked.get(timeout=WAIT_S)["is_panel"] is True


def test_persist_and_stop_session_are_frames_answered_by_replies(harness):
    harness.connect()
    asked = replying(harness, "persist", {"params": {}})
    harness.session.persist_shell("s1", is_shared=True)
    persist = asked.get(timeout=WAIT_S)
    assert persist["session_id"] == "s1" and persist["is_shared"] is True
    assert "is_persistent" not in persist
    asked = replying(harness, "stop_session", {"params": {}})
    harness.session.stop_shell_session("s1")
    assert asked.get(timeout=WAIT_S)["session_id"] == "s1"


def test_a_question_while_the_hub_is_not_connected_is_unreachable(harness):
    with pytest.raises(GatewayUnreachable):
        harness.session.ask_service("x", timeout_s=0.1)


def test_a_question_whose_session_ends_is_unreachable(harness):
    harness.connect()
    failures = queue.Queue()

    def ask():
        try:
            harness.session.ask_service("x", timeout_s=WAIT_S)
        except GatewayUnreachable as error:
            failures.put(error)

    threading.Thread(target=ask, daemon=True).start()
    harness.transport.next_frame("service")
    harness.transport.emit({"event": "session_end", "binding": "c1"})
    assert isinstance(failures.get(timeout=WAIT_S), GatewayUnreachable)


# --- the waits ---


def test_a_round_that_reached_no_address_waits_for_the_transports_next_round(
    harness,
):
    harness.transport.next_command("dial")
    harness.transport.emit(
        {
            "event": "round_end",
            "binding": "c1",
            "code": "hub_unreachable",
            "params": {"detail": "refused"},
            "next_round_s": 20,
        }
    )
    assert wait_for(lambda: harness.session.connection() == CONNECTION_WAITING)
    waiting = harness.session.waiting()
    assert waiting["reason"] == "hub_silent"
    assert waiting["code"] == {
        "code": "hub_unreachable",
        "params": {"detail": "refused"},
    }
    assert 15 < waiting["next_round_at"] - time.time() <= 20


def test_a_round_with_the_hubs_network_on_waits_off_the_overlay(harness):
    harness.session.set_overlay_route("100.64.0.1", "netbird")
    harness.transport.next_command("dial")
    harness.transport.emit(
        {"event": "round_end", "binding": "c1", "code": "hub_unreachable"}
    )
    assert wait_for(lambda: harness.session.waiting() is not None)
    assert harness.session.waiting()["reason"] == "hub_off_overlay"


def test_a_round_on_a_machine_with_no_network_waits_for_one(config_path):
    bind(config_path, url=HUB_URL)
    made = Harness(
        dict(BINDING, gateway_url=HUB_URL), local_networks=lambda: ["127.0.0.0/8"]
    )
    try:
        made.transport.next_command("dial")
        made.transport.emit(
            {"event": "round_end", "binding": "c1", "code": "hub_unreachable"}
        )
        assert wait_for(lambda: made.session.waiting() is not None)
        assert made.session.waiting()["reason"] == "no_network"
        assert made.session.waiting()["next_round_at"] is None
    finally:
        made.close()


@pytest.mark.parametrize(
    "code, reason, has_countdown",
    [
        ("hub_untrusted", "untrusted", True),
        ("protocol_too_old", "too_old", False),
        ("protocol_too_new", "too_old", False),
        ("channel_full", "hub_silent", True),
        ("control_unavailable", "hub_silent", True),
    ],
)
def test_each_code_waits_as_the_hubs_table_words_it(
    harness, code, reason, has_countdown
):
    harness.transport.next_command("dial")
    harness.transport.emit({"event": "round_end", "binding": "c1", "code": code})
    assert wait_for(lambda: harness.session.waiting() is not None)
    waiting = harness.session.waiting()
    assert waiting["reason"] == reason
    assert (waiting["next_round_at"] is not None) is has_countdown


def test_thirty_control_unavailable_refusals_in_150_s_write_four_lines(config_path):
    bind(config_path, url=HUB_URL)
    now = [1000.0]
    made = Harness(dict(BINDING, gateway_url=HUB_URL), clock=lambda: now[0])
    try:
        made.transport.next_command("dial")
        for turn in range(30):
            now[0] = 1000.0 + 5 * turn
            made.session._take_round_end(
                {
                    "binding": "c1",
                    "code": "control_unavailable",
                    "params": {"retry_after_s": 5},
                    "next_round_s": 5,
                }
            )
        made.transport.emit(
            {
                "event": "session_open",
                "binding": "c1",
                "address": HUB_URL,
                "path": "lan",
                "handshake_ms": 3,
            }
        )
        made.transport.next_frame("hello")
        made.transport.frame("c1", WELCOME)
        assert wait_for(lambda: made.session.connection() == CONNECTION_CONNECTED)

        assert [line for line in made.lines if "control_unavailable" in line] == [
            "the hub refused the session: control_unavailable",
            "the hub refused the session: control_unavailable,"
            " 12 times since the last line",
            "the hub refused the session: control_unavailable,"
            " 12 times since the last line",
            "the hub welcomed this client;"
            " refused control_unavailable 5 times since the last line",
        ]
    finally:
        made.close()


def test_binding_unknown_unbinds_once(harness):
    harness.connect()
    harness.transport.frame("c1", {"type": "refused", "code": "binding_unknown"})
    harness.transport.emit(
        {"event": "session_end", "binding": "c1", "code": "binding_unknown"}
    )
    assert wait_for(lambda: harness.unbound == [harness.session])
    time.sleep(0.1)
    assert harness.unbound == [harness.session]
    assert harness.session.waiting()["reason"] == "unknown_device"


def test_another_clients_replaced_stands_aside_until_reconnect(harness):
    harness.connect()
    harness.transport.frame("c1", {"type": "refused", "code": "replaced"})
    harness.transport.emit(
        {"event": "session_end", "binding": "c1", "code": "replaced"}
    )
    assert wait_for(lambda: harness.session.connection() == CONNECTION_REPLACED)
    harness.session.reconnect()
    harness.transport.next_command("dial")
    assert harness.session.connection() == CONNECTION_CONNECTING


def test_a_session_that_ends_with_no_code_is_connecting_at_once(harness):
    harness.connect()
    harness.transport.emit({"event": "session_end", "binding": "c1"})
    assert wait_for(lambda: harness.session.connection() == CONNECTION_CONNECTING)
    assert harness.session.service_entries() == []


@pytest.mark.parametrize("is_frame_first", [True, False])
@pytest.mark.parametrize(
    "params, wait_s",
    [({"retry_after_s": 5}, 5), ({}, CLIENT_BACKOFF_MAX_S)],
)
def test_a_session_refused_mid_session_counts_down_the_transports_wait(
    harness, is_frame_first, params, wait_s
):
    harness.connect()
    if is_frame_first:
        harness.transport.frame(
            "c1", {"type": "refused", "code": "control_unavailable", "params": params}
        )
    harness.transport.emit(
        {
            "event": "session_end",
            "binding": "c1",
            "code": "control_unavailable",
            "params": params,
        }
    )
    assert wait_for(lambda: harness.session.waiting() is not None)
    waiting = harness.session.waiting()
    assert waiting["reason"] == "hub_silent"
    assert wait_s - 2 < waiting["next_round_at"] - time.time() <= wait_s


def test_a_round_end_while_connected_changes_nothing(harness):
    harness.connect()
    harness.transport.emit(
        {"event": "round_end", "binding": "c1", "code": "hub_unreachable"}
    )
    time.sleep(0.1)
    assert harness.session.connection() == CONNECTION_CONNECTED


# --- the person's presses ---


def test_a_refresh_on_a_connected_hub_asks_for_the_whole_state(harness):
    harness.connect()
    assert harness.session.refresh()
    assert harness.transport.next_frame("report")["frame"]["is_refresh"] is True
    assert harness.session.is_refreshing()
    harness.transport.frame("c1", STATE)
    assert wait_for(lambda: not harness.session.is_refreshing())


def test_a_refresh_on_a_waiting_hub_starts_a_round(harness):
    harness.transport.next_command("dial")
    # The session takes the dial's answer first. A refresh before it starts no round.
    assert wait_for(
        lambda: any(line.startswith("dialling the hub at") for line in harness.lines)
    )
    harness.transport.emit(
        {"event": "round_end", "binding": "c1", "code": "hub_unreachable"}
    )
    assert wait_for(lambda: harness.session.waiting() is not None)
    assert harness.session.refresh()
    assert harness.transport.next_command("round")["binding"] == "c1"
    assert harness.session.connection() == CONNECTION_CONNECTING


def test_a_network_change_is_a_round(harness):
    harness.connect()
    harness.session.change_network()
    assert harness.transport.next_command("round")["binding"] == "c1"


def test_a_network_turning_on_gives_its_address_and_a_round(harness):
    harness.connect()
    harness.session.set_overlay_route("100.64.0.1", "netbird")
    dial = harness.transport.next_command("dial")
    assert dial["candidates"][0] == {
        "address": "tcp://100.64.0.1:8443",
        "path": "netbird",
    }
    harness.transport.next_command("round")


# --- the transport ending, and the stop ---


def test_a_transport_that_ends_drops_the_session_and_dials_again_once_back(harness):
    harness.connect()
    harness.transport.drop_control()
    assert wait_for(lambda: harness.session.connection() == CONNECTION_CONNECTING)
    assert harness.transport.next_command("dial")["binding"] == "c1"


def test_a_stop_undials(harness):
    harness.connect()
    harness.session.stop()
    assert harness.transport.next_command("undial")["binding"] == "c1"


def test_a_leave_is_told_through_the_transport(harness):
    harness.connect()
    harness.transport.answers["leave"] = lambda line: {}
    assert harness.session.tell_left() == {}
    leave = harness.transport.next_command("leave")
    assert leave["binding"] == "c1"
    assert leave["psk"] == hashlib.sha256(b"tok").hexdigest()
    assert HUB_URL in leave["addresses"]


# --- the streams ---


def test_a_shell_opens_naming_its_machine_its_size_and_its_account(harness):
    harness.connect()
    harness.session.open_shell("d1", 80, 24, "s1", is_shared=True, account="lab")
    peer = harness.transport.next_open()
    assert peer.binding == "c1"
    assert peer.open == {
        "kind": "shell",
        "device_id": "d1",
        "cols": 80,
        "rows": 24,
        "account": "lab",
        "session_id": "s1",
        "is_shared": True,
    }


def test_an_exec_opens_with_its_argv_and_tags_its_outputs_without_a_terminal(
    harness,
):
    harness.connect()
    stream = harness.session.open_exec("d1", ["uptime"], False, 80, 24)
    peer = harness.transport.next_open()
    assert peer.open == {
        "kind": "exec",
        "device_id": "d1",
        "argv": ["uptime"],
        "is_tty": False,
        "cols": 80,
        "rows": 24,
        "account": "",
    }
    peer.accept()
    peer.send_record(RECORD_DATA, b"up")
    assert stream.read(WAIT_S) == b"\x01up"


def test_a_connect_opens_raw_after_its_accept(harness):
    harness.connect()
    stream = harness.session.open_connect({"id": "ssh_server_d1_lab"})
    peer = harness.transport.next_open()
    assert peer.open == {"kind": "connect", "id": "ssh_server_d1_lab"}
    peer.accept()
    peer.send_raw(b"SSH-2.0-x\r\n")
    assert stream.read(WAIT_S) == b"SSH-2.0-x\r\n"


def test_no_stream_opens_while_the_hub_is_not_connected(harness):
    with pytest.raises(GatewayUnreachable):
        harness.session.open_connect({"id": "x"})


# --- the join ---


def pending(config_path) -> dict:
    binding = enrollment._binding(
        {
            "id": "pending_1",
            "name": "box",
            "gateway_url": HUB_URL,
            "gateway_urls": [HUB_URL],
            "hub_key": HUB_KEY,
            "private_key": PRIVATE_KEY,
            "ticket": "tkt",
            "is_pending": True,
        }
    )
    bind(config_path, bindings=[binding])
    return binding


def test_a_pending_join_is_spent_through_the_transport_and_then_dialled(config_path):
    made = Harness(
        pending(config_path),
        answers={"join": lambda line: {"binding_id": "c9", "token": "t9"}},
    )
    try:
        join = made.transport.next_command("join")
        assert join["binding"] == "pending_1"
        assert join["ticket"] == "tkt"
        assert join["hub_key"] == HUB_KEY
        assert join["private_key"] == PRIVATE_KEY
        assert join["role"] == "client" and join["protocol"] == PROTOCOL
        assert join["addresses"] == ["tcp://hub.neutrino.internal:8443", HUB_URL]
        assert join["platform"]["os"]
        dial = made.transport.next_command("dial")
        assert dial["binding"] == "c9"
        assert dial["psk"] == hashlib.sha256(b"t9").hexdigest()
        kept = enrollment.load_config()["bindings"]
        assert [(item["id"], item["token"]) for item in kept] == [("c9", "t9")]
        assert "ticket" not in kept[0]
        assert made.session.local_key == "pending_1"
        assert made.session.label == "c9"
    finally:
        made.close()


def test_a_refused_ticket_waits_for_good(config_path):
    made = Harness(
        pending(config_path), answers={"join": lambda line: {"code": "ticket_spent"}}
    )
    try:
        made.transport.next_command("join")
        assert wait_for(lambda: made.session.waiting() is not None)
        assert made.session.waiting()["reason"] == "join_refused"
        with pytest.raises(queue.Empty):
            made.transport.next_command("join", timeout_s=1.5)
    finally:
        made.close()


def test_a_paused_join_counts_down_and_joins_again(config_path):
    made = Harness(
        pending(config_path),
        answers={
            "join": lambda line: {
                "code": "admission_paused",
                "params": {"retry_after_s": 1},
            }
        },
    )
    try:
        made.transport.next_command("join")
        assert wait_for(lambda: made.session.waiting() is not None)
        assert made.session.waiting()["reason"] == "admission_paused"
        made.transport.next_command("join", timeout_s=4)
    finally:
        made.close()


@pytest.mark.parametrize(
    "params, wait_s", [({"retry_after_s": 5}, 5), ({}, CLIENT_BACKOFF_MAX_S)]
)
def test_a_join_refused_control_unavailable_joins_again_after_its_retry_after_s(
    config_path, params, wait_s
):
    now = [1000.0]
    made = Harness(
        pending(config_path),
        clock=lambda: now[0],
        answers={
            "join": lambda line: {
                "code": "control_unavailable",
                "params": params,
            }
        },
    )
    try:
        made.transport.next_command("join")
        assert wait_for(lambda: made.session.waiting() is not None)
        waiting = made.session.waiting()
        assert waiting["reason"] == "hub_silent"
        assert wait_s - 2 < waiting["next_round_at"] - time.time() <= wait_s
        now[0] += wait_s - 1
        with pytest.raises(queue.Empty):
            made.transport.next_command("join", timeout_s=1.5)
        now[0] += 1
        made.transport.next_command("join", timeout_s=4)
    finally:
        made.close()


def test_a_join_that_reached_no_address_waits_and_tries_again(config_path):
    made = Harness(
        pending(config_path),
        answers={
            "join": lambda line: {
                "code": "hub_unreachable",
                "params": {"detail": "timeout"},
            }
        },
    )
    try:
        made.transport.next_command("join")
        assert wait_for(lambda: made.session.waiting() is not None)
        assert made.session.waiting()["reason"] == "hub_silent"
        made.session.change_network()
        made.transport.next_command("join")
    finally:
        made.close()


def test_a_join_on_another_key_waits_untrusted_a_minute(config_path):
    made = Harness(
        pending(config_path), answers={"join": lambda line: {"code": "hub_untrusted"}}
    )
    try:
        made.transport.next_command("join")
        assert wait_for(lambda: made.session.waiting() is not None)
        waiting = made.session.waiting()
        assert waiting["reason"] == "untrusted"
        assert waiting["next_round_at"] - time.time() > CLIENT_BACKOFF_MAX_S - 5
    finally:
        made.close()


# --- a binding of 0.5 ---


def legacy(config_path) -> dict:
    binding = dict(
        BINDING,
        gateway_url="https://192.168.1.2:8443",
        gateway_urls=["https://192.168.1.2:8443"],
        hub_key="",
        private_key="",
        fingerprint="ff" * 32,
    )
    bind(config_path, bindings=[binding])
    return enrollment._binding(binding)


def test_a_binding_of_05_waits_on_hub_key_missing_and_dials_nothing(config_path):
    made = Harness(legacy(config_path))
    try:
        assert made.session.waiting() == {
            "reason": "join_refused",
            "code": {"code": "hub_key_missing", "params": {}},
            "next_round_at": None,
        }
        assert not made.session.refresh()
        made.session.change_network()
        with pytest.raises(queue.Empty):
            made.transport.next_command(timeout_s=1.5)
        assert made.session.tell_left() == {}
    finally:
        made.close()
