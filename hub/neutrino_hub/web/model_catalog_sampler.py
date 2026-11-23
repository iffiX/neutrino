"""Reading the gateway's model catalog into the stored read.

The gateway downloads a new catalog every 3 hours, and an account's names
change with the account, so this reads the catalog at the panel's start once
the gateway serves, at each wake (a change of the served list, an account
signed in or removed) and every ``CLIPROXYAPI_CATALOG_INTERVAL_S``
(hub_components/ai.md, "A cloud name's length"). Until a read after the
panel's start succeeds, it tries again every ``CLIPROXYAPI_CATALOG_RETRY_S``.
"""

import logging
import threading

from neutrino_hub.modules.cliproxyapi.constants import (
    CLIPROXYAPI_CATALOG_INTERVAL_S,
    CLIPROXYAPI_CATALOG_RETRY_S,
)
from neutrino_hub.modules.cliproxyapi.management_key import read_management_key
from neutrino_hub.modules.cliproxyapi.model_catalog import refresh_model_catalog
from neutrino_hub.modules.cliproxyapi.ops import load_config

LOGGER = logging.getLogger(__name__)


class PanelModelCatalogSampler:
    """Reads the gateway's model catalog on a daemon thread."""

    def __init__(
        self,
        *,
        on_change,
        interval_s: float = CLIPROXYAPI_CATALOG_INTERVAL_S,
        retry_s: float = CLIPROXYAPI_CATALOG_RETRY_S,
        refresh=refresh_model_catalog,
    ):
        """
        Args:
            on_change: Called with nothing after a read changed the stored
                read.
            interval_s: Seconds between reads.
            retry_s: Seconds between reads until one succeeds after the
                start.
            refresh: Reads the catalog, as :func:`refresh_model_catalog`.
        """
        self._on_change = on_change
        self._interval_s = interval_s
        self._retry_s = retry_s
        self._refresh = refresh
        self._wake = threading.Event()
        self._is_stopped = threading.Event()
        self._thread: "threading.Thread | None" = None

    def start(self) -> None:
        """Run the read loop on a daemon thread; a second start is a no-op."""
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._loop, name="model_catalog", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the loop; the read in flight finishes."""
        self._is_stopped.set()
        self._wake.set()

    def wake(self) -> None:
        """Read the catalog now: the served list changed, or an account was signed in or removed."""
        self._wake.set()

    def read_once(self) -> "bool | None":
        """Read the catalog once.

        Returns:
            Whether the stored read changed; None when the read failed or
            the gateway was not asked, for a box with no management key.
        """
        management_key = read_management_key()
        if not management_key:
            return None
        try:
            port = load_config().listen_port
        except ValueError:
            return None
        is_changed = self._refresh(port=port, management_key=management_key)
        if is_changed:
            self._on_change()
        return is_changed

    def _loop(self) -> None:
        is_read = False
        while not self._is_stopped.is_set():
            try:
                result = self.read_once()
            except Exception:  # noqa: BLE001 - the loop must outlive one read
                LOGGER.exception("the gateway's model catalog read failed")
                result = None
            is_read = is_read or result is not None
            self._wake.wait(self._interval_s if is_read else self._retry_s)
            self._wake.clear()
