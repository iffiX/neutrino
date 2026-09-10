"""Every exception kind the agent declares, and nothing else declares one.

A kind lives here only because a caller acts differently on it: the
connection loop tells an unreachable hub from one that refused this token,
the session answers a refused stream with the code it carries, and a runner
turns a refused configuration into a typed status. Everything else raises
the builtin that already says it.
"""


class GatewayUnreachable(ConnectionError):
    """Raised when the hub cannot be reached or answers with an error."""


class GatewayRefusedDetail(GatewayUnreachable):
    """Raised when the hub refused a request with a typed reason of its own.

    Attributes:
        code: The hub's own code.
        params: What its wording names.
    """

    def __init__(self, *, code: str, params: dict):
        """
        Args:
            code: The hub's code.
            params: Its parameters.
        """
        super().__init__(code)
        self.code = code
        self.params = params


class GatewayUntrusted(ConnectionError):
    """Raised when the peer's certificate does not match the pinned one.

    Nothing was sent: the check runs on the peer certificate before any
    request bytes leave the machine.
    """


class SocketClosed(ConnectionError):
    """Raised when the hub sent a close frame.

    Attributes:
        code: The close code, 1005 when the close frame carried none.
        reason: The reason text.
    """

    def __init__(self, code: int, reason: str = ""):
        """
        Args:
            code: The close code.
            reason: The reason text.
        """
        super().__init__(f"socket closed ({code}) {reason}".rstrip())
        self.code = code
        self.reason = reason


class StreamClosed(ConnectionError):
    """Raised when a stream ended under its handler, by the hub or the socket."""


class GatewayRefused(PermissionError):
    """Raised when the hub answered but rejected this machine's token."""


class GatewayVersionRefused(GatewayRefused):
    """Raised when the hub turned this agent away as newer than itself.

    Attributes:
        hub_version: What the hub reported itself as.
        agent_version: What this agent reported itself as.
    """

    def __init__(self, *, hub_version: str, agent_version: str):
        """
        Args:
            hub_version: What the hub reported itself as.
            agent_version: What this agent reported itself as.
        """
        super().__init__(
            f"this agent ({agent_version}) is newer than the hub "
            f"({hub_version}); update the hub first"
        )
        self.hub_version = hub_version
        self.agent_version = agent_version


class GatewayWireStale(GatewayRefused):
    """Raised when the hub says this agent's wire generation is not its own.

    Attributes:
        hub_wire: The generation the hub serves.
        agent_wire: The generation this agent was built to.
    """

    def __init__(self, *, hub_wire: int, agent_wire: int):
        """
        Args:
            hub_wire: The generation the hub serves.
            agent_wire: The generation this agent was built to.
        """
        super().__init__(
            f"this agent speaks wire generation {agent_wire}, the hub "
            f"generation {hub_wire}; it reinstalls itself from the hub"
        )
        self.hub_wire = hub_wire
        self.agent_wire = agent_wire


class StreamRefused(ValueError):
    """Raised when a stream handler will not serve the stream it was opened for.

    Attributes:
        code: The typed refusal.
        params: What the wording names.
    """

    def __init__(self, code: str, params: "dict | None" = None):
        """
        Args:
            code: The typed refusal.
            params: What the wording names.
        """
        super().__init__(code)
        self.code = code
        self.params = dict(params or {})


class ModuleApplyError(ValueError):
    """Raised when a module refuses a configuration or cannot make it true.

    Attributes:
        code: The typed reason.
        params: What the wording names.
    """

    def __init__(self, code: str, params: "dict | None" = None):
        """
        Args:
            code: The typed reason.
            params: What the wording names.
        """
        super().__init__(code)
        self.code = code
        self.params = dict(params or {})


class EnrollmentError(RuntimeError):
    """Raised when a machine cannot join a gateway."""


class InstallError(RuntimeError):
    """Raised when a package cannot be installed, removed or configured."""


class SelfUpdateError(RuntimeError):
    """Raised when the agent's own update cannot be fetched, verified or launched."""


class PlatformUnsupportedError(NotImplementedError):
    """Raised when a capability this platform does not have is invoked."""

    code = "unsupported_platform"
