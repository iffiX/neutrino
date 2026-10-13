"""What Windows says about its network, read through iphlpapi.

The default routes, the addresses each interface holds, the adapters and the
resolvers they name, decoded here from the bytes of iphlpapi's tables; no
process is started. The calls that return those bytes sit behind
:class:`IphlpapiTableReader`, the one seam a test replaces with recorded
buffers.

Not pure: calls iphlpapi.
"""

import ctypes
import ipaddress
import struct
from operator import itemgetter

from neutrino_hub.platforms import win32
from neutrino_hub.system.constants import (
    SYSTEM_WINDOWS_ADAPTERS_BUFFER_BYTES,
    SYSTEM_WINDOWS_ADAPTERS_TRIES,
)

# The reader every read shares, bound on first use.
_READER = None


def default_routes(family: int) -> list[dict]:
    """Every default route of one address family.

    Args:
        family: ``win32.AF_INET`` or ``win32.AF_INET6``.

    Returns:
        Entries shaped as ``ip -json route show default`` prints them:
        ``dev`` the interface's alias, ``gateway`` when the route has a next
        hop, and ``metric`` the route's metric plus its interface's. Lowest
        metric first, then by ``dev``.

    Raises:
        OSError: When iphlpapi cannot be loaded or refuses a table, with the
            Win32 code.
    """
    reader = _reader()
    forward = _rows(reader.forward_table(family), win32.MibIpForwardRow2)
    metrics = {
        row.InterfaceLuid: row.Metric
        for row in _rows(reader.interface_table(family), win32.MibIpInterfaceRow)
    }
    luids = {row.InterfaceLuid for row in forward}
    aliases = {luid: reader.alias(luid) for luid in luids}
    routes = []
    for row in forward:
        prefix = row.DestinationPrefix
        device = aliases[row.InterfaceLuid]
        if prefix.PrefixLength or prefix.Prefix.si_family != family or not device:
            continue
        route = {
            "dev": device,
            "metric": row.Metric + metrics.get(row.InterfaceLuid, 0),
        }
        gateway = _inet_text(row.NextHop)
        if gateway and not ipaddress.ip_address(gateway).is_unspecified:
            route["gateway"] = gateway
        routes.append(route)
    routes.sort(key=itemgetter("metric", "dev"))
    return routes


def unicast_addresses(family: int) -> list[dict]:
    """Every unicast address of one address family, in the system's order.

    Args:
        family: ``win32.AF_INET`` or ``win32.AF_INET6``.

    Returns:
        One entry per address: ``dev`` the interface's alias, ``address``
        with no zone, ``prefixlen`` its on-link prefix length, and ``state``
        and ``suffix`` its duplicate detection state and suffix origin in
        the words ``Get-NetIPAddress`` prints: ``Preferred``, ``Deprecated``
        and the rest; ``Random``, ``Link``, ``Dhcp`` and the rest.

    Raises:
        OSError: When iphlpapi cannot be loaded or refuses the table, with
            the Win32 code.
    """
    reader = _reader()
    rows = [
        row
        for row in _rows(reader.unicast_table(family), win32.MibUnicastIpAddressRow)
        if row.Address.si_family == family
    ]
    luids = {row.InterfaceLuid for row in rows}
    aliases = {luid: reader.alias(luid) for luid in luids}
    found = []
    for row in rows:
        if not aliases[row.InterfaceLuid]:
            continue
        found.append(
            {
                "dev": aliases[row.InterfaceLuid],
                "address": _inet_text(row.Address),
                "prefixlen": row.OnLinkPrefixLength,
                "state": win32.NL_DAD_STATE_WORDS.get(row.DadState, str(row.DadState)),
                "suffix": win32.NL_SUFFIX_ORIGIN_WORDS.get(
                    row.SuffixOrigin, str(row.SuffixOrigin)
                ),
            }
        )
    return found


def adapters() -> list[dict]:
    """Every network adapter, with its addresses and its resolvers.

    Returns:
        One entry per adapter in the system's order, the loopback and the
        tunnel pseudo-interfaces left out as ``Get-NetAdapter`` leaves them:
        ``index``, ``luid``, ``name`` its alias, ``mac`` lowercase with
        colons and empty when it has none, ``is_up``, ``ipv4_metric``,
        ``addresses`` each as ``address/prefixlen``, and ``dns_servers`` of
        both families.

    Raises:
        OSError: When iphlpapi cannot be loaded or GetAdaptersAddresses
            fails, with the Win32 code.
    """
    buffer, base = _reader().adapters_buffer(win32.AF_UNSPEC)
    found = []
    at = 0 if buffer else None
    while at is not None:
        if _dword(buffer, at + win32.ADAPTER_IF_TYPE_OFFSET) not in (
            win32.IF_TYPE_SOFTWARE_LOOPBACK,
            win32.IF_TYPE_TUNNEL,
        ):
            found.append(_adapter(buffer, base, at))
        at = _offset(buffer, base, at + win32.ADAPTER_NEXT_OFFSET)
    return found


def resolvers() -> list[str]:
    """The IPv4 resolvers of every connected interface.

    Returns:
        The addresses by their interface's metric, then its index, each
        once.

    Raises:
        OSError: When iphlpapi cannot be loaded or refuses a call, with the
            Win32 code.
    """
    connected = {
        row.InterfaceLuid: (row.Metric, row.InterfaceIndex)
        for row in _rows(
            _reader().interface_table(win32.AF_INET), win32.MibIpInterfaceRow
        )
        if row.Connected
    }
    ranked = sorted(
        (connected[adapter["luid"]], adapter["dns_servers"])
        for adapter in adapters()
        if adapter["luid"] in connected
    )
    servers = []
    for _, named in ranked:
        for server in named:
            if ipaddress.ip_address(server).version == 4 and server not in servers:
                servers.append(server)
    return servers


def _reader() -> "IphlpapiTableReader":
    """The reader every read shares, bound on first use."""
    global _READER
    if _READER is None:
        _READER = IphlpapiTableReader(iphlpapi=win32.libraries().iphlpapi)
    return _READER


def _rows(table: bytes, row_type) -> list:
    """The rows of one MIB table: a 32-bit count, then the rows."""
    if len(table) < win32.MIB_TABLE_ROWS_OFFSET:
        return []
    size = ctypes.sizeof(row_type)
    return [
        row_type.from_buffer_copy(table, win32.MIB_TABLE_ROWS_OFFSET + index * size)
        for index in range(_dword(table, 0))
    ]


def _inet_text(address: win32.SockaddrInet) -> str:
    """A SOCKADDR_INET's address as text; empty for another family."""
    if address.si_family == win32.AF_INET:
        return str(ipaddress.IPv4Address(bytes(address.Ipv4.sin_addr)))
    if address.si_family == win32.AF_INET6:
        return str(ipaddress.IPv6Address(bytes(address.Ipv6.sin6_addr)))
    return ""


def _adapter(buffer: bytes, base: int, at: int) -> dict:
    """The IP_ADAPTER_ADDRESSES_LH entry at one offset of the buffer."""
    start = at + win32.ADAPTER_PHYSICAL_ADDRESS_OFFSET
    length = min(_dword(buffer, at + win32.ADAPTER_PHYSICAL_ADDRESS_LENGTH_OFFSET), 8)
    addresses = []
    for entry in _chain(buffer, base, at + win32.ADAPTER_FIRST_UNICAST_OFFSET):
        address = _sockaddr_text(buffer, base, entry)
        if address:
            prefix = buffer[entry + win32.ADDRESS_ON_LINK_PREFIX_LENGTH_OFFSET]
            addresses.append(f"{address}/{prefix}")
    servers = [
        _sockaddr_text(buffer, base, entry)
        for entry in _chain(buffer, base, at + win32.ADAPTER_FIRST_DNS_SERVER_OFFSET)
    ]
    name_at = _offset(buffer, base, at + win32.ADAPTER_FRIENDLY_NAME_OFFSET)
    return {
        "index": _dword(buffer, at + win32.ADAPTER_IF_INDEX_OFFSET),
        "luid": _qword(buffer, at + win32.ADAPTER_LUID_OFFSET),
        "name": "" if name_at is None else _utf16_text(buffer, name_at),
        "mac": ":".join(f"{byte:02x}" for byte in buffer[start : start + length]),
        "is_up": _dword(buffer, at + win32.ADAPTER_OPER_STATUS_OFFSET)
        == win32.IF_OPER_STATUS_UP,
        "ipv4_metric": _dword(buffer, at + win32.ADAPTER_IPV4_METRIC_OFFSET),
        "addresses": addresses,
        "dns_servers": [server for server in servers if server],
    }


def _chain(buffer: bytes, base: int, first: int) -> list[int]:
    """The offsets of a linked list of address entries, from the pointer at ``first``."""
    entries = []
    at = _offset(buffer, base, first)
    while at is not None:
        entries.append(at)
        at = _offset(buffer, base, at + win32.ADDRESS_NEXT_OFFSET)
    return entries


def _sockaddr_text(buffer: bytes, base: int, entry: int) -> str:
    """The address an entry's SOCKET_ADDRESS points to; empty for another family."""
    at = _offset(buffer, base, entry + win32.ADDRESS_SOCKADDR_OFFSET)
    if at is None:
        return ""
    family = struct.unpack_from("<H", buffer, at)[0]
    if family == win32.AF_INET:
        start = at + win32.SockaddrIn.sin_addr.offset
        return str(ipaddress.IPv4Address(buffer[start : start + 4]))
    if family == win32.AF_INET6:
        start = at + win32.SockaddrIn6.sin6_addr.offset
        return str(ipaddress.IPv6Address(buffer[start : start + 16]))
    return ""


def _offset(buffer: bytes, base: int, at: int) -> "int | None":
    """Where in the buffer the pointer stored at ``at`` points; None for null."""
    pointer = _qword(buffer, at)
    return None if pointer == 0 else pointer - base


def _dword(buffer: bytes, at: int) -> int:
    """The little-endian 32-bit word at an offset."""
    return struct.unpack_from("<I", buffer, at)[0]


def _qword(buffer: bytes, at: int) -> int:
    """The little-endian 64-bit word at an offset."""
    return struct.unpack_from("<Q", buffer, at)[0]


def _utf16_text(buffer: bytes, at: int) -> str:
    """The NUL-terminated UTF-16-LE string starting at an offset."""
    end = at
    while end + 1 < len(buffer) and buffer[end : end + 2] != b"\0\0":
        end += 2
    return buffer[at:end].decode("utf-16-le", errors="replace")


class IphlpapiTableReader:
    """iphlpapi's network tables and adapter list, copied out as bytes."""

    def __init__(self, *, iphlpapi):
        """
        Args:
            iphlpapi: The bound library, its prototypes set by
                :class:`neutrino_hub.platforms.win32.Win32Libraries`.
        """
        self._iphlpapi = iphlpapi

    def forward_table(self, family: int) -> bytes:
        """The route table, as GetIpForwardTable2 lays it out.

        Args:
            family: The address family, as Windows numbers it.

        Returns:
            The MIB_IPFORWARD_TABLE2 bytes.

        Raises:
            OSError: When the call fails, with its Win32 code.
        """
        return self._table(
            self._iphlpapi.GetIpForwardTable2, family, win32.MibIpForwardRow2
        )

    def interface_table(self, family: int) -> bytes:
        """The interface table, as GetIpInterfaceTable lays it out.

        Args:
            family: The address family, as Windows numbers it.

        Returns:
            The MIB_IPINTERFACE_TABLE bytes.

        Raises:
            OSError: When the call fails, with its Win32 code.
        """
        return self._table(
            self._iphlpapi.GetIpInterfaceTable, family, win32.MibIpInterfaceRow
        )

    def unicast_table(self, family: int) -> bytes:
        """The unicast address table, as GetUnicastIpAddressTable lays it out.

        Args:
            family: The address family, as Windows numbers it.

        Returns:
            The MIB_UNICASTIPADDRESS_TABLE bytes.

        Raises:
            OSError: When the call fails, with its Win32 code.
        """
        return self._table(
            self._iphlpapi.GetUnicastIpAddressTable,
            family,
            win32.MibUnicastIpAddressRow,
        )

    def adapters_buffer(self, family: int) -> tuple[bytes, int]:
        """The adapter list, as GetAdaptersAddresses fills a buffer.

        Args:
            family: The address family, as Windows numbers it.

        Returns:
            The buffer's bytes and the address it was filled at, which its
            pointers are relative to.

        Raises:
            OSError: When the call fails, or the buffer is still too small
                after :data:`SYSTEM_WINDOWS_ADAPTERS_TRIES` tries, with the
                Win32 code.
        """
        size = win32.DWORD(SYSTEM_WINDOWS_ADAPTERS_BUFFER_BYTES)
        flags = win32.GAA_FLAG_SKIP_ANYCAST | win32.GAA_FLAG_SKIP_MULTICAST
        code = win32.ERROR_BUFFER_OVERFLOW
        for _ in range(SYSTEM_WINDOWS_ADAPTERS_TRIES):
            buffer = ctypes.create_string_buffer(size.value)
            code = self._iphlpapi.GetAdaptersAddresses(
                family, flags, None, buffer, ctypes.byref(size)
            )
            if code == win32.NO_ERROR:
                return buffer.raw, ctypes.addressof(buffer)
            if code != win32.ERROR_BUFFER_OVERFLOW:
                break
        raise win32.returned_error(code)

    def alias(self, luid: int) -> str:
        """An interface's alias, the name ``Get-NetAdapter`` shows.

        Args:
            luid: The interface's LUID.

        Returns:
            The alias; empty when Windows names no interface by it.
        """
        characters = win32.IF_MAX_STRING_SIZE + 1
        text = ctypes.create_string_buffer(2 * characters)
        code = self._iphlpapi.ConvertInterfaceLuidToAlias(
            ctypes.byref(ctypes.c_uint64(luid)), text, characters
        )
        if code != win32.NO_ERROR:
            return ""
        return _utf16_text(text.raw, 0)

    def _table(self, call, family: int, row_type) -> bytes:
        """One MIB table, copied out of iphlpapi's memory before it is freed."""
        table = ctypes.c_void_p()
        code = call(family, ctypes.byref(table))
        if code != win32.NO_ERROR:
            raise win32.returned_error(code)
        try:
            count = ctypes.c_uint32.from_address(table.value).value
            return ctypes.string_at(
                table.value,
                win32.MIB_TABLE_ROWS_OFFSET + count * ctypes.sizeof(row_type),
            )
        finally:
            self._iphlpapi.FreeMibTable(table)
