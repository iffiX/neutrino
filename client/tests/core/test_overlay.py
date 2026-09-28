"""This machine's membership of each hub's virtual network.

The CLIs run on a scripted platform. Pinned here: NetBird's join carries
the setup key, the management URL and ``--disable-dns``, and refuses without
running while the daemon is on another network; two hubs on one management
URL read one membership; EasyTier's join hands the root step a secret file
that is gone afterwards, and its status asks the one portal by the
network's name; a leave on release happens only when no other hub names the
network; a lane that works answers busy; a step's failure stays until the
network is on; every state word is in the table.
"""

import json
import os
import subprocess

import pytest

from neutrino_client.constants import CLIENT_EASYTIER_RPC_PORTAL
from neutrino_client.core.overlay import (
    OVERLAY_STATES,
    OverlayMemberships,
    netbird_management_key,
    overlay_key,
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
    "network_name": "home",
    "network_secret": "s3cret",  # scan: allow
    "peer": "tcp://203.0.113.7:11010",
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
        joins: The keyword arguments of every EasyTier join.
        secrets: What the secret file held at each join, and its mode.
    """

    def __init__(self, tmp_path):
        self._config_dir = str(tmp_path / "config")
        self.runs = []
        self.answers = {}
        self.joins = []
        self.leaves = []
        self.secrets = []
        self.join_error = None
        self.resumes = 0

    def config_dir(self) -> str:
        return self._config_dir

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

    def easytier_join(self, **kwargs):
        path = kwargs["secret_path"]
        with open(path) as stream:
            self.secrets.append((stream.read(), os.stat(path).st_mode & 0o777))
        self.joins.append(dict(kwargs))
        if self.join_error is not None:
            raise self.join_error

    def easytier_leave(self, **kwargs):
        self.leaves.append(dict(kwargs))

    def easytier_resume(self):
        self.resumes += 1


def run_inline(target) -> None:
    target()


class Bindings:
    """What the resident would hand the memberships: hub id and object."""

    def __init__(self, rows):
        self.rows = list(rows)

    def __call__(self):
        return list(self.rows)


def memberships(tmp_path, rows, start_thread=run_inline):
    platform = ScriptedPlatform(tmp_path)
    bindings = Bindings(rows)
    subject = OverlayMemberships(
        platform=platform,
        bindings_of=bindings,
        hostname="Alice's box",
        log=discard,
        start_thread=start_thread,
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


def test_an_easytier_join_hands_a_0600_secret_file_that_is_gone_afterwards(tmp_path):
    subject, platform, _bindings = memberships(tmp_path, [("h1", EASYTIER)])

    assert subject.join("h1") == {}

    (join,) = platform.joins
    assert join["network_name"] == "home"
    assert join["peer"] == "tcp://203.0.113.7:11010"
    assert join["hostname"] == "Alice-s-box"
    assert platform.secrets == [("s3cret", 0o600)]  # scan: allow
    assert not os.path.exists(join["secret_path"])


def test_the_easytier_status_asks_the_one_portal_by_network_name(tmp_path):
    subject, platform, _bindings = memberships(tmp_path, [("h1", EASYTIER)])
    platform.answer("easytier-cli", "peer", stdout=easytier_peers())

    subject.probe()

    assert platform.runs == [
        (
            "easytier-cli",
            ["-p", CLIENT_EASYTIER_RPC_PORTAL, "-n", "home", "-o", "json", "peer"],
        )
    ]
    row = subject.hub_row("h1")
    assert (row["state"], row["address"], row["is_hub_seen"]) == (
        "on",
        "10.144.144.5",
        True,
    )


def test_an_instance_the_daemon_does_not_run_is_off(tmp_path):
    subject, platform, _bindings = memberships(tmp_path, [("h1", EASYTIER)])
    platform.answer(
        "easytier-cli",
        "peer",
        stderr="Error: Rust error: No instance matches the selector",
    )

    subject.probe()

    assert subject.hub_row("h1")["state"] == "off"


def test_a_portal_nobody_listens_on_is_off(tmp_path):
    subject, platform, _bindings = memberships(tmp_path, [("h1", EASYTIER)])
    platform.answer(
        "easytier-cli", "peer", returncode=1, stderr="failed to connect to server"
    )

    subject.probe()

    assert subject.hub_row("h1")["state"] == "off"


def test_a_step_failure_stays_until_the_network_is_on(tmp_path):
    subject, platform, _bindings = memberships(tmp_path, [("h1", EASYTIER)])
    platform.join_error = OverlayControlError("overlay_not_authorized")

    subject.join("h1")
    subject.probe()
    assert subject.hub_row("h1")["code"] == "overlay_not_authorized"

    platform.answer("easytier-cli", "peer", stdout=easytier_peers())
    subject.probe()
    assert subject.hub_row("h1")["state"] == "on"
    assert subject.hub_row("h1")["code"] == ""


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


def test_release_leaves_only_a_network_no_other_hub_names(tmp_path):
    subject, platform, bindings = memberships(
        tmp_path, [("h1", EASYTIER), ("h2", EASYTIER)]
    )
    platform.answer("easytier-cli", "peer", stdout=easytier_peers())
    subject.probe()

    bindings.rows = [("h2", EASYTIER)]
    assert subject.release_hub("h1") == 0
    assert platform.leaves == []

    bindings.rows = []
    assert subject.release_hub("h2") == 1
    assert platform.leaves == [{"network_name": "home"}]


def test_release_leaves_nothing_that_is_off(tmp_path):
    subject, platform, bindings = memberships(tmp_path, [("h1", EASYTIER)])
    subject.probe()
    bindings.rows = []

    assert subject.release_hub("h1") == 0
    assert platform.leaves == []


def test_a_shutdown_keeps_every_network_and_counts_them(tmp_path):
    subject, platform, _bindings = memberships(tmp_path, [("h1", EASYTIER)])
    platform.answer("easytier-cli", "peer", stdout=easytier_peers())
    subject.probe()

    assert subject.release() == 1
    assert platform.leaves == []


def test_the_poll_asks_easytier_to_resume_only_where_it_has_a_network(tmp_path):
    subject, platform, bindings = memberships(tmp_path, [("h1", NETBIRD)])
    subject.refresh_bindings()
    subject._resume()
    assert platform.resumes == 0

    bindings.rows = [("h1", EASYTIER)]
    subject.refresh_bindings()
    subject._resume()
    assert platform.resumes == 1


def test_no_secret_reaches_a_row(tmp_path):
    subject, _platform, _bindings = memberships(
        tmp_path, [("h1", EASYTIER), ("h2", NETBIRD)]
    )

    rows = json.dumps([subject.hub_row("h1"), subject.hub_row("h2")])

    assert "s3cret" not in rows and KEY not in rows  # scan: allow


@pytest.mark.parametrize("state", ["off", "joining", "on", "leaving", "failed"])
def test_every_state_word_is_in_the_table(state):
    assert state in OVERLAY_STATES
    assert len(OVERLAY_STATES) == 5
