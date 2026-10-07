"""Reading the resolvers off the lease dhcpcd, the one lease client the
router layer drives, holds on an uplink."""

import subprocess
from types import SimpleNamespace

import pytest

from neutrino_hub.modules.router import dhcp_client
from neutrino_hub.modules.router.dhcp_client import (
    RouterDhcpClient,
    lease_file_dns,
    parse_lease_dns,
)
from neutrino_hub.utils.subprocess_run import CommandResult

# What `dhcpcd --dumplease -4 enp2s0` prints for a lease naming two resolvers.
DUMP = """broadcast_address='192.168.1.255'
dhcp_lease_time='86400'
dhcp_message_type='5'
dhcp_server_identifier='192.168.1.1'
domain_name_servers='192.168.1.1 192.0.2.53'
ip_address='192.168.1.20'
network_number='192.168.1.0'
routers='192.168.1.1'
subnet_cidr='24'
subnet_mask='255.255.255.0'
"""


# --- parsing --------------------------------------------------------------------


def test_the_resolvers_come_in_the_leases_order():
    assert parse_lease_dns(DUMP) == ["192.168.1.1", "192.0.2.53"]


def test_the_name_hooks_see_reads_the_same():
    assert parse_lease_dns("new_domain_name_servers='10.0.0.1'\n") == ["10.0.0.1"]


@pytest.mark.parametrize(
    "text",
    [
        "",
        "ip_address='192.168.1.20'\nrouters='192.168.1.1'\n",
        "domain_name_servers=''\n",
        "domain_name_servers='not-an-address'\n",
    ],
    ids=["nothing", "no resolver option", "empty option", "no address in it"],
)
def test_a_lease_naming_no_resolver_gives_none(text):
    assert parse_lease_dns(text) == []


def test_a_word_that_is_not_an_address_is_left_out():
    assert parse_lease_dns("domain_name_servers='192.0.2.53 x 10.0.0.1'") == [
        "192.0.2.53",
        "10.0.0.1",
    ]


# --- asking dhcpcd ------------------------------------------------------------


@pytest.fixture
def dhcpcd(monkeypatch, tmp_path):
    """dhcpcd installed, answering with :data:`DUMP`; returns what was run."""
    ran = []
    answer = {"result": CommandResult(command=[], exit_code=0, stdout=DUMP, stderr="")}

    def run(command, **keywords):
        ran.append((command, keywords))
        if isinstance(answer["result"], Exception):
            raise answer["result"]
        return answer["result"]

    config = tmp_path / "dhcpcd_enp2s0.conf"
    monkeypatch.setattr(dhcp_client, "ROUTER_DHCP_LEASE_DIR", tmp_path / "leases")
    monkeypatch.setattr(dhcp_client, "ROUTER_DHCP_BINARIES", ("/usr/sbin/dhcpcd",))
    monkeypatch.setattr(dhcp_client.os.path, "isfile", lambda path: True)
    monkeypatch.setattr(
        dhcp_client, "router_dhcp_config_path", lambda interface: config
    )
    monkeypatch.setattr(dhcp_client, "run", run)
    return SimpleNamespace(ran=ran, config=config, answer=answer)


def test_the_lease_is_dumped_with_the_uplinks_own_configuration(dhcpcd):
    dhcpcd.config.write_text("interface enp2s0\n")

    assert RouterDhcpClient(interface="enp2s0").lease_dns() == [
        "192.168.1.1",
        "192.0.2.53",
    ]
    (command, keywords), *_ = dhcpcd.ran
    assert command == [
        "/usr/sbin/dhcpcd",
        "--dumplease",
        "-4",
        "--config",
        str(dhcpcd.config),
        "enp2s0",
    ]
    assert keywords["is_checked"] is False


def test_no_lease_and_no_answer_both_read_as_none(dhcpcd):
    dhcpcd.answer["result"] = CommandResult(
        command=[], exit_code=1, stdout="", stderr="dhcpcd: no lease"
    )
    assert RouterDhcpClient(interface="enp2s0").lease_dns() == []

    dhcpcd.answer["result"] = subprocess.TimeoutExpired(["dhcpcd"], 5)
    assert RouterDhcpClient(interface="enp2s0").lease_dns() == []


def test_without_dhcpcd_there_is_no_lease(monkeypatch, tmp_path):
    monkeypatch.setattr(dhcp_client, "ROUTER_DHCP_LEASE_DIR", tmp_path)
    monkeypatch.setattr(dhcp_client, "ROUTER_DHCP_BINARIES", ())
    monkeypatch.setattr(dhcp_client.shutil, "which", lambda name: None)

    assert RouterDhcpClient(interface="enp2s0").lease_dns() == []


# --- the lease file -------------------------------------------------------------


def lease_message(*options: bytes) -> bytes:
    """A DHCP message as dhcpcd keeps it: the fixed part, the cookie, options."""
    return bytes(236) + bytes.fromhex("63825363") + b"".join(options) + b"\xff"


# Option 53 (an ACK), then option 6 naming two resolvers, as Debian 12's
# dhcpcd 9.4.1 wrote it for a libvirt network.
RESOLVERS = bytes([6, 8, 192, 168, 122, 1, 192, 0, 2, 53])
ACK = bytes([53, 1, 5])


def test_the_lease_file_s_resolvers_come_in_their_order():
    assert lease_file_dns(lease_message(ACK, b"\x00", RESOLVERS)) == [
        "192.168.122.1",
        "192.0.2.53",
    ]


@pytest.mark.parametrize(
    "data",
    [b"", bytes(300), lease_message(ACK), lease_message(bytes([6]))],
    ids=["empty", "no cookie", "no resolver option", "cut short"],
)
def test_a_lease_file_naming_no_resolver_gives_none(data):
    assert lease_file_dns(data) == []


def test_the_lease_file_is_read_and_dhcpcd_is_not_asked(dhcpcd, tmp_path):
    leases = tmp_path / "leases"
    leases.mkdir()
    (leases / "enp2s0.lease").write_bytes(lease_message(ACK, RESOLVERS))

    assert RouterDhcpClient(interface="enp2s0").lease_dns() == [
        "192.168.122.1",
        "192.0.2.53",
    ]
    assert dhcpcd.ran == []


# --- the lease client units systemd has ---


def test_every_lease_client_unit_is_listed_in_any_state_and_when_enabled(
    monkeypatch, tmp_path
):
    listed = (
        "neutrino_hub_dhcpcd@enp1s0.service loaded active running Neutrino\n"
        "neutrino_hub_dhcpcd@enp3s0.1.service loaded activating auto-restart N\n"
    )
    wants = tmp_path / "multi-user.target.wants"
    wants.mkdir()
    (wants / "neutrino_hub_dhcpcd@enp9s0.service").write_text("")
    (wants / "neutrino_hub_web.service").write_text("")
    monkeypatch.setattr(dhcp_client, "SYSTEM_SYSTEMD_DIR", tmp_path)
    monkeypatch.setattr(
        dhcp_client,
        "run",
        lambda command, **keywords: CommandResult(
            command=command, exit_code=0, stdout=listed, stderr=""
        ),
    )

    assert dhcp_client.lease_client_interfaces() == ["enp1s0", "enp3s0.1", "enp9s0"]


@pytest.mark.parametrize(
    ("state", "is_enabled", "is_standing"),
    [
        ("active", False, True),
        ("activating", False, True),
        ("failed", False, True),
        ("inactive", True, True),
        ("inactive", False, False),
    ],
)
def test_a_lease_client_stands_in_any_state_but_stopped_or_while_enabled(
    monkeypatch, state, is_enabled, is_standing
):
    monkeypatch.setattr(dhcp_client, "unit_state", lambda unit: state)
    monkeypatch.setattr(
        dhcp_client,
        "run",
        lambda command, **keywords: CommandResult(
            command=command, exit_code=0 if is_enabled else 1, stdout="", stderr=""
        ),
    )

    assert RouterDhcpClient(interface="enp3s0.1").is_standing is is_standing
