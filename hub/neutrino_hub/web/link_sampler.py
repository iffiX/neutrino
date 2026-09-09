"""Watching the interfaces so the Network page does not have to ask.

A cable pulled out, a lease renewed, a radio losing signal: none of them is a
write anybody makes, so nothing else would tell the panel. This reads the same
live state the Network page's own view is built from, every few seconds, and
publishes ``links`` when the reading is not the one it read last.
"""

import logging
import threading

from neutrino_hub.web.constants import WEB_EVENT_LINKS, WEB_LINK_SAMPLE_INTERVAL_S

LOGGER = logging.getLogger(__name__)


def _link_reading(link) -> tuple:
    """One interface's live state, as the panel draws it."""
    return (
        link.name,
        link.kind,
        link.is_present,
        link.is_up,
        link.ipv4_address,
        link.mac_address,
        link.ssid,
        link.signal_percent,
        link.speed_mbps,
        link.is_ap_capable,
    )


class PanelLinkSampler:
    """Samples the live interface state and says when it moved."""

    def __init__(self, *, runtime, interval_s: float = WEB_LINK_SAMPLE_INTERVAL_S):
        """
        Args:
            runtime: The shared runtime, for its link reader and its event bus.
            interval_s: Seconds between samples.
        """
        self._runtime = runtime
        self._interval_s = interval_s
        self._is_stopped = threading.Event()
        self._thread: "threading.Thread | None" = None
        # None until the first sample, so starting the panel is not itself a
        # change anybody is told about.
        self._reading: "tuple | None" = None

    def start(self) -> None:
        """Run the sample loop on a daemon thread; a second start is a no-op."""
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._loop, name="panel_links", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the loop; the sample in flight finishes."""
        self._is_stopped.set()

    def sample_once(self) -> bool:
        """Read the interfaces once and publish when the reading moved.

        Returns:
            True when this sample differed from the one before it.
        """
        status = self._runtime.link_status()
        reading = (
            tuple(sorted(_link_reading(link) for link in status.all_links())),
            status.default_gateway(),
        )
        if self._reading is None:
            self._reading = reading
            return False
        if reading == self._reading:
            return False
        self._reading = reading
        self._runtime.events.publish(WEB_EVENT_LINKS)
        return True

    def _loop(self) -> None:
        while not self._is_stopped.wait(self._interval_s):
            try:
                self.sample_once()
            except Exception:  # noqa: BLE001 - the sampler must outlive one read
                LOGGER.exception("link sample failed")
