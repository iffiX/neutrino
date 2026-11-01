"""Which ports something on this box already holds.

Asked before a listener is configured, because a port two services want is
found otherwise only as the second one exiting: xray validates a configuration
without binding it, and systemd reports a Type=simple unit started at fork.
On macOS and Windows the sockets come from psutil.
"""

import socket

import psutil

from neutrino_hub.platforms.detect import is_linux
from neutrino_hub.utils.subprocess_run import run


class ListeningPortReader:
    """Reads the box's listening sockets."""

    def ports(self) -> set[int]:
        """Every port with a listening socket on it.

        Returns:
            The port numbers, TCP and UDP together. Empty when the sockets
            cannot be read, so an unreadable box refuses nothing.
        """
        if not is_linux():
            return self._system_ports()
        result = run(["ss", "-lntupH"], is_checked=False)
        held = set()
        for line in result.stdout.splitlines():
            fields = line.split()
            if len(fields) < 5:
                continue
            port = fields[4].rsplit(":", 1)[-1]
            if port.isdigit():
                held.add(int(port))
        return held

    def _system_ports(self) -> set[int]:
        """The listening TCP ports and bound UDP ports psutil reports."""
        try:
            connections = psutil.net_connections(kind="inet")
        except (psutil.Error, OSError):
            return set()
        held = set()
        for connection in connections:
            if not connection.laddr:
                continue
            is_tcp = connection.type == socket.SOCK_STREAM
            if is_tcp and connection.status != psutil.CONN_LISTEN:
                continue
            if not is_tcp and connection.raddr:
                continue
            held.add(int(connection.laddr.port))
        return held
