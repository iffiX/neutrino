"""The peer table, with the engine replaced by canned output.

The engine prints sizes and percentages for a person to read, so the parsing
is what these pin — and one absence: the engine's other read, ``node``, prints
the running configuration with the network secret in it, and nothing here may
ever ask for it.
"""

import json

import pytest

from neutrino_hub.modules.easytier import ops
from neutrino_hub.modules.easytier.ops import EasyTierStatusReader

PEERS = [
    {
        "hostname": "neutrino",
        "cost": "Local",
        "id": "3447457942",
        "version": "2.6.4-8428a89d",
    },
    {
        "hostname": "laptop",
        "ipv4": "10.0.0.4",
        "cost": "p2p",
        "lat_ms": "19.85",
        "loss_rate": "0.0%",
        "rx_bytes": "917 B",
        "tx_bytes": "1.20 MiB",
        "tunnel_proto": "tcp",
        "nat_type": "PortRestricted",
        "version": "2.6.4-8428a89d",
    },
    {
        "hostname": "phone",
        "ipv4": "10.0.0.9",
        "cost": "relay(2)",
        "lat_ms": "132.5",
        "loss_rate": "1.5%",
        "rx_bytes": "3 KB",
        "tx_bytes": "",
        "tunnel_proto": "udp",
    },
]


class FakeResult:
    def __init__(self, stdout, is_success=True):
        self.stdout = stdout
        self.is_success = is_success


def installed(monkeypatch, tmp_path) -> None:
    """Put an engine on the box, as far as the reader can tell."""
    cli = tmp_path / "easytier-cli"
    cli.write_text("")
    monkeypatch.setattr(ops, "EASYTIER_CLI_PATH", cli)


@pytest.fixture
def engine(monkeypatch, tmp_path):
    """A running engine that answers with the table above."""
    asked: list = []

    def fake_run(command, **kwargs):
        asked.append(command)
        return FakeResult(json.dumps(PEERS))

    monkeypatch.setattr(ops, "run", fake_run)
    installed(monkeypatch, tmp_path)
    return asked


def test_the_peers_are_read_and_this_box_comes_first(engine):
    peers = EasyTierStatusReader().peers()

    assert [peer.hostname for peer in peers] == ["neutrino", "laptop", "phone"]
    assert peers[0].link == "local"


def test_a_direct_tunnel_and_a_relayed_one_are_told_apart(engine):
    peers = {peer.hostname: peer for peer in EasyTierStatusReader().peers()}

    assert peers["laptop"].link == "direct"
    assert peers["laptop"].protocol == "tcp"
    assert peers["phone"].link == "relayed"


def test_what_the_engine_printed_for_a_person_comes_back_as_numbers(engine):
    peers = {peer.hostname: peer for peer in EasyTierStatusReader().peers()}

    assert peers["laptop"].latency_ms == 19.85
    assert peers["laptop"].loss_ratio == 0.0
    assert peers["laptop"].rx_bytes == 917
    assert peers["laptop"].tx_bytes == int(1.20 * 1024**2)
    assert peers["phone"].loss_ratio == 0.015
    assert peers["phone"].rx_bytes == 3000
    assert peers["phone"].tx_bytes is None


def test_the_secret_bearing_read_is_never_asked_for(engine):
    EasyTierStatusReader().peers()

    for command in engine:
        assert "node" not in command, "`node` prints the network secret"
        assert command[-1] == "peer"


def test_an_engine_that_is_not_running_has_no_peers(monkeypatch, tmp_path):
    installed(monkeypatch, tmp_path)
    monkeypatch.setattr(ops, "run", lambda command, **kwargs: FakeResult("", False))

    assert EasyTierStatusReader().peers() == []


def test_an_engine_that_is_not_installed_is_not_asked(monkeypatch, tmp_path):
    monkeypatch.setattr(ops, "EASYTIER_CLI_PATH", tmp_path / "absent")

    def refuse(command, **kwargs):
        raise AssertionError("the engine was asked anyway")

    monkeypatch.setattr(ops, "run", refuse)

    assert EasyTierStatusReader().peers() == []


def test_output_that_is_not_a_table_reads_as_no_peers(monkeypatch, tmp_path):
    installed(monkeypatch, tmp_path)
    monkeypatch.setattr(ops, "run", lambda command, **kwargs: FakeResult("not json"))

    assert EasyTierStatusReader().peers() == []
