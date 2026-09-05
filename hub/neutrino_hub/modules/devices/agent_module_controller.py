"""Turning cached bytes into an install on one managed machine.

One queue per device and one order in flight, because a machine's package
manager holds a machine-wide lock and two installs racing is a failure with
no useful diagnosis. Every request enters here — the panel's drawer and the
machine's own page alike — so the two surfaces cannot behave differently and
cannot overlap.

**Retry is a person's word, never a timer's.** Nothing in this file re-runs a
failed order: a vendor refusing now refuses in a minute, and a machine that
retries every minute spends the night doing it. Asking again is a new order,
and it runs. A failure clears without being asked in exactly two cases, both
meaning the question is settled: the software turning up on the machine
anyway, and an order for the opposite action. Orders and failures live here
in memory and nowhere else; a hub restart forgets them and a person asks
again.

Not pure: fetches through the cache and holds the device's install lock.
"""

import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

from neutrino_hub.modules.devices.agent_module_cache import (
    AgentModuleFetchError,
    resolve_platform_entry,
)
from neutrino_hub.modules.devices.constants import (
    AGENT_MODULE_ORDER_HISTORY,
    AGENT_MODULE_ORDER_TIMEOUT_S,
)

# What an order can be. The hub owns the first three; the machine's own
# report closes it into one of the last two.
ORDER_QUEUED = "queued"
ORDER_FETCHING = "fetching"
ORDER_INSTALLING = "installing"
ORDER_DONE = "done"
ORDER_FAILED = "failed"

ORDER_OPEN_STATES = (ORDER_QUEUED, ORDER_FETCHING, ORDER_INSTALLING)

# The actions an order can name. Only an install with an artifact fetches;
# a distro package or a platform capability installs by name.
ORDER_ACTION_INSTALL = "install"
ORDER_ACTION_UNINSTALL = "uninstall"

ORDER_ACTIONS = (
    ORDER_ACTION_INSTALL,
    ORDER_ACTION_UNINSTALL,
)

# What the machine reporting these means. A standing failure for a module
# reading present is cleared, because somebody installing it by hand settles
# the question the failure was asking.
ORDER_PRESENT_STATES = ("installed",)
ORDER_ABSENT_STATES = ("absent",)


def _stamp() -> str:
    """Now, as the panel writes every other timestamp."""
    return datetime.now(timezone.utc).isoformat()


@dataclass
class AgentModuleOrder:
    """One thing to do to one module on one machine.

    Attributes:
        id: What both sides address it by.
        mac_address: The device.
        module: The module name.
        action: One of :data:`ORDER_ACTIONS`.
        state: Where the order stands.
        code: Why it failed, when it did.
        params: What the wording names.
        output: What the failing step printed.
        artifact_key: What the agent asks the hub for the bytes by; empty
            for an action that needs none.
        digest: The artifact's SHA-256, which the agent checks.
        package_kind: The kind the manifest names.
        asked_at: When a person asked.
        finished_at: When it closed.
    """

    id: str
    mac_address: str
    module: str
    action: str
    state: str = ORDER_QUEUED
    code: str = ""
    params: dict = field(default_factory=dict)
    output: str = ""
    artifact_key: str = ""
    digest: str = ""
    package_kind: str = ""
    asked_at: str = field(default_factory=_stamp)
    finished_at: str = ""
    # What the fetch needs, and what the panel never sees.
    manifest: dict = field(default_factory=dict, repr=False)
    platform: dict = field(default_factory=dict, repr=False)

    @property
    def is_open(self) -> bool:
        """Whether the order is still going."""
        return self.state in ORDER_OPEN_STATES

    def to_wire(self) -> dict:
        """What the heartbeat hands the machine.

        Returns:
            The order, named the way the agent reads it: what module, what
            to do, and how to get the bytes.
        """
        return {
            "id": self.id,
            "module": self.module,
            "action": self.action,
            "artifact_key": self.artifact_key,
            "digest": self.digest,
            "package_kind": self.package_kind,
        }

    def to_view(self) -> dict:
        """What the panel's install pane shows.

        Returns:
            The order without the manifest it was resolved from.
        """
        return {
            "id": self.id,
            "module": self.module,
            "action": self.action,
            "state": self.state,
            "code": self.code,
            "params": dict(self.params),
            "output": self.output,
            "asked_at": self.asked_at,
            "finished_at": self.finished_at,
        }


class AgentModuleController:
    """The one door every module install on every managed machine goes through."""

    def __init__(
        self, *, cache, locks, timeout_s: float = AGENT_MODULE_ORDER_TIMEOUT_S
    ):
        """
        Args:
            cache: The :class:`AgentModuleCache` that resolves bytes.
            locks: The :class:`DeviceInstallLocks` registry; an order takes
                its device's lock, which the SSH bootstrap takes too.
            timeout_s: How long one handed-down order may stand before the
                controller stops waiting for the machine's word.
        """
        self._cache = cache
        self._locks = locks
        self._timeout_s = timeout_s
        self._guard = threading.Lock()
        self._queues: dict = {}
        self._history: dict = {}
        self._orders: dict = {}
        self._handed: dict = {}
        self._failures: dict = {}
        self._workers: dict = {}
        self._closed: dict = {}

    def ask(
        self,
        *,
        mac_address: str,
        module: str,
        manifest: dict,
        platform: dict,
        action: str,
        reported_state: str = "",
    ) -> "AgentModuleOrder | None":
        """Ask for something to be done to one module on one machine.

        A person asking is always a fresh start: whatever the last order
        left behind is cleared before this one is judged, which is what
        makes pressing the button again work after a failure.

        Args:
            mac_address: The device.
            module: The module name.
            manifest: Its manifest.
            platform: The tuple the agent reported.
            action: One of :data:`ORDER_ACTIONS`.
            reported_state: What the machine last said about this module, so
                an uninstall of something absent asks nothing of it.

        Returns:
            The queued order, or None when the machine is already the way
            the asker wants it.

        Raises:
            ValueError: For an action that is not one of the two.
        """
        if action not in ORDER_ACTIONS:
            raise ValueError(f"unknown order action {action!r}")
        key = (mac_address or "").lower()
        # The person has spoken again, so the last attempt's verdict is no
        # longer the answer to anything anybody is asking.
        self.clear_failure(key, module)
        if action == ORDER_ACTION_UNINSTALL and reported_state in ORDER_ABSENT_STATES:
            return None
        order = AgentModuleOrder(
            id=uuid4().hex,
            mac_address=key,
            module=module,
            action=action,
            manifest=dict(manifest),
            platform=dict(platform),
        )
        with self._guard:
            self._orders[order.id] = order
            self._queues.setdefault(key, deque()).append(order.id)
            self._history.setdefault(key, []).append(order.id)
            self._trim(key)
        self._ensure_worker(key)
        return order

    def pending_order(self, mac_address: str) -> "AgentModuleOrder | None":
        """The order this device should be working on now.

        Handed down on every beat until the machine reports how it went: a
        repeat of the order already in flight is one the agent ignores, and
        a beat lost in the wire is not an order lost.

        Args:
            mac_address: The device.

        Returns:
            The order, or None when nothing is in flight for it.
        """
        with self._guard:
            order_id = self._handed.get((mac_address or "").lower(), "")
            order = self._orders.get(order_id)
            return order if order is not None and order.is_open else None

    def record_result(
        self,
        *,
        mac_address: str,
        order_id: str,
        state: str,
        code: str = "",
        params: "dict | None" = None,
        output: str = "",
    ) -> bool:
        """Close one order with the machine's own word for how it went.

        Args:
            mac_address: The device.
            order_id: Which order the agent ran.
            state: ``done`` or ``failed``.
            code: Why it failed.
            params: What the wording names.
            output: What the failing step printed.

        Returns:
            True when this closed an order the controller was waiting on.
        """
        key = (mac_address or "").lower()
        with self._guard:
            order = self._orders.get(order_id)
            if order is None or order.mac_address != key or not order.is_open:
                return False
            order.state = ORDER_FAILED if state == ORDER_FAILED else ORDER_DONE
            order.code = code
            order.params = dict(params or {})
            order.output = output
            order.finished_at = _stamp()
            if order.state == ORDER_FAILED:
                self._failures[(key, order.module)] = order.id
            else:
                self._failures.pop((key, order.module), None)
            event = self._closed.get(order.id)
        if event is not None:
            event.set()
        return True

    def note_reported_states(self, mac_address: str, states: dict) -> None:
        """Let what the machine reports settle a standing failure.

        Software turning up on the machine anyway — somebody installed it by
        hand — is an answer to the question the failure was asking, so the
        failure goes without anybody clearing it.

        Args:
            mac_address: The device.
            states: What the beat reported, module to its status.
        """
        key = (mac_address or "").lower()
        for module, status in (states or {}).items():
            if not isinstance(status, dict):
                continue
            if status.get("state") in ORDER_PRESENT_STATES:
                self.clear_failure(key, module)

    def order_in_flight(self, mac_address: str, module: str) -> bool:
        """Whether this module already has an order that has not finished.

        Args:
            mac_address: The device.
            module: The module name.

        Returns:
            True while one is queued or running, so nothing asks twice.
        """
        key = (mac_address or "").lower()
        with self._guard:
            return any(
                order.mac_address == key
                and order.module == module
                and order.state in ORDER_OPEN_STATES
                for order in self._orders.values()
            )

    def clear_failure(self, mac_address: str, module: str) -> None:
        """Forget the failure standing against one module on one machine.

        Args:
            mac_address: The device.
            module: The module name.
        """
        with self._guard:
            self._failures.pop(((mac_address or "").lower(), module), None)

    def failure_for(self, mac_address: str, module: str) -> "AgentModuleOrder | None":
        """The failed order standing against one module, if one is.

        Args:
            mac_address: The device.
            module: The module name.

        Returns:
            The order, or None.
        """
        with self._guard:
            order_id = self._failures.get(((mac_address or "").lower(), module), "")
            return self._orders.get(order_id)

    def orders(self, mac_address: str) -> list:
        """Every order this device still keeps, newest first.

        Args:
            mac_address: The device.

        Returns:
            The orders, for the panel's one install pane.
        """
        with self._guard:
            order_ids = list(self._history.get((mac_address or "").lower(), []))
            return [
                self._orders[order_id]
                for order_id in reversed(order_ids)
                if order_id in self._orders
            ]

    def open_order_for(
        self, mac_address: str, module: str
    ) -> "AgentModuleOrder | None":
        """The order still going for one module, if there is one.

        Args:
            mac_address: The device.
            module: The module name.

        Returns:
            The order, or None.
        """
        key = (mac_address or "").lower()
        with self._guard:
            for order_id in reversed(self._history.get(key, [])):
                order = self._orders.get(order_id)
                if order is not None and order.module == module and order.is_open:
                    return order
        return None

    def forget(self, mac_address: str) -> None:
        """Drop everything held for a device the hub no longer manages.

        Args:
            mac_address: The device.
        """
        key = (mac_address or "").lower()
        with self._guard:
            for order_id in self._history.pop(key, []):
                self._orders.pop(order_id, None)
                self._closed.pop(order_id, None)
            self._queues.pop(key, None)
            self._handed.pop(key, None)
            self._failures = {
                pair: value for pair, value in self._failures.items() if pair[0] != key
            }

    def _trim(self, key: str) -> None:
        """Keep a device's history to the recent few. Call under the guard."""
        history = self._history.get(key, [])
        while len(history) > AGENT_MODULE_ORDER_HISTORY:
            dropped = history.pop(0)
            order = self._orders.get(dropped)
            if order is not None and order.is_open:
                history.insert(0, dropped)
                return
            self._orders.pop(dropped, None)
            self._closed.pop(dropped, None)

    def _ensure_worker(self, key: str) -> None:
        """Start this device's worker if it is not already running."""
        with self._guard:
            worker = self._workers.get(key)
            if worker is not None and worker.is_alive():
                return
            worker = threading.Thread(
                target=self._run, args=(key,), name=f"module_orders_{key}", daemon=True
            )
            self._workers[key] = worker
        worker.start()

    def _run(self, key: str) -> None:
        """Work one device's queue, one order at a time, until it drains."""
        while True:
            with self._guard:
                queue = self._queues.get(key)
                if not queue:
                    self._workers.pop(key, None)
                    return
                order = self._orders.get(queue.popleft())
            if order is None or not order.is_open:
                continue
            # The device's own lock, which the SSH bootstrap takes too: two
            # things installing on one machine is the failure this prevents.
            with self._locks.hold(key):
                self._run_one(order)

    def _run_one(self, order: AgentModuleOrder) -> None:
        """Fetch what an order needs, hand it down, and wait for the answer."""
        if (
            order.action == ORDER_ACTION_INSTALL
            and _names_download(order)
            and not self._fetch(order)
        ):
            return
        event = threading.Event()
        with self._guard:
            order.state = ORDER_INSTALLING
            self._closed[order.id] = event
            self._handed[order.mac_address] = order.id
        # The machine does the install and reports back on a later beat; a
        # machine that goes away mid-order must not hold its lock for ever.
        if not event.wait(timeout=self._timeout_s):
            self.record_result(
                mac_address=order.mac_address,
                order_id=order.id,
                state=ORDER_FAILED,
                code="agent_never_reported",
                params={"module": order.module},
            )
        with self._guard:
            self._closed.pop(order.id, None)
            if self._handed.get(order.mac_address) == order.id:
                self._handed.pop(order.mac_address, None)

    def _fetch(self, order: AgentModuleOrder) -> bool:
        """Put the order's bytes in the cache.

        Args:
            order: The order being run.

        Returns:
            True when the bytes are there; False having failed the order.
        """
        with self._guard:
            order.state = ORDER_FETCHING
        try:
            artifact = self._cache.artifact(
                name=order.module, manifest=order.manifest, platform=order.platform
            )
        except AgentModuleFetchError as error:
            self.record_result(
                mac_address=order.mac_address,
                order_id=order.id,
                state=ORDER_FAILED,
                code=error.code,
                params=dict(error.params),
            )
            return False
        with self._guard:
            order.artifact_key = artifact.key
            order.digest = artifact.digest
            order.package_kind = artifact.package_kind
        return True


def ask_module(
    *,
    controller: AgentModuleController,
    mac_address: str,
    module: str,
    manifest: dict,
    platform: dict,
    is_enabled: bool,
    reported_state: str = "",
) -> "AgentModuleOrder | None":
    """The one door both surfaces post a module click through.

    The panel's drawer and the machine's own page reach this by different
    routes and mean the same thing, so they call the same function and there
    is no second path to behave differently. A click is one order and
    nothing more: nothing records what the machine "should" have.

    Args:
        controller: The device's module controller.
        mac_address: The device.
        module: The module name.
        manifest: Its manifest.
        platform: The tuple the agent reported.
        is_enabled: What the person asked for.
        reported_state: What the machine last said about this module.

    Returns:
        The queued order, or None when there is nothing to do — a manifest
        with no build for this platform, or an uninstall of something the
        machine reports absent.
    """
    action = order_action_for(
        manifest=manifest, platform=platform, is_enabled=is_enabled
    )
    if action is None:
        return None
    return controller.ask(
        mac_address=mac_address,
        module=module,
        manifest=manifest,
        platform=platform,
        action=action,
        reported_state=reported_state,
    )


def order_action_for(
    *, manifest: dict, platform: dict, is_enabled: bool
) -> "str | None":
    """What a click means for one module on one platform.

    Args:
        manifest: The module's manifest.
        platform: The tuple the agent reported.
        is_enabled: What the person asked for.

    Returns:
        The action, or None when the manifest offers this platform nothing.
    """
    _, entry = resolve_platform_entry(manifest, platform)
    if entry is None and platform:
        return None
    # An empty entry means the platform carries this natively: nothing to
    # install, nothing to uninstall.
    if entry == {}:
        return None
    return ORDER_ACTION_INSTALL if is_enabled else ORDER_ACTION_UNINSTALL


def _names_download(order: AgentModuleOrder) -> bool:
    """Whether this order's platform entry has bytes to fetch.

    A distro package installs by name with the machine's own tooling; only
    an entry naming a url or a release goes through the cache.

    Args:
        order: The order being run.

    Returns:
        True when the entry names a download. An unresolvable entry also
        answers True, so the fetch fails the order with its own typed reason.
    """
    _, entry = resolve_platform_entry(order.manifest, order.platform)
    if entry is None:
        return True
    return bool(entry.get("url") or entry.get("github_repo"))
