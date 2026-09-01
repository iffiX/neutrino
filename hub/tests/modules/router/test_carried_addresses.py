"""Letting go of the address a handover carried across.

Taking an uplink over under DHCP leaves it holding two addresses for a while:
the one it arrived with, put back so the handover did not go dark, and the one
the lease client was given. The first is not the box's to keep — the server
still has it out to whoever held it before — but letting it go drops whatever
is connected over it, which is why it happens last of all and never before a
lease has actually arrived.
"""

import json

import pytest

from neutrino_hub.modules.router import links


@pytest.fixture
def machine(monkeypatch):
    """A stand-in for `ip`, recording what it was asked to remove."""
    state: dict = {"addresses": {}, "removed": []}

    def fake_run(command, **keywords):
        if command[1:4] == ["-4", "-json", "addr"]:
            name = command[command.index("dev") + 1]
            return _Result(json.dumps([{"addr_info": state["addresses"][name]}]))
        if command[1:3] == ["address", "del"]:
            state["removed"].append((command[command.index("dev") + 1], command[3]))
        return _Result("")

    monkeypatch.setattr(links, "run", fake_run)
    return state


class _Result:
    def __init__(self, stdout: str):
        self.stdout = stdout
        self.is_success = True


def address(cidr: str, *, is_leased: bool) -> dict:
    local, _, prefix = cidr.partition("/")
    entry = {"local": local, "prefixlen": int(prefix)}
    if is_leased:
        entry["dynamic"] = True
    return entry


def test_the_carried_address_goes_once_a_lease_has_replaced_it(machine):
    machine["addresses"]["eth0"] = [
        address("192.168.1.30/24", is_leased=False),
        address("192.168.1.31/24", is_leased=True),
    ]

    released = links.retire_carried(("eth0",))

    assert machine["removed"] == [("eth0", "192.168.1.30/24")]
    assert "192.168.1.31/24" in released[0]


def test_an_interface_with_no_lease_yet_keeps_what_it_has(machine):
    """Taking the carried address off before a lease arrives takes the
    interface down — which is the whole thing carrying it was for."""
    machine["addresses"]["eth0"] = [address("192.168.1.30/24", is_leased=False)]

    assert links.retire_carried(("eth0",)) == []
    assert machine["removed"] == []


def test_an_address_from_a_lease_is_never_let_go(machine):
    """A served network's address is put on by hand and stays; an uplink's
    comes from a lease and is the one to keep. Neither is removed here unless
    something else is holding the interface up."""
    machine["addresses"]["eth0"] = [address("192.168.8.1/24", is_leased=False)]

    links.retire_carried(("eth0",))

    assert machine["removed"] == []


def test_a_served_network_beside_an_uplink_is_left_alone(machine):
    """The LAN's address is static on purpose. It is only ever touched on an
    interface that has taken a lease, which a LAN does not."""
    machine["addresses"]["eth0"] = [
        address("192.168.1.30/24", is_leased=False),
        address("192.168.1.31/24", is_leased=True),
    ]
    machine["addresses"]["eth1"] = [address("192.168.8.1/24", is_leased=False)]

    links.retire_carried(("eth0", "eth1"))

    assert machine["removed"] == [("eth0", "192.168.1.30/24")]


# --- asking for a unit that is ordered after the one asking ---


def test_the_engines_are_asked_for_rather_than_waited_on(monkeypatch):
    """Both units are ordered `After=` the router unit, and the applier that
    starts them runs inside it. `--now` would have the router wait for
    something systemd will not start until the router has finished, which is a
    deadlock broken only by a job timeout — and everything ordered behind the
    router is stuck for as long as it lasts."""
    from neutrino_hub.modules.router import dhcp_client, supplicant

    commands: list = []
    for module in (dhcp_client, supplicant):
        monkeypatch.setattr(
            module,
            "run",
            lambda command, **keywords: commands.append(command) or _Ran(),
        )
    dhcp_client.RouterDhcpClient(interface="eth0").start()
    dhcp_client.RouterDhcpClient(interface="eth0").restart()
    supplicant.RouterWifiClient(interface="wlan0").start()

    words = [word for command in commands for word in command]
    assert "--now" not in words
    assert words.count("--no-block") == 3


class _Ran:
    is_success = True
    stdout = ""
