"""Finding cc-switch and pointing it at the hub.

cc-switch is what people already use to keep several AI providers on one
machine and flip between them, so the client adds the hub to it as one more
provider. The client carries its own copy of the CLI; one found on the path
is used when the bundle is absent.

Each tool is configured with its own knobs, drawn from the person's staged
choices: Claude Code's four role slots, Codex's model and reasoning effort
written into ``config.toml``, Gemini's one model. Activating keeps a copy of
each file as it stood beforehand, and deactivating puts that copy back
verbatim, deleting the file again when there was none.

The client settles what activation means: it writes the tool's configuration
itself and reads it back, rather than trusting cc-switch's exit code.

Not pure: runs the binary and edits the person's configuration.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import json
import os
import shutil
import subprocess

from neutrino_client import bundled
from neutrino_client.constants import CLIENT_ORIGINAL_DIR_NAME


class SwitcherError(RuntimeError):
    """Raised when cc-switch refuses, or a configuration cannot be kept."""


SWITCHER_PROVIDER_ID = "neutrino"
SWITCHER_PROVIDER_NAME = "Neutrino Hub"

# The tools cc-switch can point at the hub, in its own vocabulary, and where
# each keeps the file that switching would replace.
SWITCHER_APPS = ("claude", "codex", "gemini")
SWITCHER_APP_FILES = {
    "claude": ".claude/settings.json",
    "codex": ".codex/config.toml",
    "gemini": ".gemini/.env",
}

# What Claude Code's env block holds when the hub is the provider. Everything
# else in that file is the person's own and is carried across unchanged.
CLAUDE_ENV_KEYS = ("ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY")

# Claude Code's four role slots, each an env key of its own.
CLAUDE_SLOT_KEYS = {
    "default": "ANTHROPIC_MODEL",
    "opus": "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "sonnet": "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "haiku": "ANTHROPIC_DEFAULT_HAIKU_MODEL",
}

# Codex's own knobs, written into config.toml as top-level keys.
CODEX_CONFIG_KEYS = ("model", "model_reasoning_effort")

GEMINI_MODEL_KEY = "GEMINI_MODEL"

# What cc-switch draws its provider table with; its list has no
# machine-readable form, so the identifiers are read out of the columns.
TABLE_SEPARATOR = "┆"

COMMAND_TIMEOUT_S = 120

_PLATFORM = None


def _platform():
    """This machine's platform, created once on first use."""
    global _PLATFORM
    if _PLATFORM is None:
        from neutrino_client.platforms.detect import detect_platform

        _PLATFORM = detect_platform()
    return _PLATFORM


def find_cli() -> "str | None":
    """The cc-switch CLI: the carried one first, then the path.

    Returns:
        The path to a usable CLI, or None.
    """
    carried = bundled.cc_switch_path()
    if carried:
        return carried
    return shutil.which("cc-switch")


def is_installed() -> bool:
    """Whether this machine has a cc-switch CLI at all."""
    return find_cli() is not None


def activate(*, base_url: str, api_key: str, tool_configs: "dict | None" = None) -> str:
    """Register the hub in cc-switch and switch every tool to it.

    Each tool's configuration is copied aside first, as it stands, and a tool
    whose configuration cannot be copied is left untouched rather than
    replaced. Deactivating puts those copies back.

    Args:
        base_url: The hub's AI endpoint.
        api_key: This person's gateway key.
        tool_configs: Each tool's staged choices: ``claude`` slot names,
            ``codex`` model and reasoning effort, ``gemini`` model. None or
            a missing key leaves that tool's model choices unwritten.

    Returns:
        A short message naming the tools that took it.

    Raises:
        SwitcherError: If cc-switch refuses for every tool.
    """
    configs = tool_configs or {}
    done = []
    problems = []
    for app in SWITCHER_APPS:
        try:
            _add_provider(app, base_url, api_key, configs.get(app) or {})
            done.append(app)
        except SwitcherError as error:
            problems.append(f"{app}: {error}")
    if not done:
        raise SwitcherError("; ".join(problems)[:300])
    note = ", ".join(done)
    return f"{note}" if not problems else f"{note} ({len(problems)} not set up here)"


def deactivate(*, base_url: str = "") -> str:
    """Put every tool back the way activation found it.

    The hub's entry is taken out of cc-switch, switching away first because
    cc-switch refuses to delete whichever provider is current, and then each
    tool's configuration is restored from the copy activation kept. Without
    such a copy only the hub's own keys are taken out.

    Args:
        base_url: The hub's endpoint, so the tools can be checked afterwards
            for still naming it.

    Returns:
        What happened, in the words the page shows.
    """
    notes = []
    for app in SWITCHER_APPS:
        fallback = _drop_provider(app)
        if _restore_original(app):
            notes.append(f"{app} → as it was")
        else:
            _strip_hub_keys(app)
            notes.append(f"{app} → {fallback or 'unset'}")
        if _points_at_hub(app, base_url):
            _strip_hub_keys(app)
    return ", ".join(notes)


def is_active(*, base_url: str, api_key: str = "", model: str = "") -> bool:
    """Whether this person's Claude Code actually calls the hub.

    Read from the tool's own configuration rather than from cc-switch's idea
    of which provider is selected.

    Args:
        base_url: The hub's AI endpoint.
        api_key: The current key. Checked as well when given, so a rotated
            key counts as not pointed here and gets written again.
        model: The default-slot model to expect. Checked too, so a changed
            choice is applied rather than left behind.

    Returns:
        True when Claude Code's settings name that endpoint, key and model.
    """
    if not base_url:
        return False
    env = _read_json(SWITCHER_APP_FILES["claude"]).get("env", {})
    if env.get("ANTHROPIC_BASE_URL") != base_url:
        return False
    if api_key and env.get("ANTHROPIC_AUTH_TOKEN") != api_key:
        return False
    return not model or env.get("ANTHROPIC_MODEL") == model


def is_active_for(app: str) -> bool:
    """Whether cc-switch points one tool at the hub.

    Args:
        app: The tool, in cc-switch's vocabulary.

    Returns:
        True when the hub is that tool's current provider.
    """
    try:
        output = _run(["provider", "current"], app)
    except SwitcherError:
        return False
    return SWITCHER_PROVIDER_ID in output or SWITCHER_PROVIDER_NAME in output


def _drop_provider(app: str) -> str:
    """Remove the hub's provider, switching away from it first if need be.

    Args:
        app: Which tool's providers to act on.

    Returns:
        The provider switched to, or empty when there was none to switch to.
    """
    fallback = ""
    if is_active_for(app):
        fallback = _other_provider(app)
        if fallback:
            _run(["use", fallback], app, is_checked=False)
    _run(["provider", "delete", SWITCHER_PROVIDER_ID], app, is_checked=False)
    return fallback


def _other_provider(app: str) -> str:
    """Another provider in the store to fall back to, if there is one.

    Args:
        app: Which tool's providers to look at.

    Returns:
        A provider id that is not the hub's, or empty when there is none.
    """
    try:
        output = _run(["provider", "list"], app)
    except SwitcherError:
        return ""
    for line in output.splitlines():
        if TABLE_SEPARATOR not in line:
            continue
        columns = [cell.strip() for cell in line.split(TABLE_SEPARATOR)]
        if len(columns) < 3:
            continue
        identifier = columns[1]
        if not identifier or identifier == "ID" or identifier == SWITCHER_PROVIDER_ID:
            continue
        return identifier
    return ""


def _points_at_hub(app: str, base_url: str) -> bool:
    """Whether a tool's configuration still names this hub.

    Args:
        app: Which tool, in cc-switch's vocabulary.
        base_url: This hub's AI endpoint.

    Returns:
        True when that tool would still call this hub.
    """
    if app != "claude" or not base_url:
        return False
    env = _read_json(SWITCHER_APP_FILES["claude"]).get("env", {})
    return env.get("ANTHROPIC_BASE_URL") == base_url


def _capture_original(app: str) -> None:
    """Keep a copy of a tool's configuration as it stands before the hub.

    Taken once and kept until deactivate puts it back. A tool with no
    configuration yet is recorded as having none.

    Args:
        app: Which tool, in cc-switch's vocabulary.

    Raises:
        SwitcherError: If the copy cannot be stored.
    """
    relative = SWITCHER_APP_FILES.get(app, "")
    if not relative or _original(app) is not None:
        return
    mode = _file_mode(relative)
    envelope = {
        "is_present": mode != "",
        "mode": mode,
        "text": _read_text(relative),
    }
    _write_json_at(_original_path(app), envelope)
    if _original(app) is None:
        raise SwitcherError(
            "could not keep a copy of this machine's own configuration, "
            "so it was left untouched"
        )


def _restore_original(app: str) -> bool:
    """Put a tool's configuration back to the copy activation kept.

    Args:
        app: Which tool, in cc-switch's vocabulary.

    Returns:
        True when there was a copy to put back.
    """
    snapshot = _original(app)
    if snapshot is None:
        return False
    relative = SWITCHER_APP_FILES.get(app, "")
    if snapshot.get("is_present"):
        _write_text(relative, snapshot.get("text", ""), snapshot.get("mode", ""))
    else:
        _remove_file(_home_path(relative))
    _remove_file(_original_path(app))
    return True


def _original(app: str) -> "dict | None":
    """The copy kept for one tool, or None when there is none."""
    snapshot = _read_json_at(_original_path(app))
    return snapshot or None


def _original_path(app: str) -> str:
    """Where one tool's copy lives, under the client's configuration."""
    return os.path.join(
        _platform().config_dir(), CLIENT_ORIGINAL_DIR_NAME, f"{app}.json"
    )


def _strip_hub_keys(app: str) -> None:
    """Remove only the hub's own entries from a tool's configuration."""
    if app != "claude":
        return
    data = _read_json(SWITCHER_APP_FILES["claude"])
    env = dict(data.get("env", {}))
    for key in CLAUDE_ENV_KEYS:
        env.pop(key, None)
    if env:
        data["env"] = env
    else:
        data.pop("env", None)
    _write_json(SWITCHER_APP_FILES["claude"], data)


def _add_provider(app: str, base_url: str, api_key: str, config: dict) -> None:
    """Make the hub this tool's provider, applying the staged choices.

    Claude's provider is built from what is already there; the file is
    copied aside and read first, before anything is switched or deleted.
    Codex and Gemini let cc-switch write the endpoint, then get the chosen
    model settled into their own file.

    Args:
        app: Which tool, in cc-switch's vocabulary.
        base_url: The hub's AI endpoint.
        api_key: This person's gateway key.
        config: The tool's staged choices.

    Raises:
        SwitcherError: If the existing configuration cannot be copied aside,
            if cc-switch refuses, or if the settings file did not end up
            naming the hub.
    """
    _capture_original(app)
    if app == "claude":
        existing = _read_json(SWITCHER_APP_FILES["claude"])
        settings = json.dumps(
            {**existing, "env": _hub_env(existing, base_url, api_key, config)}
        )
    else:
        settings = ""

    _drop_provider(app)

    arguments = [
        "provider",
        "add",
        "--id",
        SWITCHER_PROVIDER_ID,
        "--name",
        SWITCHER_PROVIDER_NAME,
    ]
    if settings:
        arguments += ["--config", settings]
    else:
        arguments += ["--base-url", base_url, "--api-key", api_key]
    try:
        _run(arguments, app)
    except SwitcherError:
        if not settings:
            raise
    _use_provider(app)

    if app == "claude":
        _write_json(SWITCHER_APP_FILES["claude"], json.loads(settings))
        if not is_active(
            base_url=base_url, api_key=api_key, model=str(config.get("default", ""))
        ):
            raise SwitcherError("the settings file did not take the hub's endpoint")
    elif app == "codex":
        _settle_codex_config(config)
    elif app == "gemini":
        _settle_gemini_config(config)


def _hub_env(existing: dict, base_url: str, api_key: str, config: dict) -> dict:
    """The tool's environment with the hub's endpoint in place of any other.

    Args:
        existing: The tool's current environment.
        base_url: The hub's AI endpoint.
        api_key: This person's gateway key.
        config: The staged slot choices.

    Returns:
        The environment to write.
    """
    env = dict(existing.get("env", {}))
    for key in CLAUDE_ENV_KEYS:
        env.pop(key, None)
    env["ANTHROPIC_BASE_URL"] = base_url
    env["ANTHROPIC_AUTH_TOKEN"] = api_key
    for slot, key in CLAUDE_SLOT_KEYS.items():
        model = str(config.get(slot, "") or "")
        if model:
            env[key] = model
    return env


def _settle_codex_config(config: dict) -> None:
    """Write the chosen model and reasoning effort into Codex's config.toml.

    Args:
        config: The staged choices: ``model``, ``model_reasoning_effort``.
    """
    values = {}
    for key in CODEX_CONFIG_KEYS:
        value = str(config.get(key, "") or "")
        if value:
            values[key] = value
    if not values:
        return
    relative = SWITCHER_APP_FILES["codex"]
    _write_text(relative, _merge_toml_top_level(_read_text(relative), values))


def _settle_gemini_config(config: dict) -> None:
    """Write the chosen model into Gemini's env file.

    Args:
        config: The staged choices: ``model``.
    """
    model = str(config.get("model", "") or "")
    if not model:
        return
    relative = SWITCHER_APP_FILES["gemini"]
    _write_text(
        relative, _merge_env_line(_read_text(relative), GEMINI_MODEL_KEY, model)
    )


def _merge_toml_top_level(text: str, values: dict) -> str:
    """A TOML text with the given top-level keys set, the rest untouched.

    Args:
        text: The file as it stands.
        values: Key to string value.

    Returns:
        The merged text.
    """
    kept = []
    is_in_section = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            is_in_section = True
        if not is_in_section and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in values:
                continue
        kept.append(line)
    head = [f'{key} = "{value}"' for key, value in values.items()]
    merged = "\n".join(head + kept)
    return merged.rstrip("\n") + "\n"


def _merge_env_line(text: str, key: str, value: str) -> str:
    """An env-file text with one ``KEY=value`` line set, the rest untouched.

    Args:
        text: The file as it stands.
        key: The variable name.
        value: Its value.

    Returns:
        The merged text.
    """
    kept = [
        line for line in text.splitlines() if not line.strip().startswith(f"{key}=")
    ]
    kept.append(f"{key}={value}")
    return "\n".join(kept).lstrip("\n").rstrip("\n") + "\n"


def _use_provider(app: str) -> None:
    _run(["use", SWITCHER_PROVIDER_ID], app)


def _run(arguments: list, app: str, *, is_checked: bool = True) -> str:
    """Run the cc-switch CLI as this person.

    Args:
        arguments: Arguments after the app selector.
        app: Which tool's configuration to act on.
        is_checked: Whether a non-zero exit is an error.

    Returns:
        Standard output.

    Raises:
        SwitcherError: If the command fails while checked.
    """
    binary = find_cli()
    if binary is None:
        raise SwitcherError("the cc-switch command line is not installed")
    command = [binary, "--app", app] + arguments
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=COMMAND_TIMEOUT_S
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise SwitcherError(f"cc-switch could not run: {error}")
    if is_checked and result.returncode != 0:
        output = (result.stderr or result.stdout or "").strip()
        raise SwitcherError(output[-200:] or "cc-switch refused")
    return result.stdout or ""


def _home_path(relative: str) -> str:
    """One path below this person's home."""
    return os.path.join(os.path.expanduser("~"), relative)


def _file_mode(relative: str) -> str:
    """A file's permission bits as an octal string, empty when it is not there.

    Args:
        relative: Path below this person's home.

    Returns:
        Something like ``600``, or empty.
    """
    path = _home_path(relative)
    if not os.path.exists(path):
        return ""
    return oct(os.stat(path).st_mode & 0o777)[2:]


def _read_text(relative: str) -> str:
    """Read a file below this person's home, empty when absent."""
    return _read_text_at(_home_path(relative))


def _read_text_at(path: str) -> str:
    """Read one file, empty when absent or unreadable."""
    try:
        with open(path, "r", encoding="utf-8") as stream:
            return stream.read()
    except OSError:
        return ""


def _read_json(relative: str) -> dict:
    """Read a JSON file below this person's home, empty when unusable."""
    return _read_json_at(_home_path(relative))


def _read_json_at(path: str) -> dict:
    """Read one JSON file, empty when unusable."""
    try:
        data = json.loads(_read_text_at(path) or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _write_text(relative: str, text: str, mode: str = "") -> None:
    """Write a file below this person's home.

    Args:
        relative: Path below the home.
        text: What to write.
        mode: Permission bits to set, as an octal string; empty leaves them.
    """
    path = _home_path(relative)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as stream:
        stream.write(text)
    if mode:
        os.chmod(path, int(mode, 8))


def _write_json(relative: str, data: dict) -> None:
    """Write a JSON file below this person's home."""
    _write_text(relative, json.dumps(data, indent=2))


def _write_json_at(path: str, data: dict) -> None:
    """Write one JSON file, its directory made on the way."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as stream:
        stream.write(json.dumps(data, indent=2))


def _remove_file(path: str) -> None:
    """Delete one file, absent being fine."""
    try:
        os.unlink(path)
    except OSError:
        pass
