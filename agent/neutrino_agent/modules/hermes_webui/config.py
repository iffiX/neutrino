"""The Hermes WebUI module's configuration: two secrets, the login cookie's name and the app's local name.

The hub sends ``{secret, password, cookie_name, local_name}``: the secret
the page's tokens are signed with, the webui's own password, which the
forwarder signs in with, the name the webui's login cookie has on this
device, and the app's local name, a ``Host`` the forwarder accepts. The
forwarder's port is the agent's own, kept in the module's record.

Pure: parsing.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

from dataclasses import dataclass

from neutrino_agent.modules.hermes_webui.constants import HERMES_WEBUI_COOKIE


@dataclass(frozen=True)
class HermesWebuiConfig:
    """What the state names for Hermes WebUI.

    Attributes:
        secret: The secret the page's tokens are signed with.
        password: The webui's own password.
        cookie_name: The name of the webui's login cookie.
        local_name: The app's local name, a ``Host`` the forwarder accepts.
    """

    secret: str = ""
    password: str = ""
    cookie_name: str = HERMES_WEBUI_COOKIE
    local_name: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "HermesWebuiConfig":
        """Read the configuration the state carries.

        Args:
            data: ``{secret, password, cookie_name, local_name}``; a missing
                cookie name is the webui's default.

        Returns:
            The configuration.
        """
        return cls(
            secret=str(data.get("secret", "") or ""),
            password=str(data.get("password", "") or ""),
            cookie_name=str(data.get("cookie_name", "") or "") or HERMES_WEBUI_COOKIE,
            local_name=str(data.get("local_name", "") or ""),
        )
