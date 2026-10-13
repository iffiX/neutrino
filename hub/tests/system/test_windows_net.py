"""What Windows says about its network, from tables a Windows machine recorded.

The tables and the PowerShell answers given at the same moment are in
``golden/windows_net_nmxwin.json``: two adapters, two default routes at one
metric, a temporary and an RA address, DHCP resolvers on both.

What these pin: the three row layouts at their Windows sizes; the adapters
walk at every offset it reads; each read answering what PowerShell answered,
with default routes by metric then alias and resolvers by interface metric
then index; and the live reader copying a table out before freeing it,
asking for the adapters again at the size Windows names, and failing with
the Win32 code.
"""

import base64
import ctypes
import json
from functools import partial
from operator import itemgetter

import pytest

from neutrino_hub.platforms import win32
from neutrino_hub.system import windows_net
from neutrino_hub.system.constants import (
    SYSTEM_WINDOWS_ADAPTERS_BUFFER_BYTES,
    SYSTEM_WINDOWS_ADAPTERS_TRIES,
)
from neutrino_hub.system.windows_net import IphlpapiTableReader
from tests.conftest import WINDOWS_NET_GOLDEN, FakeIphlpapiTables

GOLDEN = json.loads(WINDOWS_NET_GOLDEN.read_text(encoding="utf-8"))
EXPECTED = GOLDEN["expected"]
# The two adapters' LUIDs and indexes on the recording machine.
FIRST_LUID, FIRST_INDEX = 1689399649632256, 4
SECOND_LUID, SECOND_INDEX = 1689399716741120, 20


@pytest.fixture
def recorded(monkeypatch):
    monkeypatch.setattr(windows_net, "_READER", FakeIphlpapiTables.recorded())


def _mib_table(rows: list) -> bytes:
    """A MIB table of rows built here: the count, then the rows from byte 8."""
    head = len(rows).to_bytes(4, "little").ljust(win32.MIB_TABLE_ROWS_OFFSET, b"\0")
    return head + b"".join(bytes(row) for row in rows)


# --- the layouts ---


@pytest.mark.parametrize(
    ("row_type", "size", "names"),
    [
        (win32.MibIpForwardRow2, 104, ("routes_v4", "routes_v6")),
        (win32.MibIpInterfaceRow, 168, ("interfaces_v4", "interfaces_v6")),
        (win32.MibUnicastIpAddressRow, 80, ("unicast_v4", "unicast_v6")),
    ],
)
def test_each_row_has_its_windows_size_and_a_recorded_table_holds_whole_rows(
    row_type, size, names
):
    assert ctypes.sizeof(row_type) == size
    for name in names:
        table = base64.b64decode(GOLDEN[name])
        count = int.from_bytes(table[:4], "little")
        assert count > 0
        assert len(table) == win32.MIB_TABLE_ROWS_OFFSET + count * size


def test_the_adapters_walk_reads_each_field_at_its_offset(recorded):
    """Against the buffer GetAdaptersAddresses filled: the loopback adapter
    is the third entry and is left out."""
    assert windows_net.adapters() == [
        {
            "index": FIRST_INDEX,
            "luid": FIRST_LUID,
            "name": "Ethernet Instance 0 2",
            "mac": "52:54:00:6d:07:8e",
            "is_up": True,
            "ipv4_metric": 15,
            "addresses": ["fe80::518f:bb56:acb2:22fe/64", "192.168.10.105/24"],
            "dns_servers": ["192.168.10.1"],
        },
        {
            "index": SECOND_INDEX,
            "luid": SECOND_LUID,
            "name": "Ethernet Instance 0 3",
            "mac": "52:54:00:b6:0b:21",
            "is_up": True,
            "ipv4_metric": 15,
            "addresses": [
                "2001:db8:b:0:c60a:c2e9:531e:532f/64",
                "2001:db8:b:0:8575:5a6c:3a63:e949/128",
                "fe80::3006:f6cb:ae66:ebd2/64",
                "10.10.2.166/24",
            ],
            "dns_servers": ["10.10.2.1"],
        },
    ]
    for adapter in windows_net.adapters():
        assert GOLDEN["aliases"][str(adapter["luid"])] == adapter["name"]


# --- each read against what PowerShell answered ---


def test_the_default_routes_are_the_ones_get_netroute_lists(recorded):
    expected = sorted(EXPECTED["routes"]["routes"], key=itemgetter("metric", "dev"))

    routes = windows_net.default_routes(win32.AF_INET)

    assert routes == expected
    assert [(route["metric"], route["dev"]) for route in routes] == [
        (15, "Ethernet Instance 0 2"),
        (15, "Ethernet Instance 0 3"),
    ]


def test_a_default_route_without_a_next_hop_names_no_gateway(monkeypatch):
    on_link = win32.MibIpForwardRow2(InterfaceLuid=7, Metric=5)
    on_link.DestinationPrefix.Prefix.si_family = win32.AF_INET
    on_link.NextHop.si_family = win32.AF_INET
    unnamed = win32.MibIpForwardRow2(InterfaceLuid=8, Metric=1)
    unnamed.DestinationPrefix.Prefix.si_family = win32.AF_INET
    interface = win32.MibIpInterfaceRow(InterfaceLuid=7, Metric=0)
    tables = {
        ("forward", win32.AF_INET): _mib_table([on_link, unnamed]),
        ("interface", win32.AF_INET): _mib_table([interface]),
    }
    monkeypatch.setattr(
        windows_net,
        "_READER",
        FakeIphlpapiTables(tables=tables, aliases={7: "wt0"}),
    )

    assert windows_net.default_routes(win32.AF_INET) == [{"dev": "wt0", "metric": 5}]


def test_the_ipv6_addresses_are_the_ones_get_netipaddress_lists(recorded):
    expected = [
        {**entry, "address": entry["address"].split("%", 1)[0]}
        for entry in EXPECTED["ipv6"]["addresses"]
    ]

    found = windows_net.unicast_addresses(win32.AF_INET6)

    order = itemgetter("dev", "address")
    assert sorted(found, key=order) == sorted(expected, key=order)


def test_the_adapters_are_the_ones_get_netadapter_lists_with_their_addresses(
    recorded,
):
    listed = EXPECTED["interfaces"]

    found = windows_net.adapters()

    assert sorted((a["name"], a["index"], a["mac"]) for a in found) == sorted(
        (entry["Name"], entry["ifIndex"], entry["MacAddress"].replace("-", ":").lower())
        for entry in listed["adapters"]
    )
    for adapter in found:
        assert sorted(text.split("/")[0] for text in adapter["addresses"]) == sorted(
            entry["IPAddress"].split("%", 1)[0]
            for entry in listed["addresses"]
            if entry["InterfaceIndex"] == adapter["index"]
        )


def test_the_resolvers_go_by_interface_metric_then_index(recorded):
    """Both interfaces have metric 15, so index 4 comes before index 20;
    PowerShell's own order between equal metrics is arbitrary."""
    found = windows_net.resolvers()

    assert sorted(found) == sorted(EXPECTED["resolvers"]["servers"])
    assert found == ["192.168.10.1", "10.10.2.1"]


def test_a_resolver_of_an_interface_that_is_not_connected_is_left_out(monkeypatch):
    reader = FakeIphlpapiTables.recorded()
    table = bytearray(reader.tables[("interface", win32.AF_INET)])
    size = ctypes.sizeof(win32.MibIpInterfaceRow)
    for at in range(win32.MIB_TABLE_ROWS_OFFSET, len(table), size):
        row = win32.MibIpInterfaceRow.from_buffer(table, at)
        if row.InterfaceIndex == FIRST_INDEX:
            row.Connected = 0
    reader.tables[("interface", win32.AF_INET)] = bytes(table)
    monkeypatch.setattr(windows_net, "_READER", reader)

    assert windows_net.resolvers() == ["10.10.2.1"]


@pytest.mark.parametrize(
    "read",
    [
        partial(windows_net.default_routes, win32.AF_INET),
        partial(windows_net.unicast_addresses, win32.AF_INET6),
        windows_net.adapters,
        windows_net.resolvers,
    ],
)
def test_a_refused_read_fails_with_the_readers_error(monkeypatch, read):
    monkeypatch.setattr(
        windows_net, "_READER", FakeIphlpapiTables(error=OSError(5, "denied"))
    )

    with pytest.raises(OSError) as refusal:
        read()

    assert refusal.value.errno == 5


# --- the live reader, iphlpapi faked ---


class FakeIphlpapi:
    """iphlpapi's calls, writing through the pointers they are handed.

    Attributes:
        table: The memory the table call answers with.
        freed: The address of every table freed.
        sizes: The buffer size each GetAdaptersAddresses call was handed.
        buffers: The address of each buffer it was handed.
    """

    def __init__(self, *, table=b"", code=0, adapters=b"", overflows=0, alias=""):
        self.table = ctypes.create_string_buffer(table, max(len(table), 1))
        self.freed: list = []
        self.sizes: list = []
        self.buffers: list = []
        self._code = code
        self._adapters = adapters
        self._overflows = overflows
        self._alias = alias

    def GetIpForwardTable2(self, family, pointer):
        if self._code:
            return self._code
        pointer._obj.value = ctypes.addressof(self.table)
        return 0

    def FreeMibTable(self, table):
        self.freed.append(table.value)

    def GetAdaptersAddresses(self, family, flags, reserved, buffer, size):
        self.sizes.append(size._obj.value)
        self.buffers.append(ctypes.addressof(buffer))
        if self._overflows:
            self._overflows -= 1
            size._obj.value += 4096
            return win32.ERROR_BUFFER_OVERFLOW
        ctypes.memmove(buffer, self._adapters, len(self._adapters))
        return 0

    def ConvertInterfaceLuidToAlias(self, luid, text, characters):
        if luid._obj.value != 7:
            return 1168
        encoded = self._alias.encode("utf-16-le")
        ctypes.memmove(text, encoded, len(encoded))
        return 0


def test_a_table_is_copied_out_before_iphlpapi_frees_it():
    table = base64.b64decode(GOLDEN["routes_v4"])
    iphlpapi = FakeIphlpapi(table=table)

    copied = IphlpapiTableReader(iphlpapi=iphlpapi).forward_table(win32.AF_INET)

    assert copied == table
    assert iphlpapi.freed == [ctypes.addressof(iphlpapi.table)]


def test_a_refused_table_fails_with_its_win32_code():
    iphlpapi = FakeIphlpapi(code=1168)

    with pytest.raises(OSError) as refusal:
        IphlpapiTableReader(iphlpapi=iphlpapi).forward_table(win32.AF_INET)

    assert refusal.value.errno == 1168
    assert iphlpapi.freed == []


def test_the_adapters_are_asked_again_at_the_size_windows_names():
    iphlpapi = FakeIphlpapi(adapters=b"adapters", overflows=1)

    buffer, base = IphlpapiTableReader(iphlpapi=iphlpapi).adapters_buffer(
        win32.AF_UNSPEC
    )

    assert iphlpapi.sizes == [
        SYSTEM_WINDOWS_ADAPTERS_BUFFER_BYTES,
        SYSTEM_WINDOWS_ADAPTERS_BUFFER_BYTES + 4096,
    ]
    assert buffer.startswith(b"adapters")
    assert len(buffer) == SYSTEM_WINDOWS_ADAPTERS_BUFFER_BYTES + 4096
    assert base == iphlpapi.buffers[-1]


def test_a_buffer_still_too_small_after_the_last_try_fails_with_111():
    iphlpapi = FakeIphlpapi(overflows=SYSTEM_WINDOWS_ADAPTERS_TRIES)

    with pytest.raises(OSError) as refusal:
        IphlpapiTableReader(iphlpapi=iphlpapi).adapters_buffer(win32.AF_UNSPEC)

    assert refusal.value.errno == win32.ERROR_BUFFER_OVERFLOW
    assert len(iphlpapi.sizes) == SYSTEM_WINDOWS_ADAPTERS_TRIES


def test_an_alias_is_read_as_utf16_and_is_empty_for_an_unknown_luid():
    reader = IphlpapiTableReader(iphlpapi=FakeIphlpapi(alias="Ethernet 2 Ü"))

    assert reader.alias(7) == "Ethernet 2 Ü"
    assert reader.alias(8) == ""
