"""Reading the source sets, and the ones a machine's state carries.

``data/source_sets.json`` defines each software ecosystem's one list of
sources by its name: ``{probe, sources, variables}``. A download from an
ecosystem names its set, an artifact by ``source_set`` and a ``container``
entry by ``source_sets``, and the state carries in its ``source_sets``
section each set its recipes name, which the agent probes. An environment
value ``{<set>}`` in a hub container is that set's fastest source. The
loader refuses a file outside that shape, so a wrong file fails the suite.
"""

import json
import re

from neutrino_hub.modules.devices.constants import (
    DEVICE_SOURCE_SET_NAME_PATTERN,
    DEVICE_SOURCE_SET_VARIABLE_PATTERN,
)
from neutrino_hub.utils.constants import UTILS_DATA_DIR
from neutrino_hub.utils.json_file import strip_comments

SOURCE_SETS_PATH = UTILS_DATA_DIR / "source_sets.json"
SET_KEYS = {"probe", "sources", "variables"}
# A placeholder in an environment value: ``{<set>}``.
PLACEHOLDER_PATTERN = re.compile(r"\{([a-z][a-z0-9_]*)\}")


def load_source_sets() -> dict:
    """Read every source set, by name.

    Returns:
        Set name to ``{probe, sources, variables}``, comment keys removed.

    Raises:
        ValueError: For a file that is not an object of sets, a set name
            not of the form ``[a-z][a-z0-9_]*``, a set whose keys are not
            ``probe``, ``sources`` and ``variables``, a probe that is not a
            path, a source that is not an https address, or a variable that
            is not an environment name.
    """
    try:
        held = strip_comments(json.loads(SOURCE_SETS_PATH.read_text(encoding="utf-8")))
    except (OSError, ValueError) as error:
        raise ValueError(f"source sets: {error}") from error
    if not isinstance(held, dict) or not held:
        raise ValueError("source sets: must be an object of sets")
    for name, entry in held.items():
        _check_set(name, entry)
    return held


def placeholders_in(text: str) -> list:
    """The source sets one environment value names as ``{<set>}``.

    Args:
        text: The value, or a whole ``KEY=value`` line.

    Returns:
        The set names, in order.
    """
    return PLACEHOLDER_PATTERN.findall(str(text))


def state_source_sets(modules: dict, sets: "dict | None" = None) -> dict:
    """The source sets the recipes of one state name.

    Args:
        modules: The state's modules section, each entry's ``install`` the
            recipe ``{runner, method, params}``.
        sets: The source sets by name; None reads the file.

    Returns:
        Each set an artifact's ``source_set`` or an entry's ``source_sets``
        names, as the file defines it, by name; empty while no recipe names
        one.
    """
    names = []
    for entry in modules.values():
        params = ((entry or {}).get("install") or {}).get("params") or {}
        for name in params.get("source_sets") or []:
            if name not in names:
                names.append(str(name))
        for artifact in params.get("artifacts") or []:
            name = artifact.get("source_set") if isinstance(artifact, dict) else None
            if name and name not in names:
                names.append(str(name))
    if not names:
        return {}
    defined = sets if sets is not None else load_source_sets()
    return {name: dict(defined[name]) for name in names if name in defined}


def _check_set(name, entry) -> None:
    """Refuse one source set outside its shape.

    Raises:
        ValueError: Naming the set and what is wrong.
    """
    if not isinstance(name, str) or not re.fullmatch(
        DEVICE_SOURCE_SET_NAME_PATTERN, name
    ):
        raise ValueError(f"source sets: {name!r} is no set name")
    if not isinstance(entry, dict) or set(entry) != SET_KEYS:
        raise ValueError(f"source set {name}: must name probe, sources and variables")
    probe = entry["probe"]
    if not isinstance(probe, str) or not probe.startswith("/"):
        raise ValueError(f"source set {name}: probe must be a path, not {probe!r}")
    sources = entry["sources"]
    if not isinstance(sources, list) or not sources:
        raise ValueError(f"source set {name}: must list at least one source")
    for source in sources:
        if not isinstance(source, str) or not source.startswith("https://"):
            raise ValueError(f"source set {name}: {source!r} is no https address")
    variables = entry["variables"]
    if not isinstance(variables, list) or not variables:
        raise ValueError(f"source set {name}: must list at least one variable")
    for variable in variables:
        if not isinstance(variable, str) or not re.fullmatch(
            DEVICE_SOURCE_SET_VARIABLE_PATTERN, variable
        ):
            raise ValueError(f"source set {name}: {variable!r} is no variable name")
