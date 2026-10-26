"""The AI gateway forward: how the machine's AI tools reach the hub's gateway.

The gateway answers on the hub's loopback alone, so while the state's
``ai_tools`` section says ``is_forwarded``, which the hub sends true on a
managed machine while its AI tools setting is on or a container module that
uses the gateway is installed, and false on its own machine, the agent's
transport listens on ``127.0.0.1:8317``, the endpoint the switch writes
into each tool, and opens ``connect {id: ai}`` to the hub for each
connection it accepts. The agent asks for the listener with
``forward_start`` and gives it back with ``forward_stop``. While the
transport holds no session the listener accepts nothing new and stays bound.
A port the transport cannot listen on is one line in the log, and the
listener is asked for again every report interval while a state asks for
it. The machine's containers reach the same port through the agent's relays.
The forward adds no key and reads none.

Not pure: commands the transport.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import threading

from neutrino_agent.constants import (
    AGENT_AI_ENTRY_ID,
    AGENT_AI_FORWARD_HOST,
    AGENT_AI_FORWARD_PORT,
    AGENT_CONNECT_TCP,
)
from neutrino_agent.exceptions import GatewayUnreachable
from neutrino_agent.streams import STREAM_KIND_CONNECT

COMMAND_FORWARD_START = "forward_start"
COMMAND_FORWARD_STOP = "forward_stop"


def is_forward_wanted(document: dict) -> bool:
    """Whether a state asks for the forward.

    Args:
        document: The state, ``{ai_tools, ...}``.

    Returns:
        True while its ``ai_tools`` section's ``is_forwarded`` is true.
    """
    section = document.get("ai_tools")
    if not isinstance(section, dict):
        return False
    return section.get("is_forwarded") is True


def listen_port(listen: str) -> int:
    """The port a listener's address names.

    Args:
        listen: ``host:port``.

    Returns:
        The port, 0 when the address names none.
    """
    try:
        return int(str(listen).rsplit(":", 1)[1])
    except (IndexError, ValueError):
        return 0


class AiGatewayForward:
    """The transport's loopback listener whose every connection is one
    ``connect`` stream to the hub's gateway."""

    def __init__(self, *, command, log=print, port: int = AGENT_AI_FORWARD_PORT):
        """
        Args:
            command: Called with ``(name, **fields)`` to command the
                transport; returns the answer's fields and raises
                :class:`GatewayUnreachable` while there is no transport.
            log: Callable used for progress messages.
            port: The loopback port to listen on; 0 lets the system pick.
        """
        self._command = command
        self._log = log
        self._port = port
        self._lock = threading.Lock()
        self._is_wanted = False
        # The address the transport bound, empty while it listens on none.
        self._listen = ""
        # The failure last written to the log; the same one is not written again.
        self._noted = ""

    @property
    def local_port(self) -> int:
        """The port the forward listens on, 0 while it listens on none."""
        with self._lock:
            return listen_port(self._listen)

    def take(self, document) -> None:
        """Listen while a state asks for the forward, and close otherwise.

        Args:
            document: The state; anything but a dict closes the forward.
        """
        is_wanted = isinstance(document, dict) and is_forward_wanted(document)
        with self._lock:
            self._is_wanted = is_wanted
        if is_wanted:
            self.ensure()
        else:
            self.stop()

    def ensure(self) -> None:
        """Ask the transport for the listener when the last state asked for
        the forward and none is held; a refusal is one line in the log."""
        with self._lock:
            if not self._is_wanted or self._listen:
                return
        try:
            answer = self._command(
                COMMAND_FORWARD_START,
                listen=f"{AGENT_AI_FORWARD_HOST}:{self._port}",
                protocol=AGENT_CONNECT_TCP,
                open={"kind": STREAM_KIND_CONNECT, "id": AGENT_AI_ENTRY_ID},
            )
        except GatewayUnreachable as error:
            self._note(f"AI gateway forward not asked for: {error}")
            return
        if answer.get("code"):
            self._note(
                f"AI gateway forward cannot listen on {AGENT_AI_FORWARD_HOST}:"
                f"{self._port}: {answer['code']} {answer.get('params') or {}}"
            )
            return
        listen = str(answer.get("listen", "") or "")
        if not listen:
            listen = f"{AGENT_AI_FORWARD_HOST}:{self._port}"
        with self._lock:
            self._listen = listen
            self._noted = ""
        self._log(f"AI gateway forward listening on {listen}")

    def stop(self) -> None:
        """Give the listener back to the transport, which closes it."""
        with self._lock:
            self._is_wanted = False
            listen, self._listen = self._listen, ""
        if not listen:
            return
        try:
            self._command(
                COMMAND_FORWARD_STOP, listen=listen, protocol=AGENT_CONNECT_TCP
            )
        except GatewayUnreachable:
            return
        self._log("AI gateway forward closed")

    def reset(self) -> None:
        """Forget the listener of a transport that ended; a state that asks
        for the forward gets it from the next transport."""
        with self._lock:
            self._listen = ""

    def _note(self, line: str) -> None:
        """Write a failure to the log unless it is the one written last."""
        with self._lock:
            if line == self._noted:
                return
            self._noted = line
        self._log(line)
