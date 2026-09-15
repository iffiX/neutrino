"""The channel as a stream handler sees it, with the hub played by a test.

The fake holds the handler to the credit it offered: a data item is taken
off the queue only while the bytes taken so far fit inside the credit
granted so far, the way the hub would never have sent past it.
"""

import queue

from neutrino_agent.exceptions import StreamClosed


class FakeChannel:
    """Records what a handler sends; a test feeds what the hub would."""

    def __init__(self, stream_id: int = 2):
        self.id = stream_id
        self.sent: list = []
        self.credits: list = []
        self.closed = None
        self.is_closed = False
        self.taken = 0
        self._inbound: queue.Queue = queue.Queue()

    def recv(self, timeout=None):
        try:
            item = self._inbound.get(timeout=timeout)
        except queue.Empty:
            return None
        if item[0] == "data":
            self.taken += len(item[1])
            assert self.taken <= sum(self.credits), "bytes past the credit offered"
        return item

    def send_bytes(self, data: bytes) -> None:
        if self.is_closed:
            raise StreamClosed(self.id)
        self.sent.append(bytes(data))

    def send_line(self, text: str) -> None:
        self.send_bytes((text + "\n").encode("utf-8"))

    def offer_credit(self, size: int) -> None:
        self.credits.append(int(size))

    def close(self, code: str = "", params=None) -> None:
        if self.is_closed:
            return
        self.is_closed = True
        self.closed = {"code": code, "params": dict(params or {})}

    def feed(self, item: tuple) -> None:
        """Deliver one item as the session would."""
        self._inbound.put(item)

    def close_from_hub(self, code: str = "", params=None) -> None:
        self.is_closed = True
        self._inbound.put(("close", code, dict(params or {})))

    def output(self) -> bytes:
        return b"".join(self.sent)
