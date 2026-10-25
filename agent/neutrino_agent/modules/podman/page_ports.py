"""The loopback port each hub container's page is published at, kept in its module's record.

A hub container whose module has a page publishes its ``page_port`` on
``127.0.0.1`` at a port the agent picks the first time and keeps, so the
container's file stays the same across applies, and the module's forwarder
reads the same port. The record is ``page_ports.json`` in the module's
directory under the configuration root, root-only: one port per container
name.

Not pure: binds a socket and writes files.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import contextlib
import json
import os
import socket
import tempfile
import threading

from neutrino_agent.modules.podman.constants import (
    PODMAN_PAGE_ADDRESS,
    PODMAN_PAGE_PORTS_NAME,
)


def free_loopback_port() -> int:
    """A TCP port nothing listens on at ``127.0.0.1`` now.

    Returns:
        The port the system hands a socket bound to port 0.

    Raises:
        OSError: When no socket can be bound.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((PODMAN_PAGE_ADDRESS, 0))
        return int(probe.getsockname()[1])


class PodmanPagePortStore:
    """The picked page ports of every container module, one record per module."""

    def __init__(self, *, directory: str, pick=free_loopback_port):
        """
        Args:
            directory: The configuration root; each module's record is in
                its own directory under it.
            pick: Returns a free loopback port.
        """
        self._directory = directory
        self._pick = pick
        self._lock = threading.Lock()

    def ports(self, module: str) -> dict:
        """The ports one module's containers are published at.

        Args:
            module: The container module.

        Returns:
            Container name to its loopback port; empty when none is kept.
        """
        try:
            with open(self._path(module), "r", encoding="utf-8") as stream:
                held = json.load(stream)
        except (OSError, ValueError):
            return {}
        if not isinstance(held, dict):
            return {}
        return {
            str(name): int(port)
            for name, port in held.items()
            if isinstance(port, int) and 0 < port < 65536
        }

    def port_for(self, module: str, name: str) -> int:
        """The port one container's page is published at, picked the first time.

        Args:
            module: The container module.
            name: The hub container.

        Returns:
            The kept port, or a free one just picked and kept.

        Raises:
            OSError: When no port can be picked or the record cannot be
                written.
        """
        with self._lock:
            held = self.ports(module)
            if name in held:
                return held[name]
            held[name] = self._pick()
            self._write(module, held)
            return held[name]

    def remove(self, module: str) -> None:
        """Forget one module's ports, with its directory when nothing else is in it.

        Args:
            module: The container module.
        """
        with self._lock:
            with contextlib.suppress(OSError):
                os.unlink(self._path(module))
            with contextlib.suppress(OSError):
                os.rmdir(os.path.dirname(self._path(module)))

    def _write(self, module: str, held: dict) -> None:
        """Keep one module's ports whole, mode 0600, in a directory of mode 0700."""
        directory = os.path.dirname(self._path(module))
        os.makedirs(directory, mode=0o700, exist_ok=True)
        handle, temporary = tempfile.mkstemp(dir=directory, prefix=".page_ports_")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(held, stream, sort_keys=True)
            os.chmod(temporary, 0o600)
            os.replace(temporary, self._path(module))
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(temporary)
            raise

    def _path(self, module: str) -> str:
        return os.path.join(self._directory, module, PODMAN_PAGE_PORTS_NAME)
