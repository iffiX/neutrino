"""The daemon's status, reshaped, with netbird replaced by canned output."""

import json
import subprocess

import pytest

from neutrino_hub.modules.netbird import ops
from neutrino_hub.modules.netbird.constants import NETBIRD_BINARY_PATH
from neutrino_hub.modules.netbird.ops import NetbirdStatusReader

# The client the package carries, which is the only netbird this box drives.
NETBIRD = str(NETBIRD_BINARY_PATH)


class FakeResult:
    def __init__(self, stdout, is_success=True):
        self.stdout = stdout
        self.is_success = is_success


NEEDS_LOGIN = {
    "peers": {"total": 0, "connected": 0, "details": None},
    "daemonVersion": "0.77.1",
    "daemonStatus": "NeedsLogin",
    "management": {"url": "https://api.netbird.io:443", "connected": False},
    "netbirdIp": "",
    "fqdn": "",
}

CONNECTED = {
    "peers": {
        "total": 2,
        "connected": 1,
        "details": [
            {
                "fqdn": "laptop.netbird.cloud",
                "netbirdIp": "100.92.0.2",
                "status": "Connected",
                "connectionType": "P2P",
                "latency": 42_000_000,
            },
            {
                "fqdn": "phone.netbird.cloud",
                "netbirdIp": "100.92.0.3",
                "status": "Disconnected",
                "connectionType": "",
                "latency": 0,
            },
        ],
    },
    "daemonVersion": "0.77.1",
    "daemonStatus": "Connected",
    "management": {"url": "https://api.netbird.io:443", "connected": True},
    "netbirdIp": "100.92.0.1/16",
    "fqdn": "neutrino.netbird.cloud",
}


def survey_with(monkeypatch, payload):
    monkeypatch.setattr(ops, "run", lambda *a, **k: FakeResult(json.dumps(payload)))
    return NetbirdStatusReader().survey()


def test_needs_login_reads_as_not_enrolled(monkeypatch):
    state = survey_with(monkeypatch, NEEDS_LOGIN)

    assert state.is_installed is True
    assert state.is_enrolled is False
    assert state.is_management_connected is False


def test_a_connected_daemon_reports_identity_and_peers(monkeypatch):
    state = survey_with(monkeypatch, CONNECTED)

    assert state.is_enrolled is True
    assert state.netbird_ip == "100.92.0.1/16"
    assert state.fqdn == "neutrino.netbird.cloud"
    assert [peer.fqdn for peer in state.peers] == [
        "laptop.netbird.cloud",
        "phone.netbird.cloud",
    ]
    laptop = state.peers[0]
    assert laptop.is_connected is True
    assert laptop.connection_type == "P2P"
    # Nanoseconds from the daemon, milliseconds for a person.
    assert laptop.latency_ms == 42


def test_a_missing_daemon_reads_as_not_installed(monkeypatch):
    monkeypatch.setattr(ops, "run", lambda *a, **k: FakeResult("", False))

    assert NetbirdStatusReader().survey().is_installed is False


def enroller_over(monkeypatch, tmp_path, status, refusals=()):
    """The enroller over a daemon, its profile under tmp_path; returns the
    commands run. ``status`` is one payload, or a list answered in order
    with the last repeating. Each entry of ``refusals`` makes one ``up``
    raise, in order."""
    commands = []
    refusing = list(refusals)
    statuses = list(status) if isinstance(status, list) else [status]
    (tmp_path / "active_profile.json").write_text('{"name": "default"}')
    (tmp_path / "default.json").write_text("{}")
    monkeypatch.setattr(
        ops, "NETBIRD_ACTIVE_PROFILE_PATH", tmp_path / "active_profile.json"
    )
    monkeypatch.setattr(ops, "NETBIRD_STATE_DIR", tmp_path)

    def run(cmd, **keywords):
        commands.append(cmd)
        if cmd[1:2] == ["status"]:
            answered = statuses.pop(0) if len(statuses) > 1 else statuses[0]
            return FakeResult(json.dumps(answered))
        if cmd[1:2] == ["up"] and refusing:
            raise refusing.pop(0)
        return FakeResult("")

    monkeypatch.setattr(ops, "run", run)
    return commands


def driven(commands):
    """The commands that drive the daemon, the status reads left out."""
    return [cmd for cmd in commands if cmd[1:2] != ["status"]]


RESET = [
    [NETBIRD, "deregister"],
    ["systemctl", "restart", "neutrino_hub_netbird.service"],
]


def test_a_connected_peer_joins_again_as_itself(monkeypatch, tmp_path):
    """A peer the plane still takes keeps its identity, and with it the
    routes the console holds for it."""
    commands = enroller_over(monkeypatch, tmp_path, CONNECTED)

    ops.NetbirdEnroller().join(setup_key="KEY-1")
    ops.NetbirdEnroller().join(
        setup_key="KEY-2", management_url="https://mgmt.example.com"
    )

    assert driven(commands)[0] == [NETBIRD, "down"]
    assert driven(commands)[1] == [
        NETBIRD,
        "up",
        "--setup-key",
        "KEY-1",
        "--disable-dns",
    ]
    assert driven(commands)[3][-2:] == ["--management-url", "https://mgmt.example.com"]
    assert [NETBIRD, "deregister"] not in driven(commands)
    assert (tmp_path / "default.json").exists()


@pytest.mark.parametrize("word", ["NeedsLogin", "LoginFailed", "SessionExpired"])
def test_a_profile_without_a_login_is_reset_before_the_key_is_used(
    monkeypatch, tmp_path, word
):
    """The daemon registers a new peer only from a fresh profile: a login
    the plane refuses, or an SSO session that ran out, would make every
    setup key fail with the old identity's refusal. The plane is asked to
    drop the peer, the profile goes from disk either way, and the restarted
    daemon writes a new one."""
    commands = enroller_over(
        monkeypatch, tmp_path, dict(NEEDS_LOGIN, daemonStatus=word)
    )

    ops.NetbirdEnroller().join(setup_key="KEY-1")

    assert driven(commands) == [
        [NETBIRD, "down"],
        *RESET,
        [NETBIRD, "up", "--setup-key", "KEY-1", "--disable-dns"],
    ]
    assert not (tmp_path / "default.json").exists()
    assert not (tmp_path / "active_profile.json").exists()


def test_an_idle_identity_the_plane_refuses_is_reset_and_the_key_used_again(
    monkeypatch, tmp_path
):
    """A survey cannot tell an idle identity's standing; the refusal can."""
    refused = subprocess.CalledProcessError(
        1, [NETBIRD, "up"], stderr="PermissionDenied"
    )
    commands = enroller_over(
        monkeypatch,
        tmp_path,
        [dict(NEEDS_LOGIN, daemonStatus="Idle"), NEEDS_LOGIN],
        refusals=[refused],
    )

    ops.NetbirdEnroller().join(setup_key="KEY-1")

    assert driven(commands) == [
        [NETBIRD, "down"],
        [NETBIRD, "up", "--setup-key", "KEY-1", "--disable-dns"],
        *RESET,
        [NETBIRD, "up", "--setup-key", "KEY-1", "--disable-dns"],
    ]


def test_a_key_the_plane_refuses_twice_is_refused_to_the_caller(monkeypatch, tmp_path):
    refused = subprocess.CalledProcessError(1, [NETBIRD, "up"], stderr="bad key")
    commands = enroller_over(
        monkeypatch, tmp_path, NEEDS_LOGIN, refusals=[refused, refused]
    )

    with pytest.raises(subprocess.CalledProcessError):
        ops.NetbirdEnroller().join(setup_key="KEY-1")

    assert (
        driven(commands).count([NETBIRD, "up", "--setup-key", "KEY-1", "--disable-dns"])
        == 1
    )


@pytest.mark.parametrize("word", ["LoginFailed", "SessionExpired"])
def test_a_refused_or_expired_login_reads_as_not_enrolled(monkeypatch, word):
    state = survey_with(monkeypatch, dict(NEEDS_LOGIN, daemonStatus=word))

    assert state.is_enrolled is False


# --- The inbound gate -------------------------------------------------------
#
# Measured on a running 0.77.1 client, because none of it is guessable: the
# daemon re-inserts an accept for its interface into whatever input chain it
# finds within seconds of a reload, `netbird up` does nothing while the client
# is connected, and the flag is sticky rather than defaulting to off.


def gate_over(monkeypatch, tmp_path, *, stored, status=None):
    """A gate reading a state directory of this test's own making."""
    (tmp_path / "active_profile.json").write_text(json.dumps({"name": "default"}))
    if stored is not None:
        (tmp_path / "default.json").write_text(json.dumps(stored))
    monkeypatch.setattr(ops, "NETBIRD_STATE_DIR", tmp_path)
    monkeypatch.setattr(
        ops, "NETBIRD_ACTIVE_PROFILE_PATH", tmp_path / "active_profile.json"
    )
    monkeypatch.setattr(ops, "NETBIRD_LEGACY_CONFIG_PATH", tmp_path / "nothing.json")
    ran = []
    monkeypatch.setattr(
        ops, "run", lambda command, **kwargs: ran.append(command) or FakeResult("")
    )
    monkeypatch.setattr(
        NetbirdStatusReader,
        "survey",
        lambda self: status or ops.NetbirdState(is_installed=True, is_enrolled=True),
    )
    return ops.NetbirdInboundGate(), ran


def test_the_gate_reads_what_the_daemon_was_last_told(monkeypatch, tmp_path):
    gate, _ = gate_over(monkeypatch, tmp_path, stored={"BlockInbound": True})

    assert gate.state() is True


def test_a_machine_that_never_enrolled_says_nothing_either_way(monkeypatch, tmp_path):
    gate, _ = gate_over(monkeypatch, tmp_path, stored=None)

    assert gate.state() is None


def test_a_state_that_already_agrees_costs_no_reconnection(monkeypatch, tmp_path):
    """A network apply runs on every interface save. Setting this each time
    would drop the overlay every time."""
    gate, ran = gate_over(
        monkeypatch, tmp_path, stored={"BlockInbound": False, "DisableDNS": True}
    )

    assert gate.converge(is_blocked=False) == ""
    assert ran == []


def test_a_daemon_still_managing_dns_is_told_to_stop(monkeypatch, tmp_path):
    """The box resolves at its own dnsmasq, whatever the served network's
    address becomes; a daemon holding the resolver reads its upstream once."""
    gate, ran = gate_over(
        monkeypatch, tmp_path, stored={"BlockInbound": False, "DisableDNS": False}
    )

    note = gate.converge(is_blocked=False)

    assert ran == [
        [NETBIRD, "down"],
        [NETBIRD, "up", "--block-inbound=false", "--disable-dns"],
    ]
    assert note == "overlay DNS management turned off"


def test_closing_takes_the_session_down_first_and_states_the_value(
    monkeypatch, tmp_path
):
    """`netbird up` answers "already connected" and changes nothing while the
    client is up, and the flag left off keeps whatever was stored."""
    gate, ran = gate_over(monkeypatch, tmp_path, stored={"BlockInbound": False})

    note = gate.converge(is_blocked=True)

    assert ran == [
        [NETBIRD, "down"],
        [NETBIRD, "up", "--block-inbound=true", "--disable-dns"],
    ]
    assert note == "overlay closed"


def test_opening_states_the_value_too_because_the_flag_is_sticky(monkeypatch, tmp_path):
    """Running `netbird up` with no flag leaves a blocked client blocked."""
    gate, ran = gate_over(monkeypatch, tmp_path, stored={"BlockInbound": True})

    note = gate.converge(is_blocked=False)

    assert ran[-1] == [NETBIRD, "up", "--block-inbound=false", "--disable-dns"]
    assert note == "overlay opened"


def test_a_box_without_netbird_is_left_alone(monkeypatch, tmp_path):
    gate, ran = gate_over(
        monkeypatch,
        tmp_path,
        stored={"BlockInbound": False},
        status=ops.NetbirdState(is_installed=False),
    )

    assert gate.converge(is_blocked=True) == ""
    assert ran == []


def test_a_box_that_has_not_joined_a_network_is_left_alone(monkeypatch, tmp_path):
    """`netbird up` on an unenrolled machine is a login it cannot finish."""
    gate, ran = gate_over(
        monkeypatch,
        tmp_path,
        stored=None,
        status=ops.NetbirdState(is_installed=True, is_enrolled=False),
    )

    assert gate.converge(is_blocked=True) == ""
    assert ran == []
