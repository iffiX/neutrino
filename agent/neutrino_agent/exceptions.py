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

    A ``refused`` frame, a session's end with a code, or an HTTP error whose
    ``detail`` names one; the loop splits on the code.

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


class StreamClosed(ConnectionError):
    """Raised when a stream ended under its handler, by the hub or its connection."""


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


class ModuleSetupError(ModuleApplyError):
    """Raised when a step of a module's first start fails, which ends its install.

    The module reads ``install_failed`` with the code and params, and the
    next **Install** runs the steps its record does not hold.
    """


class ModuleInstallPending(RuntimeError):
    """Raised when a module's step waits on something outside the agent.

    The module reads ``installing``, and its task runs the step again every
    30 seconds until what it waits for has happened.
    """


class StepSuperseded(RuntimeError):
    """Raised inside a step that waits for another module, once its task holds a newer entry.

    The step has done nothing yet, and the task plans again from what the
    machine shows.
    """


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
    """Raised when a package cannot be installed, removed or configured.

    Attributes:
        exit_code: The installer's exit code; None when none is known.
    """

    def __init__(self, message: str, *, exit_code: "int | None" = None):
        """
        Args:
            message: What failed, with the installer's own words.
            exit_code: The installer's exit code; None when none is known.
        """
        super().__init__(message)
        self.exit_code = exit_code


class SelfUpdateError(RuntimeError):
    """Raised when the agent's own update cannot be fetched, verified or launched."""


class ToolSwitchError(RuntimeError):
    """Raised when an account's AI tools cannot be switched or switched back.

    Attributes:
        code: The typed reason the report carries.
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


class PlatformUnsupportedError(NotImplementedError):
    """Raised when a capability this platform does not have is invoked."""

    code = "unsupported_platform"
