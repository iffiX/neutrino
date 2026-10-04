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
from neutrino_hub.utils.json_file import write_config
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


# What `easytier-cli -o json -v peer` prints on 2.6.4, cut to the fields the
# reader takes: one peer this box dialled by name, one that dialled in.
VERBOSE_PEERS = [
    {
        "route": {"peer_id": 903187897, "hostname": "laptop", "cost": 1},
        "peer": {
            "peer_id": 903187897,
            "conns": [
                {
                    "conn_id": "50db2c50-92a2-42f0-9435-c9e697a89e36",
                    "my_peer_id": 804466385,
                    "peer_id": 903187897,
                    "features": [],
                    "tunnel": {
                        "tunnel_type": "tcp",
                        "local_addr": {"url": "tcp://192.168.1.20:42407"},
                        "remote_addr": {"url": "tcp://public.easytier.top:11010"},
                        "resolved_remote_addr": {"url": "tcp://192.0.2.61:11010"},
                    },
                    "stats": {"rx_bytes": 1301, "tx_bytes": 1466, "latency_us": 87},
                    "loss_rate": 0.0,
                    "is_client": True,
                    "network_name": "home",
                    "is_closed": False,
                }
            ],
        },
    },
    {
        "route": {"peer_id": 1176, "hostname": "phone", "cost": 2},
        "peer": {
            "peer_id": 1176,
            "conns": [
                {
                    "tunnel": {
                        "tunnel_type": "udp",
                        "local_addr": {"url": "udp://0.0.0.0:11010"},
                        "remote_addr": {"url": "udp://198.51.100.40:40112"},
                    },
                    "is_client": False,
                }
            ],
        },
    },
]
# What `easytier-cli -o json connector` prints for a peer the console handed
# down and one this box was configured with.
CONNECTORS = [
    {
        "url": {
            "url": "https://api.console.easytier.net/api/v1/network/peer-resolve/ab12"
        },
        "status": 0,
    },
    {"url": {"url": "tcp://public.easytier.top:11010"}, "status": 0},
]


def test_where_the_engine_reaches_its_peers_is_read(monkeypatch, tmp_path):
    installed(monkeypatch, tmp_path)
    asked = []

    def fake_run(command, **kwargs):
        asked.append(command[5:])
        if command[-1] == "connector":
            return FakeResult(json.dumps(CONNECTORS))
        return FakeResult(json.dumps(VERBOSE_PEERS))

    monkeypatch.setattr(ops, "run", fake_run)

    assert EasyTierStatusReader().endpoints() == [
        "tcp://public.easytier.top:11010",
        "tcp://192.0.2.61:11010",
        "udp://198.51.100.40:40112",
        "https://api.console.easytier.net/api/v1/network/peer-resolve/ab12",
    ]
    assert asked == [["-v", "peer"], ["connector"]]


def test_an_engine_not_running_reaches_no_peer(monkeypatch, tmp_path):
    installed(monkeypatch, tmp_path)
    monkeypatch.setattr(ops, "run", lambda command, **kwargs: FakeResult("", False))

    assert EasyTierStatusReader().endpoints() == []


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


# --- the console network's interface ----------------------------------------


def test_one_address_finds_the_one_interface_holding_it():
    held = {"enp1s0": "192.168.1.5/24", "tun0": "10.144.0.2/16"}

    assert ops.devices_holding(held, ["10.144.0.2/16"]) == ["tun0"]


def test_several_addresses_find_every_interface_holding_one():
    held = {
        "enp1s0": "192.168.1.5/24",
        "tun1": "10.145.0.7/16",
        "tun0": "10.144.0.2/16",
    }

    assert ops.devices_holding(held, ["10.144.0.2/16", "10.145.0.7"]) == [
        "tun0",
        "tun1",
    ]


def test_an_address_nobody_holds_finds_nothing():
    held = {"enp1s0": "192.168.1.5/24", "easytier": "10.0.0.9/24"}

    assert ops.devices_holding(held, ["10.144.0.2/16"]) == []
    assert ops.devices_holding(held, []) == []


def test_the_engine_reports_this_box_address_on_each_network(monkeypatch, tmp_path):
    node = [
        {"instance_id": "a", "instance_name": "one", "result": NODE_INFO},
        {"instance_id": "b", "instance_name": "two", "result": {"ipv4_addr": ""}},
    ]
    answering(monkeypatch, tmp_path, node, [])

    assert EasyTierStatusReader().addresses() == ["10.144.99.1/24"]


def test_the_console_interface_is_the_one_holding_the_reported_address(
    monkeypatch, tmp_path
):
    answering(monkeypatch, tmp_path, NODE_INFO, PEERS)
    monkeypatch.setattr(
        ops,
        "device_addresses",
        lambda: {"enp1s0": "192.168.1.5/24", "tun0": "10.144.99.1/24"},
    )

    assert ops.console_device_names() == ["tun0"]


def test_an_engine_with_no_network_names_no_interface(monkeypatch, tmp_path):
    installed(monkeypatch, tmp_path)
    monkeypatch.setattr(ops, "run", lambda command, **kwargs: FakeResult("", False))

    def refuse():
        raise AssertionError("the interfaces were read anyway")

    monkeypatch.setattr(ops, "device_addresses", refuse)

    assert ops.console_device_names() == []


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
    monkeypatch.setattr(ops, "SYSTEM_SYSTEMD_DIR", tmp_path / "systemd")
    monkeypatch.setattr(ops, "EASYTIER_CORE_PATH", core)
    monkeypatch.setattr(ops, "is_dev_root_set", lambda: False)
    monkeypatch.setattr(ops, "refresh_unit", lambda: commands.append(["refresh"]))
    monkeypatch.setattr(
        ops, "run", lambda command, **kwargs: commands.append(list(command))
    )
    return generated, commands, core, tmp_path / "systemd"


def dropin_of(systemd):
    return systemd / "neutrino_hub_easytier.service.d" / "arguments.conf"


def test_manual_mode_runs_the_engine_on_the_network_file(applier_box):
    generated, commands, core, systemd = applier_box
    config = EasyTierConfig(network_name="home")
    config.set_secret("a-network-secret")

    ops.EasyTierConfigApplier().apply(config, hostname="neutrino")

    network = generated / "easytier.toml"
    assert 'network_name = "home"' in network.read_text()
    assert dropin_of(systemd).read_text() == (
        "[Service]\nExecStart=\n"
        f'ExecStart="{core}" "-c" "{network}" "--rpc-portal" "127.0.0.1:15888"\n'
    )
    assert oct(network.stat().st_mode & 0o777) == "0o600"
    assert commands == [
        ["refresh"],
        ["systemctl", "daemon-reload"],
        ["systemctl", "restart", "neutrino_hub_easytier.service"],
    ]


def test_console_mode_runs_the_engine_on_the_console_and_leaves_no_network_file(
    applier_box,
):
    generated, commands, core, systemd = applier_box
    generated.mkdir()
    (generated / "easytier.toml").write_text("stale")
    (generated / "easytier.env").write_text("stale")
    config = EasyTierConfig(mode="console", is_secure_mode=True)
    config.set_config_server(CONSOLE)

    ops.EasyTierConfigApplier().apply(config, hostname="neutrino")

    dropin = dropin_of(systemd)
    assert dropin.read_text().splitlines()[-1] == (
        f'ExecStart="{core}" "--config-server" "{CONSOLE}" "--secure-mode=true" '
        '"--rpc-portal" "127.0.0.1:15888"'
    )
    assert oct(dropin.stat().st_mode & 0o777) == "0o644"
    assert list(generated.iterdir()) == []
    assert commands[-2:] == [
        ["systemctl", "daemon-reload"],
        ["systemctl", "restart", "neutrino_hub_easytier.service"],
    ]


def test_a_mode_with_nothing_to_run_stops_the_engine_and_leaves_no_file(
    applier_box,
):
    generated, commands, _, systemd = applier_box
    generated.mkdir()
    (generated / "easytier.env").write_text("stale")
    (generated / "easytier.toml").write_text("stale")
    dropin_of(systemd).parent.mkdir(parents=True)
    dropin_of(systemd).write_text("stale")

    ops.EasyTierConfigApplier().apply(
        EasyTierConfig(mode="console"), hostname="neutrino"
    )

    assert list(generated.iterdir()) == []
    assert not dropin_of(systemd).exists()
    assert commands == [
        ["systemctl", "daemon-reload"],
        ["systemctl", "stop", "neutrino_hub_easytier.service"],
    ]


def test_apply_stored_runs_the_engine_on_the_file_as_it_stands(
    applier_box, monkeypatch, tmp_path
):
    """The engine ends on what config/ holds when the apply runs, whatever a
    request read before another one wrote."""
    _, commands, _, _ = applier_box
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", config_dir)
    stored = EasyTierConfig(mode="console")
    stored.set_config_server(CONSOLE)
    write_config(ops.EASYTIER_CONFIG_NAME, stored.to_dict())

    ops.apply_stored(hostname="neutrino")

    assert commands[-1] == ["systemctl", "restart", "neutrino_hub_easytier.service"]


# --- the start line outside Linux --------------------------------------------


@pytest.fixture
def supervised_box(elsewhere, applier_box, monkeypatch, tmp_path, fake_controller):
    """The applier box on macOS or Windows: the controller holds the start line."""
    generated, commands, core, systemd = applier_box
    monkeypatch.setattr(ops, "SYSTEM_SERVICES_STATE_PATH", tmp_path / "services.json")
    monkeypatch.setattr(ops, "EASYTIER_HUB_HOME_DIR", tmp_path / "easytier")
    return generated, commands, core, systemd, fake_controller


def test_elsewhere_the_start_line_goes_to_the_controller(supervised_box):
    generated, commands, core, systemd, controller = supervised_box
    config = EasyTierConfig(network_name="home")
    config.set_secret("a-network-secret")

    ops.EasyTierConfigApplier().apply(config, hostname="neutrino")

    network = generated / "easytier.toml"
    assert controller.verbs() == [
        (
            "set_start_line",
            "easytier",
            [str(core), "-c", str(network), "--rpc-portal", "127.0.0.1:15888"],
            {"HOME": str(ops.EASYTIER_HUB_HOME_DIR)},
            None,
        ),
        ("enable", "easytier"),
    ]
    assert commands == []
    assert not systemd.exists()


def test_elsewhere_an_enabled_engine_is_restarted_on_its_new_line(supervised_box):
    _, _, core, _, controller = supervised_box
    controller.enabled.add("easytier")
    config = EasyTierConfig(mode="console", is_secure_mode=True)
    config.set_config_server(CONSOLE)

    ops.EasyTierConfigApplier().apply(config, hostname="neutrino")

    assert controller.verbs() == [
        (
            "set_start_line",
            "easytier",
            [
                str(core),
                "--config-server",
                CONSOLE,
                "--secure-mode=true",
                "--rpc-portal",
                "127.0.0.1:15888",
            ],
            {"HOME": str(ops.EASYTIER_HUB_HOME_DIR)},
            None,
        ),
        ("restart", "easytier"),
    ]


def test_elsewhere_nothing_to_run_stops_the_engine_and_forgets_its_line(
    supervised_box,
):
    generated, commands, _, _, controller = supervised_box
    generated.mkdir()
    (generated / "easytier.toml").write_text("stale")

    note = ops.EasyTierConfigApplier().apply(
        EasyTierConfig(mode="console"), hostname="neutrino"
    )

    assert note == "stopped; there is no network to run"
    assert list(generated.iterdir()) == []
    assert controller.verbs() == [
        ("stop", "easytier"),
        ("set_start_line", "easytier", [], {}, None),
    ]
    assert commands == []


def test_elsewhere_the_held_start_line_is_what_current_means(supervised_box, tmp_path):
    generated, _, core, _, controller = supervised_box
    config = EasyTierConfig(mode="console")
    config.set_config_server(CONSOLE)
    argv = [str(core), "--config-server", CONSOLE, "--rpc-portal", "127.0.0.1:15888"]
    (tmp_path / "services.json").write_text(
        json.dumps(
            {"enabled": ["easytier"], "start_lines": {"easytier": {"argv": argv}}}
        )
    )
    controller.active.add("easytier")
    applier = ops.EasyTierConfigApplier()

    assert applier.is_current(config, hostname="neutrino")
    config.is_secure_mode = True
    assert not applier.is_current(config, hostname="neutrino")
    controller.active.clear()
    config.is_secure_mode = False
    assert not applier.is_current(config, hostname="neutrino")


def test_console_devices_are_found_by_address_on_the_psutil_path(
    elsewhere, monkeypatch
):
    import socket

    from neutrino_hub.modules.router import link_status
    from tests.conftest import FakePsutil

    machine = FakePsutil()
    machine.addresses = {
        "utun5": [(socket.AF_INET, "10.144.144.3", "255.255.255.0")],
        "en0": [(socket.AF_INET, "192.168.1.20", "255.255.255.0")],
    }
    monkeypatch.setattr(link_status, "psutil", machine)
    monkeypatch.setattr(
        ops.EasyTierStatusReader, "addresses", lambda self: ["10.144.144.3/24"]
    )

    assert ops.console_device_names() == ["utun5"]
