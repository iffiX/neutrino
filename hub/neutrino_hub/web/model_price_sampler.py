"""Reading the models.dev price list once a day.

A vendor's new price is no write anybody makes on the hub, so this reads
the list at the panel's start when the copy in force is more than
``AI_PRICES_INTERVAL_S`` old, and every ``AI_PRICES_INTERVAL_S`` after, as
the hub's own connection (hub_components/ai.md, "Prices"). A read that
fails is tried again after ``AI_PRICES_RETRY_S``; a download the checks
refuse waits for the next day's read.
"""

import logging
import threading

from neutrino_hub.modules.ai.constants import AI_PRICES_INTERVAL_S, AI_PRICES_RETRY_S
from neutrino_hub.modules.ai.model_prices import (
    PRICES_FAILED,
    kept_providers,
    next_read_wait_s,
    prices_in_force,
    refresh_model_prices,
    seconds_until_due,
)
from neutrino_hub.modules.ai.vendors import load_vendors

LOGGER = logging.getLogger(__name__)


class PanelModelPriceSampler:
    """Reads the models.dev price list on a daemon thread."""

    def __init__(
        self,
        *,
        interval_s: float = AI_PRICES_INTERVAL_S,
        retry_s: float = AI_PRICES_RETRY_S,
        refresh=refresh_model_prices,
        fetched_at=None,
    ):
        """
        Args:
            interval_s: Seconds between reads.
            retry_s: Seconds before a failed read is tried again.
            refresh: Reads the list once, as :func:`refresh_model_prices`.
            fetched_at: Returns when the copy in force was made; None reads
                it from the copy in force.
        """
        self._interval_s = interval_s
        self._retry_s = retry_s
        self._refresh = refresh
        self._fetched_at = fetched_at or _fetched_at_in_force
        self._is_stopped = threading.Event()
        self._thread: "threading.Thread | None" = None

    def start(self) -> None:
        """Run the read loop on a daemon thread; a second start is a no-op."""
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._loop, name="model_prices", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the loop; the read in flight finishes."""
        self._is_stopped.set()

    def read_once(self) -> str:
        """Read the list once.

        Returns:
            ``written``, ``refused`` or ``failed``.
        """
        try:
            return self._refresh(providers=kept_providers(load_vendors()))
        except Exception:  # noqa: BLE001 - the loop must outlive one read
            LOGGER.exception("the price list read failed")
            return PRICES_FAILED

    def first_wait_s(self) -> float:
        """How long the panel's start waits before its first read.

        Returns:
            0 when the copy in force is the interval old, else what is left
            of the interval.
        """
        return seconds_until_due(self._fetched_at(), interval_s=self._interval_s)

    def _loop(self) -> None:
        wait_s = self.first_wait_s()
        while not self._is_stopped.wait(wait_s):
            wait_s = next_read_wait_s(
                self.read_once(), interval_s=self._interval_s, retry_s=self._retry_s
            )


def _fetched_at_in_force() -> str:
    """When the copy in force was made."""
    return prices_in_force()["fetched_at"]
