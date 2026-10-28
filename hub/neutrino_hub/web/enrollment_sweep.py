"""Removing the client rows whose link expired before anybody joined.

A client row is made with its link and waits to join while the link works.
A link that expires unused is no write anybody makes, so this removes its
row once every ``ENROLLMENT_SWEEP_INTERVAL_S`` and tells the Clients page
(protocol.md, ``/api/hub/client``).
"""

import logging
import threading
import time

from neutrino_hub.modules.channel.constants import ENROLLMENT_SWEEP_INTERVAL_S
from neutrino_hub.modules.clients.registry import ClientRegistry
from neutrino_hub.web.constants import WEB_EVENT_CLIENTS

LOGGER = logging.getLogger(__name__)


class PanelEnrollmentSweeper:
    """Removes the expired waiting client rows on a daemon thread."""

    def __init__(self, *, events, interval_s: float = ENROLLMENT_SWEEP_INTERVAL_S):
        """
        Args:
            events: The event bus the Clients page listens on.
            interval_s: Seconds between sweeps.
        """
        self._events = events
        self._interval_s = interval_s
        self._is_stopped = threading.Event()
        self._thread: "threading.Thread | None" = None

    def start(self) -> None:
        """Run the sweep loop on a daemon thread; a second start is a no-op."""
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._loop, name="panel_enrollment_sweep", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the loop; the sweep in flight finishes."""
        self._is_stopped.set()

    def sweep_once(self, now: "float | None" = None) -> list:
        """Remove every waiting client row whose link expired.

        Args:
            now: The time in Unix seconds; None reads the clock.

        Returns:
            The removed clients' ids.
        """
        try:
            removed = ClientRegistry().sweep_waiting(
                time.time() if now is None else now
            )
        except (OSError, ValueError) as error:
            LOGGER.warning("waiting clients not swept: %s", error)
            return []
        if removed:
            LOGGER.info(
                "clients: %d waiting row(s) removed with their link", len(removed)
            )
            self._events.publish(WEB_EVENT_CLIENTS)
        return removed

    def _loop(self) -> None:
        while not self._is_stopped.wait(self._interval_s):
            self.sweep_once()
