"""The Ayakaleaf module's configuration: two secrets, the session cookie's name, the app's local name, the guests.

The hub sends ``{secret, password, cookie_name, local_name, guests}``: the
secret the page's tokens are signed with, the administrator's password,
which the forwarder signs in with, the name the app's session cookie has on
this device, the app's local name, a ``Host`` the forwarder accepts, and the
guest account of each live Web share of the app. The forwarder's port is
the agent's own, kept in the module's record.

Pure: parsing.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

from dataclasses import dataclass

from neutrino_agent.modules.ayakaleaf.constants import AYAKALEAF_COOKIE


@dataclass(frozen=True)
class AyakaleafGuest:
    """The guest account of one live Web share of the app.

    Attributes:
        account: ``guest-`` and 4 characters, the account's name.
        email: ``<account>@share.neutrino``.
        password: The account's password.
        secret: The secret a visitor's token is signed with.
    """

    account: str
    email: str
    password: str
    secret: str

    @classmethod
    def from_dict(cls, data: dict) -> "AyakaleafGuest | None":
        """Read one guest the state carries.

        Args:
            data: ``{account, email, password, secret}``.

        Returns:
            The guest; None when a field is missing or empty.
        """
        fields = {
            name: str(data.get(name, "") or "")
            for name in ("account", "email", "password", "secret")
        }
        if not all(fields.values()):
            return None
        return cls(**fields)

    def to_dict(self) -> dict:
        return {
            "account": self.account,
            "email": self.email,
            "password": self.password,
            "secret": self.secret,
        }


@dataclass(frozen=True)
class AyakaleafConfig:
    """What the state names for Ayakaleaf.

    Attributes:
        secret: The secret the page's tokens are signed with.
        password: The administrator's password.
        cookie_name: The name of the app's session cookie.
        local_name: The app's local name, a ``Host`` the forwarder accepts.
        guests: The guest accounts of the live Web shares, in order.
    """

    secret: str = ""
    password: str = ""
    cookie_name: str = AYAKALEAF_COOKIE
    local_name: str = ""
    guests: tuple = ()

    @classmethod
    def from_dict(cls, data: dict) -> "AyakaleafConfig":
        """Read the configuration the state carries.

        Args:
            data: ``{secret, password, cookie_name, local_name, guests}``; a
                missing cookie name is the app's default, and a guest
                missing a field is left out.

        Returns:
            The configuration.
        """
        guests = []
        accounts = set()
        for entry in data.get("guests") or []:
            guest = AyakaleafGuest.from_dict(entry) if isinstance(entry, dict) else None
            if guest is None or guest.account in accounts:
                continue
            accounts.add(guest.account)
            guests.append(guest)
        return cls(
            secret=str(data.get("secret", "") or ""),
            password=str(data.get("password", "") or ""),
            cookie_name=str(data.get("cookie_name", "") or "") or AYAKALEAF_COOKIE,
            local_name=str(data.get("local_name", "") or ""),
            guests=tuple(guests),
        )
