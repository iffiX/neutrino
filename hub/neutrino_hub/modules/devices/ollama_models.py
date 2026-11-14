"""A machine's Ollama models, read and changed through Ollama's own API.

The hub reaches the API through a forward of its transport on its own
loopback (``hub_forwards.py``) with a plain HTTP client: ``/api/tags`` and
``/api/ps`` list, ``/api/delete`` removes, ``/api/generate`` with
``keep_alive`` 0 unloads, and ``/api/pull`` streams a pull's progress as
JSON lines. A pull is a background task of the hub's: one at a time per
machine, in the order asked, each further pull waiting behind the running
one, its progress the sum of every layer's bytes. Nothing here is kept on
disk: a hub that restarts forgets its queue, and Ollama keeps the layers a
cut pull fetched.

Not pure: holds connections and threads.
"""

import http.client
import json
import operator
import re
import threading
import time
from dataclasses import dataclass, field

from neutrino_hub.modules.devices.constants import (
    DEVICE_OLLAMA_CALL_TIMEOUT_S,
    DEVICE_OLLAMA_MODEL_NAME_PATTERN,
    DEVICE_OLLAMA_PULL_FAILED,
    DEVICE_OLLAMA_PULL_QUEUED,
    DEVICE_OLLAMA_PULL_READ_TIMEOUT_S,
    DEVICE_OLLAMA_PULL_RUNNING,
    DEVICE_OLLAMA_SPEED_WINDOW_S,
)

# The words a refused name and a failed pull carry, as the panel words them.
CODE_PULL_FAILED = "ollama_pull_failed"
CODE_UNREACHABLE = "ollama_unreachable"
# The most of Ollama's own words a failure carries.
DETAIL_LIMIT = 300

_NAME = re.compile(DEVICE_OLLAMA_MODEL_NAME_PATTERN + r"\Z")


def is_model_name(name: str) -> bool:
    """Whether a name is one the pull form takes. Pure.

    Args:
        name: The name.

    Returns:
        True for a letter or a digit first, then letters, digits and
        ``._-:/``, at most 200 characters, and no ``..``.
    """
    return bool(_NAME.match(name or "")) and ".." not in name


def model_rows(tags: dict, ps: dict) -> list:
    """The pulled models joined with the ones in memory. Pure.

    Args:
        tags: ``/api/tags``'s answer.
        ps: ``/api/ps``'s answer.

    Returns:
        ``{name, parameter_size, quantization, size_bytes, modified_at,
        is_loaded, memory_bytes, vram_bytes}`` per model, by name.
    """
    loaded = {}
    for model in ps.get("models") or []:
        if isinstance(model, dict):
            loaded[str(model.get("name", "") or model.get("model", ""))] = model
    rows = []
    for model in tags.get("models") or []:
        if not isinstance(model, dict):
            continue
        name = str(model.get("name", "") or model.get("model", ""))
        details = model.get("details") if isinstance(model.get("details"), dict) else {}
        in_memory = loaded.get(name)
        rows.append(
            {
                "name": name,
                "parameter_size": str(details.get("parameter_size", "") or ""),
                "quantization": str(details.get("quantization_level", "") or ""),
                "size_bytes": _bytes(model.get("size")),
                "modified_at": str(model.get("modified_at", "") or ""),
                "is_loaded": in_memory is not None,
                "memory_bytes": _bytes((in_memory or {}).get("size")),
                "vram_bytes": _bytes((in_memory or {}).get("size_vram")),
            }
        )
    return sorted(rows, key=operator.itemgetter("name"))


def pull_progress(layers: dict) -> tuple:
    """A pull's bytes done and its total, over every layer named so far. Pure.

    Args:
        layers: Each layer's ``(completed, total)`` by digest.

    Returns:
        ``(completed, total)``.
    """
    completed = sum(done for done, _total in layers.values())
    total = sum(whole for _done, whole in layers.values())
    return completed, total


class OllamaApiClient:
    """Ollama's API at one address, one request per connection."""

    def __init__(
        self, address: str, *, timeout_s: float = DEVICE_OLLAMA_CALL_TIMEOUT_S
    ):
        """
        Args:
            address: ``host:port`` the API is reached at.
            timeout_s: How long a call waits for an answer.
        """
        host, _, port = address.rpartition(":")
        self._host = host
        self._port = int(port)
        self._timeout_s = timeout_s

    def tags(self) -> dict:
        """``/api/tags``: the pulled models.

        Raises:
            ConnectionError: When the API does not answer.
        """
        return self._call("GET", "/api/tags")

    def ps(self) -> dict:
        """``/api/ps``: the models in memory.

        Raises:
            ConnectionError: When the API does not answer.
        """
        return self._call("GET", "/api/ps")

    def delete(self, name: str) -> None:
        """``/api/delete`` for one model.

        Args:
            name: The model.

        Raises:
            KeyError: When the machine has no such model.
            ConnectionError: When the API does not answer.
        """
        self._call("DELETE", "/api/delete", {"model": name}, missing=name)

    def unload(self, name: str) -> None:
        """``/api/generate`` with ``keep_alive`` 0, which takes the model out of memory.

        Args:
            name: The model.

        Raises:
            KeyError: When the machine has no such model.
            ConnectionError: When the API does not answer.
        """
        self._call(
            "POST",
            "/api/generate",
            {"model": name, "keep_alive": 0, "stream": False},
            missing=name,
        )

    def pull(self, name: str, *, on_line, on_open=None) -> None:
        """``/api/pull`` for one model, each line of its progress handed on.

        Args:
            name: The model.
            on_line: Called with each JSON line Ollama streams.
            on_open: Called with the connection once the request is sent, so
                another thread can close it.

        Raises:
            ConnectionError: When the API does not answer, the connection
                ends before ``success``, or Ollama names an error.
        """
        connection = http.client.HTTPConnection(
            self._host, self._port, timeout=DEVICE_OLLAMA_PULL_READ_TIMEOUT_S
        )
        try:
            if on_open is not None:
                on_open(connection)
            body = json.dumps({"model": name, "stream": True}).encode("utf-8")
            connection.request(
                "POST", "/api/pull", body, {"Content-Type": "application/json"}
            )
            answer = connection.getresponse()
            if answer.status != 200:
                raise ConnectionError(_said(answer.read()) or f"http {answer.status}")
            is_done = False
            for raw in answer:
                line = _line(raw)
                if line is None:
                    continue
                if line.get("error"):
                    raise ConnectionError(str(line["error"])[:DETAIL_LIMIT])
                on_line(line)
                if line.get("status") == "success":
                    is_done = True
            if not is_done:
                raise ConnectionError("the pull ended before success")
        except (OSError, http.client.HTTPException) as error:
            raise ConnectionError(str(error)[:DETAIL_LIMIT] or type(error).__name__)
        finally:
            connection.close()

    def _call(self, method: str, path: str, body=None, *, missing: str = "") -> dict:
        """One request and its JSON answer.

        Raises:
            KeyError: On a 404 for a call that names a model.
            ConnectionError: When the API does not answer, or answers an error.
        """
        connection = http.client.HTTPConnection(
            self._host, self._port, timeout=self._timeout_s
        )
        try:
            payload = json.dumps(body).encode("utf-8") if body is not None else None
            headers = {"Content-Type": "application/json"} if body is not None else {}
            connection.request(method, path, payload, headers)
            answer = connection.getresponse()
            data = answer.read()
        except (OSError, http.client.HTTPException) as error:
            raise ConnectionError(str(error)[:DETAIL_LIMIT] or type(error).__name__)
        finally:
            connection.close()
        if answer.status == 404 and missing:
            raise KeyError(missing)
        if answer.status != 200:
            raise ConnectionError(_said(data) or f"http {answer.status}")
        try:
            decoded = json.loads(data.decode("utf-8")) if data.strip() else {}
        except ValueError:
            return {}
        return decoded if isinstance(decoded, dict) else {}


@dataclass
class OllamaPull:
    """One pull in a machine's queue.

    Attributes:
        name: The model.
        state: ``queued``, ``running`` or ``failed``.
        completed_bytes: The bytes fetched over every layer named so far.
        total_bytes: The bytes of every layer named so far.
        speed_bytes: The bytes per second of the last few seconds.
        code: Why it failed; empty otherwise.
        params: What the code's words name.
    """

    name: str
    state: str = DEVICE_OLLAMA_PULL_QUEUED
    completed_bytes: int = 0
    total_bytes: int = 0
    speed_bytes: int = 0
    code: str = ""
    params: dict = field(default_factory=dict)

    def view(self) -> dict:
        """What the panel draws of the pull.

        Returns:
            Every attribute by name.
        """
        return {
            "name": self.name,
            "state": self.state,
            "completed_bytes": self.completed_bytes,
            "total_bytes": self.total_bytes,
            "speed_bytes": self.speed_bytes,
            "code": self.code,
            "params": dict(self.params),
        }


class OllamaPullQueue:
    """Every machine's pulls, one running at a time per machine, on a thread of its own."""

    def __init__(
        self,
        *,
        address_of,
        client_class=OllamaApiClient,
        clock=time.monotonic,
        on_pulled=None,
    ):
        """
        Args:
            address_of: Called with a device id; returns the address its
                Ollama's API is reached at, raising ``ConnectionError`` when
                it cannot be reached.
            client_class: Makes the client for an address.
            clock: The monotonic clock a pull's speed is measured on.
            on_pulled: Called with the device id after a pull succeeds.
        """
        self._address_of = address_of
        self._on_pulled = on_pulled
        self._client_class = client_class
        self._clock = clock
        self._lock = threading.Lock()
        # Each machine's pulls in the order asked, by device id.
        self._queues: dict = {}
        # The connection of each machine's running pull, by device id.
        self._connections: dict = {}
        # The machines a worker thread serves now.
        self._workers: set = set()

    def pulls(self, device_id: str) -> list:
        """One machine's pulls, the running one first.

        Args:
            device_id: The machine.

        Returns:
            Each pull's view, in the queue's order.
        """
        with self._lock:
            return [pull.view() for pull in self._queues.get(device_id, [])]

    def is_busy(self, device_id: str) -> bool:
        """Whether a pull of the machine runs or waits.

        Args:
            device_id: The machine.

        Returns:
            True while one is running or queued.
        """
        with self._lock:
            return any(
                pull.state != DEVICE_OLLAMA_PULL_FAILED
                for pull in self._queues.get(device_id, [])
            )

    def add(self, device_id: str, name: str) -> None:
        """Put a pull at the end of the machine's queue, a failed one of the name dropped first.

        A name already running or waiting is left where it is.

        Args:
            device_id: The machine.
            name: The model.
        """
        with self._lock:
            queue = self._queues.setdefault(device_id, [])
            queue[:] = [
                pull
                for pull in queue
                if not (pull.name == name and pull.state == DEVICE_OLLAMA_PULL_FAILED)
            ]
            if not any(pull.name == name for pull in queue):
                queue.append(OllamaPull(name=name))
            if device_id in self._workers:
                return
            self._workers.add(device_id)
        threading.Thread(
            target=self._serve,
            args=(device_id,),
            name=f"ollama_pull_{device_id}",
            daemon=True,
        ).start()

    def cancel(self, device_id: str, name: str) -> bool:
        """End a running pull, or take a waiting or failed one off the queue.

        Args:
            device_id: The machine.
            name: The model.

        Returns:
            Whether the queue held the pull.
        """
        with self._lock:
            queue = self._queues.get(device_id, [])
            held = next((pull for pull in queue if pull.name == name), None)
            if held is None:
                return False
            queue.remove(held)
            connection = (
                self._connections.get(device_id)
                if held.state == DEVICE_OLLAMA_PULL_RUNNING
                else None
            )
        if connection is not None:
            _close(connection)
        return True

    def _serve(self, device_id: str) -> None:
        """Run the machine's pulls one after another until none waits."""
        while True:
            with self._lock:
                queue = self._queues.get(device_id, [])
                pull = next(
                    (held for held in queue if held.state == DEVICE_OLLAMA_PULL_QUEUED),
                    None,
                )
                if pull is None:
                    self._workers.discard(device_id)
                    return
                pull.state = DEVICE_OLLAMA_PULL_RUNNING
            self._run(device_id, pull)

    def _run(self, device_id: str, pull: OllamaPull) -> None:
        """Run one pull to its end, keeping its progress; a failure stays in the queue."""
        layers: dict = {}
        marks: list = []

        def take(line: dict) -> None:
            digest = str(line.get("digest", "") or "")
            if digest and isinstance(line.get("total"), int):
                layers[digest] = (
                    _bytes(line.get("completed")),
                    _bytes(line.get("total")),
                )
            completed, total = pull_progress(layers)
            now = self._clock()
            marks.append((now, completed))
            while marks and now - marks[0][0] > DEVICE_OLLAMA_SPEED_WINDOW_S:
                marks.pop(0)
            span = now - marks[0][0]
            speed = int((completed - marks[0][1]) / span) if span > 0 else 0
            with self._lock:
                pull.completed_bytes = completed
                pull.total_bytes = total
                pull.speed_bytes = max(0, speed)

        def opened(connection) -> None:
            with self._lock:
                self._connections[device_id] = connection

        try:
            client = self._client_class(self._address_of(device_id))
            client.pull(pull.name, on_line=take, on_open=opened)
        except (ConnectionError, OSError, ValueError) as error:
            with self._lock:
                self._connections.pop(device_id, None)
                if pull in self._queues.get(device_id, []):
                    pull.state = DEVICE_OLLAMA_PULL_FAILED
                    pull.code = CODE_PULL_FAILED
                    pull.params = {
                        "name": pull.name,
                        "detail": str(error)[:DETAIL_LIMIT],
                    }
            return
        with self._lock:
            self._connections.pop(device_id, None)
            queue = self._queues.get(device_id, [])
            if pull in queue:
                queue.remove(pull)
        if self._on_pulled is not None:
            self._on_pulled(device_id)


def _close(connection) -> None:
    """Close a pull's connection from another thread, ending its read."""
    sock = getattr(connection, "sock", None)
    try:
        if sock is not None:
            sock.shutdown(2)
    except OSError:
        pass
    try:
        connection.close()
    except OSError:
        pass


def _bytes(value) -> int:
    """A byte count, 0 for anything that is not one."""
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return max(0, value)


def _line(raw: bytes) -> "dict | None":
    """One JSON line of a stream, None for a blank or broken one."""
    text = raw.strip()
    if not text:
        return None
    try:
        decoded = json.loads(text.decode("utf-8"))
    except ValueError:
        return None
    return decoded if isinstance(decoded, dict) else None


def _said(data: bytes) -> str:
    """Ollama's own words in an error answer: its ``error``, else the body."""
    text = data.decode("utf-8", "replace").strip()
    try:
        decoded = json.loads(text)
    except ValueError:
        return text[:DETAIL_LIMIT]
    if isinstance(decoded, dict) and decoded.get("error"):
        return str(decoded["error"])[:DETAIL_LIMIT]
    return text[:DETAIL_LIMIT]
