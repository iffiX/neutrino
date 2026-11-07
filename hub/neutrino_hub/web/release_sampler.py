"""Reading every module's publisher feeds once a day.

A publisher's new release is no write anybody makes on the hub, so nothing
else would list it. This reads every manifest's feeds through the fetcher,
every ``DEVICE_MODULE_RELEASES_INTERVAL_S``, into the module releases store the
version routes read (module_install.md, "Module versions"), each read waiting
``DEVICE_MODULE_RELEASES_WAIT_S`` for data at each wait. While a module with a
feed holds no list, the interval is ``DEVICE_MODULE_RELEASES_RETRY_S``. A
panel's start reads only when the store lists no version or its last good
read is the interval old, and otherwise waits out what is left of it. A read
that fails leaves the last list.
"""

import logging
import threading

from neutrino_hub.modules.devices.constants import (
    DEVICE_MODULE_RELEASES_INTERVAL_S,
    DEVICE_MODULE_RELEASES_RETRY_S,
    DEVICE_MODULE_RELEASES_WAIT_S,
)
from neutrino_hub.modules.devices.module_releases import (
    ModuleReleaseReader,
    modules_with_feeds,
)
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
        retry_s: float = DEVICE_MODULE_RELEASES_RETRY_S,
        feed_modules=modules_with_feeds,
    ):
        """
        Args:
            store: The :class:`ModuleReleaseStore` the read lands in.
            fetcher: The :class:`SourceFetcher` the feeds are read with; None
                makes one whose document reads wait
                ``DEVICE_MODULE_RELEASES_WAIT_S`` for data.
            interval_s: Seconds between reads.
            retry_s: Seconds between reads while a module with a feed holds
                no list.
            feed_modules: Returns the modules whose manifests name a feed.
        """
        self._store = store
        self._reader = ModuleReleaseReader(
            fetcher=(
                fetcher
                if fetcher is not None
                else SourceFetcher(document_wait_s=DEVICE_MODULE_RELEASES_WAIT_S)
            ),
            store=store,
        )
        self._interval_s = interval_s
        self._retry_s = retry_s
        self._feed_modules = feed_modules
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
        wait_s = self._store.seconds_until_due(self._interval_now())
        while not self._is_stopped.wait(wait_s):
            self.read_once()
            wait_s = self._interval_now()

    def _interval_now(self) -> float:
        """The hour while a module with a feed holds no list, else the day."""
        if self._store.modules_without_list(self._feed_modules()):
            return self._retry_s
        return self._interval_s
