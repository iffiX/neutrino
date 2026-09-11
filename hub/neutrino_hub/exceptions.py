"""Every exception kind the hub declares, in one table.

A kind is here only because a caller acts on it: a coded refusal the panel
answers with, a locked vault the API reports with its own status, a device
with no live channel. Everything else raises one of Python's own, and a
command that exited non-zero raises ``subprocess.CalledProcessError``.
"""


class KeyMaterialError(ValueError):
    """Raised when pasted key material cannot be used.

    Attributes:
        code: Machine name of the refusal; the panel does the wording.
        params: The values the refusal's sentence needs.
    """

    def __init__(self, code: str, params: dict | None = None):
        super().__init__(code)
        self.code = code
        self.params = params or {}


class PasswordRefusedError(ValueError):
    """Raised when a password does not satisfy its rule set.

    Attributes:
        code: Machine name of the refusal; the askers do the wording.
        params: The values the refusal's sentence needs.
    """

    def __init__(self, code: str, params: dict | None = None):
        super().__init__(code)
        self.code = code
        self.params = params or {}


class ServiceFieldInvalidError(ValueError):
    """Raised when a declared service carries a field that cannot be stored.

    Attributes:
        code: Machine name of the refusal; the pages do the wording.
        params: The values the refusal's sentence needs.
    """

    def __init__(self, code: str, params: dict | None = None):
        super().__init__(code)
        self.code = code
        self.params = params or {}


class VaultLockedError(ValueError):
    """Raised when the vault's data key state file is missing.

    Attributes:
        code: The machine name callers answer with.
    """

    code = "vault_locked"

    def __init__(self):
        super().__init__("the vault is locked: no data key on this box")


class VaultPassphraseError(ValueError):
    """Raised when a passphrase does not open what it was offered."""


class AgentOfflineError(ConnectionError):
    """Raised when a device has no live channel.

    Attributes:
        code: The machine name callers answer with.
        params: The device the channel was wanted for.
    """

    code = "agent_offline"

    def __init__(self, device: str):
        super().__init__(device)
        self.params = {"device": device}


class StreamRefusedError(ConnectionError):
    """Raised when an agent will not open a stream, or never answers.

    Attributes:
        code: The typed reason, for every surface to word.
        params: What the wording names.
    """

    def __init__(self, code: str, params: "dict | None" = None):
        super().__init__(code)
        self.code = code
        self.params = dict(params or {})


class AgentArtifactFetchError(RuntimeError):
    """Raised when an agent package or module artifact cannot be produced.

    Attributes:
        code: The typed reason, for every surface to word.
        params: What the wording names.
    """

    def __init__(self, code: str, **params):
        super().__init__(code)
        self.code = code
        self.params = params


class AiAccountRefusedError(RuntimeError):
    """Raised when the AI gateway will not carry out an account action.

    Attributes:
        code: What the panel words, one of ``gateway_unreachable``,
            ``login_expired``, ``unsupported_kind``, ``unknown_account`` or
            ``management_key_missing``.
        params: What the wording needs, by name.
    """

    def __init__(self, code: str, **params):
        super().__init__(code)
        self.code = code
        self.params = params


class WizardAborted(RuntimeError):
    """Raised when the wizard cannot go on.

    A refused answer, an answers document it cannot use, or nothing to read
    from.
    """
