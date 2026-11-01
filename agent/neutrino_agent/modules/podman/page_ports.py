"""The loopback port each hub container's page is published at, kept in its module's record.

A hub container whose module has a page publishes its ``page_port`` on
``127.0.0.1`` at a port the agent picks the first time and keeps, so the
container's file stays the same across applies, and the module's forwarder
reads the same port. A port the system refuses after a boot is picked again
at the next render. The record is ``page_ports.json`` in the module's
directory under the state root, root-only: one port per container name.

Not pure: binds a socket and writes files.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import contextlib
import json
import os
import tempfile
import threading

from neutrino_agent.modules.podman.constants import (
    PODMAN_PAGE_PORT_BASE,
    PODMAN_PAGE_PORTS_NAME,
)
from neutrino_agent.modules.shared.loopback_port import is_port_refused, pick_port


def free_loopback_port(taken=()) -> int:
    """A TCP port nothing listens on at ``127.0.0.1`` now, below the dynamic ports.

    Args:
        taken: Ports kept for other containers, which may not listen yet.

    Returns:
        The first free port from ``PODMAN_PAGE_PORT_BASE`` up.

    Raises:
        OSError: When no port from there up is free.
    """
    return pick_port(PODMAN_PAGE_PORT_BASE, taken=taken)


class PodmanPagePortStore:
    """The picked page ports of every container module, one record per module."""

    def __init__(
        self,
        *,
        directory: str,
        pick=free_loopback_port,
        is_refused=is_port_refused,
        log=print,
    ):
        """
        Args:
            directory: The state root; each module's record is in its own
                directory under it.
            pick: Returns a free loopback port, given the ports kept already.
            is_refused: Answers whether the system refuses a port now.
            log: Called with the line of a port picked again.
        """
        self._directory = directory
        self._pick = pick
        self._is_refused = is_refused
        self._log = log
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
            held[name] = self._pick(self._kept_ports())
            self._write(module, held)
            return held[name]

    def rendered_port_for(self, module: str, name: str) -> int:
        """The port a render publishes one container's page at, picked again when refused.

        Args:
            module: The container module.
            name: The hub container.

        Returns:
            The kept port while the system accepts it, or a free one just
            picked and kept.

        Raises:
            OSError: When no port can be picked or the record cannot be
                written.
        """
        with self._lock:
            held = self.ports(module)
            kept = held.get(name, 0)
            if kept and not self._is_refused(kept):
                return kept
            held[name] = self._pick(self._kept_ports())
            self._write(module, held)
        if kept:
            self._log(
                f"podman: the system refuses port {kept} of {name}, "
                f"published at {held[name]} now"
            )
        return held[name]

    def refused_ports(self, module: str) -> list:
        """The ports one module keeps that the system refuses now.

        Args:
            module: The container module.

        Returns:
            The refused ports, in the record's order.
        """
        return [port for port in self.ports(module).values() if self._is_refused(port)]

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

    def _kept_ports(self) -> set:
        """Every port kept for a container of any module."""
        try:
            modules = os.listdir(self._directory)
        except OSError:
            return set()
        kept: set = set()
        for module in modules:
            kept.update(self.ports(module).values())
        return kept

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
