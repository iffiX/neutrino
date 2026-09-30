"""This machine's membership of each hub's virtual network.

The CLIs run on a scripted platform. Pinned here: NetBird's join carries
the setup key, the management URL and ``--disable-dns``, and refuses without
running while the daemon is on another network; two hubs on one management
URL read one membership; EasyTier is asked of the client's EasyTier daemon,
here the real daemon behind a fake socket, with the secret and the console's
address in the request's body and never on a CLI's argument vector; a
manual network's status asks the one portal by the network's name, and a
console's is the instance the daemon's own networks do not name; a leave on
release happens only when no other hub names the network; a lane that works
answers busy; a step's failure stays until the network is on; every state
word is in the table. A hub whose wish is on joins the first of its networks
or the one picked, once; its channel lost for the failover time, or its
current network gone from the list, moves it to the next, leaving first;
a hub with one network never switches.
"""

import json
import subprocess

import pytest

from neutrino_client.constants import (
    CLIENT_EASYTIER_RPC_PORTAL,
    CLIENT_OVERLAY_FAILOVER_S,
)
from neutrino_client.core.easytier_daemon import EasytierDaemon
from neutrino_client.core.overlay import (
    OVERLAY_STATES,
    OverlayEasytierDriver,
    OverlayMemberships,
    OverlayNetbirdDriver,
    netbird_management_key,
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
    "hub_address": "",
}
CONSOLE_ADDRESS = "tcp://et-web.console.easytier.net:22020/etk_token1"  # scan: allow
CONSOLE = {
    "provider": "easytier",
    "mode": "console",
    "config_server": CONSOLE_ADDRESS,
    "is_secure_mode": True,
    "hub_address": "10.126.126.1",
}


def netbird_status(url="https://nb.example:443", is_connected=True, peers=()):
    return json.dumps(
        {
            "management": {"url": url, "connected": is_connected},
            "netbirdIp": "100.64.0.7/16",
            "peers": {"details": list(peers)},
        }
    )


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
        if isinstance(answer, Exception):
            raise answer
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


def run_inline(target) -> None:
    target()


class Bindings:
    """What the resident would hand the memberships, one row per hub.

    Attributes:
        rows: ``(hub_id, object, a list of objects, or None)``.
        wishes: ``{hub_id: (is_wanted, pick)}``; a hub not named wants nothing.
        lost: ``{hub_id: monotonic time its channel was lost}``.
    """

    def __init__(self, rows):
        self.rows = list(rows)
        self.wishes = {}
        self.lost = {}

    def __call__(self):
        answer = []
        for hub_id, material in self.rows:
            if isinstance(material, dict):
                overlays = [material]
            else:
                overlays = list(material or [])
            is_wanted, pick = self.wishes.get(hub_id, (False, ""))
            answer.append(
                {
                    "hub_id": hub_id,
                    "overlays": overlays,
                    "is_wanted": is_wanted,
                    "pick": pick,
                    "lost_since": self.lost.get(hub_id),
                }
            )
        return answer


def memberships(tmp_path, rows, start_thread=run_inline):
    platform = ScriptedPlatform(tmp_path)
    platform.socket = FakeSocket(tmp_path)
    bindings = Bindings(rows)
    subject = OverlayMemberships(
        platform=platform,
        bindings_of=bindings,
        hostname="Alice's box",
        log=discard,
        start_thread=start_thread,
        drivers={
            "netbird": OverlayNetbirdDriver(platform=platform),
            "easytier": OverlayEasytierDriver(platform=platform, ask=platform.socket),
        },
    )
    return subject, platform, bindings


# --- NetBird ---


def test_a_netbird_join_carries_the_key_the_url_and_no_dns(tmp_path):
    subject, platform, _bindings = memberships(tmp_path, [("h1", NETBIRD)])
    platform.answer("netbird", "status", stdout=netbird_status(is_connected=False))

    assert subject.join("h1") == {}

    ups = [args for binary, args in platform.runs if args[0] == "up"]
    assert ups == [
        [
            "up",
            "--setup-key",
            KEY,
            "--management-url",
            "https://nb.example:443",
            "--disable-dns",
        ]
    ]


def test_a_daemon_on_another_network_is_refused_and_left_alone(tmp_path):
    subject, platform, _bindings = memberships(tmp_path, [("h1", NETBIRD)])
    platform.answer(
        "netbird", "status", stdout=netbird_status(url="https://api.netbird.io:443")
    )

    subject.join("h1")

    assert all(args[0] != "up" for _binary, args in platform.runs)
    row = subject.hub_row("h1")
    assert row["state"] == "failed"
    assert row["code"] == "overlay_other_network"
    assert row["params"] == {"network": "nb.example"}


def test_a_connected_daemon_reads_on_with_its_address_and_the_hub_seen(tmp_path):
    subject, platform, _bindings = memberships(tmp_path, [("h1", NETBIRD)])
    platform.answer(
        "netbird",
        "status",
        stdout=netbird_status(
            peers=[{"fqdn": "hub.nb.example", "status": "Connected"}]
        ),
    )

    subject.probe()

    row = subject.hub_row("h1")
    assert (row["state"], row["address"], row["is_hub_seen"]) == (
        "on",
        "100.64.0.7",
        True,
    )


def test_two_hubs_on_one_management_url_read_one_membership(tmp_path):
    other = dict(NETBIRD, management_url="https://NB.example:443/", fqdn="o")
    subject, platform, _bindings = memberships(
        tmp_path, [("h1", NETBIRD), ("h2", other)]
    )
    platform.answer("netbird", "status", stdout=netbird_status())

    subject.probe()

    assert overlay_key(NETBIRD) == overlay_key(other)
    assert [subject.hub_row(hub)["state"] for hub in ("h1", "h2")] == ["on", "on"]
    assert len([run for run in platform.runs if run[1][0] == "status"]) == 1


def test_a_daemon_that_does_not_answer_is_daemon_down(tmp_path):
    subject, platform, _bindings = memberships(tmp_path, [("h1", NETBIRD)])
    platform.answer(
        "netbird",
        "status",
        returncode=1,
        stderr="failed to connect to daemon error: context deadline exceeded",
    )

    subject.probe()

    assert subject.hub_row("h1")["code"] == "overlay_daemon_down"


def test_a_daemon_that_needs_login_reads_off(tmp_path):
    subject, platform, _bindings = memberships(tmp_path, [("h1", NETBIRD)])
    platform.answer("netbird", "status", stdout="Daemon status: NeedsLogin\n")

    subject.probe()

    assert subject.hub_row("h1")["state"] == "off"


def test_a_leave_is_netbird_down(tmp_path):
    subject, platform, _bindings = memberships(tmp_path, [("h1", NETBIRD)])
    platform.answer("netbird", "status", stdout=netbird_status(is_connected=False))

    assert subject.leave("h1") == {}

    assert ("netbird", ["down"]) in platform.runs
    assert subject.hub_row("h1")["state"] == "off"


def test_the_default_management_url_is_netbirds_own():
    assert netbird_management_key("") == "https://api.netbird.io:443"
    assert netbird_management_key("http://nb.lan") == "http://nb.lan:80"


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
    subject, platform, _bindings = memberships(tmp_path, [("h1", EASYTIER)])

    assert subject.join("h1") == {}

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
    subject, platform, _bindings = memberships(tmp_path, [("h1", EASYTIER)])
    joined(platform, "home")
    platform.answer("easytier-cli", "peer", stdout=easytier_peers())

    subject.probe()

    assert platform.runs == [
        (
            "easytier-cli",
            ["-p", CLIENT_EASYTIER_RPC_PORTAL, "-o", "json", "-n", "home", "peer"],
        )
    ]
    row = subject.hub_row("h1")
    assert (row["state"], row["address"], row["is_hub_seen"]) == (
        "on",
        "10.144.144.5",
        True,
    )


def test_a_network_the_daemon_does_not_hold_is_off_without_asking_the_core(
    tmp_path,
):
    subject, platform, _bindings = memberships(tmp_path, [("h1", EASYTIER)])

    subject.probe()

    assert subject.hub_row("h1")["state"] == "off"
    assert platform.runs == []


def test_the_hub_is_seen_only_at_its_own_address_when_it_names_one(tmp_path):
    named = dict(EASYTIER, hub_address="10.144.144.9")
    subject, platform, _bindings = memberships(tmp_path, [("h1", named)])
    joined(platform, "home")
    platform.answer("easytier-cli", "peer", stdout=easytier_peers())

    subject.probe()
    assert subject.hub_row("h1")["is_hub_seen"] is False

    bindings_row = dict(EASYTIER, hub_address="10.144.144.1")
    subject._bindings_of = Bindings([("h1", bindings_row)])
    subject.probe()
    assert subject.hub_row("h1")["is_hub_seen"] is True


def test_an_instance_the_core_does_not_run_is_off(tmp_path):
    subject, platform, _bindings = memberships(tmp_path, [("h1", EASYTIER)])
    joined(platform, "home")
    platform.answer(
        "easytier-cli",
        "peer",
        stderr="Error: Rust error: No instance matches the selector",
    )

    subject.probe()

    assert subject.hub_row("h1")["state"] == "off"


def test_a_portal_nobody_listens_on_is_off(tmp_path):
    subject, platform, _bindings = memberships(tmp_path, [("h1", EASYTIER)])
    joined(platform, "home")
    platform.answer(
        "easytier-cli", "peer", returncode=1, stderr="failed to connect to server"
    )

    subject.probe()

    assert subject.hub_row("h1")["state"] == "off"


def test_a_daemon_that_does_not_answer_is_daemon_down_for_easytier(tmp_path):
    subject, platform, _bindings = memberships(tmp_path, [("h1", EASYTIER)])
    platform.socket.error = ConnectionRefusedError(111, "Connection refused")

    subject.probe()
    assert subject.hub_row("h1")["code"] == "overlay_daemon_down"

    assert subject.join("h1") == {}
    assert subject.hub_row("h1")["state"] == "failed"
    assert subject.hub_row("h1")["code"] == "overlay_daemon_down"


def test_a_daemons_refusal_is_the_rows_code(tmp_path):
    subject, platform, _bindings = memberships(tmp_path, [("h1", EASYTIER)])
    platform.socket.refusal = {"code": "overlay_peer_invalid", "params": {}}

    subject.join("h1")

    assert subject.hub_row("h1")["code"] == "overlay_peer_invalid"


def test_a_step_failure_stays_until_the_network_is_on(tmp_path):
    subject, platform, _bindings = memberships(tmp_path, [("h1", EASYTIER)])
    platform.socket.refusal = {"code": "overlay_restart_failed", "params": {}}

    subject.join("h1")
    subject.probe()
    assert subject.hub_row("h1")["code"] == "overlay_restart_failed"

    platform.socket.refusal = None
    joined(platform, "home")
    platform.answer("easytier-cli", "peer", stdout=easytier_peers())
    subject.probe()
    assert subject.hub_row("h1")["state"] == "on"
    assert subject.hub_row("h1")["code"] == ""


def test_an_easytier_leave_asks_the_daemon_to_drop_the_network(tmp_path):
    subject, platform, _bindings = memberships(tmp_path, [("h1", EASYTIER)])
    joined(platform, "home")

    assert subject.leave("h1") == {}

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
    subject, platform, _bindings = memberships(tmp_path, [("h1", CONSOLE)])

    assert subject.join("h1") == {}

    joins = [r for r in platform.socket.requests if r["verb"] == "join_console"]
    assert joins == [
        {
            "verb": "join_console",
            "config_server": CONSOLE_ADDRESS,
            "is_secure_mode": True,
        }
    ]
    assert platform.socket.daemon.console() == {
        "config_server": CONSOLE_ADDRESS,
        "is_secure_mode": True,
    }
    assert all("etk_token1" not in " ".join(args) for _b, args in platform.runs)


def test_a_console_is_on_at_the_instance_no_manual_network_names(tmp_path):
    subject, platform, _bindings = memberships(tmp_path, [("h1", CONSOLE)])
    joined(platform, "home")
    subject.join("h1")
    platform.answer("easytier-cli", "node", stdout=console_nodes())
    platform.answer("easytier-cli", "peer", stdout=console_peers())

    subject.probe()

    row = subject.hub_row("h1")
    assert (row["state"], row["address"], row["is_hub_seen"]) == (
        "on",
        "10.126.126.4",
        True,
    )
    assert (
        "easytier-cli",
        ["-p", CLIENT_EASYTIER_RPC_PORTAL, "-o", "json", "-n", "office", "peer"],
    ) in platform.runs
    assert row["network"] == "et-web.console.easytier.net"


def test_a_lone_console_instance_is_read_from_its_configuration(tmp_path):
    subject, platform, _bindings = memberships(tmp_path, [("h1", CONSOLE)])
    subject.join("h1")
    platform.answer(
        "easytier-cli",
        "node",
        stdout=json.dumps({"config": 'instance_name = "office"\n'}),
    )
    platform.answer("easytier-cli", "peer", stdout=console_peers())

    subject.probe()

    assert subject.hub_row("h1")["state"] == "on"


def test_a_console_whose_core_runs_no_instance_yet_is_waiting(tmp_path):
    """The console holds the machine and has attached it to no network."""
    subject, platform, _bindings = memberships(tmp_path, [("h1", CONSOLE)])
    subject.join("h1")
    platform.answer(
        "easytier-cli", "node", returncode=1, stderr="no running instances found"
    )

    subject.probe()

    row = subject.hub_row("h1")
    assert (row["state"], row["code"], row["address"]) == ("waiting", "", "")
    assert subject.release() == 1


def test_a_waiting_console_turns_on_once_an_instance_appears(tmp_path):
    subject, platform, _bindings = memberships(tmp_path, [("h1", CONSOLE)])
    subject.join("h1")
    assert subject.hub_row("h1")["state"] == "waiting"

    platform.answer("easytier-cli", "node", stdout=console_nodes())
    platform.answer("easytier-cli", "peer", stdout=console_peers())
    subject.probe()

    assert subject.hub_row("h1")["state"] == "on"


def test_a_console_whose_core_is_not_running_is_off(tmp_path):
    subject, platform, _bindings = memberships(tmp_path, [("h1", CONSOLE)])
    subject.join("h1")
    platform.socket.supervisor.is_running = False

    subject.probe()

    assert subject.hub_row("h1")["state"] == "off"


def test_a_console_that_is_not_configured_is_off(tmp_path):
    subject, _platform, _bindings = memberships(tmp_path, [("h1", CONSOLE)])

    subject.probe()

    assert subject.hub_row("h1")["state"] == "off"


def test_leaving_a_waiting_console_drops_it(tmp_path):
    subject, platform, _bindings = memberships(tmp_path, [("h1", CONSOLE)])
    subject.join("h1")
    assert subject.hub_row("h1")["state"] == "waiting"

    assert subject.leave("h1") == {}

    assert platform.socket.daemon.console() is None
    assert subject.hub_row("h1")["state"] == "off"


def test_another_console_held_by_the_daemon_is_another_network(tmp_path):
    other = dict(CONSOLE, config_server="tcp://console.example:22020/etk_other")
    subject, platform, _bindings = memberships(tmp_path, [("h1", CONSOLE)])
    platform.socket.daemon.handle(
        {"verb": "join_console", "config_server": other["config_server"]}
    )

    subject.probe()
    assert subject.hub_row("h1")["code"] == "overlay_other_network"

    subject.join("h1")
    row = subject.hub_row("h1")
    assert (row["state"], row["code"]) == ("failed", "overlay_other_network")
    assert row["params"] == {"network": "et-web.console.easytier.net"}


def test_a_console_leave_drops_only_the_console_this_hub_names(tmp_path):
    other = dict(CONSOLE, config_server="tcp://console.example:22020/etk_other")
    subject, platform, bindings = memberships(tmp_path, [("h1", CONSOLE)])
    platform.socket.daemon.handle(
        {"verb": "join_console", "config_server": other["config_server"]}
    )

    subject.leave("h1")
    assert platform.socket.daemon.console() is not None
    assert all(r["verb"] != "leave_console" for r in platform.socket.requests)

    platform.socket.daemon.handle({"verb": "leave_console"})
    subject.join("h1")
    subject.leave("h1")
    assert platform.socket.daemon.console() is None


# --- the memberships ---


def test_a_hub_naming_no_network_has_no_row_and_no_join(tmp_path):
    subject, _platform, _bindings = memberships(tmp_path, [("h1", None)])

    assert subject.hub_row("h1") is None
    assert subject.join("h1") == {
        "code": "overlay_missing",
        "params": {"hub_id": "h1"},
    }


def test_a_working_lane_answers_busy(tmp_path):
    held = []
    subject, _platform, _bindings = memberships(
        tmp_path, [("h1", EASYTIER)], start_thread=held.append
    )

    assert subject.join("h1") == {}
    assert subject.hub_row("h1")["state"] == "joining"
    assert subject.leave("h1") == {"code": "busy", "params": {"step": "joining"}}
    held[0]()
    assert subject.hub_row("h1")["work"]["state"] == "idle"


def leaves(platform):
    return [r for r in platform.socket.requests if r["verb"] == "leave"]


def test_release_leaves_only_a_network_no_other_hub_names(tmp_path):
    subject, platform, bindings = memberships(
        tmp_path, [("h1", EASYTIER), ("h2", EASYTIER)]
    )
    joined(platform, "home")
    platform.answer("easytier-cli", "peer", stdout=easytier_peers())
    subject.probe()

    bindings.rows = [("h2", EASYTIER)]
    assert subject.release_hub("h1") == 0
    assert leaves(platform) == []

    bindings.rows = []
    assert subject.release_hub("h2") == 1
    assert leaves(platform) == [{"verb": "leave", "network_name": "home"}]


def test_release_leaves_nothing_that_is_off(tmp_path):
    subject, platform, bindings = memberships(tmp_path, [("h1", EASYTIER)])
    subject.probe()
    bindings.rows = []

    assert subject.release_hub("h1") == 0
    assert leaves(platform) == []


def test_a_shutdown_keeps_every_network_and_counts_them(tmp_path):
    subject, platform, _bindings = memberships(tmp_path, [("h1", EASYTIER)])
    joined(platform, "home")
    platform.answer("easytier-cli", "peer", stdout=easytier_peers())
    subject.probe()

    assert subject.release() == 1
    assert leaves(platform) == []


def test_no_secret_reaches_a_row(tmp_path):
    subject, _platform, _bindings = memberships(
        tmp_path, [("h1", EASYTIER), ("h2", NETBIRD), ("h3", CONSOLE)]
    )

    rows = json.dumps([subject.hub_row(hub) for hub in ("h1", "h2", "h3")])

    assert "s3cret" not in rows and KEY not in rows  # scan: allow
    assert "etk_token1" not in rows


@pytest.mark.parametrize(
    "state", ["off", "joining", "waiting", "on", "leaving", "failed"]
)
def test_every_state_word_is_in_the_table(state):
    assert state in OVERLAY_STATES
    assert len(OVERLAY_STATES) == 6


# --- the wish per hub, the pick and the failover ---


class RecordingDriver:
    """A provider's daemon that does as it is told and remembers what.

    Attributes:
        steps: ``(verb, provider)`` for every join and leave, in order,
            shared between the drivers of one test.
        is_on: Whether this provider's network is held.
        refusal: The code a join fails with, empty for none.
    """

    def __init__(self, provider, steps):
        self.provider = provider
        self.steps = steps
        self.is_on = False
        self.refusal = ""

    def status(self, material):
        return {
            "is_on": self.is_on,
            "is_waiting": False,
            "is_other_network": False,
            "address": "10.0.0.5" if self.is_on else "",
            "is_hub_seen": self.is_on,
        }

    def join(self, material, hostname):
        self.steps.append(("join", self.provider))
        if self.refusal:
            raise OverlayControlError(self.refusal)
        self.is_on = True

    def leave(self, material):
        self.steps.append(("leave", self.provider))
        self.is_on = False


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def wishful(rows, wishes, *, lost=None):
    """Memberships over recording drivers and a clock, every joined network told."""
    steps = []
    bindings = Bindings(rows)
    bindings.wishes = dict(wishes)
    bindings.lost = dict(lost or {})
    clock = Clock()
    joined_networks = []
    drivers = {
        "netbird": RecordingDriver("netbird", steps),
        "easytier": RecordingDriver("easytier", steps),
    }
    subject = OverlayMemberships(
        platform=None,
        bindings_of=bindings,
        hostname="box",
        log=discard,
        on_joined=joined_networks.append,
        start_thread=run_inline,
        drivers=drivers,
        clock=clock,
    )
    return subject, steps, bindings, clock, joined_networks, drivers


def test_a_wanted_hub_joins_the_first_of_its_two_networks():
    subject, steps, _bindings, _clock, joined_networks, _drivers = wishful(
        [("h1", [NETBIRD, EASYTIER])], {"h1": (True, "")}
    )

    subject.probe()
    subject.reconcile()

    assert steps == [("join", "netbird")]
    assert joined_networks == [NETBIRD]
    row = subject.hub_row("h1")
    assert (row["provider"], row["state"], row["is_wanted"]) == ("netbird", "on", True)
    assert row["networks"] == [
        {"provider": "netbird", "network": "nb.example"},
        {"provider": "easytier", "network": "home"},
    ]


def test_a_hub_whose_wish_is_off_joins_nothing():
    subject, steps, _bindings, _clock, _joined, _drivers = wishful(
        [("h1", [NETBIRD, EASYTIER])], {}
    )

    subject.probe()
    subject.reconcile()

    assert steps == []
    assert subject.hub_row("h1")["is_wanted"] is False


def test_a_channel_lost_for_the_failover_time_moves_to_the_next_network():
    subject, steps, bindings, clock, joined_networks, _drivers = wishful(
        [("h1", [NETBIRD, EASYTIER])], {"h1": (True, "")}
    )
    subject.reconcile()
    bindings.lost = {"h1": clock.now}

    clock.now += CLIENT_OVERLAY_FAILOVER_S - 1
    subject.reconcile()
    assert steps == [("join", "netbird")]
    assert subject.next_deadline() == 1

    clock.now += 1
    subject.reconcile()
    assert steps == [("join", "netbird"), ("leave", "netbird"), ("join", "easytier")]
    assert joined_networks == [NETBIRD, EASYTIER]
    assert subject.hub_row("h1")["provider"] == "easytier"

    clock.now += 1
    subject.reconcile()
    assert len(steps) == 3


def test_a_network_the_hub_stops_naming_is_left_for_its_new_first():
    subject, steps, bindings, _clock, _joined, _drivers = wishful(
        [("h1", [NETBIRD, EASYTIER])], {"h1": (True, "")}
    )
    subject.reconcile()

    bindings.rows = [("h1", [EASYTIER])]
    subject.reconcile()

    assert steps == [("join", "netbird"), ("leave", "netbird"), ("join", "easytier")]
    assert subject.hub_row("h1")["provider"] == "easytier"


def test_the_network_the_person_picked_is_joined_first():
    subject, steps, _bindings, _clock, _joined, _drivers = wishful(
        [("h1", [NETBIRD, EASYTIER])], {"h1": (True, "easytier")}
    )

    subject.reconcile()

    assert steps == [("join", "easytier")]


def test_a_hub_with_one_network_never_switches():
    subject, steps, bindings, clock, _joined, _drivers = wishful(
        [("h1", [NETBIRD])], {"h1": (True, "")}
    )
    subject.reconcile()
    bindings.lost = {"h1": clock.now}

    clock.now += 10 * CLIENT_OVERLAY_FAILOVER_S
    subject.reconcile()

    assert steps == [("join", "netbird")]
    assert subject.next_deadline() is None


def test_a_pick_while_on_leaves_the_current_network_and_joins_the_picked():
    subject, steps, _bindings, _clock, _joined, _drivers = wishful(
        [("h1", [NETBIRD, EASYTIER])], {"h1": (True, "")}
    )
    subject.reconcile()

    assert subject.pick("h1", "easytier") == {}

    assert steps == [("join", "netbird"), ("leave", "netbird"), ("join", "easytier")]
    assert subject.hub_row("h1")["provider"] == "easytier"


def test_a_pick_while_off_moves_the_row_and_joins_nothing():
    subject, steps, _bindings, _clock, _joined, _drivers = wishful(
        [("h1", [NETBIRD, EASYTIER])], {}
    )

    assert subject.pick("h1", "easytier") == {}
    assert subject.pick("h1", "zerotier")["code"] == "overlay_missing"

    assert steps == []
    assert subject.hub_row("h1")["provider"] == "easytier"


def test_a_join_that_failed_is_not_tried_again_by_itself():
    subject, steps, _bindings, _clock, _joined, drivers = wishful(
        [("h1", [NETBIRD, EASYTIER])], {"h1": (True, "")}
    )
    drivers["netbird"].refusal = "overlay_join_failed"

    subject.reconcile()
    subject.probe()
    subject.reconcile()

    assert steps == [("join", "netbird")]
    assert subject.hub_row("h1")["code"] == "overlay_join_failed"


def test_a_network_already_held_stays_current_after_a_restart():
    subject, steps, _bindings, _clock, _joined, drivers = wishful(
        [("h1", [NETBIRD, EASYTIER])], {"h1": (True, "")}
    )
    drivers["easytier"].is_on = True

    subject.probe()
    subject.reconcile()

    assert steps == []
    assert subject.hub_row("h1")["provider"] == "easytier"
