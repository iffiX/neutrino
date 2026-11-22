"""The models a person loaded on each machine, loaded again whenever its Ollama lost them.

**Load** keeps a model in memory with ``keep_alive`` -1, and the hub keeps
its name in ``kept_models`` of the machine's ``ollama.json``. A server that
restarts, for a settings change, by a person's hand, after a crash or a
reboot, holds nothing in memory. The controller follows each machine whose
Ollama runs by its forward's address, reads its ``/api/ps`` when it is first
followed and every period after while it keeps a model, and loads each kept
model the answer does not list, one load per model at a time on a thread of
its own. A failed load is tried again after the retry time or at a press,
and a load that ends after its name was taken off unloads the model.

Not pure: holds threads and calls Ollama's API.
"""

import logging
import threading
import time

from neutrino_hub.modules.devices.constants import (
    DEVICE_OLLAMA_KEPT_READ_INTERVAL_S,
    DEVICE_OLLAMA_KEPT_RETRY_S,
    DEVICE_OLLAMA_LOAD_TIMEOUT_S,
)
from neutrino_hub.modules.devices.ollama_models import OllamaApiClient, model_names

LOGGER = logging.getLogger(__name__)


class OllamaKeptModelController:
    """The kept models of every followed machine, loaded again while its Ollama runs."""

    def __init__(
        self,
        *,
        kept_of,
        client_class=OllamaApiClient,
        period_s: float = DEVICE_OLLAMA_KEPT_READ_INTERVAL_S,
        retry_s: float = DEVICE_OLLAMA_KEPT_RETRY_S,
        clock=time.monotonic,
    ):
        """
        Args:
            kept_of: Called with a device id; returns the names the machine
                keeps in memory.
            client_class: Makes the client for an address.
            period_s: How often a followed machine that keeps a model is
                read again.
            retry_s: How long a failed load waits before a check tries it
                again.
            clock: The monotonic clock the retry is measured on.
        """
        self._kept_of = kept_of
        self._client_class = client_class
        self._period_s = period_s
        self._retry_s = retry_s
        self._clock = clock
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._is_stopped = threading.Event()
        self._thread: "threading.Thread | None" = None
        # The forward address of each machine whose Ollama runs, by device id.
        self._followed: dict = {}
        # The machines checked at the next settle.
        self._pending: set = set()
        # The ``(device id, name)`` of each load running now.
        self._loading: set = set()
        # When each ``(device id, name)`` load last failed.
        self._failed: dict = {}

    def follow(self, device_id: str, address: str) -> None:
        """Take one report's word on a machine's Ollama.

        Args:
            device_id: The machine.
            address: The hub's forward to its Ollama port while it runs;
                empty while it does not.
        """
        if not address:
            self.drop(device_id)
            return
        with self._lock:
            if self._followed.get(device_id) == address:
                return
            self._followed[device_id] = address
            self._pending.add(device_id)
        self._wake.set()

    def drop(self, device_id: str) -> None:
        """Check a machine no more: offline, left, or its Ollama not running.

        Args:
            device_id: The machine.
        """
        with self._lock:
            self._followed.pop(device_id, None)
            self._pending.discard(device_id)

    def forget_all(self) -> None:
        """Follow no machine: a new control connection to the transport holds no forward."""
        with self._lock:
            self._followed.clear()
            self._pending.clear()

    def load(self, device_id: str, address: str, name: str) -> None:
        """Load one model now, a **Load** press: an earlier failure is forgotten.

        Args:
            device_id: The machine.
            address: The hub's forward to its Ollama port.
            name: The model.
        """
        with self._lock:
            self._failed.pop((device_id, name), None)
        self._start(device_id, address, name)

    def loading(self, device_id: str) -> set:
        """The names one machine's loads hold now.

        Args:
            device_id: The machine.

        Returns:
            The names.
        """
        with self._lock:
            return {name for key, name in self._loading if key == device_id}

    def settle(self, *, is_tick: bool = False) -> dict:
        """Check the machines pending, and with ``is_tick`` every followed one.

        Args:
            is_tick: Whether this is the periodic check.

        Returns:
            Device id to the names a load started for, for each machine
            read; a machine that keeps no model is not read.
        """
        with self._lock:
            keys = set(self._pending) | (set(self._followed) if is_tick else set())
            self._pending.clear()
            asked = {key: self._followed[key] for key in keys if key in self._followed}
        started = {}
        for device_id, address in sorted(asked.items()):
            kept = self._kept(device_id)
            if not kept:
                continue
            try:
                in_memory = model_names(self._client_class(address).ps())
            except (ConnectionError, OSError, ValueError) as error:
                LOGGER.info("Ollama at %s was not read: %s", address, error)
                continue
            started[device_id] = [
                name
                for name in kept
                if name not in in_memory and self._start_due(device_id, address, name)
            ]
        return started

    def start(self) -> None:
        """Settle on a daemon thread from now on; a second start is a no-op."""
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._loop, name="ollama_kept_models", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the thread; the loads in flight finish."""
        self._is_stopped.set()
        self._wake.set()

    def _loop(self) -> None:
        """Settle at each wake, and check every followed machine once a period."""
        next_tick_at = time.monotonic() + self._period_s
        while not self._is_stopped.is_set():
            self._wake.wait(max(0.0, next_tick_at - time.monotonic()))
            self._wake.clear()
            if self._is_stopped.is_set():
                return
            is_tick = time.monotonic() >= next_tick_at
            if is_tick:
                next_tick_at = time.monotonic() + self._period_s
            try:
                self.settle(is_tick=is_tick)
            except Exception:  # noqa: BLE001 - the loop must outlive one settle
                LOGGER.exception("the kept Ollama models did not settle")

    def _kept(self, device_id: str) -> list:
        """The names one machine keeps, empty when they cannot be read."""
        try:
            kept = self._kept_of(device_id)
        except (OSError, ValueError) as error:
            LOGGER.info("device %s: kept models not read: %s", device_id, error)
            return []
        return [str(name) for name in kept or [] if isinstance(name, str) and name]

    def _start_due(self, device_id: str, address: str, name: str) -> bool:
        """Start a check's load unless its last failure is younger than the retry time."""
        with self._lock:
            failed_at = self._failed.get((device_id, name))
            if failed_at is not None and self._clock() - failed_at < self._retry_s:
                return False
        return self._start(device_id, address, name)

    def _start(self, device_id: str, address: str, name: str) -> bool:
        """Start one load on a thread of its own; False while one already runs."""
        with self._lock:
            if (device_id, name) in self._loading:
                return False
            self._loading.add((device_id, name))
        threading.Thread(
            target=self._run,
            args=(device_id, address, name),
            name=f"ollama_load_{device_id}",
            daemon=True,
        ).start()
        return True

    def _run(self, device_id: str, address: str, name: str) -> None:
        """Load one model to its end, keeping a failure, and unload it when no longer kept."""
        client = self._client_class(address, timeout_s=DEVICE_OLLAMA_LOAD_TIMEOUT_S)
        is_loaded = False
        try:
            client.keep(name)
            is_loaded = True
        except (KeyError, ConnectionError, OSError, ValueError) as error:
            LOGGER.info("device %s: %s was not loaded: %s", device_id, name, error)
        with self._lock:
            self._loading.discard((device_id, name))
            if is_loaded:
                self._failed.pop((device_id, name), None)
            else:
                self._failed[(device_id, name)] = self._clock()
        if is_loaded and name not in self._kept(device_id):
            try:
                client.unload(name)
            except (KeyError, ConnectionError, OSError) as error:
                LOGGER.info(
                    "device %s: %s was not unloaded: %s", device_id, name, error
                )
