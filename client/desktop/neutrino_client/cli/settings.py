"""``nclient settings``: the client's own settings, as the Settings page holds them.

Each setting is one control of the page: ``language``, ``theme`` and
``ssh_include``, the switch **SSH programs reach the machines**. ``show``
prints each with its value and the values it takes; ``set`` changes one.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

from neutrino_client.cli import wording
from neutrino_client.constants import CLIENT_LANGUAGES, CLIENT_THEMES

SETTING_SWITCH_VALUES = ("on", "off")
# Each setting: the state's field, and the values it takes.
SETTINGS = (
    ("language", "language", CLIENT_LANGUAGES),
    ("theme", "theme", CLIENT_THEMES),
    ("ssh_include", "is_ssh_include_enabled", SETTING_SWITCH_VALUES),
)


def main_show() -> int:
    """Print each setting: its name, its value and the values it takes.

    Returns:
        0, or 1 when the client does not answer.
    """
    state = wording.read_state()
    if state is None:
        return 1
    width = max(len(name) for name, _field, _values in SETTINGS)
    for name, field, values in SETTINGS:
        value = state.get(field)
        if isinstance(value, bool) or field == "is_ssh_include_enabled":
            value = "on" if value is True else "off"
        wording.say(f"{name:<{width}}  {value}  {', '.join(values)}")
    return 0


def main_set(name: str, value: str) -> int:
    """Change one setting.

    Args:
        name: ``language``, ``theme`` or ``ssh_include``.
        value: One of the values the setting takes.

    Returns:
        0 when it is kept, 1 for a name or a value it does not take.
    """
    found = next((row for row in SETTINGS if row[0] == name), None)
    if found is None:
        wording.unknown_name("what_setting", name, [row[0] for row in SETTINGS])
        return 1
    _name, field, values = found
    if value not in values:
        wording.refuse("setting_value_unknown", {"name": name, "value": value})
        return 1
    sent = value == "on" if field == "is_ssh_include_enabled" else value
    if wording.post("/api/settings/set", {field: sent}) is None:
        return 1
    return 0
