"""Measuring every node, choosing the exit, and telling xray to use it.

The hub owns both halves. It measures each node itself, keeps the window, ranks
the nodes and pins one outbound with ``xray api bo``; xray moves the
connections and decides nothing. Its own balancer is never consulted while the
override stands.

A round is: check that xray carries the exits the render names, measure every
node it carries, fetch the reference directly, record what the two together
allow, rank, choose, pin, save.

Being switched off keeps a node out of the choice, never out of the
measurement. The render gives every node with secret material an outbound and
a probe account of its own, switched on or off, so a node that is off still
shows what it would cost to switch back on.

The choice keeps the exit it has unless a challenger is better by all three of
the ratio, the margin and the dwell time. Two nodes a millisecond apart would
otherwise trade the exit every round.

Ignorance never moves the exit. A node nobody has measured is not a candidate
and not a failure, and a round that found the uplink down records nothing at
all: a node cannot be blamed for a WAN that is not there.
"""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone

from neutrino_hub.modules.xray.constants import (
    XRAY_DIRECT_TAG,
    XRAY_EXIT_DWELL_S,
    XRAY_EXIT_REASSERT_DELAY_S,
    XRAY_EXIT_REASSERT_TRIES,
    XRAY_EXIT_SWITCH_MARGIN_MS,
    XRAY_EXIT_SWITCH_RATIO,
    XRAY_NODE_TAG_PREFIX,
    XRAY_PROBE_INTERVAL_DEFAULT_S,
    XRAY_PROBE_INTERVAL_MAX_S,
    XRAY_PROBE_INTERVAL_MIN_S,
    XRAY_PROBE_WORKER_LIMIT,
)
from neutrino_hub.modules.xray.node_health import XrayNodeHealth

LOGGER = logging.getLogger(__name__)


def _score_of(health: XrayNodeHealth) -> float:
    """A node's score, with a node that never answered sorting last."""
    if health.score_ms is None:
        return float("inf")
    return health.score_ms


@dataclass
class XrayExitStatus:
    """What one round concluded.

    Attributes:
        exit_tag: The outbound the hub has pinned; empty when it holds none.
        since: When that pin last changed.
        is_xray_reachable: Whether xray answered its API and its probe inbound.
        is_wan_reachable: Whether the reference URL answered directly. True
            when no node failed, since nothing asked.
        is_in_sync: Whether xray carries exactly the node outbounds the
            rendered config names.
        missing_tags: Node outbounds the render names and xray does not carry.
        extra_tags: Node outbounds xray carries and the render does not name.
        at: When the round ended.
    """

    exit_tag: str = ""
    since: datetime | None = None
    is_xray_reachable: bool = True
    is_wan_reachable: bool = True
    is_in_sync: bool = True
    missing_tags: list[str] = field(default_factory=list)
    extra_tags: list[str] = field(default_factory=list)
    at: datetime | None = None


class XrayExitController:
    """Runs the rounds, holds the choice, and drives xray's override.

    Two locks. The round lock guards a whole round, so the background loop
    skips a tick that would overlap one and a Test of every node waits for it.
    The state lock guards the short tail — record, rank, choose, pin, save —
    and is all a Test of one node takes, so that Test and a round already
    running both record.
    """

    def __init__(
        self,
        *,
        probe,
        store,
        api,
        node_list_of,
        routing_of,
        rendered_config_of,
        on_change=None,
        on_out_of_sync=None,
    ):
        """
        Args:
            probe: The node probe, which measures one node and the reference.
            store: The health store, which holds the windows and the pin.
            api: The statistics client, which reads and sets the override.
            node_list_of: Called with nothing, answers the parsed node list.
                Called once a round, so a change in ``config/`` lands on the
                next one with nothing to invalidate.
            routing_of: Called with nothing, answers parsed
                ``config/xray/routing.json``.
            rendered_config_of: Called with nothing, answers the rendered xray
                config. Only its outbound tags are read, and its contents are
                never logged: it carries every node's secret.
            on_change: Called with the status when the pinned exit moved.
            on_out_of_sync: Called with the status when what xray carries stops
                matching the render, once per change of that mismatch.
        """
        self._probe = probe
        self._store = store
        self._api = api
        self._node_list_of = node_list_of
        self._routing_of = routing_of
        self._rendered_config_of = rendered_config_of
        self._on_change = on_change
        self._on_out_of_sync = on_out_of_sync
        self._status = XrayExitStatus()
        self._round_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._is_stopped = threading.Event()
        self._wake = threading.Event()
        self._thread: "threading.Thread | None" = None
        # What the last sync check found, so a mismatch is said once rather
        # than every round.
        self._sync_mismatch: "tuple[tuple[str, ...], tuple[str, ...]]" = ((), ())

    @property
    def status(self) -> XrayExitStatus:
        """What the last round concluded."""
        return self._status

    def start(self) -> None:
        """Load the store and run rounds from now on; a second start is a no-op.

        The thread re-pins what the store names before its first round, which
        it runs at once rather than after an interval.
        """
        if self._thread is not None:
            return
        self._store.load()
        self._thread = threading.Thread(
            target=self._loop, name="xray_exit", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the loop; the round in flight finishes."""
        self._is_stopped.set()
        self._wake.set()

    def wake(self) -> None:
        """Run a round now instead of at the next tick.

        Does nothing until the loop is started.
        """
        self._wake.set()

    def refresh(self, *, only: str | None = None) -> XrayExitStatus:
        """Measure now, then rank, choose and pin.

        Args:
            only: One node's id; None measures every node the running xray
                carries, switched on or off. One node's measurement takes only
                the state lock, so it overlaps a round already running and both
                record.

        Returns:
            What the round concluded.

        Raises:
            KeyError: If ``only`` names no node in the list.
        """
        node_list = self._node_list_of()
        if only is None:
            with self._round_lock:
                return self._round(node_list=node_list)
        chosen = [node for node in node_list.nodes if node.id == only]
        if not chosen:
            raise KeyError(f"no node with id {only!r}")
        return self._round(node_list=node_list, nodes=chosen)

    def reselect(self) -> XrayExitStatus:
        """Rank and pin again from what is stored, measuring nothing.

        Enabling or disabling a node changes who may be chosen without changing
        what anybody measured.

        Returns:
            What the choice concluded.
        """
        node_list = self._node_list_of()
        status = XrayExitStatus()
        resident = self._residency(status)
        with self._state_lock:
            is_changed = self._settle(
                status=status,
                node_list=node_list,
                resident=resident,
                now=datetime.now(timezone.utc),
            )
        return self._publish(status, is_changed=is_changed)

    def reassert(self) -> bool:
        """Pin the stored exit again, waiting for xray's API to come up.

        The unit is ``Type=simple``, so systemd reports the restart before the
        API inbound is listening.

        Returns:
            True when xray holds the stored exit at the end, False when the
            store names none or xray never answered.
        """
        tag = self._store.exit_tag
        if not tag:
            return False
        for attempt in range(XRAY_EXIT_REASSERT_TRIES):
            try:
                if self._api.override_target() != tag:
                    self._api.set_override(tag)
                return True
            except ConnectionError as error:
                if attempt == XRAY_EXIT_REASSERT_TRIES - 1:
                    LOGGER.warning("xray did not take the stored exit: %s", error)
                    return False
            time.sleep(XRAY_EXIT_REASSERT_DELAY_S)
        return False

    def healths(self) -> dict[str, XrayNodeHealth]:
        """Every node's window as it reads now, measuring nothing.

        Returns:
            One entry per tag the store holds, keyed by tag.
        """
        with self._state_lock:
            return self._store.health()

    def _loop(self) -> None:
        """Re-pin what the store names, then run a round every interval."""
        self.reassert()
        while not self._is_stopped.is_set():
            self._tick()
            self._wake.wait(self._interval_s())
            self._wake.clear()

    def _tick(self) -> None:
        """One round from the loop, skipped while another one holds the lock."""
        if not self._round_lock.acquire(blocking=False):
            return
        try:
            self._round(node_list=self._node_list_of())
        except Exception:  # noqa: BLE001 - one bad round never stops measuring
            LOGGER.exception("the exit round failed")
        finally:
            self._round_lock.release()

    def _interval_s(self) -> float:
        """Seconds to the next round, read from the node list each tick."""
        try:
            interval = float(self._node_list_of().probe_interval_s)
        except (OSError, TypeError, ValueError, KeyError):
            interval = XRAY_PROBE_INTERVAL_DEFAULT_S
        return min(max(interval, XRAY_PROBE_INTERVAL_MIN_S), XRAY_PROBE_INTERVAL_MAX_S)

    def _round(self, *, node_list, nodes=None) -> XrayExitStatus:
        """Measure, then rank, choose and pin.

        Args:
            node_list: The node list this round reads.
            nodes: The nodes to measure; None measures every node xray carries
                an outbound for, which is every node the render named. A node
                whose secret reference did not resolve is not in the render and
                has no probe account, so there is nothing to measure it
                through.

        Returns:
            What the round concluded.
        """
        status = XrayExitStatus()
        resident = self._residency(status)
        if not status.is_xray_reachable:
            status.exit_tag = self._store.exit_tag
            status.since = self._store.exit_since
            return self._publish(status)
        if nodes is None:
            nodes = [node for node in node_list.nodes if node.tag in resident]
        measurements = self._measure(nodes, url=node_list.probe_url)
        reference_ms = None
        if any(not one.is_success and one.is_xray_reachable for one in measurements):
            reference_ms = self._probe.probe_reference(node_list.reference_url)
            status.is_wan_reachable = reference_ms is not None
        measurements += self._retried(
            nodes, measurements, node_list=node_list, status=status
        )
        now = datetime.now(timezone.utc)
        with self._state_lock:
            self._record(measurements, status=status, now=now)
            is_changed = self._settle(
                status=status, node_list=node_list, resident=resident, now=now
            )
        return self._publish(status, is_changed=is_changed)

    def _measure(self, nodes, *, url: str) -> list:
        """Measure every node given, several at a time.

        Args:
            nodes: The nodes to measure.
            url: The URL fetched through each of them.

        Returns:
            One measurement per node, in the order given.
        """
        if not nodes:
            return []
        worker_count = min(XRAY_PROBE_WORKER_LIMIT, len(nodes))
        with ThreadPoolExecutor(max_workers=worker_count) as pool:
            measured = [pool.submit(self._probe.probe, node, url=url) for node in nodes]
            return [one.result() for one in measured]

    def _retried(self, nodes, measurements, *, node_list, status) -> list:
        """Measure the pinned node once more when it just failed.

        Both measurements are recorded, so the exit moves off a node only on
        two failures in a row.

        Args:
            nodes: The nodes this round measured.
            measurements: What it measured.
            node_list: The node list this round read.
            status: The round's status, for whether the uplink answered.

        Returns:
            The second measurement, or nothing when none was called for.
        """
        tag = self._store.exit_tag
        if not tag or not status.is_wan_reachable:
            return []
        is_failed = any(
            one.tag == tag and one.is_xray_reachable and not one.is_success
            for one in measurements
        )
        if not is_failed:
            return []
        pinned = [node for node in nodes if node.tag == tag]
        if not pinned:
            return []
        return [self._probe.probe(pinned[0], url=node_list.probe_url)]

    def _record(self, measurements, *, status, now: datetime) -> None:
        """Write the measurements this round is allowed to keep.

        A success is always kept: a working exit is evidence whatever the
        reference said. A failure is kept only when the reference answered,
        and nothing at all is kept when xray's own probe inbound refused.

        Args:
            measurements: What the round measured.
            status: The round's status, filled in as the measurements say.
            now: The moment every sample is stamped with.
        """
        for one in measurements:
            if not one.is_xray_reachable:
                status.is_xray_reachable = False
                continue
            if not one.is_success and not status.is_wan_reachable:
                continue
            self._store.record(
                one.tag,
                connect_ms=one.connect_ms,
                request_ms=one.request_ms,
                now=now,
            )

    def _settle(self, *, status, node_list, resident, now: datetime) -> bool:
        """Rank, choose, pin and save, filling the status in.

        Args:
            status: The round's status.
            node_list: The node list this round read.
            resident: The node outbounds xray carries and the render names.
            now: The moment the choice is made at.

        Returns:
            Whether the pinned exit moved.
        """
        health = self._store.health(now=now)
        previous = self._store.exit_tag
        choice = self._choice(
            node_list=node_list, resident=resident, health=health, now=now
        )
        if self._pin(choice, resident=resident):
            self._store.set_exit(choice, now=now)
        else:
            status.is_xray_reachable = False
        self._store.save(tags=[node.tag for node in node_list.nodes])
        status.exit_tag = self._store.exit_tag
        status.since = self._store.exit_since
        status.at = now
        return status.exit_tag != previous

    def _choice(self, *, node_list, resident, health, now: datetime) -> str:
        """Which outbound this round wants pinned.

        Args:
            node_list: The node list this round read.
            resident: The node outbounds xray carries and the render names.
            health: Every node's window, keyed by tag.
            now: The moment the choice is made at.

        Returns:
            The outbound tag, which is a node's, ``direct``, or the empty
            string when the hub holds no opinion yet.
        """
        current = self._store.exit_tag
        candidates = []
        is_any_unknown = False
        for node in node_list.enabled_nodes:
            if node.tag not in resident:
                continue
            one = health.get(node.tag) or XrayNodeHealth(tag=node.tag)
            if one.sample_count == 0:
                is_any_unknown = True
                continue
            if one.is_down:
                continue
            candidates.append(one)
        candidates.sort(key=_score_of)
        if candidates:
            return self._best_of(candidates, current=current, now=now)
        if is_any_unknown:
            return current
        if self._routing_of().get("is_direct_fallback_enabled", False):
            return XRAY_DIRECT_TAG
        return current

    def _best_of(self, candidates, *, current: str, now: datetime) -> str:
        """The exit to hold, given the nodes that may be chosen.

        Args:
            candidates: The eligible nodes, best score first.
            current: The tag pinned now.
            now: The moment the choice is made at.

        Returns:
            The outbound tag to pin.
        """
        best = candidates[0]
        held = [one for one in candidates if one.tag == current]
        if not held:
            return best.tag
        best_score = _score_of(best)
        held_score = _score_of(held[0])
        since = self._store.exit_since
        is_dwelt = since is None or (now - since).total_seconds() >= XRAY_EXIT_DWELL_S
        if (
            best_score < held_score * (1 - XRAY_EXIT_SWITCH_RATIO)
            and held_score - best_score >= XRAY_EXIT_SWITCH_MARGIN_MS
            and is_dwelt
        ):
            return best.tag
        return current

    def _pin(self, choice: str, *, resident) -> bool:
        """Tell xray to use one outbound, when it is not using it already.

        Args:
            choice: The outbound tag to pin; empty clears the override.
            resident: The node outbounds xray carries and the render names.

        Returns:
            Whether xray answered.
        """
        try:
            override = self._api.override_target()
            if choice == override:
                return True
            if not choice:
                if override:
                    self._api.clear_override()
                return True
            if choice != XRAY_DIRECT_TAG and choice not in resident:
                return False
            if not override and self._store.exit_tag:
                LOGGER.info("xray holds no override; pinning %s again", choice)
            self._api.set_override(choice)
        except ConnectionError as error:
            LOGGER.warning("xray did not take the exit: %s", error)
            return False
        return True

    def _residency(self, status: XrayExitStatus) -> set[str]:
        """Which node outbounds xray carries and the render names.

        Args:
            status: The round's status, filled in with what does not match.

        Returns:
            The tags in both, which are the only ones that may be chosen.
        """
        expected = self._expected_tags()
        try:
            live = set(self._api.inbound_tags()) | set(self._api.outbound_tags())
        except ConnectionError as error:
            LOGGER.warning("xray did not answer its API: %s", error)
            status.is_xray_reachable = False
            return set()
        carried = {tag for tag in live if tag.startswith(XRAY_NODE_TAG_PREFIX)}
        status.missing_tags = sorted(expected - carried)
        status.extra_tags = sorted(carried - expected)
        status.is_in_sync = not status.missing_tags and not status.extra_tags
        return expected & carried

    def _expected_tags(self) -> set[str]:
        """The node outbounds the rendered config names."""
        try:
            config = self._rendered_config_of()
        except (OSError, ValueError) as error:
            LOGGER.warning("the rendered xray config could not be read: %s", error)
            return set()
        tags = set()
        for outbound in config.get("outbounds", []):
            if not isinstance(outbound, dict):
                continue
            tag = outbound.get("tag")
            if isinstance(tag, str) and tag.startswith(XRAY_NODE_TAG_PREFIX):
                tags.add(tag)
        return tags

    def _publish(
        self, status: XrayExitStatus, *, is_changed: bool = False
    ) -> XrayExitStatus:
        """Hold the status, and say what moved.

        Args:
            status: What the round concluded.
            is_changed: Whether the pinned exit moved.

        Returns:
            The status, as the caller reads it.
        """
        if status.at is None:
            status.at = datetime.now(timezone.utc)
        self._status = status
        if is_changed and self._on_change is not None:
            self._on_change(status)
        if not status.is_xray_reachable:
            return status
        mismatch = (tuple(status.missing_tags), tuple(status.extra_tags))
        if mismatch != self._sync_mismatch:
            self._sync_mismatch = mismatch
            if mismatch != ((), ()):
                LOGGER.warning(
                    "xray does not carry the exits the render names: "
                    "missing %s, extra %s",
                    ", ".join(status.missing_tags) or "none",
                    ", ".join(status.extra_tags) or "none",
                )
                if self._on_out_of_sync is not None:
                    self._on_out_of_sync(status)
        return status
