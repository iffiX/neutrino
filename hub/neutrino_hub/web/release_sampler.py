"""Reading every module's publisher feeds once a day.

A publisher's new release is no write anybody makes on the hub, so nothing
else would list it. This reads every manifest's feeds through the fetcher,
every ``DEVICE_MODULE_RELEASES_INTERVAL_S``, into the module releases store the
version routes read (module_install.md, "Module versions"). A panel's start
reads only when the store lists no version or its last good read is that old,
and otherwise waits out what is left of it. A read that fails leaves the last
list.
"""

import logging
import threading

from neutrino_hub.modules.devices.constants import DEVICE_MODULE_RELEASES_INTERVAL_S
from neutrino_hub.modules.devices.module_releases import ModuleReleaseReader
from neutrino_hub.utils.source_fetch import SourceFetcher

LOGGER = logging.getLogger(__name__)


class PanelReleaseSampler:
    """Reads the module release feeds on a daemon thread."""

    def __init__(
        self,
        *,
        store,
        fetcher=None,
        interval_s: float = DEVICE_MODULE_RELEASES_INTERVAL_S,
    ):
        """
        Args:
            store: The :class:`ModuleReleaseStore` the read lands in.
            fetcher: The :class:`SourceFetcher` the feeds are read with; None
                makes one.
            interval_s: Seconds between reads.
        """
        self._store = store
        self._reader = ModuleReleaseReader(
            fetcher=fetcher if fetcher is not None else SourceFetcher(), store=store
        )
        self._interval_s = interval_s
        self._is_stopped = threading.Event()
        self._thread: "threading.Thread | None" = None

    def start(self) -> None:
        """Run the read loop on a daemon thread; a second start is a no-op."""
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._loop, name="panel_releases", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the loop; the read in flight finishes."""
        self._is_stopped.set()

    def read_once(self) -> bool:
        """Read every feed once.

        Returns:
            True when the store was written.
        """
        try:
            self._reader.read()
        except (OSError, ValueError) as error:
            LOGGER.warning("module releases not read: %s", error)
            return False
        return True

    def _loop(self) -> None:
        wait_s = self._store.seconds_until_due(self._interval_s)
        while not self._is_stopped.wait(wait_s):
            self.read_once()
            wait_s = self._interval_s
