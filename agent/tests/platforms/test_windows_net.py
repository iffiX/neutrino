"""What Windows says about its network through iphlpapi, decoded from recorded bytes.

What these pin: the structures keep their x64 sizes and the offsets the
recorded buffers were read with; the adapters of a two-NIC Windows 11
machine, recorded on nmxwin with ``GetAdaptersAddresses``, decode to the
interfaces its ``Get-NetAdapter`` and ``Get-NetIPAddress`` named, names,
MACs and addresses, the loopback pseudo interface and the tunnels left
out; a pointer outside the buffer, a structure past its end and a list that
loops raise ``ValueError``, and an empty buffer is no interface; a socket
table yields the owners listening on a port, IPv4 and IPv6, and a table
shorter than its rows raises; the live reads grow their buffer as Windows
asks and say what refused.
"""

import base64
import ctypes
import json
import struct
from pathlib import Path

import pytest

from neutrino_agent.platforms import win32
from neutrino_agent.platforms.windows_net import (
    interfaces_from,
    listener_pids_from,
    read_interfaces,
    read_listener_pids,
)

GOLDEN = json.loads(
    (Path(__file__).parent / "golden" / "windows_net_nmxwin.json").read_text()
)
ADAPTERS = base64.b64decode(GOLDEN["adapters"]["data"])
BASE = GOLDEN["adapters"]["base"]


def expected_interfaces() -> dict:
    """What PowerShell joined, by adapter name: the MAC and the addresses."""
    recorded = GOLDEN["expected"]["interfaces"]
    found = {}
    for adapter in recorded["adapters"]:
        mac = adapter["MacAddress"].replace("-", ":").lower()
        addresses = sorted(
            entry["IPAddress"].split("%", 1)[0]
            for entry in recorded["addresses"]
            if entry["InterfaceIndex"] == adapter["ifIndex"]
        )
        found[adapter["Name"]] = (mac, addresses)
    return found


def test_the_structures_keep_their_x64_sizes_and_offsets():
    assert ctypes.sizeof(win32.SocketAddress) == 16
    assert ctypes.sizeof(win32.IpAdapterUnicastAddress) == 64
    assert win32.IpAdapterUnicastAddress.OnLinkPrefixLength.offset == 56
    assert win32.IpAdapterAddresses.FriendlyName.offset == 72
    assert win32.IpAdapterAddresses.PhysicalAddress.offset == 80
    assert win32.IpAdapterAddresses.IfType.offset == 100
    assert win32.IpAdapterAddresses.OperStatus.offset == 104
    assert win32.IpAdapterAddresses.Ipv4Metric.offset == 216
    assert win32.IpAdapterAddresses.Luid.offset == 224
    assert ctypes.sizeof(win32.MibTcpRowOwnerPid) == 24
    assert ctypes.sizeof(win32.MibTcp6RowOwnerPid) == 56
    assert ctypes.sizeof(win32.UserInfo1) == 56
    assert ctypes.sizeof(win32.ProcessBasicInformation) == 48
    assert ctypes.sizeof(win32.QueryServiceConfig) == 64


def test_the_recorded_offsets_read_the_recorded_metrics():
    first = win32.IpAdapterAddresses.from_buffer_copy(ADAPTERS, 0)

    assert first.Length == 448
    assert (first.IfIndex, first.IfType, first.OperStatus) == (4, 6, 1)
    assert first.Ipv4Metric == 15
    assert first.Luid == 1689399649632256


def test_the_recorded_adapters_decode_to_what_powershell_named():
    interfaces = interfaces_from(ADAPTERS, BASE)

    decoded = {
        entry["name"]: (entry["mac"], sorted(entry["addresses"]))
        for entry in interfaces
    }
    assert decoded == expected_interfaces()
    assert interfaces == [
        {
            "name": "Ethernet Instance 0 2",
            "mac": "52:54:00:6d:07:8e",
            "addresses": ["fe80::518f:bb56:acb2:22fe", "192.168.10.105"],
        },
        {
            "name": "Ethernet Instance 0 3",
            "mac": "52:54:00:b6:0b:21",
            "addresses": [
                "2001:db8:b:0:c60a:c2e9:531e:532f",
                "2001:db8:b:0:8575:5a6c:3a63:e949",
                "fe80::3006:f6cb:ae66:ebd2",
                "10.10.2.166",
            ],
        },
    ]


def test_an_empty_buffer_is_no_interface():
    assert interfaces_from(b"", BASE) == []


@pytest.mark.parametrize(
    "data, base",
    [
        (ADAPTERS[:100], BASE),
        (ADAPTERS, BASE + 0x100000),
        (ADAPTERS[:900], BASE),
    ],
    ids=["structure_past_the_end", "pointer_outside", "next_outside"],
)
def test_a_malformed_buffer_raises(data, base):
    with pytest.raises(ValueError):
        interfaces_from(data, base)


def test_a_list_that_loops_raises():
    looped = bytearray(ADAPTERS)
    struct.pack_into("<Q", looped, 8, BASE)

    with pytest.raises(ValueError, match="loop"):
        interfaces_from(bytes(looped), BASE)


def tcp_table(rows) -> bytes:
    """An IPv4 listener table: ``(state, port, pid)`` per row."""
    data = struct.pack("<I", len(rows))
    for state, port, pid in rows:
        row = win32.MibTcpRowOwnerPid(
            dwState=state, dwLocalPort=int.from_bytes(port.to_bytes(2, "big"), "little")
        )
        row.dwOwningPid = pid
        data += bytes(row)
    return data


def tcp6_table(rows) -> bytes:
    """An IPv6 listener table: ``(state, port, pid)`` per row."""
    data = struct.pack("<I", len(rows))
    for state, port, pid in rows:
        row = win32.MibTcp6RowOwnerPid(
            dwState=state, dwLocalPort=int.from_bytes(port.to_bytes(2, "big"), "little")
        )
        row.dwOwningPid = pid
        data += bytes(row)
    return data


def test_the_owners_listening_on_a_port_are_read_off_the_socket_table():
    table = tcp_table([(2, 8000, 31), (2, 8001, 40), (2, 8000, 31), (5, 8000, 50)])

    assert listener_pids_from(table, win32.AF_INET, 8000) == [31]
    assert listener_pids_from(tcp6_table([(2, 8000, 32)]), win32.AF_INET6, 8000) == [32]
    assert listener_pids_from(tcp_table([]), win32.AF_INET, 8000) == []


@pytest.mark.parametrize(
    "data, family",
    [
        (b"\x01", win32.AF_INET),
        (struct.pack("<I", 2) + bytes(24), win32.AF_INET),
        (tcp_table([]), 99),
    ],
)
def test_a_socket_table_that_cannot_be_read_raises(data, family):
    with pytest.raises(ValueError):
        listener_pids_from(data, family, 8000)


class FakeIphlpapi:
    """GetAdaptersAddresses and GetExtendedTcpTable, scripted."""

    def __init__(self, *, adapters_status=(0,), tables=None):
        self.adapters_status = list(adapters_status)
        self.tables = dict(tables or {})
        self.sizes: list = []

    def GetAdaptersAddresses(self, family, flags, reserved, buffer, size):
        assert family == win32.AF_UNSPEC
        assert flags == 0x2 | 0x4 | 0x80
        self.sizes.append(size._obj.value)
        status = self.adapters_status.pop(0)
        if status == win32.ERROR_BUFFER_OVERFLOW:
            size._obj.value *= 2
        return status

    def GetExtendedTcpTable(self, buffer, size, order, family, kind, reserved):
        assert kind == win32.TCP_TABLE_OWNER_PID_LISTENER
        data = self.tables[family]
        if size._obj.value < len(data):
            size._obj.value = len(data)
            return win32.ERROR_INSUFFICIENT_BUFFER
        ctypes.memmove(buffer, data, len(data))
        return 0


def test_the_adapters_buffer_grows_as_windows_asks():
    iphlpapi = FakeIphlpapi(adapters_status=[win32.ERROR_BUFFER_OVERFLOW, 0])

    assert read_interfaces(iphlpapi) == []
    assert iphlpapi.sizes == [16 * 1024, 32 * 1024]


def test_no_adapter_is_no_interface_and_a_refusal_says_its_code():
    assert read_interfaces(FakeIphlpapi(adapters_status=[win32.ERROR_NO_DATA])) == []
    with pytest.raises(OSError, match="answered 87"):
        read_interfaces(FakeIphlpapi(adapters_status=[87]))
    with pytest.raises(OSError):
        read_interfaces(FakeIphlpapi(adapters_status=[win32.ERROR_BUFFER_OVERFLOW] * 4))


def test_the_listeners_are_read_on_both_families_each_once():
    iphlpapi = FakeIphlpapi(
        tables={
            win32.AF_INET: tcp_table([(2, 8000, 31)]),
            win32.AF_INET6: tcp6_table([(2, 8000, 31), (2, 8000, 32)]),
        }
    )

    assert read_listener_pids(8000, iphlpapi) == [31, 32]


def test_off_windows_nothing_is_read():
    with pytest.raises(OSError):
        read_interfaces()
    with pytest.raises(OSError):
        read_listener_pids(8000)
