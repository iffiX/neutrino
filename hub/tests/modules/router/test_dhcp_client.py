"""Reading the resolvers off the lease dhcpcd, the one lease client the
router layer drives, holds on an uplink."""

import subprocess
from types import SimpleNamespace

import pytest

from neutrino_hub.modules.router import dhcp_client
from neutrino_hub.modules.router.dhcp_client import RouterDhcpClient, parse_lease_dns
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


def test_without_dhcpcd_there_is_no_lease(monkeypatch):
    monkeypatch.setattr(dhcp_client, "ROUTER_DHCP_BINARIES", ())
    monkeypatch.setattr(dhcp_client.shutil, "which", lambda name: None)

    assert RouterDhcpClient(interface="enp2s0").lease_dns() == []
