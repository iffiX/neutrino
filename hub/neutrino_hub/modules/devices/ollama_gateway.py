"""The AI gateway's providers generated from each machine's Ollama.

One OpenAI-compatible provider per machine whose Ollama runs and lists at
least one model: its address the hub's forward to the machine's Ollama port,
its models the names ``/api/tags`` returns (hub_components/ai.md, "Every
machine's Ollama"). The table follows each machine by its reports, reads
``/api/tags`` through the forward on a thread of its own, and stores the
list under the state root, where every render of the gateway reads it.

Not pure: holds a thread, calls Ollama's API and writes the stored list.
"""

import logging
import threading
import time

from neutrino_hub.modules.cliproxyapi.ops import (
    read_ollama_providers,
    write_ollama_providers,
)
from neutrino_hub.modules.devices.constants import (
    DEVICE_OLLAMA_GATEWAY_READ_INTERVAL_S,
)
from neutrino_hub.modules.devices.ollama_models import OllamaApiClient

LOGGER = logging.getLogger(__name__)


class OllamaGatewayProviderTable:
    """The generated providers by device, kept in step with each machine's Ollama."""

    def __init__(
        self,
        *,
        on_change,
        client_class=OllamaApiClient,
        period_s: float = DEVICE_OLLAMA_GATEWAY_READ_INTERVAL_S,
    ):
        """
        Args:
            on_change: Called after the stored list changed.
            client_class: Makes the client for an address.
            period_s: How often every followed machine is read again.
        """
        self._on_change = on_change
        self._client_class = client_class
        self._period_s = period_s
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._is_stopped = threading.Event()
        self._thread: "threading.Thread | None" = None
        # The forward address of each machine whose Ollama runs, by device id.
        self._followed: dict = {}
        # The machines read at the next settle.
        self._pending: set = set()
        # The machines taken out at the next settle.
        self._dropped: set = set()
        # The providers served now, by device id. None until the stored list
        # is read.
        self._providers: "dict | None" = None
        # When the next periodic read is due, on the monotonic clock.
        self._next_tick_at = time.monotonic() + period_s

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
        """Take a machine's provider out: offline, left, or its Ollama not running.

        Args:
            device_id: The machine.
        """
        with self._lock:
            is_held = device_id in self._followed or device_id in self._load()
            self._followed.pop(device_id, None)
            self._pending.discard(device_id)
            if not is_held:
                return
            self._dropped.add(device_id)
        self._wake.set()

    def refresh(self, device_id: str) -> None:
        """Read a followed machine's models again: a pull landed or a model went.

        Args:
            device_id: The machine.
        """
        with self._lock:
            if device_id not in self._followed:
                return
            self._pending.add(device_id)
        self._wake.set()

    def forget_all(self) -> None:
        """Follow no machine and keep every provider: a new control connection to the transport.

        The first periodic read comes a whole period later.
        """
        with self._lock:
            self._followed.clear()
            self._pending.clear()
            self._next_tick_at = time.monotonic() + self._period_s

    def providers(self) -> list:
        """The providers served now.

        Returns:
            ``{device_id, address, models}`` per provider, by device id.
        """
        with self._lock:
            return [dict(self._load()[key]) for key in sorted(self._load())]

    def start(self) -> None:
        """Settle on a daemon thread from now on; a second start is a no-op."""
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._loop, name="ollama_gateway", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the thread; the settle in flight finishes."""
        self._is_stopped.set()
        self._wake.set()

    def settle(self, *, is_tick: bool = False) -> bool:
        """Read what is pending, take out what was dropped, and store a changed list.

        Args:
            is_tick: Whether this is the periodic read: every followed
                machine is read, and a stored provider no report followed is
                taken out.

        Returns:
            Whether the list changed.
        """
        with self._lock:
            providers = dict(self._load())
            for device_id in self._dropped:
                providers.pop(device_id, None)
            self._dropped.clear()
            if is_tick:
                providers = {
                    key: held
                    for key, held in providers.items()
                    if key in self._followed
                }
            reads = set(self._pending) | (set(self._followed) if is_tick else set())
            self._pending.clear()
            asked = {key: self._followed[key] for key in reads if key in self._followed}
        found = {key: self._models(address) for key, address in asked.items()}
        with self._lock:
            for device_id, models in found.items():
                address = asked[device_id]
                if self._followed.get(device_id) != address:
                    continue
                if models is None:
                    held = providers.get(device_id)
                    if held is not None:
                        providers[device_id] = dict(held, address=address)
                elif models:
                    providers[device_id] = {
                        "device_id": device_id,
                        "address": address,
                        "models": models,
                    }
                else:
                    providers.pop(device_id, None)
            if providers == self._load():
                return False
            stored = [dict(providers[key]) for key in sorted(providers)]
        write_ollama_providers(stored)
        with self._lock:
            self._providers = providers
        self._on_change()
        return True

    def _loop(self) -> None:
        """Settle at each wake, and read every followed machine once a period."""
        while not self._is_stopped.is_set():
            with self._lock:
                remaining = self._next_tick_at - time.monotonic()
            self._wake.wait(max(0.0, remaining))
            self._wake.clear()
            if self._is_stopped.is_set():
                return
            with self._lock:
                is_tick = time.monotonic() >= self._next_tick_at
                if is_tick:
                    self._next_tick_at = time.monotonic() + self._period_s
            try:
                self.settle(is_tick=is_tick)
            except Exception:  # noqa: BLE001 - the loop must outlive one settle
                LOGGER.exception("the gateway's Ollama providers did not settle")

    def _load(self) -> dict:
        """The providers served now, read from the stored list the first time.

        Call with the lock held.
        """
        if self._providers is None:
            self._providers = {
                held["device_id"]: held for held in read_ollama_providers()
            }
        return self._providers

    def _models(self, address: str) -> "list | None":
        """The names one machine's ``/api/tags`` lists, sorted; None when the read fails."""
        try:
            tags = self._client_class(address).tags()
        except (ConnectionError, OSError, ValueError) as error:
            LOGGER.info("Ollama at %s was not read: %s", address, error)
            return None
        names = set()
        for model in tags.get("models") or []:
            if isinstance(model, dict):
                name = str(model.get("name", "") or model.get("model", ""))
                if name:
                    names.add(name)
        return sorted(names)
