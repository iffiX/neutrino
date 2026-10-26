"""The SSH server module's configuration: which accounts run an instance, with which key.

Each instance is one account's SSH server on loopback, admitting the one
public key the hub made for that account on this machine. ``shell_path`` is
the account row's, empty for the account's login shell; on Windows an
instance also carries the account's password, which its scheduled task
signs in with.

Pure: parsing, validation and what follows from the values.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import re
from dataclasses import dataclass, field

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.ssh_server.openssh_key import is_public_key

# An account name that survives a unit name, a launchd label, a task name,
# a path and a command line.
ACCOUNT_PATTERN = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}\Z")


@dataclass
class SshServerInstance:
    """One account's SSH server.

    Attributes:
        account: The account it runs as.
        authorized_key: The one public key it admits, in OpenSSH form.
        shell_path: The shell a session starts; empty is the account's
            login shell, PowerShell on Windows.
        password: The account's password; Windows only.
        port: The loopback port it listens on, from its record.
    """

    account: str
    authorized_key: str = ""
    shell_path: str = ""
    password: str = ""
    port: int = 0

    @classmethod
    def from_dict(cls, data: dict) -> "SshServerInstance":
        try:
            port = int(data.get("port", 0) or 0)
        except (TypeError, ValueError):
            port = 0
        return cls(
            account=str(data.get("account", "") or ""),
            authorized_key=str(data.get("authorized_key", "") or "").strip(),
            shell_path=str(data.get("shell_path", "") or "").strip(),
            password=str(data.get("password", "") or ""),
            port=port,
        )


@dataclass
class SshServerConfig:
    """Everything the module's desired configuration holds.

    Attributes:
        instances: One SSH server per enabled account, in the order the
            accounts were enabled.
    """

    instances: list = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "SshServerConfig":
        instances = data.get("instances") if isinstance(data, dict) else None
        return cls(
            instances=[
                SshServerInstance.from_dict(entry)
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
            ModuleApplyError: ``account_invalid``, ``account_duplicate`` or
                ``key_missing``, for a key that is empty or not an OpenSSH
                public key, each naming the account, and on Windows
                ``credential_missing {account}`` for an instance with no
                password; the first problem found.
        """
        accounts: set = set()
        for instance in self.instances:
            if not ACCOUNT_PATTERN.match(instance.account):
                raise ModuleApplyError("account_invalid", {"account": instance.account})
            if instance.account.lower() in accounts:
                raise ModuleApplyError(
                    "account_duplicate", {"account": instance.account}
                )
            accounts.add(instance.account.lower())
            if not is_public_key(instance.authorized_key):
                raise ModuleApplyError("key_missing", {"account": instance.account})
            if os_name == "windows" and not instance.password:
                raise ModuleApplyError(
                    "credential_missing", {"account": instance.account}
                )
