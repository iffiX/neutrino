"""Watching the hub's own addresses so every peer holds the current set.

An uplink's lease renewed to another address, an overlay joined or left, a
name the overlay's daemon starts reporting: none of them is a write anybody
makes, so nothing else would tell the agents and the clients. This reads
:func:`channel_urls` every half minute and, when the set is not the one it
read last, runs the runtime's converge step, which pushes the state to every
live binding of both roles. Before each read it asks the runtime to converge
when an overlay's device moved, so the firewall follows an EasyTier console
bringing its network up, or an engine's unit started under a new cgroup, or
when the network's resolvers moved, so dnsmasq and xray follow an uplink's
lease; and it checks the routes the overlays installed. After each read it issues the panel's
certificate again when the names in it are no longer the set.
"""

import logging
import threading

from neutrino_hub.web import panel_tls
from neutrino_hub.web.channel_addresses import channel_urls
from neutrino_hub.web.constants import WEB_ADDRESS_SAMPLE_INTERVAL_S

LOGGER = logging.getLogger(__name__)


class PanelAddressSampler:
    """Samples the channel's address set and pushes the states when it moved."""

    def __init__(self, *, runtime, interval_s: float = WEB_ADDRESS_SAMPLE_INTERVAL_S):
        """
        Args:
            runtime: The shared runtime, for its network and its sessions.
            interval_s: Seconds between samples.
        """
        self._runtime = runtime
        self._interval_s = interval_s
        self._is_stopped = threading.Event()
        self._thread: "threading.Thread | None" = None
        # None until the first sample: a peer's first report is where the
        # set the panel started with is handed down.
        self._urls: "list | None" = None

    def start(self) -> None:
        """Run the sample loop on a daemon thread; a second start is a no-op."""
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._loop, name="panel_addresses", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the loop; the sample in flight finishes."""
        self._is_stopped.set()

    def sample_once(self) -> bool:
        """Read the address set once and converge when it moved.

        Returns:
            True when this sample differed from the one before it.
        """
        is_converged = (
            self._runtime.follow_overlay_devices()
            or self._runtime.follow_network_resolvers()
        )
        self._runtime.check_overlay_routes()
        urls = channel_urls(self._runtime)
        panel_tls.follow_addresses(urls)
        if self._urls is None:
            self._urls = urls
            return False
        if urls == self._urls:
            return False
        self._urls = urls
        LOGGER.info("channel addresses moved: %s", ", ".join(urls))
        if not is_converged:
            self._runtime.converge_network_blocking()
        return True

    def _loop(self) -> None:
        while not self._is_stopped.wait(self._interval_s):
            try:
                self.sample_once()
            except Exception:  # noqa: BLE001 - the sampler must outlive one read
                LOGGER.exception("address sample failed")
