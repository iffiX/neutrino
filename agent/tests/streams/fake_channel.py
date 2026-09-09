"""The channel as a stream handler sees it, with the hub played by a test."""

import queue

from neutrino_agent.streams.channel import StreamClosed


class FakeChannel:
    """Records what a handler sends; a test feeds what the hub would."""

    def __init__(self, stream_id: str = "00000001"):
        self.id = stream_id
        self.sent: list = []
        self.events: list = []
        self.credits: list = []
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

    def offer_credit(self, size: int) -> None:
        self.credits.append(int(size))

    def event(self, **fields) -> None:
        self.events.append(dict(fields))

    def feed(self, item: tuple) -> None:
        """Deliver one item as the session would."""
        self._inbound.put(item)

    def close_from_hub(self) -> None:
        self.is_closed = True
        self._inbound.put(("close",))

    def output(self) -> bytes:
        return b"".join(self.sent)
