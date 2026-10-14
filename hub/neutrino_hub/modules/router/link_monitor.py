"""Watching the kernel for the changes the routing state depends on.

A link going up or down, an address or a lease arriving, a route or a rule
appearing or going: each is a moment the routing state can need applying
again. `ip monitor` prints each as it happens. A fingerprint of the fields
that matter tells a real change from the echo of the reconciler's own
idempotent writes.

Not pure: runs `ip`.
"""

import json
import subprocess
import threading

from neutrino_hub.modules.router.constants import (
    ROUTER_FAMILY_IPV6,
    ROUTER_FWMARK_TPROXY,
    ROUTER_MONITOR_COMMAND,
    ROUTER_ROUTE_TABLE,
)
from neutrino_hub.modules.router.interfaces import held_networks
from neutrino_hub.utils.subprocess_run import run


class RouterLinkMonitor:
    """Reports each line `ip monitor` prints, and when it stops."""

    def __init__(
        self,
        *,
        on_change,
        on_gone,
        command: tuple = ROUTER_MONITOR_COMMAND,
        popen=subprocess.Popen,
    ):
        """
        Args:
            on_change: Called with nothing for each line the monitor prints.
            on_gone: Called with nothing once the monitor exits.
            command: The monitor's command line.
            popen: Starts the process; a test passes its own.
        """
        self._on_change = on_change
        self._on_gone = on_gone
        self._command = command
        self._popen = popen
        self._process = None

    def start(self) -> None:
        """Start the monitor and a thread reading what it prints.

        Raises:
            OSError: When `ip` cannot be started.
        """
        self._process = self._popen(
            list(self._command),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        threading.Thread(
            target=self._read, name="router_link_monitor", daemon=True
        ).start()

    def stop(self) -> None:
        """Stop the monitor, when it is running."""
        if self._process is not None and self._process.poll() is None:
            self._process.terminate()

    def _read(self) -> None:
        for _ in self._process.stdout:
            self._on_change()
        self._on_gone()


def link_fingerprint() -> tuple:
    """The fields of the kernel's state the routing state depends on.

    Address lifetimes, signal strength and which IPv6 address an interface
    holds inside one network are left out, so a lease renewal, a replace
    that changed nothing or a temporary address replaced reads the same; a
    new IPv6 network does not, since an exposed segment's rules name it.

    Returns:
        A value equal before and after an event that changed none of them.
    """
    return (
        _links(),
        _addresses(),
        _default_routes(),
        _policy_table(),
        _policy_rule(),
    )


def _json(arguments: list) -> list:
    """What `ip -json` answers, or an empty list when it answers nothing."""
    result = run(["ip", "-json", *arguments], is_checked=False)
    if not result.is_success:
        return []
    try:
        return json.loads(result.stdout or "[]")
    except ValueError:
        return []


def _links() -> tuple:
    return tuple(
        sorted(
            (
                str(entry.get("ifname", "")),
                "UP" in entry.get("flags", []),
                "LOWER_UP" in entry.get("flags", []),
            )
            for entry in _json(["link", "show"])
        )
    )


def _addresses() -> tuple:
    found = set()
    for entry in _json(["addr", "show"]):
        name = str(entry.get("ifname", ""))
        for address in entry.get("addr_info", []):
            if address.get("family") == "inet":
                found.add(
                    (
                        name,
                        str(address.get("local", "")),
                        int(address.get("prefixlen", 0)),
                        bool(address.get("dynamic")),
                    )
                )
            elif address.get("family") == "inet6":
                held = f"{address.get('local', '')}/{address.get('prefixlen', 128)}"
                for network in held_networks([held], ROUTER_FAMILY_IPV6, is_link=True):
                    found.add((name, network, 0, False))
    return tuple(sorted(found))


def _default_routes() -> tuple:
    found = []
    for route in _json(["route", "show", "default"]):
        hops = tuple(
            sorted(
                (str(hop.get("dev", "")), str(hop.get("gateway", "")))
                for hop in route.get("nexthops", [])
            )
        )
        found.append(
            (
                str(route.get("dev", "")),
                str(route.get("gateway", "")),
                int(route.get("metric", 0)),
                hops,
            )
        )
    return tuple(sorted(found))


def _policy_table() -> tuple:
    return tuple(
        sorted(
            (
                str(route.get("dst", "")),
                str(route.get("dev", "")),
                str(route.get("type", "")),
            )
            for route in _json(["route", "show", "table", str(ROUTER_ROUTE_TABLE)])
        )
    )


def _policy_rule() -> bool:
    mark = hex(ROUTER_FWMARK_TPROXY)
    return any(
        str(rule.get("fwmark", "")) == mark
        and str(rule.get("table", "")) == str(ROUTER_ROUTE_TABLE)
        for rule in _json(["rule", "show"])
    )
