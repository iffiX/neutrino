"""The file share's configuration: one share per enabled account, and its SMB user.

The hub composes it from the machine's enabled accounts: each share is
named after its account and lists that account's SMB user, ``users`` names
every SMB user, and ``passwords`` holds each user's password, which the
hub generated and the agent sets on the machine.

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
# network browser, and are the names of the machine's accounts; user names
# are those accounts on Linux and the module's own accounts elsewhere. Both
# are kept to charsets that cannot smuggle syntax into either place. \\Z
# rather than $, which would also match just before a trailing newline.
SHARE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._ -]{0,79}\Z")
USER_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,31}\$?\Z")
# A Windows or macOS account the module makes: ``smb_`` and the person's
# account, whose name may hold a space on Windows.
NATIVE_USER_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_. -]{0,31}\Z")

# Section names smb.conf gives a meaning of its own.
RESERVED_SHARE_NAMES = ("global", "homes", "printers")
# An absolute Windows path starts at a drive.
WINDOWS_PATH_PATTERN = re.compile(r"^[A-Za-z]:\\")
# Windows refuses a local account name longer than this.
WINDOWS_USER_NAME_MAX = 20


def _is_absolute(path: str, os_name: str) -> bool:
    """Whether a share path is absolute on the system that serves it."""
    if os_name == "windows":
        return bool(WINDOWS_PATH_PATTERN.match(path))
    return path.startswith("/")


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
        passwords: Each user's password, as the hub generated it.
        allowed_subnets: The networks the shares answer, as the hub composed
            them from where this machine sits.
    """

    shares: list = field(default_factory=list)
    users: list = field(default_factory=list)
    passwords: dict = field(default_factory=dict)
    allowed_subnets: list = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "SambaConfig":
        passwords = data.get("passwords")
        return cls(
            shares=[SambaShare.from_dict(entry) for entry in data.get("shares", [])],
            users=[str(user) for user in data.get("users", [])],
            passwords=(
                {str(user): str(word) for user, word in passwords.items()}
                if isinstance(passwords, dict)
                else {}
            ),
            allowed_subnets=[str(net) for net in data.get("allowed_subnets", [])],
        )

    def to_dict(self) -> dict:
        return {
            "shares": [share.to_dict() for share in self.shares],
            "users": list(self.users),
            "passwords": dict(self.passwords),
            "allowed_subnets": list(self.allowed_subnets),
        }

    def validate(self, *, os_name: str = "linux") -> None:
        """Check the configuration holds together.

        Args:
            os_name: The system the shares are served from: a share path is
                absolute from a drive on ``windows`` and from ``/`` on any
                other, and a Windows account name is at most 20 characters.

        Raises:
            ModuleApplyError: Naming the first problem found; on Windows
                and macOS two users of one name are ``user_name_taken``,
                since the hub cut two accounts to the same name.
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
            if not _is_absolute(share.path, os_name):
                raise ModuleApplyError(
                    "share_path_relative", {"name": share.name, "path": share.path}
                )
            for user in share.valid_users:
                if user not in self.users:
                    raise ModuleApplyError(
                        "share_user_unknown", {"name": share.name, "user": user}
                    )
        is_native = os_name in ("windows", "darwin")
        pattern = NATIVE_USER_NAME_PATTERN if is_native else USER_NAME_PATTERN
        seen_users: set = set()
        for user in self.users:
            is_too_long = os_name == "windows" and len(user) > WINDOWS_USER_NAME_MAX
            if not pattern.match(user) or is_too_long:
                raise ModuleApplyError("user_name_invalid", {"user": user})
            key = user.lower() if is_native else user
            if key in seen_users:
                code = "user_name_taken" if is_native else "user_name_duplicate"
                raise ModuleApplyError(code, {"user": user})
            seen_users.add(key)
