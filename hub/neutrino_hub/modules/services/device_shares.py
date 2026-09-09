"""The desktop shares managed machines have declared.

A machine's own agent is the only thing that can declare one: the panel's
form offers no rdp type and no hub module publishes one. A declaration
arrives on the heartbeat, lives here in memory, and is composed into the
published list like any other entry.

**A share is only ever as true as the last beat that said so.** Nothing is
written to ``config/``: a machine that stops sharing drops its declaration
on its next beat, one that goes quiet ages out of the list, and a hub
restart forgets every share until each machine says it again — which the
next beat does.

Not pure only in that it holds state; it touches nothing outside itself.
"""

import threading
import time
from dataclasses import dataclass

from neutrino_hub.modules.devices.constants import DEVICE_AGENT_ONLINE_WINDOW_S


@dataclass
class DeviceShare:
    """One machine's word that its desktop is reachable.

    Attributes:
        share_id: What the declaring machine calls this share; the entry id
            is built from it, so the machine can tell its own entry from
            the rest of the fleet's.
        mac_address: The machine that declared it.
        hostname: What the machine calls itself, for the entry's title.
        host: The address the hub reaches that machine on.
        port: The port a direct connection lands on.
        attention: What somebody must do at the sharing machine before a
            peer is shown its desktop, as a typed code; empty when nothing
            stands in the way. A machine about to dial says this rather
            than waiting in "connecting" for a dialog it cannot see.
        declared_at: When the declaring beat arrived, on the monotonic
            clock; a share older than the online window is gone.
        account: Whose desktop is shared, as the machine named it.
        connected_count: How many viewers the machine has right now.
    """

    share_id: str
    mac_address: str
    hostname: str
    host: str
    port: int
    declared_at: float
    attention: str = ""
    account: str = ""
    connected_count: int = 0


class DeviceShareRegistry:
    """Holds what each machine last said about sharing its desktop."""

    def __init__(self, *, window_s: float = DEVICE_AGENT_ONLINE_WINDOW_S):
        """
        Args:
            window_s: How long a declaration outlives the beat that made
                it. A machine that goes offline stops answering, so its
                share disappears rather than standing for ever.
        """
        self._window_s = window_s
        self._lock = threading.Lock()
        self._shares: dict = {}

    def declare(
        self,
        *,
        mac_address: str,
        share_id: str,
        hostname: str,
        host: str,
        port: int,
        attention: str = "",
        account: str = "",
        connected_count: int = 0,
        now: "float | None" = None,
    ) -> None:
        """Record that one machine is sharing its desktop.

        Args:
            mac_address: The machine.
            share_id: What the machine calls this share.
            hostname: What the machine calls itself.
            host: The address the hub reaches it on.
            port: The port a direct connection lands on.
            attention: What somebody must do at that machine before a peer
                is shown its desktop; empty when nothing stands in the way.
            account: Whose desktop is shared.
            connected_count: How many viewers the machine has right now.
            now: The monotonic reading to stamp with; None reads the clock.
        """
        key = (mac_address or "").lower()
        if not key or not share_id or not host:
            return
        with self._lock:
            self._shares[key] = DeviceShare(
                share_id=str(share_id),
                mac_address=key,
                hostname=str(hostname),
                host=str(host),
                port=int(port),
                attention=str(attention or ""),
                account=str(account or ""),
                connected_count=int(connected_count or 0),
                declared_at=time.monotonic() if now is None else now,
            )

    def withdraw(self, mac_address: str) -> None:
        """Forget one machine's share, because it stopped sharing.

        Args:
            mac_address: The machine.
        """
        with self._lock:
            self._shares.pop((mac_address or "").lower(), None)

    def live(self, *, now: "float | None" = None) -> list:
        """Every share still standing, oldest declaration first.

        Args:
            now: The monotonic reading to judge against; None reads the
                clock.

        Returns:
            The live shares. One whose machine has not beaten within the
            online window is dropped here rather than shown as reachable.
        """
        reading = time.monotonic() if now is None else now
        with self._lock:
            live = [
                share
                for share in self._shares.values()
                if reading - share.declared_at <= self._window_s
            ]
        return sorted(live, key=lambda share: (share.hostname, share.share_id))

    def fingerprint(self, *, now: "float | None" = None) -> tuple:
        """What changes whenever the live set changes.

        Args:
            now: The monotonic reading to judge against.

        Returns:
            A tuple the published cache folds into its own stamp, so a
            share appearing or ageing out recomposes the list.
        """
        return tuple(
            (share.share_id, share.mac_address, share.host, share.port)
            for share in self.live(now=now)
        )
