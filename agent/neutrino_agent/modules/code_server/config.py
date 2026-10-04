"""The code-server module's configuration: which accounts run it, on which port.

Each instance is one account's code-server behind the agent's forwarder on
one port. The hub sends each instance's token secret, which signs the
one-time tokens a client opens the instance with and keys the forwarder's
login cookie.

Pure: parsing, validation and what follows from the values.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass, field

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.code_server.constants import (
    CODE_SERVER_COOKIE_LABEL,
    CODE_SERVER_PORT_MAX,
    CODE_SERVER_PORT_MIN,
)

# An account name that survives a unit name, a launchd label, a path and a
# command line.
ACCOUNT_PATTERN = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}\Z")


def cookie_key(secret: str) -> bytes:
    """The key the forwarder's login cookie is signed with, derived from the instance's secret.

    Args:
        secret: The instance's token secret.

    Returns:
        32 bytes.
    """
    return hmac.new(
        secret.encode("utf-8"), CODE_SERVER_COOKIE_LABEL, hashlib.sha256
    ).digest()


@dataclass
class CodeServerInstance:
    """One account's code-server.

    Attributes:
        account: The account it runs as.
        port: The port the forwarder listens on.
        secret: The secret a token for this instance is signed with.
    """

    account: str
    port: int
    secret: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "CodeServerInstance":
        try:
            port = int(data.get("port", 0))
        except (TypeError, ValueError):
            port = 0
        return cls(
            account=str(data.get("account", "") or ""),
            port=port,
            secret=str(data.get("secret", "") or ""),
        )


@dataclass
class CodeServerConfig:
    """Everything the module's desired configuration holds.

    Attributes:
        instances: One code-server per account.
    """

    instances: list = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "CodeServerConfig":
        instances = data.get("instances")
        return cls(
            instances=[
                CodeServerInstance.from_dict(entry)
                for entry in (instances if isinstance(instances, list) else [])
                if isinstance(entry, dict)
            ]
        )

    def validate(self) -> None:
        """Check the configuration holds together.

        Raises:
            ModuleApplyError: ``account_invalid``, ``account_duplicate``,
                ``port_invalid``, ``port_duplicate`` or ``secret_missing``,
                naming the first problem found.
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
            if not CODE_SERVER_PORT_MIN <= instance.port <= CODE_SERVER_PORT_MAX:
                raise ModuleApplyError("port_invalid", {"port": instance.port})
            if instance.port in ports:
                raise ModuleApplyError("port_duplicate", {"port": instance.port})
            ports.add(instance.port)
            if not instance.secret:
                raise ModuleApplyError("secret_missing", {"account": instance.account})
