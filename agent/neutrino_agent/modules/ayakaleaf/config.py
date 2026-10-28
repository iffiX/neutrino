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
from neutrino_agent.modules.shared.guest_accounts import share_guests


@dataclass(frozen=True)
class AyakaleafConfig:
    """What the state names for Ayakaleaf.

    Attributes:
        secret: The secret the page's tokens are signed with.
        password: The administrator's password.
        cookie_name: The name of the app's session cookie.
        local_name: The app's local name, a ``Host`` the forwarder accepts.
        guests: The guest accounts of the live Web shares, in order, each
            a :class:`ShareGuest`.
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
        return cls(
            secret=str(data.get("secret", "") or ""),
            password=str(data.get("password", "") or ""),
            cookie_name=str(data.get("cookie_name", "") or "") or AYAKALEAF_COOKIE,
            local_name=str(data.get("local_name", "") or ""),
            guests=share_guests(data.get("guests")),
        )
