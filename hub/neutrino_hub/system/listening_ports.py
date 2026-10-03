"""Which ports something on this box already holds.

Asked before a listener is configured, because a port two services want is
found otherwise only as the second one exiting: xray validates a configuration
without binding it, and systemd reports a Type=simple unit started at fork.
On macOS and Windows the sockets come from psutil.
"""

import socket
from pathlib import PurePath

import psutil

from neutrino_hub.platforms.detect import is_linux
from neutrino_hub.utils.subprocess_run import run


def _process_name(pid, names: dict) -> str:
    """A process's program name without its suffix, read once per pid."""
    if pid not in names:
        try:
            names[pid] = PurePath(psutil.Process(pid).name()).stem if pid else ""
        except (psutil.Error, OSError):
            names[pid] = ""
    return names[pid]


class ListeningPortReader:
    """Reads the box's listening sockets."""

    def ports(self, *, ignoring: str = "") -> set[int]:
        """Every port with a listening socket on it.

        Args:
            ignoring: A process name whose sockets do not count. Re-applying a
                configuration would otherwise trip over the listeners the
                service being configured already holds.

        Returns:
            The port numbers, TCP and UDP together. Empty when the sockets
            cannot be read, so an unreadable box refuses nothing.
        """
        if not is_linux():
            return self._system_ports(ignoring=ignoring)
        result = run(["ss", "-lntupH"], is_checked=False)
        held = set()
        for line in result.stdout.splitlines():
            fields = line.split()
            if len(fields) < 5:
                continue
            if ignoring and f'"{ignoring}"' in " ".join(fields[5:]):
                continue
            port = fields[4].rsplit(":", 1)[-1]
            if port.isdigit():
                held.add(int(port))
        return held

    def _system_ports(self, *, ignoring: str) -> set[int]:
        """The listening TCP ports and bound UDP ports psutil reports."""
        try:
            connections = psutil.net_connections(kind="inet")
        except (psutil.Error, OSError):
            return set()
        held = set()
        names: dict = {}
        for connection in connections:
            if not connection.laddr:
                continue
            is_tcp = connection.type == socket.SOCK_STREAM
            if is_tcp and connection.status != psutil.CONN_LISTEN:
                continue
            if not is_tcp and connection.raddr:
                continue
            if ignoring and _process_name(connection.pid, names) == ignoring:
                continue
            held.add(int(connection.laddr.port))
        return held
