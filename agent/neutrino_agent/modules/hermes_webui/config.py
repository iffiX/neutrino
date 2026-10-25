"""The Hermes WebUI module's configuration: the forwarder's port, two secrets and the login cookie's name.

The hub sends ``{port, secret, password, cookie_name}``: the port the
agent's forwarder serves the page on, the secret the page's tokens are
signed with, the webui's own password, which the forwarder signs in with,
and the name the webui's login cookie has on this device.

Pure: parsing and validation.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

from dataclasses import dataclass

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.hermes_webui.constants import (
    HERMES_WEBUI_COOKIE,
    HERMES_WEBUI_DEFAULT_PORT,
    HERMES_WEBUI_PORT_MAX,
    HERMES_WEBUI_PORT_MIN,
)


@dataclass(frozen=True)
class HermesWebuiConfig:
    """What the state names for Hermes WebUI.

    Attributes:
        port: The port the forwarder listens on, on ``127.0.0.1``.
        secret: The secret the page's tokens are signed with.
        password: The webui's own password.
        cookie_name: The name of the webui's login cookie.
    """

    port: int = HERMES_WEBUI_DEFAULT_PORT
    secret: str = ""
    password: str = ""
    cookie_name: str = HERMES_WEBUI_COOKIE

    @classmethod
    def from_dict(cls, data: dict) -> "HermesWebuiConfig":
        """Read the configuration the state carries.

        Args:
            data: ``{port, secret, password, cookie_name}``; a missing port
                is 8787, and a missing cookie name the webui's default.

        Returns:
            The configuration, unchecked.
        """
        port = data.get("port", HERMES_WEBUI_DEFAULT_PORT)
        return cls(
            port=port,
            secret=str(data.get("secret", "") or ""),
            password=str(data.get("password", "") or ""),
            cookie_name=str(data.get("cookie_name", "") or "") or HERMES_WEBUI_COOKIE,
        )

    def validate(self) -> None:
        """Check the port.

        Raises:
            ModuleApplyError: ``port_invalid {port}`` for a port outside 1024
                to 65535.
        """
        port = self.port
        is_port = isinstance(port, int) and not isinstance(port, bool)
        if not is_port or not HERMES_WEBUI_PORT_MIN <= port <= HERMES_WEBUI_PORT_MAX:
            raise ModuleApplyError("port_invalid", {"port": port})
