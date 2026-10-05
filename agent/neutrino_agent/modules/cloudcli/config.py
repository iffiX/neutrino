"""The CloudCLI module's configuration: which accounts run it, on which port.

Each instance is one account's CloudCLI behind the agent's forwarder on one
port. The hub sends each instance's CloudCLI password and the secret its
tokens are signed with. The AI tools CloudCLI starts read the account's own
files, which the machine's AI tools setting points at the gateway. On
Windows an instance also carries the
account's password, from the login the hub holds for it, because a task
that runs as an account needs its password to sign in.

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
from neutrino_agent.modules.cloudcli.constants import (
    CLOUDCLI_JWT_LABEL,
    CLOUDCLI_PORT_MAX,
    CLOUDCLI_PORT_MIN,
    CLOUDCLI_USERNAME_MIN,
)

# An account name that survives a unit name, a launchd label, a task name
# and a command line.
ACCOUNT_PATTERN = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}\Z")
# An npm setting the hub may name: npm reads it from the environment.
NPM_SETTING_PATTERN = re.compile(r"^npm_config_[a-z0-9_]+\Z")


def npm_settings_of(held) -> dict:
    """The npm settings a state carries, those named ``npm_config_*`` alone.

    Args:
        held: The state's ``npm_environment``.

    Returns:
        Name to value, both text; anything else is left out.
    """
    if not isinstance(held, dict):
        return {}
    return {
        str(name): str(value)
        for name, value in held.items()
        if NPM_SETTING_PATTERN.match(str(name)) and isinstance(value, str)
    }


def jwt_secret(token_secret: str) -> str:
    """The secret CloudCLI signs its logins with, derived from the instance's.

    Args:
        token_secret: The instance's token secret.

    Returns:
        64 hex digits, handed to CloudCLI as ``JWT_SECRET``.
    """
    return hmac.new(
        token_secret.encode("utf-8"), CLOUDCLI_JWT_LABEL, hashlib.sha256
    ).hexdigest()


def username_of(account: str) -> str:
    """The name the account's CloudCLI administrator is registered under.

    Args:
        account: The account.

    Returns:
        The account's name, padded with underscores to the length CloudCLI
        asks for.
    """
    return account.ljust(CLOUDCLI_USERNAME_MIN, "_")


@dataclass
class CloudcliInstance:
    """One account's CloudCLI.

    Attributes:
        account: The account it runs as.
        port: The port the forwarder listens on.
        web_password: The password CloudCLI's administrator signs in with.
        token_secret: The secret a token for this instance is signed with.
        password: The account's password; Windows only.
    """

    account: str
    port: int
    web_password: str = ""
    token_secret: str = ""
    password: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "CloudcliInstance":
        try:
            port = int(data.get("port", 0))
        except (TypeError, ValueError):
            port = 0
        return cls(
            account=str(data.get("account", "") or ""),
            port=port,
            web_password=str(data.get("web_password", "") or ""),
            token_secret=str(data.get("token_secret", "") or ""),
            password=str(data.get("password", "") or ""),
        )


@dataclass
class CloudcliConfig:
    """Everything the module's desired configuration holds.

    Attributes:
        npm_registry: The npm registry of the hub's edition, which npm
            installs CloudCLI from; empty for npm's own default.
        npm_environment: More of npm's settings the hub's edition names,
            such as where a native module fetches its prebuilt binary; only
            names that start ``npm_config_`` are kept.
        instances: One CloudCLI per account.
    """

    npm_registry: str = ""
    npm_environment: dict = field(default_factory=dict)
    instances: list = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "CloudcliConfig":
        instances = data.get("instances")
        return cls(
            npm_registry=str(data.get("npm_registry", "") or ""),
            npm_environment=npm_settings_of(data.get("npm_environment")),
            instances=[
                CloudcliInstance.from_dict(entry)
                for entry in (instances if isinstance(instances, list) else [])
                if isinstance(entry, dict)
            ],
        )

    def validate(self, *, os_name: str = "linux") -> None:
        """Check the configuration holds together.

        Args:
            os_name: The system the instances run on; on ``windows`` every
                instance needs its account's password.

        Raises:
            ModuleApplyError: Naming the first problem found.
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
            if not CLOUDCLI_PORT_MIN <= instance.port <= CLOUDCLI_PORT_MAX:
                raise ModuleApplyError("port_invalid", {"port": instance.port})
            if instance.port in ports:
                raise ModuleApplyError("port_duplicate", {"port": instance.port})
            ports.add(instance.port)
            if not instance.web_password or not instance.token_secret:
                raise ModuleApplyError("token_missing", {"account": instance.account})
            if os_name == "windows" and not instance.password:
                raise ModuleApplyError(
                    "credential_missing", {"account": instance.account}
                )
