"""The VS Code module's configuration: which accounts run a server, where.

Each instance is one account's ``code serve-web`` on one port, reached with
the connection token the hub generated for it. On Windows an instance also
carries the account's password, from the login the hub holds for it,
because a task that runs as an account needs its password to sign in.

Pure: parsing and validation only.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import re
from dataclasses import dataclass, field

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.vscode.constants import (
    VSCODE_LOOPBACK_ADDRESS,
    VSCODE_PORT_MAX,
    VSCODE_PORT_MIN,
)

# An account name that survives a unit name, a launchd label, a task name
# and a command line.
ACCOUNT_PATTERN = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}\Z")


@dataclass
class VscodeInstance:
    """One account's server.

    Attributes:
        account: The account it runs as.
        port: The port it listens on.
        token: The connection token a browser opens it with.
        password: The account's password; Windows only.
    """

    account: str
    port: int
    token: str = ""
    password: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "VscodeInstance":
        try:
            port = int(data.get("port", 0))
        except (TypeError, ValueError):
            port = 0
        return cls(
            account=str(data.get("account", "") or ""),
            port=port,
            token=str(data.get("token", "") or ""),
            password=str(data.get("password", "") or ""),
        )


@dataclass
class VscodeConfig:
    """Everything the module's desired configuration holds.

    Attributes:
        address: This machine's address the servers listen on, as the hub
            composed it; empty listens on loopback alone.
        instances: One server per account.
    """

    address: str = ""
    instances: list = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "VscodeConfig":
        instances = data.get("instances")
        return cls(
            address=str(data.get("address", "") or ""),
            instances=[
                VscodeInstance.from_dict(entry)
                for entry in (instances if isinstance(instances, list) else [])
                if isinstance(entry, dict)
            ],
        )

    @property
    def host(self) -> str:
        """The address the servers listen on."""
        return self.address or VSCODE_LOOPBACK_ADDRESS

    @property
    def url_host(self) -> str:
        """The address a reported url names."""
        return self.address or VSCODE_LOOPBACK_ADDRESS

    def url_of(self, instance: VscodeInstance) -> str:
        """Where one instance answers, without its token.

        Args:
            instance: The instance.

        Returns:
            ``http://<address>:<port>/``.
        """
        return f"http://{self.url_host}:{instance.port}/"

    def validate(self, *, os_name: str = "linux") -> None:
        """Check the configuration holds together.

        Args:
            os_name: The system the servers run on; on ``windows`` every
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
            if not VSCODE_PORT_MIN <= instance.port <= VSCODE_PORT_MAX:
                raise ModuleApplyError("port_invalid", {"port": instance.port})
            if instance.port in ports:
                raise ModuleApplyError("port_duplicate", {"port": instance.port})
            ports.add(instance.port)
            if not instance.token:
                raise ModuleApplyError("token_missing", {"account": instance.account})
            if os_name == "windows" and not instance.password:
                raise ModuleApplyError(
                    "credential_missing", {"account": instance.account}
                )
