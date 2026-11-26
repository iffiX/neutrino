"""The ComfyUI module's configuration as the hub sends it.

``{secret, cookie_name, local_name, torch_build, idle_unload, account,
password, tools}``: the forwarder's token secret, the name of its login
cookie and the app's local name; the PyTorch build, empty on a Mac; the
idle unload time; the machine's default account, empty while it has none,
with its login on Windows alone; and the program modules comfy-mcp is named
in.

Pure: parsing and checking only.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.comfyui.constants import (
    COMFYUI_CODE_CONFIG_INVALID,
    COMFYUI_COOKIE_LABEL,
    COMFYUI_IDLE_UNLOAD_DEFAULT,
    COMFYUI_IDLE_UNLOAD_NEVER,
    COMFYUI_IDLE_UNLOAD_SECONDS,
    COMFYUI_TOOLS,
    COMFYUI_TORCH_BUILD_CPU,
    COMFYUI_TORCH_BUILDS,
)


def cookie_key(secret: str) -> bytes:
    """The key the forwarder's login cookie is signed with, derived from the module's secret.

    Args:
        secret: The module's token secret.

    Returns:
        32 bytes.
    """
    return hmac.new(
        secret.encode("utf-8"), COMFYUI_COOKIE_LABEL, hashlib.sha256
    ).digest()


def idle_seconds(idle_unload: str) -> "int | None":
    """How long ComfyUI stays idle before its models are unloaded. Pure.

    Args:
        idle_unload: The setting.

    Returns:
        The seconds; None for ``-1``, never.
    """
    if idle_unload == COMFYUI_IDLE_UNLOAD_NEVER:
        return None
    return COMFYUI_IDLE_UNLOAD_SECONDS.get(
        idle_unload, COMFYUI_IDLE_UNLOAD_SECONDS[COMFYUI_IDLE_UNLOAD_DEFAULT]
    )


@dataclass(frozen=True)
class ComfyuiConfig:
    """What the state names for ComfyUI.

    Attributes:
        secret: The secret the page's tokens are signed with.
        cookie_name: The name of the forwarder's login cookie.
        local_name: The app's local name, a ``Host`` the forwarder accepts.
        torch_build: ``nvidia``, ``amd``, ``intel`` or ``cpu``; empty on a
            Mac.
        idle_unload: ``5m``, ``30m``, ``1h``, ``4h`` or ``-1``.
        account: The machine's default account; empty while it has none.
        password: The default account's login, on Windows alone.
        tools: The program modules among Claude Code, Codex and OpenCode
            comfy-mcp is named in.
    """

    secret: object = ""
    cookie_name: object = ""
    local_name: object = ""
    torch_build: object = ""
    idle_unload: object = COMFYUI_IDLE_UNLOAD_DEFAULT
    account: object = ""
    password: object = ""
    tools: object = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "ComfyuiConfig":
        """Read a configuration as the hub sent it, unchecked.

        Args:
            data: The configuration.

        Returns:
            The configuration, ``30m`` where it names no idle unload time.
        """
        return cls(
            secret=data.get("secret", ""),
            cookie_name=data.get("cookie_name", ""),
            local_name=data.get("local_name", ""),
            torch_build=data.get("torch_build", ""),
            idle_unload=data.get("idle_unload", COMFYUI_IDLE_UNLOAD_DEFAULT),
            account=data.get("account", ""),
            password=data.get("password", ""),
            tools=data.get("tools", []),
        )

    def validate(self, os_name: str) -> None:
        """Check every field against its choices.

        Args:
            os_name: ``linux``, ``windows`` or ``darwin``; a Mac names no
                build, every other system one.

        Raises:
            ModuleApplyError: ``config_invalid {field}`` for the first field
                outside its choices.
        """
        for name in ("secret", "cookie_name", "local_name", "account", "password"):
            if not isinstance(getattr(self, name), str):
                raise ModuleApplyError(COMFYUI_CODE_CONFIG_INVALID, {"field": name})
        if not self.secret or not self.cookie_name:
            field_name = "secret" if not self.secret else "cookie_name"
            raise ModuleApplyError(COMFYUI_CODE_CONFIG_INVALID, {"field": field_name})
        builds = ("",) if os_name == "darwin" else COMFYUI_TORCH_BUILDS
        if self.torch_build not in builds:
            raise ModuleApplyError(
                COMFYUI_CODE_CONFIG_INVALID, {"field": "torch_build"}
            )
        if self.idle_unload not in (
            *COMFYUI_IDLE_UNLOAD_SECONDS,
            COMFYUI_IDLE_UNLOAD_NEVER,
        ):
            raise ModuleApplyError(
                COMFYUI_CODE_CONFIG_INVALID, {"field": "idle_unload"}
            )
        if not isinstance(self.tools, list) or not all(
            tool in COMFYUI_TOOLS for tool in self.tools
        ):
            raise ModuleApplyError(COMFYUI_CODE_CONFIG_INVALID, {"field": "tools"})

    @property
    def is_cpu(self) -> bool:
        """Whether the server runs on the CPU alone: the CPU build."""
        return self.torch_build == COMFYUI_TORCH_BUILD_CPU
