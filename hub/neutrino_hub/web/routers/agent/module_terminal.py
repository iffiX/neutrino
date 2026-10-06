"""The Terminal block: the account and the shell program a terminal runs.

The two settings hold for every ``shell`` stream opened on the machine
afterwards, from the panel and from clients alike; a session already open
keeps what it runs, and a container's shell is not touched. Both empty is
the shell the agent runs by default. A Windows machine takes the shell
program alone: its shells run as SYSTEM, and the state sends it no account.
"""

import ntpath
import posixpath

from fastapi import APIRouter, Depends, HTTPException, status

from neutrino_hub.modules.devices.constants import (
    DEVICE_TERMINAL_ACCOUNT_OS,
    DEVICE_TERMINAL_MODULE,
)
from neutrino_hub.web.dependencies import get_runtime
from neutrino_hub.web.models import TerminalConfigUpdate, TerminalDeviceView
from neutrino_hub.web.panel_runtime import PanelRuntime
from neutrino_hub.web.routers.agent.module import (
    DeviceModuleContext,
    device_context,
    module_router,
    store_config,
)

MODULE = DEVICE_TERMINAL_MODULE
OS_WINDOWS = "windows"

CODE_ACCOUNT_UNKNOWN = "account_unknown"
CODE_PATH_INVALID = "path_invalid"


def device_view(
    runtime: PanelRuntime, context: DeviceModuleContext
) -> TerminalDeviceView:
    """One device's Terminal module: its two settings and the machine's accounts.

    Args:
        runtime: The shared runtime.
        context: The device.

    Returns:
        The settings as stored, the human accounts the machine last
        reported, and whether an account can be set there.
    """
    platform = runtime.device_platform.get(context.key, {})
    return TerminalDeviceView(
        **context.fields(),
        account=str(context.config.get("account", "") or ""),
        shell_path=str(context.config.get("shell_path", "") or ""),
        accounts=[str(name) for name in runtime.device_accounts.get(context.key, [])],
        is_account_settable=_is_account_settable(platform),
    )


router: APIRouter = module_router(
    MODULE, view_model=TerminalDeviceView, build_view=device_view
)


@router.post("/set", response_model=TerminalDeviceView)
def update_settings(
    update: TerminalConfigUpdate,
    runtime: PanelRuntime = Depends(get_runtime),
) -> TerminalDeviceView:
    """Replace the account and the shell program.

    The agent checks them as it will receive them before they are stored
    and pushed: a shell program that is missing or not executable is its
    ``shell_program_unusable {path}``.

    Args:
        update: The device and its two settings.
        runtime: The shared runtime.

    Returns:
        The device's view afterwards.

    Raises:
        HTTPException: 400 ``account_unknown`` for an account the machine
            did not report, ``path_invalid`` for a shell program that is not
            an absolute path, and the agent's own codes; 409
            ``agent_offline``.
    """
    context = device_context(runtime, MODULE, update.device_id)
    platform = runtime.device_platform.get(context.key, {})
    account = update.account.strip()
    shell_path = update.shell_path.strip()
    if account and _is_account_settable(platform):
        reported = {str(name) for name in runtime.device_accounts.get(context.key, [])}
        if account not in reported:
            raise _refusal(CODE_ACCOUNT_UNKNOWN, account=account)
    if shell_path and not (posixpath.isabs(shell_path) or ntpath.isabs(shell_path)):
        raise _refusal(CODE_PATH_INVALID, path=shell_path)
    stored = {"account": account, "shell_path": shell_path}
    store_config(runtime, context, stored)
    return device_view(runtime, context)


def _is_account_settable(platform: dict) -> bool:
    """Whether a shell on the machine can run as an account the module names."""
    system = str(platform.get("os", "") or "")
    return not system or system in DEVICE_TERMINAL_ACCOUNT_OS


def _refusal(code: str, **params) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"code": code, "params": dict(params)},
    )
