"""The engine's reports and the applier, with the engine replaced by canned
output and the disk by a temporary directory.

The engine prints sizes and percentages for a person to read, so the parsing
is what these pin, and one absence: ``node info`` prints the running
configuration with the network secret in it, and nothing read from it may
carry the secret. The applier renders the start arguments for the stored
mode, and a mode with nothing to run leaves no file behind.
"""

import json

import pytest

from neutrino_hub.modules.easytier import ops
from neutrino_hub.modules.easytier.config import EasyTierConfig
from neutrino_hub.modules.easytier.ops import EasyTierStatusReader
from tests.conftest import unlock_vault

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


def test_reading_the_peers_asks_only_for_the_peer_table(engine):
    EasyTierStatusReader().peers()

    assert [command[-1] for command in engine] == ["peer"]
    assert all(
        command[1:5] == ["-p", "127.0.0.1:15888", "-o", "json"] for command in engine
    )


NODE_INFO = {
    "peer_id": 4261311561,
    "ipv4_addr": "10.144.99.1/24",
    "proxy_cidrs": ["192.168.77.0/24"],
    "hostname": "neutrino",
    "config": (
        'hostname = "neutrino"\n[network_identity]\n'
        'network_name = "home"\nnetwork_secret = "the-secret"\n'  # scan: allow
    ),
    "version": "2.6.4-8428a89d",
}


def answering(monkeypatch, tmp_path, node, peer) -> None:
    """An engine whose two reads answer with what is given."""
    installed(monkeypatch, tmp_path)

    def fake_run(command, **kwargs):
        return FakeResult(json.dumps(node if command[-1] == "info" else peer))

    monkeypatch.setattr(ops, "run", fake_run)


def test_one_instance_is_read_with_its_network_address_and_routes(
    monkeypatch, tmp_path
):
    answering(monkeypatch, tmp_path, NODE_INFO, PEERS)

    [instance] = EasyTierStatusReader().instances()

    assert instance.network_name == "home"
    assert instance.address == "10.144.99.1/24"
    assert instance.hostname == "neutrino"
    assert instance.subnet_routes == ["192.168.77.0/24"]
    assert [peer.hostname for peer in instance.peers] == ["neutrino", "laptop", "phone"]
    assert instance.withheld == []


def test_the_network_secret_never_leaves_the_reader(monkeypatch, tmp_path):
    answering(monkeypatch, tmp_path, NODE_INFO, PEERS)

    instances = EasyTierStatusReader().instances()

    assert "the-secret" not in repr(instances)


def test_several_instances_are_read_apart_with_their_own_peers(monkeypatch, tmp_path):
    node = [
        {"instance_id": "a", "instance_name": "one", "result": NODE_INFO},
        {
            "instance_id": "b",
            "instance_name": "two",
            "result": {"ipv4_addr": "", "hostname": "", "config": ""},
        },
    ]
    peer = [
        {"instance_id": "a", "instance_name": "one", "result": PEERS[:2]},
        {"instance_id": "b", "instance_name": "two", "result": PEERS[:1]},
    ]
    answering(monkeypatch, tmp_path, node, peer)

    one, two = EasyTierStatusReader().instances()

    assert (one.instance_name, len(one.peers)) == ("one", 2)
    assert (two.instance_name, len(two.peers)) == ("two", 1)
    assert two.withheld == ["network_name", "address", "hostname"]
    assert len(EasyTierStatusReader().peers()) == 3


def test_an_engine_running_no_instance_reports_none(monkeypatch, tmp_path):
    installed(monkeypatch, tmp_path)
    monkeypatch.setattr(ops, "run", lambda command, **kwargs: FakeResult("", False))

    assert EasyTierStatusReader().instances() == []


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


# --- applying ---------------------------------------------------------------

CONSOLE = "tcp://et-web.console.easytier.net:22020/etk_example"  # scan: allow


@pytest.fixture
def applier_box(monkeypatch, tmp_path):
    """An open vault, an installed engine, and the generated files under tmp."""
    unlock_vault(monkeypatch, tmp_path)
    generated = tmp_path / "generated"
    core = tmp_path / "easytier-core"
    core.write_text("")
    commands: list = []
    monkeypatch.setattr(ops, "UTILS_GENERATED_DIR", generated)
    monkeypatch.setattr(ops, "EASYTIER_CORE_PATH", core)
    monkeypatch.setattr(ops, "is_dev_root_set", lambda: False)
    monkeypatch.setattr(ops, "refresh_unit", lambda: commands.append(["refresh"]))
    monkeypatch.setattr(
        ops, "run", lambda command, **kwargs: commands.append(list(command))
    )
    return generated, commands


def test_manual_mode_runs_the_engine_on_the_network_file(applier_box):
    generated, commands = applier_box
    config = EasyTierConfig(network_name="home")
    config.set_secret("a-network-secret")

    ops.EasyTierConfigApplier().apply(config, hostname="neutrino")

    network = generated / "easytier.toml"
    assert 'network_name = "home"' in network.read_text()
    assert (generated / "easytier.env").read_text() == (
        f"EASYTIER_ARGUMENTS=-c {network} --rpc-portal 127.0.0.1:15888\n"
    )
    assert oct(network.stat().st_mode & 0o777) == "0o600"
    assert commands == [
        ["refresh"],
        ["systemctl", "restart", "neutrino_hub_easytier.service"],
    ]


def test_console_mode_runs_the_engine_on_the_console_and_leaves_no_network_file(
    applier_box,
):
    generated, commands = applier_box
    generated.mkdir()
    (generated / "easytier.toml").write_text("stale")
    config = EasyTierConfig(mode="console", is_secure_mode=True)
    config.set_config_server(CONSOLE)

    ops.EasyTierConfigApplier().apply(config, hostname="neutrino")

    arguments = generated / "easytier.env"
    assert arguments.read_text() == (
        f"EASYTIER_ARGUMENTS=--config-server {CONSOLE} --secure-mode=true "
        "--rpc-portal 127.0.0.1:15888\n"
    )
    assert oct(arguments.stat().st_mode & 0o777) == "0o600"
    assert not (generated / "easytier.toml").exists()
    assert commands[-1] == ["systemctl", "restart", "neutrino_hub_easytier.service"]


def test_a_mode_with_nothing_to_run_stops_the_engine_and_leaves_no_file(
    applier_box,
):
    generated, commands = applier_box
    generated.mkdir()
    (generated / "easytier.env").write_text("stale")
    (generated / "easytier.toml").write_text("stale")

    ops.EasyTierConfigApplier().apply(
        EasyTierConfig(mode="console"), hostname="neutrino"
    )

    assert list(generated.iterdir()) == []
    assert commands == [["systemctl", "stop", "neutrino_hub_easytier.service"]]
