"""Counting a port's established connections in what netstat printed.

Windows and macOS both list their connections with ``netstat -an``; the two
differ only in how an address is joined to its port.
"""


def established_count(
    printed: str, port: int, *, established: str, separator: str
) -> int:
    """How many established rows of a netstat table land on one local port.

    Args:
        printed: What netstat printed: local address, foreign address and
            state are the last three fields of each row.
        port: The local port.
        established: How this netstat spells an established connection.
        separator: What comes between an address and its port: ``:`` on
            Windows, ``.`` on a Mac.

    Returns:
        The number of rows.
    """
    total = 0
    for row in printed.splitlines():
        fields = row.split()
        if len(fields) < 4 or fields[-1] != established:
            continue
        _, _, local_port = fields[-3].rpartition(separator)
        if local_port == str(port):
            total += 1
    return total
