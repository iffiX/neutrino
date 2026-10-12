"""The Codeg module's configuration: which accounts run it, on which port.

Each instance is one account's Codeg behind the agent's forwarder on one
port. The hub sends each instance's token secret, which signs the one-time
tokens a client opens the instance with, derives the token Codeg's own
page keeps and keys the forwarder's login cookie. On Windows an instance also carries the account's password,
from the login the hub holds for it, because a task that runs as an account
needs its password to sign in.

Pure: parsing, validation and what follows from the values.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import base64
import hashlib
import hmac
import re
from dataclasses import dataclass, field

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.codeg.constants import (
    CODEG_COOKIE_LABEL,
    CODEG_PORT_MAX,
    CODEG_PORT_MIN,
    CODEG_SUBPROTOCOL_PREFIX,
    CODEG_TOKEN_LABEL,
)

# An account name that survives a unit name, a launchd label, a task name
# and a command line.
ACCOUNT_PATTERN = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}\Z")


def instance_token(secret: str) -> str:
    """The token Codeg checks every call with, derived from the instance's secret.

    Args:
        secret: The instance's token secret.

    Returns:
        ``base64url(HMAC-SHA256(secret, label))`` without padding, handed to
        Codeg as ``CODEG_TOKEN`` and kept by its page.
    """
    digest = hmac.new(secret.encode("utf-8"), CODEG_TOKEN_LABEL, hashlib.sha256)
    return base64.urlsafe_b64encode(digest.digest()).rstrip(b"=").decode("ascii")


def subprotocol_of(token: str) -> str:
    """The WebSocket subprotocol Codeg's page carries the token in.

    Args:
        token: The instance token.

    Returns:
        ``codeg-token.`` and the token's bytes as base64url without padding.
    """
    encoded = base64.urlsafe_b64encode(token.encode("utf-8")).rstrip(b"=")
    return CODEG_SUBPROTOCOL_PREFIX + encoded.decode("ascii")


def cookie_key(secret: str) -> bytes:
    """The key the forwarder's login cookie is signed with, derived from the instance's secret.

    Args:
        secret: The instance's token secret.

    Returns:
        32 bytes.
    """
    return hmac.new(secret.encode("utf-8"), CODEG_COOKIE_LABEL, hashlib.sha256).digest()


@dataclass
class CodegInstance:
    """One account's Codeg.

    Attributes:
        account: The account it runs as.
        port: The port the forwarder listens on.
        secret: The secret a token for this instance is signed with.
        password: The account's password; Windows only.
    """

    account: str
    port: int
    secret: str = ""
    password: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "CodegInstance":
        try:
            port = int(data.get("port", 0))
        except (TypeError, ValueError):
            port = 0
        return cls(
            account=str(data.get("account", "") or ""),
            port=port,
            secret=str(data.get("secret", "") or ""),
            password=str(data.get("password", "") or ""),
        )


@dataclass
class CodegConfig:
    """Everything the module's desired configuration holds.

    Attributes:
        instances: One Codeg per account.
    """

    instances: list = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "CodegConfig":
        instances = data.get("instances")
        return cls(
            instances=[
                CodegInstance.from_dict(entry)
                for entry in (instances if isinstance(instances, list) else [])
                if isinstance(entry, dict)
            ]
        )

    def validate(self, *, os_name: str = "linux") -> None:
        """Check the configuration holds together.

        Args:
            os_name: The system the instances run on; on ``windows`` every
                instance needs its account's password.

        Raises:
            ModuleApplyError: ``account_invalid``, ``account_duplicate``,
                ``port_invalid``, ``port_duplicate`` or ``secret_missing``,
                naming the first problem found, and on Windows
                ``credential_missing`` for an instance with no password.
        """
        accounts: set = set()
        ports: set = set()
        for instance in self.instances:
            if not ACCOUNT_PATTERN.match(instance.account):
                raise ModuleApplyError("account_invalid", {"account": instance.account})
            if instance.account.lower() in accounts:
                raise ModuleApplyError(
                    "account_duplicate", {"account": instance.account}
                )
            accounts.add(instance.account.lower())
            if not CODEG_PORT_MIN <= instance.port <= CODEG_PORT_MAX:
                raise ModuleApplyError("port_invalid", {"port": instance.port})
            if instance.port in ports:
                raise ModuleApplyError("port_duplicate", {"port": instance.port})
            ports.add(instance.port)
            if not instance.secret:
                raise ModuleApplyError("secret_missing", {"account": instance.account})
            if os_name == "windows" and not instance.password:
                raise ModuleApplyError(
                    "credential_missing", {"account": instance.account}
                )
