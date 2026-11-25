"""The Hermes WebUI module's configuration: two secrets, the login cookie's name, the app's local name, the hub's default model, each model's context length and whether the gateway is used.

The hub sends ``{secret, password, cookie_name, local_name, model,
context_lengths, is_gateway_used}``: the secret the page's tokens are signed
with, the webui's own password, which the forwarder signs in with, the name
the webui's login cookie has on this device, the app's local name, a
``Host`` the forwarder accepts, the hub's default model, empty while the
gateway serves none, each served name's context length, and the default
account's AI switch. The forwarder's port is the agent's own, kept in the
module's record.

Pure: parsing.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

from dataclasses import dataclass, field

from neutrino_agent.modules.hermes_webui.constants import HERMES_WEBUI_COOKIE


@dataclass(frozen=True)
class HermesWebuiConfig:
    """What the state names for Hermes WebUI.

    Attributes:
        secret: The secret the page's tokens are signed with.
        password: The webui's own password.
        cookie_name: The name of the webui's login cookie.
        local_name: The app's local name, a ``Host`` the forwarder accepts.
        model: The hub's default model, empty while the gateway serves
            none.
        context_lengths: Each served name to its context length in tokens;
            empty from a hub that sends none.
        is_gateway_used: Whether Hermes uses the gateway; true from a hub
            that sends none.
    """

    secret: str = ""
    password: str = ""
    cookie_name: str = HERMES_WEBUI_COOKIE
    local_name: str = ""
    model: str = ""
    context_lengths: dict = field(default_factory=dict)
    is_gateway_used: bool = True

    @classmethod
    def from_dict(cls, data: dict) -> "HermesWebuiConfig":
        """Read the configuration the state carries.

        Args:
            data: ``{secret, password, cookie_name, local_name, model,
                context_lengths, is_gateway_used}``; a missing cookie name is
                the webui's default, a length that is no positive whole
                number is left out, and anything but ``false`` uses the
                gateway.

        Returns:
            The configuration.
        """
        held = data.get("context_lengths")
        return cls(
            secret=str(data.get("secret", "") or ""),
            password=str(data.get("password", "") or ""),
            cookie_name=str(data.get("cookie_name", "") or "") or HERMES_WEBUI_COOKIE,
            local_name=str(data.get("local_name", "") or ""),
            model=str(data.get("model", "") or ""),
            context_lengths={
                str(name): length
                for name, length in (held if isinstance(held, dict) else {}).items()
                if isinstance(length, int)
                and not isinstance(length, bool)
                and length > 0
            },
            is_gateway_used=data.get("is_gateway_used") is not False,
        )
