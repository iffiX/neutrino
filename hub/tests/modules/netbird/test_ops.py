"""The daemon's status, reshaped, with netbird replaced by canned output."""

import json

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


def test_join_goes_down_first_so_reenrollment_works(monkeypatch):
    commands = []
    monkeypatch.setattr(ops, "run", lambda cmd, **k: commands.append(cmd))

    ops.NetbirdEnroller().join(setup_key="KEY-1")
    ops.NetbirdEnroller().join(
        setup_key="KEY-2", management_url="https://mgmt.example.com"
    )

    assert commands[0] == [NETBIRD, "down"]
    assert commands[1] == [NETBIRD, "up", "--setup-key", "KEY-1"]
    assert commands[3][-2:] == ["--management-url", "https://mgmt.example.com"]


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
    gate, ran = gate_over(monkeypatch, tmp_path, stored={"BlockInbound": False})

    assert gate.converge(is_blocked=False) == ""
    assert ran == []


def test_closing_takes_the_session_down_first_and_states_the_value(
    monkeypatch, tmp_path
):
    """`netbird up` answers "already connected" and changes nothing while the
    client is up, and the flag left off keeps whatever was stored."""
    gate, ran = gate_over(monkeypatch, tmp_path, stored={"BlockInbound": False})

    note = gate.converge(is_blocked=True)

    assert ran == [
        [NETBIRD, "down"],
        [NETBIRD, "up", "--block-inbound=true"],
    ]
    assert note == "overlay closed"


def test_opening_states_the_value_too_because_the_flag_is_sticky(monkeypatch, tmp_path):
    """Running `netbird up` with no flag leaves a blocked client blocked."""
    gate, ran = gate_over(monkeypatch, tmp_path, stored={"BlockInbound": True})

    note = gate.converge(is_blocked=False)

    assert ran[-1] == [NETBIRD, "up", "--block-inbound=false"]
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
