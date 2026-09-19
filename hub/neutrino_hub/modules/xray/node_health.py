"""What every node's measurements say, and where they live between runs.

A node keeps a window: the last :data:`XRAY_HEALTH_WINDOW_SAMPLES` samples no
older than :data:`XRAY_HEALTH_SAMPLE_MAX_AGE_S`. The count bounds the file and
the arithmetic; the age bounds how stale a reading may be after the box was
off, whatever the interval is set to. Two stamps sit outside the window and
never age out: when the node was last probed, and when it last answered.

Three readings, not two. A node whose newest sample failed is down. A node with
a sample that succeeded is alive. A node nobody has probed inside the window is
neither: its window is empty, and ignorance never moves the exit.

The score is a median rather than a mean, so one slow answer does not move it,
plus the spread around that median and what the failures in the window cost.

The file is state: losing it costs one round of measurements and the pin, never
a decision. A file that will not parse loads as empty.
"""

import json
import logging
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from neutrino_hub.modules.xray.constants import (
    XRAY_HEALTH_FAILURE_PENALTY_MS,
    XRAY_HEALTH_SAMPLE_MAX_AGE_S,
    XRAY_HEALTH_WINDOW_SAMPLES,
    XRAY_NODE_HEALTH_RELATIVE,
)
from neutrino_hub.utils import constants
from neutrino_hub.utils.json_file import write_generated

LOGGER = logging.getLogger(__name__)

# The file is read by the panel alone, which is root.
HEALTH_FILE_MODE = 0o600


@dataclass
class XrayNodeSample:
    """One stored measurement of one node.

    Attributes:
        at: When the measurement was taken.
        connect_ms: The TCP connect to the node's own address and port, in
            milliseconds; None when it did not answer.
        request_ms: A whole request through the node, in milliseconds; None
            when it failed.
    """

    at: datetime
    connect_ms: int | None
    request_ms: int | None

    @property
    def is_success(self) -> bool:
        """Whether the request through the node completed."""
        return self.request_ms is not None

    @classmethod
    def from_dict(cls, data: dict) -> "XrayNodeSample":
        """Build one sample from its stored object.

        Args:
            data: One element of a node's ``samples`` array.

        Returns:
            The parsed sample.

        Raises:
            ValueError: If the stamp is missing or unreadable.
            TypeError: If the object is not a mapping.
        """
        return cls(
            at=_moment(data["at"]),
            connect_ms=_milliseconds(data.get("connect_ms")),
            request_ms=_milliseconds(data.get("request_ms")),
        )

    def to_dict(self) -> dict:
        """Serialize back to the stored shape.

        Returns:
            A JSON-ready object.
        """
        return {
            "at": _stamp(self.at),
            "connect_ms": self.connect_ms,
            "request_ms": self.request_ms,
        }


@dataclass
class XrayNodeHealth:
    """One node's window, and what it says about the node.

    Attributes:
        tag: The node's outbound tag.
        samples: The window, oldest first.
        probed_at: The latest attempt, however old; None when there was none.
        succeeded_at: The latest success, however old; None when there was
            none.
    """

    tag: str
    samples: list[XrayNodeSample] = field(default_factory=list)
    probed_at: datetime | None = None
    succeeded_at: datetime | None = None

    @property
    def sample_count(self) -> int:
        """How many samples the window holds."""
        return len(self.samples)

    @property
    def connect_ms(self) -> int | None:
        """The newest sample's connect, None when the window is empty."""
        if not self.samples:
            return None
        return self.samples[-1].connect_ms

    @property
    def request_ms(self) -> int | None:
        """The newest sample's request, None when the window is empty."""
        if not self.samples:
            return None
        return self.samples[-1].request_ms

    @property
    def success_rate(self) -> float:
        """The share of the window that succeeded, zero for an empty window."""
        if not self.samples:
            return 0.0
        return self._successes() / len(self.samples)

    @property
    def median_ms(self) -> float | None:
        """The median request through the node, None when none succeeded."""
        values = self._request_values()
        if not values:
            return None
        return statistics.median(values)

    @property
    def jitter_ms(self) -> float | None:
        """The median deviation around that median, None when none succeeded."""
        values = self._request_values()
        if not values:
            return None
        middle = statistics.median(values)
        return statistics.median([abs(value - middle) for value in values])

    @property
    def score_ms(self) -> float | None:
        """What the node costs: its median, its spread, and its failures.

        None when no sample in the window succeeded, which is every node the
        exit choice already refuses to consider.
        """
        middle = self.median_ms
        if middle is None:
            return None
        jitter = self.jitter_ms or 0.0
        return (
            middle + jitter + XRAY_HEALTH_FAILURE_PENALTY_MS * (1 - self.success_rate)
        )

    @property
    def is_down(self) -> bool:
        """Whether the newest sample in the window failed."""
        if not self.samples:
            return False
        return not self.samples[-1].is_success

    @property
    def is_alive(self) -> bool:
        """Whether the window holds a sample and the newest one succeeded."""
        return self.sample_count > 0 and not self.is_down

    def to_dict(self) -> dict:
        """Serialize back to the stored shape.

        Returns:
            A JSON-ready object.
        """
        return {
            "probed_at": _stamp(self.probed_at) if self.probed_at else None,
            "succeeded_at": _stamp(self.succeeded_at) if self.succeeded_at else None,
            "samples": [sample.to_dict() for sample in self.samples],
        }

    def _successes(self) -> int:
        """How many samples in the window succeeded."""
        return sum(1 for sample in self.samples if sample.is_success)

    def _request_values(self) -> list[int]:
        """Every successful request time in the window."""
        return [
            sample.request_ms
            for sample in self.samples
            if sample.request_ms is not None
        ]


class XrayNodeHealthStore:
    """Every node's window and the exit the hub pinned, kept across runs.

    Held in memory and written as a whole: :meth:`load` reads the file,
    :meth:`record` and :meth:`set_exit` move what is held, and :meth:`save`
    writes it back.
    """

    def __init__(self, *, path: Path | None = None):
        """
        Args:
            path: The store file; None resolves it under the state root per
                call, so a test points the whole store elsewhere by path.
        """
        self._path = path
        self._nodes: dict[str, XrayNodeHealth] = {}
        self._exit_tag = ""
        self._exit_since: datetime | None = None

    @property
    def exit_tag(self) -> str:
        """The outbound the hub pinned, empty when it pinned none."""
        return self._exit_tag

    @property
    def exit_since(self) -> datetime | None:
        """When that pin last changed, None when nothing is pinned."""
        return self._exit_since

    def load(self) -> None:
        """Read the store, tolerant of anything on disk.

        A file that is missing, unreadable, or not shaped like a store loads
        as empty: a machine that has to measure again is a machine that works,
        and refusing to start over a state file is not.
        """
        self._nodes = {}
        self._exit_tag = ""
        self._exit_since = None
        path = self._resolved_path()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, ValueError) as error:
            LOGGER.warning(
                "the node health store is unreadable, starting fresh: %s", error
            )
            return
        if not isinstance(raw, dict):
            LOGGER.warning("the node health store is not an object, starting fresh")
            return
        self._read_exit(raw.get("exit"))
        self._read_nodes(raw.get("nodes"))

    def save(self, *, tags: "list[str] | None" = None) -> None:
        """Write the store out, dropping the nodes that are gone.

        Args:
            tags: Every tag the node list still names; entries under any other
                tag are dropped. None keeps every entry.
        """
        if tags is not None:
            kept = set(tags)
            self._nodes = {
                tag: health for tag, health in self._nodes.items() if tag in kept
            }
        data = {
            "exit": {
                "tag": self._exit_tag,
                "since": _stamp(self._exit_since) if self._exit_since else None,
            },
            "nodes": {tag: health.to_dict() for tag, health in self._nodes.items()},
        }
        write_generated(
            self._resolved_path(),
            json.dumps(data, indent=2) + "\n",
            mode=HEALTH_FILE_MODE,
        )

    def record(
        self,
        tag: str,
        *,
        connect_ms: int | None,
        request_ms: int | None,
        now: datetime | None = None,
    ) -> None:
        """Add one measurement to a node's window.

        Args:
            tag: The node's outbound tag.
            connect_ms: What the connect to the node's own address measured.
            request_ms: What the request through the node measured; None
                means it failed.
            now: When it was measured; None is the real clock.
        """
        moment = now or _utc_now()
        health = self._nodes.setdefault(tag, XrayNodeHealth(tag=tag))
        health.samples.append(
            XrayNodeSample(at=moment, connect_ms=connect_ms, request_ms=request_ms)
        )
        del health.samples[:-XRAY_HEALTH_WINDOW_SAMPLES]
        health.probed_at = moment
        if request_ms is not None:
            health.succeeded_at = moment

    def health(self, *, now: datetime | None = None) -> dict[str, XrayNodeHealth]:
        """Every node's window as it reads at one moment.

        Args:
            now: The moment the window is measured back from; None is the real
                clock.

        Returns:
            One entry per tag the store holds, keyed by tag.
        """
        moment = now or _utc_now()
        return {tag: self.health_of(tag, now=moment) for tag in self._nodes}

    def health_of(self, tag: str, *, now: datetime | None = None) -> XrayNodeHealth:
        """One node's window as it reads at one moment.

        Args:
            tag: The node's outbound tag.
            now: The moment the window is measured back from; None is the real
                clock.

        Returns:
            Its window, trimmed by age. A tag the store does not hold reads as
            an empty window, which is what a node nobody has probed is.
        """
        held = self._nodes.get(tag)
        if held is None:
            return XrayNodeHealth(tag=tag)
        floor = (now or _utc_now()) - timedelta(seconds=XRAY_HEALTH_SAMPLE_MAX_AGE_S)
        return XrayNodeHealth(
            tag=tag,
            samples=[sample for sample in held.samples if sample.at > floor],
            probed_at=held.probed_at,
            succeeded_at=held.succeeded_at,
        )

    def set_exit(self, tag: str, *, now: datetime | None = None) -> None:
        """Write down which outbound the hub pinned.

        The stamp moves only when the tag does, so the dwell time measures how
        long this exit has held.

        Args:
            tag: The pinned outbound tag.
            now: When it was pinned; None is the real clock.
        """
        if tag == self._exit_tag:
            return
        self._exit_tag = tag
        self._exit_since = now or _utc_now()

    def _read_exit(self, stored) -> None:
        """Take the pinned exit out of a loaded file."""
        if not isinstance(stored, dict):
            return
        tag = stored.get("tag")
        if not isinstance(tag, str) or not tag:
            return
        self._exit_tag = tag
        try:
            self._exit_since = _moment(stored.get("since"))
        except (TypeError, ValueError):
            self._exit_since = None

    def _read_nodes(self, stored) -> None:
        """Take every node's window out of a loaded file."""
        if not isinstance(stored, dict):
            return
        for tag, entry in stored.items():
            if not isinstance(tag, str) or not isinstance(entry, dict):
                continue
            self._nodes[tag] = XrayNodeHealth(
                tag=tag,
                samples=_read_samples(entry.get("samples")),
                probed_at=_read_moment(entry.get("probed_at")),
                succeeded_at=_read_moment(entry.get("succeeded_at")),
            )

    def _resolved_path(self) -> Path:
        # Resolved per call, against the state root as it is right now.
        return self._path or constants.UTILS_STATE_ROOT / XRAY_NODE_HEALTH_RELATIVE


def _read_samples(stored) -> list[XrayNodeSample]:
    """Every sample a loaded file holds for one node, the unreadable dropped."""
    if not isinstance(stored, list):
        return []
    samples = []
    for entry in stored:
        try:
            samples.append(XrayNodeSample.from_dict(entry))
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
    samples.sort(key=_sample_moment)
    return samples[-XRAY_HEALTH_WINDOW_SAMPLES:]


def _sample_moment(sample: XrayNodeSample) -> datetime:
    """When a sample was taken, for ordering a loaded window."""
    return sample.at


def _read_moment(value) -> datetime | None:
    """One stamp out of a loaded file, None when it is missing or unreadable."""
    try:
        return _moment(value)
    except (TypeError, ValueError):
        return None


def _moment(value) -> datetime:
    """A stored stamp as a moment.

    Args:
        value: The stamp as it was written.

    Returns:
        The moment, in UTC.

    Raises:
        TypeError: If the value is not a string.
        ValueError: If it is not an ISO stamp.
    """
    if not isinstance(value, str):
        raise TypeError(f"a stamp must be a string, not {type(value).__name__}")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _stamp(value: datetime) -> str:
    """A moment as the file carries it."""
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds")


def _milliseconds(value) -> int | None:
    """A stored duration, None for anything that is not a whole number."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return max(value, 0)


def _utc_now() -> datetime:
    """The moment, as every stamp here is taken."""
    return datetime.now(timezone.utc)
