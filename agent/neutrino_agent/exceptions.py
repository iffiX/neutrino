"""Every exception kind the agent declares, and nothing else declares one.

A kind lives here only because a caller acts differently on it: the
connection loop tells an unreachable hub from one that refused this machine
with a code, the session answers a refused stream with the code it carries,
and a runner turns a refused configuration into a typed status. Everything
else raises the builtin that already says it.
"""


class GatewayUnreachable(ConnectionError):
    """Raised when the hub cannot be reached or answers with an error."""


class GatewayRefusedDetail(GatewayUnreachable):
    """Raised when the hub refused with ``{code, params}``.

    A ``refused`` frame, a close the hub gave a code to, or an HTTP error
    whose ``detail`` names one; the loop splits on the code.

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
    """Raised when a machine cannot join a hub, or its link is unusable.

    Attributes:
        code: The hub's refusal code, empty when the fault is on this side.
        params: What the code's wording names.
    """

    def __init__(self, message: str, *, code: str = "", params: "dict | None" = None):
        """
        Args:
            message: The words for a fault on this side; the code otherwise.
            code: The hub's refusal code.
            params: Its parameters.
        """
        super().__init__(message)
        self.code = code
        self.params = dict(params or {})


class InstallError(RuntimeError):
    """Raised when a package cannot be installed, removed or configured."""


class SelfUpdateError(RuntimeError):
    """Raised when the agent's own update cannot be fetched, verified or launched."""


class PlatformUnsupportedError(NotImplementedError):
    """Raised when a capability this platform does not have is invoked."""

    code = "unsupported_platform"
