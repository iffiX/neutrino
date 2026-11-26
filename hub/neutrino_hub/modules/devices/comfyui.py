"""ComfyUI on the hub: its file, its settings, its recipe and the configuration the state sends.

The file is ``config/devices/<id>/comfyui.json``: the forwarder's token
secret, generated the first time the module is installed and sealed under
the vault's data key, and the settings ``{torch_build, idle_unload}``. The
build is written at Install from the machine's last report and names the
venv's lock in the recipe; a Mac's file names none. The idle unload time is
``30m`` while the file names none. The state carries ``{secret,
cookie_name, local_name, torch_build, idle_unload, account, password,
tools}``: the secret opened, the forwarder's login cookie's name and the
app's local name, the settings, the machine's default account with its
login on Windows, and the command line programs whose MCP server lists name
comfy-mcp (agent/modules/comfyui.md, "The settings are the hub's").

Pure apart from the module's file, read and written through the store.
"""

import re
import secrets

from neutrino_hub.exceptions import VaultLockedError
from neutrino_hub.modules.channel.constants import CHANNEL_MODULE_STATE_ABSENT
from neutrino_hub.modules.credentials.vault import seal_bytes, unseal_bytes
from neutrino_hub.modules.devices.constants import (
    DEVICE_COMFYUI_DEFAULT_OS,
    DEVICE_COMFYUI_IDLE_UNLOAD_CHOICES,
    DEVICE_COMFYUI_IDLE_UNLOAD_DEFAULT,
    DEVICE_COMFYUI_IDLE_UNLOAD_KEY,
    DEVICE_COMFYUI_INTEL_BUILD,
    DEVICE_COMFYUI_INTEL_CARD_PATTERN,
    DEVICE_COMFYUI_MODELS_DIRS,
    DEVICE_COMFYUI_MODULE,
    DEVICE_COMFYUI_TOOL_MODULES,
    DEVICE_COMFYUI_TORCH_BUILD_CPU,
    DEVICE_COMFYUI_TORCH_BUILD_KEY,
    DEVICE_COMFYUI_TORCH_BUILDS,
    DEVICE_COMFYUI_USERS,
)
from neutrino_hub.modules.devices.manifests import (
    load_module_manifests,
    lock_builds,
    module_recipe,
    resolve_platform_entry,
)
from neutrino_hub.modules.devices.module_table import module_row
from neutrino_hub.modules.services.apps import cookie_name, entry_id
from neutrino_hub.modules.services.constants import (
    SERVICES_COMFYUI_ID,
    SERVICES_ENTRY_WEB,
)
from neutrino_hub.utils.json_file import CONFIG_WRITE_LOCK


def entry_builds(platform: dict, manifests: "dict | None" = None) -> list:
    """The PyTorch builds one machine's entry has a lock of.

    Args:
        platform: The tuple the machine's agent reported.
        manifests: The module manifests; None reads them.

    Returns:
        The builds in the order of the module's page; empty on a Mac, whose
        one lock names no build, and on a platform with no entry.
    """
    held = load_module_manifests() if manifests is None else manifests
    manifest = held.get(DEVICE_COMFYUI_MODULE) or {}
    _, entry = resolve_platform_entry(manifest, platform)
    named = lock_builds(manifest, entry)
    return [build for build in DEVICE_COMFYUI_TORCH_BUILDS if build in named]


def picked_build(builds: list, gpus: list) -> str:
    """The build Install writes from the machine's last report. Pure.

    Args:
        builds: The builds the machine's entry has a lock of, in the page's
            order.
        gpus: ``machine.metrics.gpus`` as last reported, each ``{vendor,
            name}``.

    Returns:
        The first build whose vendor has a card, an Intel card counting only
        when its name holds ``Arc``; ``cpu`` when none has; empty when the
        entry names no build.
    """
    vendors = set()
    for gpu in gpus:
        if not isinstance(gpu, dict):
            continue
        vendor = str(gpu.get("vendor", "") or "")
        name = str(gpu.get("name", "") or "")
        if vendor == DEVICE_COMFYUI_INTEL_BUILD and not re.search(
            DEVICE_COMFYUI_INTEL_CARD_PATTERN, name, re.IGNORECASE
        ):
            continue
        vendors.add(vendor)
    for build in builds:
        if build == DEVICE_COMFYUI_TORCH_BUILD_CPU or build in vendors:
            return build
    return ""


def settings(stored: dict, builds: list) -> dict:
    """The module's settings as the file holds them, the defaults where it names none. Pure.

    Args:
        stored: ``comfyui.json``.
        builds: The builds the machine's entry has a lock of.

    Returns:
        ``{torch_build, idle_unload}``: the stored build while the entry
        has a lock of it, else ``cpu``, empty while the entry names no
        build; the stored idle unload time while it is one of the five,
        else ``30m``.
    """
    build = stored.get(DEVICE_COMFYUI_TORCH_BUILD_KEY)
    if build not in builds:
        build = (
            DEVICE_COMFYUI_TORCH_BUILD_CPU
            if DEVICE_COMFYUI_TORCH_BUILD_CPU in builds
            else ""
        )
    idle_unload = stored.get(DEVICE_COMFYUI_IDLE_UNLOAD_KEY)
    if idle_unload not in DEVICE_COMFYUI_IDLE_UNLOAD_CHOICES:
        idle_unload = DEVICE_COMFYUI_IDLE_UNLOAD_DEFAULT
    return {
        DEVICE_COMFYUI_TORCH_BUILD_KEY: build,
        DEVICE_COMFYUI_IDLE_UNLOAD_KEY: idle_unload,
    }


def ensure_config(store, key: str, platform: dict, gpus: list) -> dict:
    """Write the module's file with its token secret and its build, ahead of its install.

    A build the file names that the machine's entry has a lock of is kept,
    whatever the report now reads. A locked vault leaves the secret for a
    later press.

    Args:
        store: The desired state store.
        key: The device.
        platform: The tuple the machine's agent reported.
        gpus: ``machine.metrics.gpus`` as last reported.

    Returns:
        The file as it stands afterwards.

    Raises:
        OSError: When the file cannot be written.
    """
    sealed = module_row(DEVICE_COMFYUI_MODULE).sealed_fields[0]
    builds = entry_builds(platform)
    with CONFIG_WRITE_LOCK:
        held = store.read(key, DEVICE_COMFYUI_MODULE)
        written = dict(held)
        if builds and held.get(DEVICE_COMFYUI_TORCH_BUILD_KEY) not in builds:
            written[DEVICE_COMFYUI_TORCH_BUILD_KEY] = picked_build(builds, gpus)
        current = held.get(sealed.key)
        if not isinstance(current, dict) or not current:
            try:
                written[sealed.key] = seal_bytes(
                    secrets.token_urlsafe(sealed.secret_bytes).encode(), sealed.aad
                )
            except VaultLockedError:
                pass
        if written != held:
            store.write(key, DEVICE_COMFYUI_MODULE, written)
    return written


def agent_config(
    stored: dict,
    key: str,
    platform: dict,
    *,
    local_name: str = "",
    account: str = "",
    password: str = "",
    wanted: "dict | None" = None,
    manifests: "dict | None" = None,
) -> dict:
    """What the agent is sent for ComfyUI.

    Args:
        stored: The module's file.
        key: The device.
        platform: The tuple the machine's agent reported.
        local_name: The app's local name, which the forwarder checks the
            ``Host`` against.
        account: The machine's default account; empty while it has none.
        password: That account's login, sent to a Windows machine alone.
        wanted: The modules ``modules.json`` names; None names none.
        manifests: The module manifests; None reads them.

    Returns:
        ``{secret, cookie_name, local_name, torch_build, idle_unload,
        account, password, tools}``: the secret opened, empty when the file
        holds none or the vault cannot open it; ``cookie_name`` the
        entry's; ``tools`` the modules among Claude Code, Codex and
        OpenCode whose ``want`` is neither empty nor ``absent``, none while
        the machine has no default account.
    """
    sealed = module_row(DEVICE_COMFYUI_MODULE).sealed_fields[0]
    held = wanted or {}
    tools = [
        name
        for name in DEVICE_COMFYUI_TOOL_MODULES
        if str((held.get(name) or {}).get("want", "") or "")
        not in ("", CHANNEL_MODULE_STATE_ABSENT)
    ]
    return {
        sealed.opened_key: _opened(stored.get(sealed.key), sealed.aad),
        "cookie_name": cookie_name(
            entry_id(f"{SERVICES_COMFYUI_ID}_{key}", SERVICES_ENTRY_WEB)
        ),
        "local_name": local_name,
        **settings(stored, entry_builds(platform, manifests)),
        "account": account,
        "password": password if account else "",
        "tools": tools if account else [],
    }


def built_recipe(stored: dict, platform: dict, manifests: "dict | None" = None) -> dict:
    """The recipe the state carries for ComfyUI on one machine.

    Args:
        stored: ``comfyui.json``.
        platform: The tuple the machine's agent reported.
        manifests: The module manifests; None reads them.

    Returns:
        The entry's recipe with the venv's lock of the stored build; empty
        for a platform with no entry.
    """
    held = load_module_manifests() if manifests is None else manifests
    _, entry = resolve_platform_entry(held.get(DEVICE_COMFYUI_MODULE) or {}, platform)
    build = settings(stored, entry_builds(platform, held))[
        DEVICE_COMFYUI_TORCH_BUILD_KEY
    ]
    return module_recipe(entry, build=build)


def models_dir(platform: dict) -> str:
    """The shared models folder on one machine. Pure.

    Args:
        platform: The tuple the machine's agent reported.

    Returns:
        The folder under the agent's state root on the machine's system,
        the Linux one before the machine reported a system.
    """
    os_name = str(platform.get("os", "") or "")
    if os_name not in DEVICE_COMFYUI_MODELS_DIRS:
        os_name = DEVICE_COMFYUI_DEFAULT_OS
    return DEVICE_COMFYUI_MODELS_DIRS[os_name]


def service_user(platform: dict) -> str:
    """The account ComfyUI's service runs as on one machine. Pure.

    Args:
        platform: The tuple the machine's agent reported.

    Returns:
        ``neutrino_comfyui``, ``LOCAL SERVICE`` on Windows.
    """
    os_name = str(platform.get("os", "") or "")
    if os_name not in DEVICE_COMFYUI_USERS:
        os_name = DEVICE_COMFYUI_DEFAULT_OS
    return DEVICE_COMFYUI_USERS[os_name]


def _opened(sealed, aad: bytes) -> str:
    """A sealed string opened, empty when there is none or it does not open."""
    if not isinstance(sealed, dict) or not sealed:
        return ""
    try:
        return unseal_bytes(sealed, aad).decode()
    except ValueError:
        return ""
