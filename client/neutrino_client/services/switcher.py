"""Finding cc-switch and pointing it at the hub.

cc-switch is what people already use to keep several AI providers on one
machine and flip between them, so the client adds the hub to it as one more
provider and lets it write each tool's configuration. The client carries
its own copy of the CLI; one found on the path is used when the bundle is
absent.

cc-switch replaces a tool's file whole when it switches, so before the hub
is ever made current the client hands cc-switch what the person already
had, through cc-switch's own means: the live MCP servers go into its MCP
store, and the settings that belong to no provider go into its per-tool
common snippet, which the hub's provider then carries. A snippet the person
already set is never replaced. That adoption happens once per tool and is
recorded; every activation after it is two calls per tool, add and use, and
none at all when nothing changed. The provider that was current beforehand
is remembered, and deactivating switches back to it and deletes the hub's
entry; a tool that had no configuration file has the one cc-switch made
taken away again.

Activation is all or nothing: a tool that refuses has every tool switched
before it put back, and the refusal is the answer.

One knob has no flag in cc-switch: Codex's reasoning effort, which is
settled into ``config.toml`` after the switch when the person chose one.

Not pure: runs the binary and edits the person's configuration.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile

from neutrino_client import bundled
from neutrino_client.constants import CLIENT_ORIGINAL_DIR_NAME
from neutrino_client.platforms.base import PlatformUnsupportedError, run_quietly


class SwitcherError(RuntimeError):
    """Raised when cc-switch refuses, or a configuration cannot be kept."""


SWITCHER_PROVIDER_ID = "neutrino"
SWITCHER_PROVIDER_NAME = "Neutrino Hub"

# The tools cc-switch can point at the hub, in its own vocabulary, and where
# each keeps the file that switching replaces.
SWITCHER_APPS = ("claude", "codex", "gemini")
SWITCHER_APP_FILES = {
    "claude": ".claude/settings.json",
    "codex": ".codex/config.toml",
    "gemini": ".gemini/.env",
}

# Claude Code's role slots, each a flag of cc-switch's provider add.
CLAUDE_SLOT_FLAGS = {
    "default": "--model",
    "opus": "--opus-model",
    "sonnet": "--sonnet-model",
    "haiku": "--haiku-model",
}

# Codex's one knob cc-switch has no flag for, a top-level key of config.toml.
CODEX_EFFORT_KEY = "model_reasoning_effort"

# What cc-switch's extract leaves in a common snippet that is nonetheless the
# provider's own: a snippet carrying these would override the hub's choice.
COMMON_SNIPPET_OWN_KEYS = {
    "claude": (),
    "codex": ("model",),
    "gemini": ("GEMINI_MODEL",),
}

COMMAND_TIMEOUT_S = 120

# The provider cc-switch itself seeds for each tool, there to switch to when
# nothing of the person's own was current before the hub: cc-switch refuses
# to delete whichever provider is current.
OFFICIAL_PROVIDER_IDS = {
    "claude": "claude-official",
    "codex": "codex-official",
    "gemini": "gemini-official",
}

# What cc-switch asks before deleting a provider, and the answer. It takes
# no flag in the prompt's place, so the question is answered on a terminal.
DELETE_PROMPT = "(y/N)"
DELETE_ANSWER = "y\n"

# What cc-switch draws its provider table with.
TABLE_SEPARATOR = "┆"

# cc-switch draws its tables in UTF-8 whatever the console's own code page
# is.
COMMAND_ENCODING = "utf-8"

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

    Args:
        base_url: The hub's AI endpoint.
        api_key: This person's gateway key.
        tool_configs: Each tool's staged choices: ``claude`` slot names,
            ``codex`` model and reasoning effort, ``gemini`` model. None or
            a missing key leaves that choice to cc-switch.

    Returns:
        A short message naming the tools that took it.

    Raises:
        SwitcherError: If cc-switch refuses for any tool; the tools switched
            before it are put back first.
    """
    configs = tool_configs or {}
    done = []
    for app in SWITCHER_APPS:
        try:
            _point_at_hub(app, base_url, api_key, configs.get(app) or {})
        except SwitcherError as error:
            undone = []
            for switched in done:
                try:
                    _point_away(switched)
                except SwitcherError as failure:
                    undone.append(f"{switched}: {failure}")
            problem = f"{app}: {error}"
            if undone:
                problem += "; not put back: " + "; ".join(undone)
            raise SwitcherError(problem[:300])
        done.append(app)
    return ", ".join(done)


def deactivate(*, base_url: str = "") -> str:
    """Put every tool back on the provider it had before the hub.

    Args:
        base_url: The hub's endpoint; accepted for the caller's symmetry
            with activation.

    Returns:
        What happened, in the words the page shows.
    """
    notes = []
    for app in SWITCHER_APPS:
        previous = _point_away(app)
        notes.append(f"{app} → {previous or 'unset'}")
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
    return _current_provider(app) == SWITCHER_PROVIDER_ID


def _point_at_hub(app: str, base_url: str, api_key: str, config: dict) -> None:
    """Make the hub one tool's provider, the person's own settings kept.

    Args:
        app: Which tool, in cc-switch's vocabulary.
        base_url: The hub's AI endpoint.
        api_key: This person's gateway key.
        config: The tool's staged choices.

    Raises:
        SwitcherError: If cc-switch refuses, or if Claude Code's settings
            did not end up naming the hub.
    """
    relative = SWITCHER_APP_FILES[app]
    record = _read_record(app)
    if record is None:
        record = _adopt_once(app)
    wanted = _wanted(app, base_url, api_key, config)
    if record.get("added") == wanted and is_active_for(app):
        _verify(app, base_url, api_key, config)
        return

    _drop_provider(app, record.get("previous", ""))
    arguments = [
        "provider",
        "add",
        "--id",
        SWITCHER_PROVIDER_ID,
        "--name",
        SWITCHER_PROVIDER_NAME,
        "--base-url",
        base_url,
        "--api-key",
        api_key,
    ]
    arguments += _model_flags(app, config)
    if _common_snippet(app):
        arguments.append("--common-config")
    _run(arguments, app)
    _run(["use", SWITCHER_PROVIDER_ID], app)

    if app == "codex":
        effort = str(config.get(CODEX_EFFORT_KEY, "") or "")
        if effort:
            _write_text(
                relative,
                _merge_toml_top_level(_read_text(relative), {CODEX_EFFORT_KEY: effort}),
            )
    _verify(app, base_url, api_key, config)
    record["added"] = wanted
    _write_record(app, record)


def _adopt_once(app: str) -> dict:
    """Take the tool as it stands into cc-switch, and start its record.

    Listing is what makes cc-switch take a configuration it has never seen
    into its store, as the provider switching back will return to; the MCP
    servers and the shared settings follow. None of it happens again for
    this tool while its record stands.

    Args:
        app: Which tool, in cc-switch's vocabulary.

    Returns:
        The record written.
    """
    is_present = os.path.isfile(_home_path(SWITCHER_APP_FILES[app]))
    _run(["provider", "list"], app, is_checked=False)
    if is_present:
        _adopt(app)
    current = _current_provider(app)
    record = {
        "is_present": is_present,
        "previous": "" if current == SWITCHER_PROVIDER_ID else current,
        "added": None,
    }
    _write_record(app, record)
    return record


def _wanted(app: str, base_url: str, api_key: str, config: dict) -> dict:
    """What the hub's provider should carry, as the record remembers it.

    Args:
        app: Which tool, in cc-switch's vocabulary.
        base_url: The hub's AI endpoint.
        api_key: This person's gateway key.
        config: The tool's staged choices.

    Returns:
        The endpoint, a digest of the key, and the flags; the key itself
        is never written down.
    """
    return {
        "base_url": base_url,
        "key_digest": hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16],
        "flags": _model_flags(app, config),
        "effort": str(config.get(CODEX_EFFORT_KEY, "") or "") if app == "codex" else "",
    }


def _verify(app: str, base_url: str, api_key: str, config: dict) -> None:
    """Read the tool's own file back and refuse when it does not name the hub.

    Only Claude Code's file is read: it is the one the hub's grant is
    measured by, and a tool that is not on this machine has no file.

    Args:
        app: Which tool, in cc-switch's vocabulary.
        base_url: The hub's AI endpoint.
        api_key: This person's gateway key.
        config: The tool's staged choices.

    Raises:
        SwitcherError: When Claude Code's settings do not name the hub.
    """
    if app != "claude":
        return
    if not is_active(
        base_url=base_url, api_key=api_key, model=str(config.get("default", ""))
    ):
        raise SwitcherError("the settings file did not take the hub's endpoint")


def _point_away(app: str) -> str:
    """Return one tool to the provider it had, and take the hub's out.

    Args:
        app: Which tool, in cc-switch's vocabulary.

    Returns:
        The provider switched back to, empty when there was none.
    """
    record = _read_record(app) or {}
    previous = str(record.get("previous", "") or "")
    returned_to = _drop_provider(app, previous)
    path = _home_path(SWITCHER_APP_FILES[app])
    if record and not record.get("is_present") and os.path.isfile(path):
        _remove_file(path)
    _remove_file(_record_path(app))
    return returned_to


def _drop_provider(app: str, previous: str) -> str:
    """Remove the hub's provider, switching away first if it is current.

    cc-switch refuses to delete whichever provider is current, and asks
    before deleting at all. With nothing of the person's own to return to,
    the tool goes to the provider cc-switch seeds for it.

    Args:
        app: Which tool's providers to act on.
        previous: The provider to switch back to, empty for none.

    Returns:
        The provider switched to, empty when no switch was needed.

    Raises:
        SwitcherError: If the provider is still there afterwards.
    """
    if not _has_provider(app):
        return ""
    returned_to = ""
    if is_active_for(app):
        returned_to = previous or OFFICIAL_PROVIDER_IDS.get(app, "")
        if returned_to:
            _run(["use", returned_to], app, is_checked=False)
    _delete_provider(app)
    if _has_provider(app):
        raise SwitcherError("cc-switch kept the hub's provider")
    return returned_to


def _delete_provider(app: str) -> None:
    """Answer cc-switch's question and have it delete the hub's provider.

    Args:
        app: Which tool's providers to act on.

    Raises:
        SwitcherError: If no terminal can be made for the question.
    """
    binary = find_cli()
    if binary is None:
        raise SwitcherError("the cc-switch command line is not installed")
    argv = [binary, "--app", app, "provider", "delete", SWITCHER_PROVIDER_ID]
    try:
        _platform().run_answering(
            argv,
            prompt=DELETE_PROMPT,
            answer=DELETE_ANSWER,
            timeout_s=COMMAND_TIMEOUT_S,
        )
    except (PlatformUnsupportedError, OSError) as error:
        raise SwitcherError(f"could not answer cc-switch: {error}")


def _has_provider(app: str) -> bool:
    """Whether the hub's provider is in cc-switch's list for a tool.

    Args:
        app: Which tool's providers to look at.

    Returns:
        True when a row names the hub's id.
    """
    output = _run(["provider", "list"], app, is_checked=False)
    for line in output.splitlines():
        if TABLE_SEPARATOR not in line:
            continue
        cells = [cell.strip() for cell in line.split(TABLE_SEPARATOR)]
        if len(cells) > 1 and cells[1] == SWITCHER_PROVIDER_ID:
            return True
    return False


def _adopt(app: str) -> None:
    """Hand cc-switch what the person already had, through its own stores.

    The live MCP servers go into its MCP store, which it writes into every
    configuration it makes. The settings that belong to no provider go into
    its common snippet for the tool, unless the person set one already.

    Args:
        app: Which tool, in cc-switch's vocabulary.
    """
    _run(["mcp", "import"], app, is_checked=False)
    if _common_snippet(app):
        return
    with _payload_file(_live_payload(app)) as payload_path:
        extracted = _run(
            ["config", "common", "extract", "--file", payload_path],
            app,
            is_checked=False,
        )
    snippet = _without_own_keys(app, extracted.strip())
    if not snippet:
        return
    with _payload_file(snippet) as snippet_path:
        _run(["config", "common", "set", "--file", snippet_path], app, is_checked=False)


def _live_payload(app: str) -> str:
    """A tool's live configuration in the shape cc-switch's extract reads.

    Args:
        app: Which tool, in cc-switch's vocabulary.

    Returns:
        JSON text: Claude's settings as they are, Codex's TOML wrapped as
        ``config``, Gemini's env lines as an object.
    """
    text = _read_text(SWITCHER_APP_FILES[app])
    if app == "claude":
        return text or "{}"
    if app == "codex":
        return json.dumps({"config": text, "auth": {}})
    env = {}
    for line in text.splitlines():
        key, separator, value = line.partition("=")
        if separator and key.strip():
            env[key.strip()] = value.strip()
    return json.dumps({"env": env})


def _without_own_keys(app: str, snippet: str) -> str:
    """A common snippet with the provider's own keys taken out.

    Args:
        app: Which tool, in cc-switch's vocabulary.
        snippet: What cc-switch extracted, in the tool's snippet format.

    Returns:
        The snippet to keep, empty when nothing is left of it.
    """
    own = COMMON_SNIPPET_OWN_KEYS.get(app, ())
    if not snippet:
        return ""
    if app == "codex":
        kept = []
        is_in_section = False
        for line in snippet.splitlines():
            stripped = line.strip()
            if stripped.startswith("["):
                is_in_section = True
            if not is_in_section and "=" in stripped:
                if stripped.split("=", 1)[0].strip() in own:
                    continue
            kept.append(line)
        return "\n".join(kept).strip()
    try:
        data = json.loads(snippet)
    except ValueError:
        return ""
    if not isinstance(data, dict):
        return ""
    for key in own:
        data.pop(key, None)
    return json.dumps(data, indent=2) if data else ""


def _common_snippet(app: str) -> str:
    """The common snippet cc-switch holds for a tool, empty when none.

    Args:
        app: Which tool, in cc-switch's vocabulary.

    Returns:
        The snippet's text.
    """
    output = _run(["config", "common", "show"], app, is_checked=False)
    lines = output.splitlines()
    for at, line in enumerate(lines):
        if line.strip().startswith("App:"):
            return "\n".join(lines[at + 1 :]).strip()
    return ""


def _current_provider(app: str) -> str:
    """The provider cc-switch has current for a tool, empty when none.

    Args:
        app: Which tool, in cc-switch's vocabulary.

    Returns:
        The provider id.
    """
    output = _run(["provider", "current"], app, is_checked=False)
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("ID:"):
            return stripped[3:].strip()
    return ""


def _model_flags(app: str, config: dict) -> list:
    """The provider-add flags carrying the person's model choices.

    Args:
        app: Which tool, in cc-switch's vocabulary.
        config: The tool's staged choices.

    Returns:
        Flag and value pairs, flattened.
    """
    flags = []
    if app == "claude":
        for slot, flag in CLAUDE_SLOT_FLAGS.items():
            model = str(config.get(slot, "") or "")
            if model:
                flags += [flag, model]
        return flags
    model = str(config.get("model", "") or "")
    if model:
        flags += ["--model", model]
    return flags


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
        result = run_quietly(
            command, timeout_s=COMMAND_TIMEOUT_S, encoding=COMMAND_ENCODING
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise SwitcherError(f"cc-switch could not run: {error}")
    if is_checked and result.returncode != 0:
        output = (result.stderr or result.stdout or "").strip()
        raise SwitcherError(output[-200:] or "cc-switch refused")
    return result.stdout or ""


class _payload_file:
    """A file holding text for one cc-switch call, gone afterwards."""

    def __init__(self, text: str):
        self._text = text
        self._path = ""

    def __enter__(self) -> str:
        handle, self._path = tempfile.mkstemp(prefix="neutrino_switch_", suffix=".txt")
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(self._text)
        return self._path

    def __exit__(self, *_exc) -> None:
        _remove_file(self._path)


def _record_path(app: str) -> str:
    """Where one tool's record lives, under the client's configuration."""
    return os.path.join(
        _platform().config_dir(), CLIENT_ORIGINAL_DIR_NAME, f"{app}.json"
    )


def _read_record(app: str) -> "dict | None":
    """The record kept for one tool, or None when there is none."""
    record = _read_json_at(_record_path(app))
    return record or None


def _write_record(app: str, record: dict) -> None:
    """Keep one tool's record: whether it had a file, and what was current."""
    path = _record_path(app)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as stream:
        stream.write(json.dumps(record, indent=2))


def _home_path(relative: str) -> str:
    """One path below this person's home."""
    return os.path.join(os.path.expanduser("~"), relative)


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


def _write_text(relative: str, text: str) -> None:
    """Write a file below this person's home.

    Args:
        relative: Path below the home.
        text: What to write.
    """
    path = _home_path(relative)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as stream:
        stream.write(text)


def _remove_file(path: str) -> None:
    """Delete one file, quietly when it is not there."""
    try:
        os.remove(path)
    except OSError:
        pass
