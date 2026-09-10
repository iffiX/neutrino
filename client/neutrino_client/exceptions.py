"""The client's own exception kinds, declared here and nowhere else.

Each kind subclasses the builtin closest to what happened, so a caller that
knows nothing of this package still catches it by that builtin. The gateway
kinds are the copy the agent keeps of the same channel; the typed refusals
carry the ``code`` and the parameters their surface words.
"""


class GatewayUnreachable(ConnectionError):
    """Raised when the hub cannot be reached or answers with an error."""


class GatewayRefusedDetail(GatewayUnreachable):
    """Raised when the hub refused a request with a typed reason.

    Not about the binding: the hub answered about the thing that was asked
    for, and the caller words it.

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
    """Raised when the peer's certificate does not match the pinned fingerprint.

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


class GatewayRefused(PermissionError):
    """Raised when the hub answered but rejected this client's token."""


class GatewayVersionRefused(GatewayRefused):
    """Raised when the hub turned this client away as newer than itself.

    Attributes:
        hub_version: What the hub reported itself as.
        client_version: What this client reported itself as.
    """

    def __init__(self, *, hub_version: str, client_version: str):
        """
        Args:
            hub_version: What the hub reported itself as.
            client_version: What this client reported itself as.
        """
        super().__init__(
            f"this client ({client_version}) is newer than the hub "
            f"({hub_version}); update the hub first"
        )
        self.hub_version = hub_version
        self.client_version = client_version


class ShareAttachError(OSError):
    """Raised when a share cannot be attached or detached.

    Attributes:
        code: The typed reason.
        detail: The tool's own words, for the failure's params.
    """

    def __init__(self, code: str, detail: str = ""):
        """
        Args:
            code: The typed reason.
            detail: The tool's own words, for the failure's params.
        """
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


class PlatformUnsupportedError(NotImplementedError):
    """Raised when a capability this platform does not have is invoked."""

    code = "unsupported_platform"


class ControlSocketUnavailableError(PlatformUnsupportedError):
    """Raised when the platform cannot say where the control socket lives."""

    code = "control_socket_unavailable"


class EnrollmentError(RuntimeError):
    """Raised when this person cannot join a hub.

    Attributes:
        code: The typed reason.
        params: What its wording names.
    """

    def __init__(self, code: str, params: "dict | None" = None):
        """
        Args:
            code: The typed reason.
            params: Its parameters.
        """
        super().__init__(code)
        self.code = code
        self.params = dict(params or {})


class GuiShellUnavailableError(RuntimeError):
    """Raised when the platform's web view cannot be loaded.

    Attributes:
        code: The typed refusal code.
        params: The code's parameters.
    """

    def __init__(self, code: str, params: "dict | None" = None):
        """
        Args:
            code: The typed refusal code.
            params: The code's parameters.
        """
        super().__init__(code)
        self.code = code
        self.params = dict(params or {})


class ToolSwitchError(RuntimeError):
    """Raised when cc-switch refuses, or a configuration cannot be kept."""
