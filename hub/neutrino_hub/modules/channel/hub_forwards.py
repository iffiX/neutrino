"""The hub's forwards on its own loopback, each to a port a machine publishes.

The hub's transport listens on ``127.0.0.1`` at a port the system picks and
opens a ``connect`` on a binding's session for each connection, when the
Python asks with ``forward_start`` (transport.md, "The hub's local
channel"). The table keeps the address each forward listens on, by binding
and port, so a plain HTTP client on the hub reaches the machine's service at
it. A forward lasts while the control connection that started it is open,
so a new control connection forgets every one.

Not pure: sends commands to the transport.
"""

import asyncio
import concurrent.futures
import threading

from neutrino_hub.exceptions import AgentOfflineError, StreamRefusedError
from neutrino_hub.modules.channel.constants import (
    CHANNEL_COMMAND_FORWARD_START,
    CHANNEL_COMMAND_FORWARD_STOP,
    CHANNEL_CONTROL_COMMAND_TIMEOUT_S,
    CHANNEL_FORWARD_LISTEN,
)


class HubForwardTable:
    """The forwards the hub's transport holds for the Python, by binding and port."""

    def __init__(self, *, channel):
        """
        Args:
            channel: The :class:`LocalChannelClient` the commands go through.
        """
        self._channel = channel
        self._lock = threading.Lock()
        # Each forward's listen address, by ``(binding_id, port)``.
        self._forwards: dict = {}

    def address(self, binding_id: str, port: int) -> str:
        """The address the forward to one machine's port listens on, started first when there is none.

        Call from a thread other than the channel's loop.

        Args:
            binding_id: The machine's binding.
            port: The port the machine publishes.

        Returns:
            ``127.0.0.1:<port>`` on the hub.

        Raises:
            AgentOfflineError: When the transport is not reached.
            StreamRefusedError: With the transport's code.
        """
        key = (binding_id, int(port))
        with self._lock:
            held = self._forwards.get(key)
            if held:
                return held
            answer = self._command(
                CHANNEL_COMMAND_FORWARD_START,
                binding_id=binding_id,
                listen=CHANNEL_FORWARD_LISTEN,
                protocol="tcp",
                open={"kind": "connect", "port": int(port), "protocol": "tcp"},
            )
            listen = str(answer.get("listen", "") or "")
            if not listen:
                raise AgentOfflineError(binding_id)
            self._forwards[key] = listen
            return listen

    def stop(self, binding_id: str, port: int) -> bool:
        """Stop the forward to one machine's port, if there is one.

        Call from a thread other than the channel's loop.

        Args:
            binding_id: The machine's binding.
            port: The port.

        Returns:
            Whether a forward was held.
        """
        key = (binding_id, int(port))
        with self._lock:
            listen = self._forwards.pop(key, "")
            if not listen:
                return False
            try:
                self._command(
                    CHANNEL_COMMAND_FORWARD_STOP, listen=listen, protocol="tcp"
                )
            except (AgentOfflineError, StreamRefusedError):
                pass
            return True

    def is_held(self, binding_id: str, port: int) -> bool:
        """Whether a forward to one machine's port is held.

        Args:
            binding_id: The machine's binding.
            port: The port.

        Returns:
            True while the table holds one.
        """
        with self._lock:
            return (binding_id, int(port)) in self._forwards

    def forget_all(self) -> None:
        """Forget every forward: a new control connection finds none."""
        with self._lock:
            self._forwards.clear()

    def _command(self, command: str, **fields) -> dict:
        """Send one command on the channel's loop and wait for its answer.

        Raises:
            AgentOfflineError: When the channel runs on no loop yet.
            StreamRefusedError: With the transport's code.
        """
        loop = self._channel.loop
        if loop is None:
            raise AgentOfflineError("")
        future = asyncio.run_coroutine_threadsafe(
            self._channel.send_command(command, **fields), loop
        )
        try:
            return future.result(CHANNEL_CONTROL_COMMAND_TIMEOUT_S + 1)
        except concurrent.futures.TimeoutError:
            future.cancel()
            raise StreamRefusedError("control_unavailable", {})
