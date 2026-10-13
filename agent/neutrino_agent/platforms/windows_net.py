"""What Windows says about its network through iphlpapi: the adapters and the listeners.

The adapters are ``GetAdaptersAddresses``'s, each with its MAC and its
unicast addresses, the loopback pseudo interface and the tunnels left out as
``Get-NetAdapter`` leaves them out. The listeners are ``GetExtendedTcpTable``'s
listening sockets with the process that owns each. The decoders take the
bytes a call filled, with the address the buffer sat at where it holds
pointers, and never a live handle; the calls are the two ``read_`` functions,
each taking the bound iphlpapi as its seam.

Not pure: calls iphlpapi.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import ctypes
import ipaddress
import struct

from neutrino_agent.platforms import win32

# Where the adapters' buffer starts and how often it may grow to the size
# Windows asks for.
WINDOWS_NET_ADAPTERS_BYTES = 16 * 1024
WINDOWS_NET_ATTEMPTS = 4
WINDOWS_NET_ADAPTER_FLAGS = (
    win32.GAA_FLAG_SKIP_ANYCAST
    | win32.GAA_FLAG_SKIP_MULTICAST
    | win32.GAA_FLAG_INCLUDE_GATEWAYS
)
# The interface types that are no adapter.
WINDOWS_NET_LEFT_OUT_TYPES = (win32.IF_TYPE_SOFTWARE_LOOPBACK, win32.IF_TYPE_TUNNEL)
# A socket table opens with its row count, and a row's state says it listens.
WINDOWS_NET_TABLE_HEAD_BYTES = 4
WINDOWS_NET_TCP_STATE_LISTEN = 2
# Where an address sits inside a socket address of each family.
WINDOWS_NET_SOCKADDR_FAMILY_FORMAT = "<H"
WINDOWS_NET_IPV4_AT = 4
WINDOWS_NET_IPV6_AT = 8


def interfaces_from(data: bytes, base: int) -> list:
    """Every adapter a ``GetAdaptersAddresses`` buffer lists, as the report lists interfaces.

    Args:
        data: The buffer's bytes.
        base: The address the buffer sat at, which its pointers count from.

    Returns:
        ``[{"name", "mac", "addresses"}]`` in the buffer's order, the
        loopback pseudo interface and the tunnels left out; a MAC that is
        absent or all zero is ``""``, an address carries no zone or prefix.

    Raises:
        ValueError: When a pointer leads outside the buffer, a structure
            does not fit in it, or the list loops.
    """
    interfaces = []
    offset = 0 if data else None
    seen = set()
    while offset is not None:
        if offset in seen:
            raise ValueError(f"the adapters loop at {offset}")
        seen.add(offset)
        adapter = _structure_at(win32.IpAdapterAddresses, data, offset)
        name = win32.utf16_at(data, base, adapter.FriendlyName)
        if adapter.IfType not in WINDOWS_NET_LEFT_OUT_TYPES and name:
            interfaces.append(
                {
                    "name": name,
                    "mac": _mac_of(adapter),
                    "addresses": _unicast_addresses(
                        data, base, adapter.FirstUnicastAddress
                    ),
                }
            )
        offset = _offset_of(adapter.Next, base, data) if adapter.Next else None
    return interfaces


def listener_pids_from(data: bytes, family: int, port: int) -> list:
    """The processes a ``GetExtendedTcpTable`` buffer shows listening on one port.

    Args:
        data: The buffer's bytes, an IPv4 or an IPv6 table of listeners
            with their owners.
        family: ``AF_INET`` or ``AF_INET6``, which table it is.
        port: The port.

    Returns:
        The owners' pids, each once, in the table's order.

    Raises:
        ValueError: When the buffer is shorter than its rows, or the family
            is neither.
    """
    if family == win32.AF_INET:
        row_type = win32.MibTcpRowOwnerPid
    elif family == win32.AF_INET6:
        row_type = win32.MibTcp6RowOwnerPid
    else:
        raise ValueError(f"no socket table of family {family}")
    if len(data) < WINDOWS_NET_TABLE_HEAD_BYTES:
        raise ValueError("a socket table shorter than its count")
    (count,) = struct.unpack_from("<I", data, 0)
    row_size = ctypes.sizeof(row_type)
    if WINDOWS_NET_TABLE_HEAD_BYTES + count * row_size > len(data):
        raise ValueError(f"a socket table of {count} rows in {len(data)} bytes")
    pids = []
    for index in range(count):
        row = row_type.from_buffer_copy(
            data, WINDOWS_NET_TABLE_HEAD_BYTES + index * row_size
        )
        if row.dwState != WINDOWS_NET_TCP_STATE_LISTEN:
            continue
        if _network_port(row.dwLocalPort) == port and row.dwOwningPid not in pids:
            pids.append(row.dwOwningPid)
    return pids


def read_interfaces(iphlpapi=None) -> list:
    """Every adapter of this machine, as :func:`interfaces_from` reads them.

    Args:
        iphlpapi: The bound iphlpapi; None binds the real one.

    Returns:
        The interfaces; empty when Windows lists no adapter.

    Raises:
        OSError: When the adapters cannot be read.
        ValueError: When the buffer Windows filled cannot be read.
    """
    if iphlpapi is None:
        iphlpapi = win32.libraries().iphlpapi
    size = win32.DWORD(WINDOWS_NET_ADAPTERS_BYTES)
    for _attempt in range(WINDOWS_NET_ATTEMPTS):
        buffer = ctypes.create_string_buffer(size.value)
        status = iphlpapi.GetAdaptersAddresses(
            win32.AF_UNSPEC,
            WINDOWS_NET_ADAPTER_FLAGS,
            None,
            buffer,
            ctypes.byref(size),
        )
        if status == win32.NO_ERROR:
            return interfaces_from(buffer.raw, ctypes.addressof(buffer))
        if status == win32.ERROR_NO_DATA:
            return []
        if status != win32.ERROR_BUFFER_OVERFLOW:
            raise OSError(status, f"GetAdaptersAddresses answered {status}")
    raise OSError(win32.ERROR_BUFFER_OVERFLOW, "the adapters outgrew every buffer")


def read_listener_pids(port: int, iphlpapi=None) -> list:
    """The processes listening on one TCP port, on IPv4 and on IPv6.

    Args:
        port: The port.
        iphlpapi: The bound iphlpapi; None binds the real one.

    Returns:
        Their pids, each once, the IPv4 table's first.

    Raises:
        OSError: When a table cannot be read.
        ValueError: When a buffer Windows filled cannot be read.
    """
    if iphlpapi is None:
        iphlpapi = win32.libraries().iphlpapi
    pids = []
    for family in (win32.AF_INET, win32.AF_INET6):
        for pid in listener_pids_from(_tcp_table(iphlpapi, family), family, port):
            if pid not in pids:
                pids.append(pid)
    return pids


def _tcp_table(iphlpapi, family: int) -> bytes:
    """One family's listeners with their owners, the buffer grown until it fits."""
    size = win32.DWORD(0)
    for _attempt in range(WINDOWS_NET_ATTEMPTS):
        buffer = ctypes.create_string_buffer(max(size.value, 1))
        status = iphlpapi.GetExtendedTcpTable(
            buffer,
            ctypes.byref(size),
            False,
            family,
            win32.TCP_TABLE_OWNER_PID_LISTENER,
            0,
        )
        if status == win32.NO_ERROR:
            return buffer.raw
        if status != win32.ERROR_INSUFFICIENT_BUFFER:
            raise OSError(status, f"GetExtendedTcpTable answered {status}")
    raise OSError(win32.ERROR_INSUFFICIENT_BUFFER, "the sockets outgrew every buffer")


def _structure_at(kind, data: bytes, offset: int):
    """One structure copied out of the buffer at an offset."""
    if offset < 0 or offset + ctypes.sizeof(kind) > len(data):
        raise ValueError(f"a {kind.__name__} at {offset} does not fit {len(data)}")
    return kind.from_buffer_copy(data, offset)


def _offset_of(address: int, base: int, data: bytes) -> int:
    """Where a pointer lands in the buffer."""
    offset = address - base
    if offset < 0 or offset >= len(data):
        raise ValueError(f"a pointer {address:#x} outside the buffer at {base:#x}")
    return offset


def _mac_of(adapter: "win32.IpAdapterAddresses") -> str:
    """One adapter's MAC as the other platforms spell it, empty when none."""
    length = min(adapter.PhysicalAddressLength, len(adapter.PhysicalAddress))
    octets = bytes(adapter.PhysicalAddress)[:length]
    if not any(octets):
        return ""
    return ":".join(f"{octet:02x}" for octet in octets)


def _unicast_addresses(data: bytes, base: int, first: int) -> list:
    """The addresses on one adapter's unicast list, without zone or prefix."""
    addresses = []
    address = first
    seen = set()
    while address:
        offset = _offset_of(address, base, data)
        if offset in seen:
            raise ValueError(f"the unicast addresses loop at {offset}")
        seen.add(offset)
        entry = _structure_at(win32.IpAdapterUnicastAddress, data, offset)
        text = _sockaddr_text(data, base, entry.Address.lpSockaddr)
        if text:
            addresses.append(text)
        address = entry.Next
    return addresses


def _sockaddr_text(data: bytes, base: int, address: int) -> str:
    """One socket address's IP, empty for a family that is neither."""
    if not address:
        return ""
    offset = _offset_of(address, base, data)
    if offset + 2 > len(data):
        raise ValueError(f"a socket address at {offset} does not fit")
    (family,) = struct.unpack_from(WINDOWS_NET_SOCKADDR_FAMILY_FORMAT, data, offset)
    if family == win32.AF_INET:
        start, length, kind = WINDOWS_NET_IPV4_AT, 4, ipaddress.IPv4Address
    elif family == win32.AF_INET6:
        start, length, kind = WINDOWS_NET_IPV6_AT, 16, ipaddress.IPv6Address
    else:
        return ""
    octets = data[offset + start : offset + start + length]
    if len(octets) != length:
        raise ValueError(f"a socket address at {offset} does not fit")
    return str(kind(octets))


def _network_port(value: int) -> int:
    """A port a socket table keeps in network order in a DWORD's low half."""
    return ((value & 0xFF) << 8) | ((value >> 8) & 0xFF)
