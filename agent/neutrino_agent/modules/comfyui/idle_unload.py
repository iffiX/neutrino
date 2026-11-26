"""Idle unload: ComfyUI's models taken out of memory after a time with no job.

Every 60 seconds while ComfyUI runs and the setting is not ``-1``, the
agent reads ``GET /queue`` and ``GET /history?max_items=1`` on ComfyUI's
port. When ``queue_running`` and ``queue_pending`` are empty and the newest
entry of the history ended at least the setting ago, it sends ``POST
/free`` with ``{"unload_models": true, "free_memory": true}``, once for that
entry. A history with no entry sends nothing. The unload restarts nothing.

Not pure: reads and calls ComfyUI's API on a thread of its own.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request

from neutrino_agent.modules.comfyui.constants import (
    COMFYUI_ANSWER_BYTES,
    COMFYUI_API_TIMEOUT_S,
    COMFYUI_FREE_BODY,
    COMFYUI_FREE_PATH,
    COMFYUI_HISTORY_PATH,
    COMFYUI_HOST,
    COMFYUI_IDLE_POLL_S,
    COMFYUI_QUEUE_PATH,
)


def api_call(port: int, path: str, body: "bytes | None" = None):
    """One call to ComfyUI's API on loopback.

    Args:
        port: ComfyUI's port.
        path: The path, its query included.
        body: A JSON body to ``POST``; None makes a ``GET``.

    Returns:
        The answer's JSON; None when nothing answers or the answer is no
        JSON.
    """
    request = urllib.request.Request(
        f"http://{COMFYUI_HOST}:{port}{path}",
        data=body,
        headers={"Content-Type": "application/json"} if body is not None else {},
        method="POST" if body is not None else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=COMFYUI_API_TIMEOUT_S) as answer:
            text = answer.read(COMFYUI_ANSWER_BYTES)
    except (OSError, ValueError, urllib.error.URLError):
        return None
    if not text.strip():
        return {}
    try:
        return json.loads(text.decode("utf-8"))
    except ValueError:
        return None


def entry_end(history) -> tuple:
    """The newest history entry and when it ended. Pure.

    Args:
        history: What ``GET /history?max_items=1`` answered.

    Returns:
        ``(prompt id, end in milliseconds)``: the latest timestamp among
        the entry's status messages; ``("", 0)`` for a history with no
        entry or no time.
    """
    if not isinstance(history, dict) or not history:
        return "", 0
    prompt_id, entry = list(history.items())[-1]
    status = entry.get("status") if isinstance(entry, dict) else None
    messages = status.get("messages") if isinstance(status, dict) else None
    ended = 0
    for message in messages if isinstance(messages, list) else []:
        if not isinstance(message, list) or len(message) != 2:
            continue
        facts = message[1]
        stamp = facts.get("timestamp") if isinstance(facts, dict) else None
        if isinstance(stamp, (int, float)) and not isinstance(stamp, bool):
            ended = max(ended, int(stamp))
    return str(prompt_id), ended


def is_queue_empty(queue) -> bool:
    """Whether no prompt runs or waits. Pure.

    Args:
        queue: What ``GET /queue`` answered.

    Returns:
        True when ``queue_running`` and ``queue_pending`` are both empty
        lists.
    """
    if not isinstance(queue, dict):
        return False
    running = queue.get("queue_running")
    pending = queue.get("queue_pending")
    return running == [] and pending == []


def due_entry(queue, history, *, now_s: float, idle_s: int, freed: str) -> str:
    """The history entry whose idle time has passed, or nothing. Pure.

    Args:
        queue: What ``GET /queue`` answered.
        history: What ``GET /history?max_items=1`` answered.
        now_s: The time now, in seconds since the epoch.
        idle_s: The idle unload time in seconds.
        freed: The entry the last unload was sent for.

    Returns:
        The entry's prompt id when the queue is empty, the entry ended at
        least ``idle_s`` ago and no unload was sent for it; empty otherwise.
    """
    if not is_queue_empty(queue):
        return ""
    prompt_id, ended_ms = entry_end(history)
    if not prompt_id or not ended_ms or prompt_id == freed:
        return ""
    if now_s * 1000 - ended_ms < idle_s * 1000:
        return ""
    return prompt_id


class ComfyuiIdleUnload:
    """Reads ComfyUI's queue every 60 seconds and unloads its models once it has been idle long enough."""

    def __init__(
        self,
        *,
        log=print,
        call=api_call,
        clock=time.time,
        poll_s: float = COMFYUI_IDLE_POLL_S,
    ):
        """
        Args:
            log: Called with each line.
            call: Makes one call to ComfyUI's API, as :func:`api_call`.
            clock: The time now, in seconds since the epoch.
            poll_s: How often the queue is read.
        """
        self._log = log
        self._call = call
        self._clock = clock
        self._poll_s = poll_s
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._port = 0
        self._idle_s: "int | None" = None
        self._freed = ""
        self._thread: "threading.Thread | None" = None

    def take(self, port: int, idle_s: "int | None") -> None:
        """Watch ComfyUI at a port with an idle time; the thread starts at the first.

        Args:
            port: ComfyUI's port; 0 while it does not run.
            idle_s: The idle unload time in seconds; None for never.
        """
        with self._lock:
            self._port = int(port or 0)
            self._idle_s = idle_s
            if self._thread is None:
                self._thread = threading.Thread(
                    target=self._run, name="comfyui_idle_unload", daemon=True
                )
                self._thread.start()

    def stop(self) -> None:
        """Watch nothing until the next :meth:`take`."""
        with self._lock:
            self._port = 0

    def check_once(self) -> str:
        """Read the queue once, and unload the models when the newest entry has been idle long enough.

        Returns:
            The entry the unload was sent for; empty when none was sent.
        """
        with self._lock:
            port, idle_s, freed = self._port, self._idle_s, self._freed
        if not port or idle_s is None:
            return ""
        queue = self._call(port, COMFYUI_QUEUE_PATH)
        history = self._call(port, COMFYUI_HISTORY_PATH)
        prompt_id = due_entry(
            queue, history, now_s=self._clock(), idle_s=idle_s, freed=freed
        )
        if not prompt_id:
            return ""
        if self._call(port, COMFYUI_FREE_PATH, COMFYUI_FREE_BODY) is None:
            return ""
        with self._lock:
            self._freed = prompt_id
        self._log("comfyui: idle, unloaded the models")
        return prompt_id

    def _run(self) -> None:
        """The thread: one read every poll interval."""
        while True:
            self._wake.wait(self._poll_s)
            try:
                self.check_once()
            except (
                Exception
            ) as error:  # noqa: BLE001 - logged; the next read tries again
                self._log(f"comfyui: idle unload read failed: {error}")
