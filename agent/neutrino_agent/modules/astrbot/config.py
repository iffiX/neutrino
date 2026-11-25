"""The AstrBot module's configuration: two secrets, the login cookie's name, the app's local name, the hub's default model, its context length and whether the gateway is used.

The hub sends ``{secret, password, cookie_name, local_name, model,
context_length, is_gateway_used}``: the secret the page's tokens are signed
with, the password of AstrBot's dashboard user, which the forwarder signs in
with, the name of the forwarder's login cookie on this device, the app's
local name, a ``Host`` the forwarder accepts, the hub's default model, empty
while the gateway serves none, that model's context length, and the default
account's AI switch. The forwarder's port
is the agent's own, kept in the module's record.

Pure: parsing.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass

from neutrino_agent.modules.astrbot.constants import ASTRBOT_COOKIE_LABEL


def cookie_key(secret: str) -> bytes:
    """The key the forwarder's login cookie is signed with, derived from the module's secret.

    Args:
        secret: The module's token secret.

    Returns:
        32 bytes.
    """
    return hmac.new(
        secret.encode("utf-8"), ASTRBOT_COOKIE_LABEL, hashlib.sha256
    ).digest()


@dataclass(frozen=True)
class AstrbotConfig:
    """What the state names for AstrBot.

    Attributes:
        secret: The secret the page's tokens are signed with.
        password: The password of AstrBot's dashboard user.
        cookie_name: The name of the forwarder's login cookie.
        local_name: The app's local name, a ``Host`` the forwarder accepts.
        model: The hub's default model, empty while the gateway serves
            none.
        context_length: The default model's context length in tokens, 0
            while there is no model and from a hub that sends none.
        is_gateway_used: Whether AstrBot uses the gateway; true from a hub
            that sends none.
    """

    secret: str = ""
    password: str = ""
    cookie_name: str = ""
    local_name: str = ""
    model: str = ""
    context_length: int = 0
    is_gateway_used: bool = True

    @classmethod
    def from_dict(cls, data: dict) -> "AstrbotConfig":
        """Read the configuration the state carries.

        Args:
            data: ``{secret, password, cookie_name, local_name, model,
                context_length, is_gateway_used}``; a length that is no
                positive whole number is 0, and anything but ``false`` uses
                the gateway.

        Returns:
            The configuration.
        """
        length = data.get("context_length")
        return cls(
            secret=str(data.get("secret", "") or ""),
            password=str(data.get("password", "") or ""),
            cookie_name=str(data.get("cookie_name", "") or ""),
            local_name=str(data.get("local_name", "") or ""),
            model=str(data.get("model", "") or ""),
            context_length=(
                length
                if isinstance(length, int)
                and not isinstance(length, bool)
                and length > 0
                else 0
            ),
            is_gateway_used=data.get("is_gateway_used") is not False,
        )
