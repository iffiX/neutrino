"""This machine's place on each hub's virtual network.

The drivers run on a scripted platform. Pinned here: EasyTier is asked of the
client's EasyTier daemon, here the real daemon behind a fake socket, with
the secret and the console's address in the request's body and never on a
CLI's argument vector; a manual network's status asks the one portal by the
network's name, and a console's is the instance the daemon's own networks do
not name.

The memberships run on recording drivers, beside a second engine shaped as
NetBird's in every tree. Pinned here: the three states
``off``, ``connecting`` and ``on`` and nothing else; a connect is one attempt
in two stages, ``login`` until the engine has an address, within its
limit, and ``hub`` until the hub's channel is up through the hub's own
address there, with no limit, each stage stamped with the second it began;
it ends ``on``, or ``off`` with the engine's code or ``overlay_no_address``,
its engine stopped, with no retry, or ``off`` with the engine's code when
the engine stops during the ``hub`` stage; a console that assigns no network keeps the connect waiting
with no limit; the ``hub`` stage probes one address, the hub's own first,
and never another; each stage's start and end is a log line; Cancel stops a
connect in either stage and Disconnect a network that is on; a press that
does not fit the state is dropped; the picker changes the engine only while
off and nothing changes it by itself; a network the hub stops naming goes
off with ``overlay_withdrawn``; an engine that stops by itself goes off with
its code; a binding last on gets one connect at start; a hub's release stops
the engine only when no other hub is on it.
"""

import functools
import json
import subprocess
import threading
import time
import urllib.parse

import pytest

from neutrino_client.constants import CLIENT_EASYTIER_RPC_PORTAL
from neutrino_client.core import overlay as overlay_module
from neutrino_client.core.easytier_daemon import EasytierDaemon
from neutrino_client.core.overlay import (
    OVERLAY_STATES,
    OverlayEasytierDriver,
    OverlayMemberships,
    overlay_hub_host,
    overlay_key,
    overlay_network,
)
from neutrino_client.exceptions import OverlayControlError
from tests.conftest import discard

KEY = "SETUP-KEY-1"  # scan: allow
NETBIRD = {
    "provider": "netbird",
    "setup_key": KEY,
    "management_url": "https://nb.example",
    "fqdn": "hub.nb.example",
}
EASYTIER = {
    "provider": "easytier",
    "mode": "manual",
    "network_name": "home",
    "network_secret": "s3cret",  # scan: allow
    "peer": "tcp://203.0.113.7:11010",
    "hub_address": "10.144.144.1",
}
CONSOLE_ADDRESS = "tcp://et-web.console.easytier.net:22020/etk_token1"  # scan: allow
CONSOLE = {
    "provider": "easytier",
    "mode": "console",
    "config_server": CONSOLE_ADDRESS,
    "is_secure_mode": True,
    "hub_address": "10.126.126.1",
}


class ScriptedPlatform:
    """Runs no CLI: every call is recorded and answered from a table.

    Attributes:
        runs: ``(binary, args)`` for every CLI run, in order.
        answers: ``{(binary, first arg or last arg): CompletedProcess}``.
    """

    def __init__(self, tmp_path):
        self._config_dir = str(tmp_path / "config")
        self.runs = []
        self.answers = {}

    def config_dir(self) -> str:
        return self._config_dir

    def easytier_daemon_address(self) -> str:
        return "/run/fake_easytier.sock"

    def answer(self, binary, verb, stdout="", returncode=0, stderr=""):
        self.answers[(binary, verb)] = subprocess.CompletedProcess(
            [binary], returncode, stdout=stdout, stderr=stderr
        )

    def run_overlay(self, binary, args, timeout_s):
        self.runs.append((binary, list(args)))
        verb = args[0] if binary == "netbird" else args[-1]
        answer = self.answers.get((binary, verb))
        if answer is None:
            return subprocess.CompletedProcess([binary], 0, stdout="", stderr="")
        return answer


class RunningSupervisor:
    """A core that runs whenever the daemon has something to run."""

    def __init__(self):
        self.applies = 0
        self.is_running = False

    def apply(self):
        self.applies += 1
        self.is_running = True


class FakeSocket:
    """The daemon's socket: each request crosses as JSON to a real daemon.

    Attributes:
        requests: Every request as it crossed, decoded.
        error: Raised instead of answering, for a daemon that is down.
        refusal: Answered to every request but a status.
    """

    def __init__(self, tmp_path):
        self.supervisor = RunningSupervisor()
        self.daemon = EasytierDaemon(
            state_dir=str(tmp_path / "easytier_state"),
            core_path="/opt/easytier-core",
            supervisor=self.supervisor,
            log=discard,
        )
        self.requests = []
        self.addresses = []
        self.error = None
        self.refusal = None

    def __call__(self, address, request):
        self.addresses.append(address)
        if self.error is not None:
            raise self.error
        crossed = json.loads(json.dumps(request))
        self.requests.append(crossed)
        if self.refusal is not None and crossed["verb"] != "status":
            return dict(self.refusal)
        return json.loads(json.dumps(self.daemon.handle(crossed)))


def drivers(tmp_path):
    """The EasyTier driver over one scripted platform."""
    platform = ScriptedPlatform(tmp_path)
    platform.socket = FakeSocket(tmp_path)
    return (
        OverlayEasytierDriver(platform=platform, ask=platform.socket),
        platform,
    )


def test_the_hubs_address_is_its_own_then_a_url_inside_the_network():
    urls = ["https://192.168.10.1:8443", "https://100.88.92.30:8443"]
    assert (
        overlay_hub_host(dict(EASYTIER, hub_address="10.144.144.1/24"), urls)
        == "10.144.144.1"
    )
    easytier_urls = ["https://hub.lan:8443", "https://10.144.144.9:8443"]
    bare = dict(EASYTIER, hub_address="")
    assert overlay_hub_host(bare, easytier_urls, "10.144.144.0/24") == "10.144.144.9"
    assert overlay_hub_host(bare, easytier_urls, "10.200.0.0/24") == ""
    assert overlay_hub_host(bare, easytier_urls) == ""


# --- EasyTier ---


def easytier_peers():
    return json.dumps(
        [
            {"cost": "Local", "ipv4": "10.144.144.5/24", "hostname": "box"},
            {"cost": "p2p", "ipv4": "10.144.144.1", "hostname": "hub"},
        ]
    )


def joined(platform, *names):
    """The daemon holds these manual networks."""
    for name in names:
        platform.socket.daemon.handle(
            {
                "verb": "join",
                "network_name": name,
                "network_secret": "x",  # scan: allow
                "peer": "tcp://203.0.113.7:11010",
                "hostname": "box",
            }
        )


def test_an_easytier_join_hands_the_daemon_the_secret_in_the_body(tmp_path):
    easytier, platform = drivers(tmp_path)

    easytier.join(EASYTIER, "Alice's box")

    joins = [r for r in platform.socket.requests if r["verb"] == "join"]
    assert joins == [
        {
            "verb": "join",
            "network_name": "home",
            "network_secret": "s3cret",  # scan: allow
            "peer": "tcp://203.0.113.7:11010",
            "hostname": "Alice-s-box",
        }
    ]
    assert platform.socket.addresses[0] == "/run/fake_easytier.sock"
    assert platform.socket.daemon.networks() == ["home"]
    assert all("s3cret" not in " ".join(args) for _b, args in platform.runs)


def test_the_easytier_status_asks_the_one_portal_by_network_name(tmp_path):
    easytier, platform = drivers(tmp_path)
    joined(platform, "home")
    platform.answer("easytier-cli", "peer", stdout=easytier_peers())

    status = easytier.status(EASYTIER)

    assert platform.runs == [
        (
            "easytier-cli",
            ["-p", CLIENT_EASYTIER_RPC_PORTAL, "-o", "json", "-n", "home", "peer"],
        )
    ]
    assert (status["is_on"], status["address"], status["is_hub_seen"]) == (
        True,
        "10.144.144.5",
        True,
    )


def test_a_network_the_daemon_does_not_hold_is_off_without_asking_the_core(
    tmp_path,
):
    easytier, platform = drivers(tmp_path)

    assert easytier.status(EASYTIER)["is_on"] is False
    assert platform.runs == []


def test_the_hub_is_seen_only_at_its_own_address(tmp_path):
    easytier, platform = drivers(tmp_path)
    joined(platform, "home")
    platform.answer("easytier-cli", "peer", stdout=easytier_peers())

    assert (
        easytier.status(dict(EASYTIER, hub_address="10.144.144.9"))["is_hub_seen"]
        is False
    )
    assert easytier.status(EASYTIER)["is_hub_seen"] is True


def test_an_instance_the_core_does_not_run_is_off(tmp_path):
    easytier, platform = drivers(tmp_path)
    joined(platform, "home")
    platform.answer(
        "easytier-cli",
        "peer",
        stderr="Error: Rust error: No instance matches the selector",
    )

    assert easytier.status(EASYTIER)["is_on"] is False


def test_a_daemon_that_does_not_answer_is_daemon_down_for_easytier(tmp_path):
    easytier, platform = drivers(tmp_path)
    platform.socket.error = ConnectionRefusedError(111, "Connection refused")

    with pytest.raises(OverlayControlError) as refused:
        easytier.status(EASYTIER)
    assert refused.value.code == "overlay_daemon_down"


def test_a_daemons_refusal_is_the_joins_code(tmp_path):
    easytier, platform = drivers(tmp_path)
    platform.socket.refusal = {"code": "overlay_peer_invalid", "params": {}}

    with pytest.raises(OverlayControlError) as refused:
        easytier.join(EASYTIER, "box")
    assert refused.value.code == "overlay_peer_invalid"


def test_an_easytier_leave_asks_the_daemon_to_drop_the_network(tmp_path):
    easytier, platform = drivers(tmp_path)
    joined(platform, "home")

    easytier.leave(EASYTIER)

    assert {"verb": "leave", "network_name": "home"} in platform.socket.requests
    assert platform.socket.daemon.networks() == []


# --- EasyTier consoles ---


def console_nodes():
    """Two instances: the manual ``home`` and the console's own."""
    return json.dumps(
        [
            {"instance_name": "home", "result": {"ipv4_addr": "10.144.144.5/24"}},
            {"instance_name": "office", "result": {"ipv4_addr": "10.126.126.4/24"}},
        ]
    )


def console_peers():
    return json.dumps(
        [
            {"cost": "Local", "ipv4": "10.126.126.4/24", "hostname": "box"},
            {"cost": "p2p", "ipv4": "10.126.126.1", "hostname": "hub"},
        ]
    )


def test_a_console_is_keyed_by_its_address_and_named_by_its_host():
    assert overlay_key(CONSOLE) == "easytier_console:" + CONSOLE_ADDRESS
    assert overlay_network(CONSOLE) == "et-web.console.easytier.net"
    assert overlay_key(EASYTIER) == "easytier:home"


def test_a_console_join_hands_the_daemon_the_address_in_the_body(tmp_path):
    easytier, platform = drivers(tmp_path)

    easytier.join(CONSOLE, "box")

    joins = [r for r in platform.socket.requests if r["verb"] == "join_console"]
    assert joins == [
        {
            "verb": "join_console",
            "config_server": CONSOLE_ADDRESS,
            "is_secure_mode": True,
        }
    ]
    assert all("etk_token1" not in " ".join(args) for _b, args in platform.runs)


def test_a_console_is_on_at_the_instance_no_manual_network_names(tmp_path):
    easytier, platform = drivers(tmp_path)
    joined(platform, "home")
    easytier.join(CONSOLE, "box")
    platform.answer("easytier-cli", "node", stdout=console_nodes())
    platform.answer("easytier-cli", "peer", stdout=console_peers())

    status = easytier.status(CONSOLE)

    assert (status["is_on"], status["address"], status["is_hub_seen"]) == (
        True,
        "10.126.126.4",
        True,
    )
    assert (
        "easytier-cli",
        ["-p", CLIENT_EASYTIER_RPC_PORTAL, "-o", "json", "-n", "office", "peer"],
    ) in platform.runs


def test_a_console_whose_core_runs_no_instance_yet_has_no_address(tmp_path):
    easytier, platform = drivers(tmp_path)
    easytier.join(CONSOLE, "box")
    platform.answer(
        "easytier-cli", "node", returncode=1, stderr="no running instances found"
    )

    status = easytier.status(CONSOLE)

    assert (status["is_on"], status["is_waiting"], status["address"]) == (
        False,
        True,
        "",
    )


def test_another_console_held_by_the_daemon_is_another_network(tmp_path):
    other = "tcp://console.example:22020/etk_other"
    easytier, platform = drivers(tmp_path)
    platform.socket.daemon.handle({"verb": "join_console", "config_server": other})

    assert easytier.status(CONSOLE)["is_other_network"] is True
    easytier.leave(CONSOLE)
    assert platform.socket.daemon.console() is not None


# --- the memberships ---


class SecondEngine:
    """A second engine beside EasyTier, shaped as NetBird's, in every tree."""

    provider = "netbird"

    @staticmethod
    def key(material):
        return "netbird:" + SecondEngine.network(material)

    @staticmethod
    def network(material):
        return urllib.parse.urlsplit(material.get("management_url", "")).hostname or ""

    @staticmethod
    def hub_network(network):
        return network or "100.64.0.0/10"

    @staticmethod
    def hub_name(material):
        return str(material.get("fqdn", "") or "")


@pytest.fixture(autouse=True)
def second_engine(monkeypatch):
    """The memberships see a second engine whether or not the tree has one."""
    monkeypatch.setattr(
        overlay_module, "overlay_engines", lambda: {"netbird": SecondEngine}
    )


class FakeDriver:
    """An engine that does as it is told and remembers what.

    Attributes:
        steps: ``(verb, provider)`` for every join and leave, in order,
            shared between the drivers of one test.
        is_on: Whether the engine runs the network.
        address: The address it reports while on; empty for none yet.
        join_refusal: The code a join fails with, empty for none.
        status_refusal: The code a status fails with, empty for none.
        on_join: Called inside a join, for a test to act mid-step.
    """

    def __init__(self, provider, steps):
        self.provider = provider
        self.steps = steps
        self.is_on = False
        self.address = "10.0.0.5"
        self.join_refusal = ""
        self.status_refusal = ""
        self.on_join = None
        self.on_status = None
        self.is_waiting = False

    def status(self, material):
        if self.on_status is not None:
            self.on_status()
        if self.status_refusal:
            raise OverlayControlError(self.status_refusal)
        return {
            "is_on": self.is_on,
            "is_waiting": self.is_waiting,
            "is_other_network": False,
            "address": self.address if self.is_on else "",
            "network": "",
            "is_hub_seen": self.is_on,
        }

    def join(self, material, hostname):
        self.steps.append(("join", self.provider))
        if self.on_join is not None:
            self.on_join()
        if self.join_refusal:
            raise OverlayControlError(self.join_refusal)
        self.is_on = True

    def leave(self, material):
        self.steps.append(("leave", self.provider))
        self.is_on = False


class Clock:
    """A monotonic clock a test moves by hand, moved by every wait."""

    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class Hubs:
    """What the resident hands the memberships, and what it is told.

    Attributes:
        rows: ``{hub_id: [objects]}`` in join order.
        choices: ``{hub_id: (is_on, pick)}``.
        kept: Every ``(hub_id, is_on, pick)`` written onto a binding.
        routes: Every ``(hub_id, hosts, is_only)`` the channel was pointed
            at.
        probes: Every ``hosts`` the hub was asked to answer through.
        is_reached: Whether the hub's channel answers through the network.
        urls: ``{hub_id: [urls]}`` the bindings hold.
    """

    def __init__(self, rows):
        self.rows = dict(rows)
        self.choices = {}
        self.kept = []
        self.routes = []
        self.probes = []
        self.is_reached = True
        self.urls = {}
        self.on_reach = None

    def __call__(self):
        answer = []
        for hub_id, overlays in self.rows.items():
            is_on, pick = self.choices.get(hub_id, (False, ""))
            answer.append(
                {
                    "hub_id": hub_id,
                    "overlays": list(overlays),
                    "urls": list(self.urls.get(hub_id, [])),
                    "is_on": is_on,
                    "pick": pick,
                }
            )
        return answer

    def keep(self, hub_id, is_on, pick):
        self.kept.append((hub_id, is_on, pick))
        self.choices[hub_id] = (is_on, pick)

    def route(self, hub_id, hosts, is_only):
        self.routes.append((hub_id, list(hosts), is_only))

    def reaches(self, hub_id, hosts):
        self.probes.append(list(hosts))
        if self.on_reach is not None:
            self.on_reach()
        return self.is_reached


def run_inline(target) -> None:
    target()


def subject_for(
    rows,
    *,
    start_thread=run_inline,
    timeout_s=0.05,
    log=discard,
    clock=None,
    login_s=None,
    poll_s=0.01,
):
    steps = []
    engines = {
        "netbird": FakeDriver("netbird", steps),
        "easytier": FakeDriver("easytier", steps),
    }
    hubs = Hubs(rows)
    subject = OverlayMemberships(
        platform=None,
        bindings_of=hubs,
        hostname="box",
        log=log,
        on_route=hubs.route,
        reaches_hub=hubs.reaches,
        keep_choice=hubs.keep,
        drivers=engines,
        start_thread=start_thread,
        clock=clock,
        login_timeout_s=timeout_s if login_s is None else login_s,
        hub_probe_s=poll_s,
        poll_s=poll_s,
    )
    return subject, engines, hubs, steps


def test_the_states_are_off_connecting_and_on_and_nothing_else():
    assert OVERLAY_STATES == ("off", "connecting", "on")


def test_a_hub_starts_off_on_its_first_network_with_both_listed():
    subject, _engines, _hubs, steps = subject_for({"h1": [NETBIRD, EASYTIER]})
    subject.refresh_bindings()

    row = subject.hub_row("h1")

    assert row == {
        "network": "netbird",
        "networks": [
            {"provider": "netbird", "network": "nb.example"},
            {"provider": "easytier", "network": "home"},
        ],
        "state": "off",
        "stage": "",
        "stage_since": 0,
        "is_waiting": False,
        "address": "",
        "error": None,
    }
    assert subject.job("h1") == ""
    assert steps == []


def test_a_connect_ends_on_with_the_address_once_the_hub_answers_through_it():
    subject, _engines, hubs, steps = subject_for({"h1": [NETBIRD, EASYTIER]})

    subject.connect("h1")

    row = subject.hub_row("h1")
    assert (row["state"], row["address"], row["error"]) == ("on", "10.0.0.5", None)
    assert subject.job("h1") == ""
    assert steps == [("join", "netbird")]
    assert hubs.routes == [
        ("h1", ["hub.nb.example"], True),
        ("h1", ["hub.nb.example"], False),
    ]
    assert hubs.kept == [("h1", True, "netbird")]


def test_a_connect_shows_connecting_and_its_job_until_it_ends():
    held = []
    subject, _engines, _hubs, _steps = subject_for(
        {"h1": [NETBIRD]}, start_thread=held.append
    )

    subject.connect("h1")

    assert subject.hub_row("h1")["state"] == "connecting"
    assert subject.job("h1") == "connecting"
    held[0]()
    assert subject.hub_row("h1")["state"] == "on"


def test_an_engine_that_will_not_start_is_off_with_its_code_and_no_retry():
    subject, engines, hubs, steps = subject_for({"h1": [NETBIRD, EASYTIER]})
    engines["netbird"].join_refusal = "overlay_join_failed"

    subject.connect("h1")
    subject.watch()

    row = subject.hub_row("h1")
    assert (row["state"], row["error"]) == (
        "off",
        {"code": "overlay_join_failed", "params": {}},
    )
    assert row["network"] == "netbird"
    assert steps == [("join", "netbird")]
    assert hubs.kept[-1] == ("h1", False, "")


def test_no_address_in_time_is_off_with_its_code_and_the_engine_stopped():
    subject, engines, hubs, steps = subject_for({"h1": [EASYTIER]})
    engines["easytier"].address = ""

    subject.connect("h1")

    assert subject.hub_row("h1")["error"] == {
        "code": "overlay_no_address",
        "params": {},
    }
    assert subject.hub_row("h1")["state"] == "off"
    assert steps == [("join", "easytier"), ("leave", "easytier")]
    assert hubs.routes == [("h1", [], False)]


def test_the_hub_stage_has_no_limit():
    clock = Clock()
    subject, _engines, hubs, steps = subject_for(
        {"h1": [EASYTIER]}, clock=clock, login_s=90, poll_s=0
    )
    hubs.is_reached = False

    def tick():
        clock.now += 1
        hubs.is_reached = clock.now >= 1000 + 3600

    hubs.on_reach = tick

    subject.connect("h1")

    assert subject.hub_row("h1")["state"] == "on"
    assert clock.now == 1000 + 3600
    assert steps == [("join", "easytier")]


def test_a_cancel_stops_the_connect_and_goes_off_without_an_error():
    started = threading.Event()
    release = threading.Event()
    subject, engines, hubs, steps = subject_for(
        {"h1": [NETBIRD]}, start_thread=_thread, timeout_s=5
    )

    def hold():
        started.set()
        release.wait(5)

    engines["netbird"].on_join = hold
    subject.connect("h1")
    assert started.wait(5)

    subject.cancel("h1")
    _wait_for(lambda: subject.hub_row("h1")["state"] == "off")
    release.set()
    time.sleep(0.1)

    row = subject.hub_row("h1")
    assert (row["state"], row["error"]) == ("off", None)
    assert subject.job("h1") == ""
    assert ("leave", "netbird") in steps
    assert hubs.kept[-1] == ("h1", False, "")


def test_a_disconnect_stops_the_engine_and_goes_off():
    subject, _engines, hubs, steps = subject_for({"h1": [NETBIRD]})
    subject.connect("h1")

    subject.disconnect("h1")

    assert subject.hub_row("h1")["state"] == "off"
    assert steps == [("join", "netbird"), ("leave", "netbird")]
    assert hubs.routes[-1] == ("h1", [], False)
    assert hubs.kept[-1] == ("h1", False, "netbird")


def test_a_disconnect_shows_its_job_while_the_engine_stops():
    held = []
    subject, _engines, _hubs, _steps = subject_for({"h1": [NETBIRD]})
    subject.connect("h1")
    subject._start_thread = held.append

    subject.disconnect("h1")

    assert (subject.hub_row("h1")["state"], subject.job("h1")) == (
        "on",
        "disconnecting",
    )
    held[0]()
    assert (subject.hub_row("h1")["state"], subject.job("h1")) == ("off", "")


def test_presses_that_do_not_fit_the_state_are_dropped():
    held = []
    subject, _engines, _hubs, steps = subject_for(
        {"h1": [NETBIRD], "h2": []}, start_thread=held.append
    )

    subject.cancel("h1")
    subject.disconnect("h1")
    subject.connect("h2")
    subject.connect("h1")
    subject.connect("h1")
    subject.disconnect("h1")

    assert len(held) == 1
    held[0]()
    subject.connect("h1")
    subject.cancel("h1")
    assert len(held) == 1
    assert steps == [("join", "netbird")]


def test_the_pick_moves_the_engine_only_while_off_and_is_kept():
    subject, _engines, hubs, steps = subject_for({"h1": [NETBIRD, EASYTIER]})

    subject.pick("h1", "easytier")
    assert subject.hub_row("h1")["network"] == "easytier"
    assert hubs.kept == [("h1", False, "easytier")]

    subject.connect("h1")
    subject.pick("h1", "netbird")
    assert subject.hub_row("h1")["network"] == "easytier"
    assert steps == [("join", "easytier")]
    subject.pick("h1", "wireguard")
    assert hubs.kept[-1] == ("h1", True, "easytier")


def test_a_failed_connect_never_moves_to_another_network():
    subject, engines, _hubs, steps = subject_for({"h1": [NETBIRD, EASYTIER]})
    engines["netbird"].join_refusal = "overlay_join_failed"

    subject.connect("h1")
    for _ in range(3):
        subject.watch()

    assert steps == [("join", "netbird")]
    assert subject.hub_row("h1")["network"] == "netbird"


def test_a_network_the_hub_withdraws_while_on_goes_off_with_its_code():
    subject, _engines, hubs, steps = subject_for({"h1": [NETBIRD, EASYTIER]})
    subject.connect("h1")

    hubs.rows["h1"] = [EASYTIER]
    subject.refresh()

    row = subject.hub_row("h1")
    assert (row["state"], row["error"]) == (
        "off",
        {"code": "overlay_withdrawn", "params": {"network": "nb.example"}},
    )
    assert row["network"] == "easytier"
    assert steps == [("join", "netbird"), ("leave", "netbird")]


def test_an_engine_that_stops_by_itself_goes_off_with_a_code():
    subject, engines, _hubs, _steps = subject_for({"h1": [NETBIRD]})
    subject.connect("h1")

    engines["netbird"].is_on = False
    subject.watch()
    assert subject.hub_row("h1")["error"]["code"] == "overlay_engine_stopped"

    subject.connect("h1")
    engines["netbird"].status_refusal = "overlay_daemon_down"
    subject.watch()
    assert subject.hub_row("h1")["state"] == "off"
    assert subject.hub_row("h1")["error"]["code"] == "overlay_daemon_down"


def test_a_moved_address_is_drawn_while_on():
    subject, engines, _hubs, _steps = subject_for({"h1": [NETBIRD]})
    subject.connect("h1")

    engines["netbird"].address = "10.0.0.9"
    subject.watch()

    assert subject.hub_row("h1")["address"] == "10.0.0.9"


def test_a_refresh_clears_the_error_and_nothing_else():
    subject, engines, _hubs, _steps = subject_for({"h1": [NETBIRD]})
    engines["netbird"].join_refusal = "overlay_join_failed"
    subject.connect("h1")

    subject.clear_error("h1")

    assert subject.hub_row("h1")["error"] is None
    assert subject.hub_row("h1")["state"] == "off"


def test_a_binding_last_on_gets_one_connect_at_start_and_no_retry():
    subject, engines, hubs, steps = subject_for({"h1": [EASYTIER], "h2": [NETBIRD]})
    hubs.choices = {"h1": (True, "easytier"), "h2": (False, "")}
    engines["easytier"].join_refusal = "overlay_join_failed"

    subject.resume()
    subject.watch()
    subject.watch()

    assert steps == [("join", "easytier")]
    assert subject.hub_row("h1")["state"] == "off"
    assert hubs.choices["h1"] == (False, "easytier")
    assert subject.hub_row("h2")["state"] == "off"


def test_a_release_stops_the_engine_only_when_no_other_hub_is_on_it():
    subject, _engines, _hubs, steps = subject_for({"h1": [EASYTIER], "h2": [EASYTIER]})
    subject.connect("h1")
    subject.connect("h2")

    assert subject.release_hub("h1") == 0
    assert steps == [("join", "easytier"), ("join", "easytier")]
    assert subject.release_hub("h2") == 1
    assert steps[-1] == ("leave", "easytier")


def test_a_shutdown_keeps_every_network_and_counts_them():
    subject, _engines, _hubs, steps = subject_for({"h1": [NETBIRD]})
    subject.connect("h1")

    assert subject.release() == 1
    assert ("leave", "netbird") not in steps


def test_no_secret_reaches_a_row():
    subject, _engines, _hubs, _steps = subject_for(
        {"h1": [EASYTIER], "h2": [NETBIRD], "h3": [CONSOLE]}
    )
    subject.refresh_bindings()

    rows = json.dumps([subject.hub_row(hub) for hub in ("h1", "h2", "h3")])

    assert "s3cret" not in rows and KEY not in rows  # scan: allow
    assert "etk_token1" not in rows


def test_a_connect_logs_in_then_waits_for_the_hub_then_is_on():
    lines = []
    subject, engines, hubs, _steps = subject_for(
        {"h1": [EASYTIER]}, start_thread=_thread, timeout_s=5, log=lines.append
    )
    engines["easytier"].address = ""
    hubs.is_reached = False

    subject.connect("h1")
    row = subject.hub_row("h1")
    assert (row["state"], row["stage"], row["address"]) == ("connecting", "login", "")

    assert subject.hub_row("h1")["stage_since"] > 0
    engines["easytier"].address = "10.144.144.5"
    _wait_for(lambda: subject.hub_row("h1")["stage"] == "hub")
    row = subject.hub_row("h1")
    assert (row["state"], row["address"]) == ("connecting", "10.144.144.5")
    assert row["stage_since"] >= time.time() - 5

    hubs.is_reached = True
    _wait_for(lambda: subject.hub_row("h1")["state"] == "on")
    row = subject.hub_row("h1")
    assert (row["stage"], row["address"]) == ("", "10.144.144.5")
    ends = [line for line in lines if "ended after" in line]
    assert len(ends) == 2
    assert "stage login ended after" in ends[0] and "10.144.144.5" in ends[0]
    assert "stage hub ended after" in ends[1]
    assert len([line for line in lines if "started" in line]) == 2


def test_the_login_stage_has_its_own_limit():
    clock = Clock()
    subject, engines, _hubs, steps = subject_for(
        {"h1": [NETBIRD]}, clock=clock, login_s=90, poll_s=0
    )
    engines["netbird"].address = ""
    engines["netbird"].on_status = functools.partial(_advance, clock, 1)

    subject.connect("h1")

    assert subject.hub_row("h1")["error"]["code"] == "overlay_no_address"
    assert clock.now == 1090
    assert steps == [("join", "netbird"), ("leave", "netbird")]


@pytest.mark.parametrize(
    "how, code",
    [("stops", "overlay_engine_stopped"), ("refuses", "overlay_daemon_down")],
)
def test_an_engine_that_stops_during_the_hub_stage_ends_it_with_its_code(how, code):
    subject, engines, hubs, steps = subject_for({"h1": [EASYTIER]}, poll_s=0)
    hubs.is_reached = False
    engine = engines["easytier"]

    def stop_after_a_while():
        if len(hubs.probes) < 5:
            return
        if how == "stops":
            engine.is_on = False
        else:
            engine.status_refusal = code

    hubs.on_reach = stop_after_a_while

    subject.connect("h1")

    row = subject.hub_row("h1")
    assert (row["state"], row["stage"], row["error"]["code"]) == ("off", "", code)
    assert steps == [("join", "easytier")]
    assert hubs.routes[-1] == ("h1", [], False)


def test_a_console_that_assigns_no_network_keeps_the_connect_waiting():
    lines = []
    subject, engines, hubs, _steps = subject_for(
        {"h1": [CONSOLE]}, start_thread=_thread, timeout_s=0.1, log=lines.append
    )
    engines["easytier"].address = ""
    engines["easytier"].is_waiting = True

    subject.connect("h1")
    _wait_for(lambda: subject.hub_row("h1")["is_waiting"])
    time.sleep(0.3)
    row = subject.hub_row("h1")
    assert (row["state"], row["stage"], row["error"]) == ("connecting", "login", None)

    engines["easytier"].is_waiting = False
    engines["easytier"].address = "10.126.126.4"
    _wait_for(lambda: subject.hub_row("h1")["state"] == "on")
    assert subject.hub_row("h1")["is_waiting"] is False
    assert hubs.routes[0] == ("h1", ["10.126.126.1"], True)


def test_the_hub_stage_probes_one_address_only_until_it_ends():
    subject, _engines, hubs, _steps = subject_for(
        {"h1": [NETBIRD]}, start_thread=_thread, timeout_s=5
    )
    hubs.urls["h1"] = ["https://192.168.10.1:8443", "https://100.88.92.30:8443"]
    hubs.is_reached = False

    subject.connect("h1")
    _wait_for(lambda: len(hubs.probes) >= 3)
    assert hubs.routes == [("h1", ["100.88.92.30"], True)]
    hubs.is_reached = True
    _wait_for(lambda: subject.hub_row("h1")["state"] == "on")

    assert {tuple(hosts) for hosts in hubs.probes} == {("100.88.92.30",)}
    assert hubs.routes == [
        ("h1", ["100.88.92.30"], True),
        ("h1", ["100.88.92.30"], False),
    ]


def test_the_hub_stage_holds_every_round_to_the_address_before_it_probes():
    subject, _engines, hubs, _steps = subject_for({"h1": [EASYTIER]})
    seen = []
    hubs.on_reach = functools.partial(_note_routes, hubs, seen)

    subject.connect("h1")

    assert seen[0] == [("h1", ["10.144.144.1"], True)]
    assert subject.hub_row("h1")["state"] == "on"


def _note_routes(hubs, seen) -> None:
    seen.append(list(hubs.routes))


@pytest.mark.parametrize("stage", ["login", "hub"])
def test_a_cancel_in_either_stage_goes_off_without_an_error(stage):
    lines = []
    subject, engines, hubs, steps = subject_for(
        {"h1": [EASYTIER]}, start_thread=_thread, timeout_s=5, log=lines.append
    )
    hubs.is_reached = False
    if stage == "login":
        engines["easytier"].address = ""

    subject.connect("h1")
    _wait_for(lambda: subject.hub_row("h1")["stage"] == stage)
    subject.cancel("h1")
    _wait_for(lambda: subject.hub_row("h1")["state"] == "off")
    _wait_for(lambda: any("cancelled" in line for line in lines))

    row = subject.hub_row("h1")
    assert (row["error"], row["stage"]) == (None, "")
    assert ("leave", "easytier") in steps
    assert hubs.routes[-1] == ("h1", [], False)
    assert any(f"stage {stage} ended after" in line for line in lines)


def _advance(clock, seconds) -> None:
    clock.now += seconds


def _thread(target) -> None:
    threading.Thread(target=target, daemon=True).start()


def _wait_for(predicate, timeout_s=5) -> None:
    deadline = time.monotonic() + timeout_s
    while not predicate():
        assert time.monotonic() < deadline, "the state never came"
        time.sleep(0.01)
