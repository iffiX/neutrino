"""The channel as a stream handler sees it, with the hub played by a test."""

import queue

from neutrino_agent.exceptions import StreamClosed


class FakeChannel:
    """Records what a handler sends; a test feeds what the hub would."""

    def __init__(self, stream_id: str = "2"):
        self.id = stream_id
        self.sent: list = []
        self.sent_stderr: list = []
        self.closed = None
        self.is_closed = False
        self._inbound: queue.Queue = queue.Queue()

    def recv(self, timeout=None):
        try:
            return self._inbound.get(timeout=timeout)
        except queue.Empty:
            return None

    def send_bytes(self, data: bytes) -> None:
        if self.is_closed:
            raise StreamClosed(self.id)
        self.sent.append(bytes(data))

    def send_stderr(self, data: bytes) -> None:
        if self.is_closed:
            raise StreamClosed(self.id)
        self.sent_stderr.append(bytes(data))

    def send_line(self, text: str) -> None:
        self.send_bytes((text + "\n").encode("utf-8"))

    def close(self, code: str = "", params=None) -> None:
        if self.is_closed:
            return
        self.is_closed = True
        self.closed = {"code": code, "params": dict(params or {})}

    def feed(self, item: tuple) -> None:
        """Deliver one item as the stream's connection would."""
        self._inbound.put(item)

    def close_from_hub(self, code: str = "", params=None) -> None:
        self.is_closed = True
        self._inbound.put(("close", code, dict(params or {})))

    def output(self) -> bytes:
        return b"".join(self.sent)

    def errors(self) -> bytes:
        return b"".join(self.sent_stderr)
