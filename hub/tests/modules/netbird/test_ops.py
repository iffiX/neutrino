"""The daemon's status, reshaped, with netbird replaced by canned output."""

import json

from neutrino_hub.modules.netbird import ops
from neutrino_hub.modules.netbird.ops import NetbirdStatusReader


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

    assert commands[0] == ["netbird", "down"]
    assert commands[1] == ["netbird", "up", "--setup-key", "KEY-1"]
    assert commands[3][-2:] == ["--management-url", "https://mgmt.example.com"]
