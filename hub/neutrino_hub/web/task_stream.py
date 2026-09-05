"""Background jobs whose output the panel streams to the browser.

Installing an agent or a remote desktop client takes minutes, far longer than a
request should hold open. The request starts a job and returns its id; the
browser then opens a websocket and reads the output as it is produced, including
whatever was already buffered before it connected.
"""

import asyncio
import secrets
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timezone

TASK_ID_BYTES = 8
BUFFER_LINE_LIMIT = 2000
# How many finished jobs keep their output. A drawer reopened after an install
# still shows its log; a panel that has been up for a month does not hold every
# log it ever produced, at two thousand lines each.
FINISHED_TASK_LIMIT = 8


@dataclass
class TaskStream:
    """One running or finished job.

    Attributes:
        id: Identifier the websocket route addresses it by.
        label: Human-readable description, shown in the panel.
        buffer: Output produced so far, replayed to late subscribers.
        exit_code: Set once the job finishes.
        is_finished: Whether the job has completed.
        started_at: When the job started, ISO.
        finished_at: When it finished, empty while it runs.
    """

    id: str
    label: str
    buffer: list[str] = field(default_factory=list)
    exit_code: int | None = None
    is_finished: bool = False
    started_at: str = ""
    finished_at: str = ""
    _subscribers: list[asyncio.Queue] = field(default_factory=list)

    def publish(self, chunk: str) -> None:
        """Append output and fan it out to live subscribers.

        Args:
            chunk: The text produced by the job.
        """
        self.buffer.append(chunk)
        if len(self.buffer) > BUFFER_LINE_LIMIT:
            del self.buffer[: len(self.buffer) - BUFFER_LINE_LIMIT]
        for queue in self._subscribers:
            queue.put_nowait(chunk)

    def finish(self, exit_code: int) -> None:
        """Mark the job complete and wake every subscriber.

        Args:
            exit_code: The job's exit status.
        """
        self.exit_code = exit_code
        self.is_finished = True
        self.finished_at = datetime.now(timezone.utc).isoformat()
        for queue in self._subscribers:
            queue.put_nowait(None)

    async def subscribe(self) -> AsyncIterator[str]:
        """Replay buffered output, then follow the job live.

        Yields:
            Every chunk the job has produced and will produce, until it
            finishes.
        """
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.append(queue)
        try:
            for chunk in list(self.buffer):
                yield chunk
            if self.is_finished:
                return
            while True:
                chunk = await queue.get()
                if chunk is None:
                    return
                yield chunk
        finally:
            self._subscribers.remove(queue)


class TaskStreamRegistry:
    """Starts jobs and hands out their streams."""

    def __init__(self):
        self._streams: dict[str, TaskStream] = {}

    def start(self, *, label: str, source: AsyncIterator[str]) -> TaskStream:
        """Run an async output source as a background job.

        Args:
            label: Human-readable description of the job.
            source: Async iterator producing the job's output.

        Returns:
            The stream, whose ``id`` the caller returns to the browser.
        """
        self._evict_finished()
        stream = TaskStream(
            id=secrets.token_hex(TASK_ID_BYTES),
            label=label,
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        self._streams[stream.id] = stream
        asyncio.create_task(self._drain(stream, source))
        return stream

    def running(self, label: str) -> TaskStream | None:
        """The unfinished job with this label, if one is running.

        Args:
            label: The label the job was started with.

        Returns:
            The stream, or None when nothing by that label is still going.
        """
        for stream in self._streams.values():
            if stream.label == label and stream.exit_code is None:
                return stream
        return None

    def running_all(self) -> list[TaskStream]:
        """Every job that has not finished.

        Returns:
            The unfinished streams, oldest first. A browser reload loses the id
            it was streaming while the job carries on, so this is how a page
            reopened part-way through an install finds its own again.
        """
        return [stream for stream in self._streams.values() if stream.exit_code is None]

    def get(self, task_id: str) -> TaskStream | None:
        """Look up a job by id.

        Args:
            task_id: The identifier handed to the browser.

        Returns:
            The stream, or None when the id is unknown.
        """
        return self._streams.get(task_id)

    def streams(self) -> list[TaskStream]:
        """Every job still held, running or finished.

        Returns:
            The streams, oldest first.
        """
        return list(self._streams.values())

    def _evict_finished(self) -> None:
        """Drop the oldest finished jobs, keeping the most recent few."""
        finished = [
            task_id
            for task_id, stream in self._streams.items()
            if stream.exit_code is not None
        ]
        for task_id in finished[: max(0, len(finished) - FINISHED_TASK_LIMIT)]:
            del self._streams[task_id]

    async def _drain(self, stream: TaskStream, source: AsyncIterator[str]) -> None:
        exit_code = 0
        try:
            async for chunk in source:
                stream.publish(chunk)
        except (
            Exception
        ) as error:  # noqa: BLE001 - surfaced to the panel, not swallowed
            stream.publish(f"\n[task failed: {error}]\n")
            exit_code = 1
        finally:
            stream.finish(exit_code)
