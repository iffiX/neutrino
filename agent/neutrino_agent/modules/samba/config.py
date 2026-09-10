"""The file share's configuration: which shares exist and who may use them.

Users here are names only. Passwords live in Samba's own credential store
and are set through a command, never written into the configuration.

Pure: this module parses and shapes configuration. Rendering it into
``smb.conf`` is :mod:`neutrino_agent.modules.samba.renderer`; making it
true on the machine is :mod:`neutrino_agent.modules.samba.applier`.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import re
from dataclasses import dataclass, field

from neutrino_agent.exceptions import ModuleApplyError

# Share names appear as section headers in smb.conf and on every client's
# network browser; user names become unix accounts. Both are kept to
# charsets that cannot smuggle syntax into either place. \\Z rather than $,
# which would also match just before a trailing newline.
SHARE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_ -]{0,31}\Z")
USER_NAME_PATTERN = re.compile(r"^[a-z_][a-z0-9_-]{0,31}\Z")

# Section names smb.conf gives a meaning of its own.
RESERVED_SHARE_NAMES = ("global", "homes", "printers")


@dataclass
class SambaShare:
    """One exported directory.

    Attributes:
        name: What the share appears as on the network.
        path: Absolute directory it exports.
        comment: One line shown beside the name in a client's browser.
        is_read_only: Whether writing is refused for everyone.
        valid_users: Accounts allowed in. Empty means every configured user.
    """

    name: str
    path: str
    comment: str = ""
    is_read_only: bool = False
    valid_users: list = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "SambaShare":
        return cls(
            name=str(data.get("name", "")),
            path=str(data.get("path", "")),
            comment=str(data.get("comment", "")),
            is_read_only=bool(data.get("is_read_only", False)),
            valid_users=[str(user) for user in data.get("valid_users", [])],
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "path": self.path,
            "comment": self.comment,
            "is_read_only": self.is_read_only,
            "valid_users": list(self.valid_users),
        }


@dataclass
class SambaConfig:
    """Everything the module's desired configuration holds.

    Attributes:
        shares: The exported directories.
        users: Accounts that may connect, by name.
        allowed_subnets: The networks the shares answer, as the hub composed
            them from where this machine sits.
    """

    shares: list = field(default_factory=list)
    users: list = field(default_factory=list)
    allowed_subnets: list = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "SambaConfig":
        return cls(
            shares=[SambaShare.from_dict(entry) for entry in data.get("shares", [])],
            users=[str(user) for user in data.get("users", [])],
            allowed_subnets=[str(net) for net in data.get("allowed_subnets", [])],
        )

    def to_dict(self) -> dict:
        return {
            "shares": [share.to_dict() for share in self.shares],
            "users": list(self.users),
            "allowed_subnets": list(self.allowed_subnets),
        }

    def validate(self) -> None:
        """Check the configuration holds together.

        Raises:
            ModuleApplyError: Naming the first problem found.
        """
        seen_shares: set = set()
        for share in self.shares:
            lowered = share.name.lower()
            if not SHARE_NAME_PATTERN.match(share.name):
                raise ModuleApplyError("share_name_invalid", {"name": share.name})
            if lowered in RESERVED_SHARE_NAMES:
                raise ModuleApplyError("share_name_reserved", {"name": share.name})
            if lowered in seen_shares:
                raise ModuleApplyError("share_name_duplicate", {"name": share.name})
            seen_shares.add(lowered)
            if not share.path.startswith("/"):
                raise ModuleApplyError(
                    "share_path_relative", {"name": share.name, "path": share.path}
                )
            for user in share.valid_users:
                if user not in self.users:
                    raise ModuleApplyError(
                        "share_user_unknown", {"name": share.name, "user": user}
                    )
        seen_users: set = set()
        for user in self.users:
            if not USER_NAME_PATTERN.match(user):
                raise ModuleApplyError("user_name_invalid", {"user": user})
            if user in seen_users:
                raise ModuleApplyError("user_name_duplicate", {"user": user})
            seen_users.add(user)
