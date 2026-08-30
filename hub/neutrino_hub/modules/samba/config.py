"""The file share's configuration: which shares exist and who may use them.

Users here are names only. Passwords live in Samba's own credential store and
are set through the panel as an action, never written to ``config/`` — which
also means a box rebuilt from a backup comes up with its users present but
their passwords unset, and says so, rather than silently carrying secrets
around in a tarball.

Pure: this module parses and shapes configuration. Rendering it into
``smb.conf`` is :mod:`neutrino_hub.modules.samba.renderer`; making it true on the box is
:mod:`neutrino_hub.modules.samba.ops`.
"""

import re
from dataclasses import dataclass, field

# Share names appear as section headers in smb.conf and on every client's
# network browser; user names become unix accounts. Both are kept to charsets
# that cannot smuggle syntax into either place. \Z rather than $, which would
# also match just before a trailing newline — and a name ending in a newline
# is exactly the smuggling this exists to stop.
SHARE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_ -]{0,31}\Z")
USER_NAME_PATTERN = re.compile(r"^[a-z_][a-z0-9_-]{0,31}\Z")

# Section names smb.conf gives a meaning of its own; a share by any of these
# would be read as configuration rather than as a share.
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
    valid_users: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "SambaShare":
        return cls(
            name=data.get("name", ""),
            path=data.get("path", ""),
            comment=data.get("comment", ""),
            is_read_only=bool(data.get("is_read_only", False)),
            valid_users=list(data.get("valid_users", [])),
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "path": self.path,
            "comment": self.comment,
            "is_read_only": self.is_read_only,
            "valid_users": self.valid_users,
        }


@dataclass
class SambaConfig:
    """Everything ``config/samba/samba.json`` holds.

    Attributes:
        shares: The exported directories.
        users: Accounts that may connect, by name.
    """

    shares: list[SambaShare] = field(default_factory=list)
    users: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "SambaConfig":
        return cls(
            shares=[SambaShare.from_dict(entry) for entry in data.get("shares", [])],
            users=list(data.get("users", [])),
        )

    def to_dict(self) -> dict:
        return {
            "shares": [share.to_dict() for share in self.shares],
            "users": self.users,
        }

    def validate(self) -> None:
        """Check the configuration holds together.

        Raises:
            ValueError: Naming the first problem found. Each check stands
                between a saved form and a share that cannot be served — or
                one that quietly serves the wrong thing.
        """
        seen_shares: set[str] = set()
        for share in self.shares:
            lowered = share.name.lower()
            if not SHARE_NAME_PATTERN.match(share.name):
                raise ValueError(
                    f"share name {share.name!r} is not usable; use letters, "
                    f"digits, spaces, '-' and '_', up to 32 characters"
                )
            if lowered in RESERVED_SHARE_NAMES:
                raise ValueError(f"'{share.name}' is a name Samba reserves for itself")
            if lowered in seen_shares:
                raise ValueError(f"two shares are both named {share.name!r}")
            seen_shares.add(lowered)
            if not share.path.startswith("/"):
                raise ValueError(
                    f"share {share.name!r} needs an absolute path, "
                    f"got {share.path!r}"
                )
            for user in share.valid_users:
                if user not in self.users:
                    raise ValueError(
                        f"share {share.name!r} names user {user!r}, "
                        f"which is not a configured user"
                    )

        seen_users: set[str] = set()
        for user in self.users:
            if not USER_NAME_PATTERN.match(user):
                raise ValueError(
                    f"user name {user!r} is not usable; use a lowercase unix "
                    f"name, up to 32 characters"
                )
            if user in seen_users:
                raise ValueError(f"user {user!r} is listed twice")
            seen_users.add(user)
