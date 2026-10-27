"""The legacy listener's switch: on while a 0.5 agent may still update itself.

An upgrade from 0.5 finds device rows and turns the switch on; the hub
turns it off by itself once no device row names an agent version below
0.6.0 (transport.md, "An agent of 0.5"). The switch is rendered into
``transport.json`` as ``legacy_tls_port``.
"""

from neutrino_hub.modules.channel.constants import (
    CHANNEL_SETTING_LEGACY,
    CHANNEL_TRANSPORT_FIRST_VERSION,
)
from neutrino_hub.utils.json_file import CONFIG_WRITE_LOCK, read_config, write_config
from neutrino_hub.utils.version_number import parse_version

SETTINGS_PATH = "web/settings.json"


def is_legacy_agent(version: str) -> bool:
    """Whether an agent version is one that speaks only the 0.5 channel.

    Args:
        version: The version a device row keeps for its agent; empty for a
            row whose agent never reported one.

    Returns:
        True for a version below 0.6.0; False for 0.6.0 and later, for a
        version that does not parse, and for an empty one.
    """
    parsed = parse_version(version)
    floor = parse_version(CHANNEL_TRANSPORT_FIRST_VERSION)
    return parsed is not None and floor is not None and parsed < floor


def needs_listener(device) -> bool:
    """Whether one stored device still needs the legacy listener.

    Args:
        device: The stored device.

    Returns:
        True for an enrolled device whose agent last said hello below 0.6.0,
        or has not said hello to this hub's version yet.
    """
    if not device.is_managed:
        return False
    version = str(device.client.agent_version or "")
    return not version or is_legacy_agent(version)


def wanted_switch(devices: list, *, is_first_start: bool, current: bool) -> bool:
    """What the switch should read for the stored devices.

    Args:
        devices: Every stored device.
        is_first_start: Whether this is the first 0.6.0 start, the settings
            file naming no switch yet.
        current: What the switch reads now.

    Returns:
        At the first start, on when any enrolled device still needs the
        listener; afterwards the current value, turned off once none does,
        and never turned on again by itself.
    """
    is_needed = any(needs_listener(device) for device in devices)
    if is_first_start:
        return is_needed
    return current and is_needed


def settle_legacy_switch(devices: list) -> bool:
    """Write the switch the stored devices call for, when it differs.

    Args:
        devices: Every stored device.

    Returns:
        True when the settings file was written.
    """
    with CONFIG_WRITE_LOCK:
        try:
            settings = read_config(SETTINGS_PATH)
        except (FileNotFoundError, ValueError):
            return False
        is_first_start = CHANNEL_SETTING_LEGACY not in settings
        current = settings.get(CHANNEL_SETTING_LEGACY) is True
        wanted = wanted_switch(devices, is_first_start=is_first_start, current=current)
        if not is_first_start and wanted == current:
            return False
        settings[CHANNEL_SETTING_LEGACY] = wanted
        write_config(SETTINGS_PATH, settings)
    return True
