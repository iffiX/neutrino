"""Pointing one account's AI tools at the hub with cc-switch, the desktop client's steps.

These are the client's steps (``client/desktop/neutrino_client/services/
switcher.py``), run for an account on a managed machine: the same cc-switch,
the same commands in the same order, the same record per tool, the same
switch back. What differs is only where things are done: cc-switch and every
file of the account's are reached as the account, and the records are kept
under the agent's state root, root's own, never in the account's home.

Before the hub is ever made current for a tool, cc-switch is handed what the
account already had: listing takes a configuration it has never seen into
its store, the live MCP servers go into its MCP store, and the settings that
belong to no provider go into its common snippet, unless one is set. That
adoption happens once per tool and is recorded; every activation after it is
add and use, and none at all when nothing changed. The provider that was
current beforehand is remembered; switching back makes it current again and
deletes the hub's entry. Every file of the tool's that a switch may write
is kept in the record as it was before the first switch, or as absent, and
the switch back puts each back as it was, byte for byte: a file that was
there gets its own text again, one that was absent is taken away, and a
tool directory the switch had to make is taken away once it is empty.
cc-switch writes a tool's files only into a directory that is there, so
the switch makes it, as the account, for a tool that has none. A switch
back that cannot run cc-switch is a failure, and the records stay.

Activation is all or nothing: a tool that refuses has itself, once its
record was started, and every tool switched before it put back, and the
refusal is the answer. Codex's reasoning effort
has no flag in cc-switch and is settled into ``config.toml`` after the
switch.

Not pure: runs cc-switch as the account and writes the records.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import subprocess
import tempfile

from neutrino_agent.ai_tools.constants import (
    AI_TOOLS_APP_DIRS,
    AI_TOOLS_APP_FILES,
    AI_TOOLS_APP_KEPT_FILES,
    AI_TOOLS_APP_KEY_FILES,
    AI_TOOLS_KEY_FILE_MODE,
    AI_TOOLS_APPS,
    AI_TOOLS_CLAUDE_SLOT_FLAGS,
    AI_TOOLS_CODE_SWITCH_FAILED,
    AI_TOOLS_CODEX_EFFORT_KEY,
    AI_TOOLS_COMMON_OWN_KEYS,
    AI_TOOLS_DELETE_ANSWER,
    AI_TOOLS_DELETE_PROMPT,
    AI_TOOLS_ENDPOINT_SUFFIXES,
    AI_TOOLS_KEY_DIGEST_CHARS,
    AI_TOOLS_OFFICIAL_PROVIDERS,
    AI_TOOLS_PROVIDER_ID,
    AI_TOOLS_PROVIDER_NAME,
    AI_TOOLS_RECORD_SUFFIX,
    AI_TOOLS_TABLE_SEPARATOR,
    AI_TOOLS_WORDS_LIMIT,
)
from neutrino_agent.exceptions import ToolSwitchError
from neutrino_agent.platforms.answered_run import plain_text


def endpoint_for(app: str, base_url: str) -> str:
    """The hub's endpoint as one tool's provider must carry it."""
    return base_url.rstrip("/") + AI_TOOLS_ENDPOINT_SUFFIXES.get(app, "")


def model_flags(app: str, config: dict) -> list:
    """The provider-add flags carrying the chosen models.

    Args:
        app: Which tool, in cc-switch's vocabulary.
        config: The tool's choices.

    Returns:
        Flag and value joined with ``=``, one item each.
    """
    flags = []
    if app == "claude":
        for slot, flag in AI_TOOLS_CLAUDE_SLOT_FLAGS.items():
            model = str(config.get(slot, "") or "")
            if model:
                flags.append(flag + "=" + model)
        return flags
    model = str(config.get("model", "") or "")
    if model:
        flags.append("--model=" + model)
    return flags


def wanted(app: str, base_url: str, api_key: str, config: dict) -> dict:
    """What the hub's provider should carry, as the record remembers it.

    Args:
        app: Which tool, in cc-switch's vocabulary.
        base_url: The gateway's endpoint.
        api_key: The device's gateway key.
        config: The tool's choices.

    Returns:
        The endpoint, a digest of the key, the flags and Codex's effort; the
        key itself is never written down.
    """
    return {
        "base_url": endpoint_for(app, base_url),
        "key_digest": hashlib.sha256(api_key.encode("utf-8")).hexdigest()[
            :AI_TOOLS_KEY_DIGEST_CHARS
        ],
        "flags": model_flags(app, config),
        "effort": (
            str(config.get(AI_TOOLS_CODEX_EFFORT_KEY, "") or "")
            if app == "codex"
            else ""
        ),
    }


def without_own_keys(app: str, snippet: str) -> str:
    """A common snippet with the provider's own keys taken out.

    Args:
        app: Which tool, in cc-switch's vocabulary.
        snippet: What cc-switch extracted, in the tool's snippet format.

    Returns:
        The snippet to keep, empty when nothing is left of it.
    """
    own = AI_TOOLS_COMMON_OWN_KEYS.get(app, ())
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


def merge_toml_top_level(text: str, values: dict) -> str:
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


def refusal_words(error: "subprocess.CalledProcessError") -> str:
    """What cc-switch said when it exited non-zero, trimmed."""
    output = (error.stderr or error.output or "").strip()
    return output[-AI_TOOLS_WORDS_LIMIT:] or "cc-switch refused"


def console_words(printed: str) -> str:
    """The end of what a console printed, as words.

    Args:
        printed: The console's output, escape sequences included.

    Returns:
        Its last words with the sequences taken out and the whitespace
        collapsed, or a note that nothing was printed.
    """
    text = plain_text(printed.encode("utf-8", "replace")).decode("utf-8", "replace")
    words = " ".join(text.split())
    return words[-AI_TOOLS_WORDS_LIMIT:] if words else "it printed nothing"


class AiToolsAccountSwitcher:
    """Points one account's tools at the hub and back, keeping a record per tool."""

    def __init__(self, *, session, record_dir: str):
        """
        Args:
            session: The :class:`AiToolsAccountSession` that reaches the
                account.
            record_dir: Where this account's records are kept, root's own.
        """
        self._session = session
        self._record_dir = record_dir

    def is_current(self, *, base_url: str, api_key: str, tool_configs: dict) -> bool:
        """Whether every tool's record already carries the wanted settings.

        Args:
            base_url: The gateway's endpoint.
            api_key: The device's gateway key.
            tool_configs: Each tool's choices.

        Returns:
            True when nothing would change; nothing is run to answer.
        """
        for app in AI_TOOLS_APPS:
            record = self.read_record(app)
            config = tool_configs.get(app) or {}
            if record is None or record.get("added") != wanted(
                app, base_url, api_key, config
            ):
                return False
        return True

    def activate(self, *, base_url: str, api_key: str, tool_configs: dict) -> list:
        """Register the hub in the account's cc-switch and switch every tool to it.

        Args:
            base_url: The gateway's endpoint.
            api_key: The device's gateway key.
            tool_configs: Each tool's choices.

        Returns:
            The tools switched this time; empty when every tool already
            stood on the hub as asked.

        Raises:
            ToolSwitchError: If cc-switch refuses for any tool; the tools
                switched before it are put back first.
        """
        done = []
        switched = []
        self._session.is_own_store = True
        self._session.prepare_store()
        for app in AI_TOOLS_APPS:
            try:
                if self._point_at_hub(
                    app, base_url, api_key, tool_configs.get(app) or {}
                ):
                    switched.append(app)
            except ToolSwitchError as error:
                undone = []
                if self.read_record(app) is not None:
                    done.append(app)
                for earlier in done:
                    try:
                        self._point_away(earlier)
                    except ToolSwitchError as failure:
                        undone.append(
                            f"{earlier}: {failure.params.get('detail', failure.code)}"
                        )
                self._session.is_own_store = True
                if not self.has_records():
                    self._session.remove_store()
                if error.code != AI_TOOLS_CODE_SWITCH_FAILED:
                    raise
                problem = f"{app}: {error.params.get('detail', '')}"
                if undone:
                    problem += "; not put back: " + "; ".join(undone)
                raise self._session.failure(problem) from error
            done.append(app)
        return switched

    def deactivate(self) -> list:
        """Put every tool back on the provider it had before the hub.

        Returns:
            ``<tool> → <provider>`` for each tool, ``unset`` where none was
            made current.

        Raises:
            ToolSwitchError: When cc-switch cannot run, the hub's provider
                stays in it, or a file cannot be put back; the records of
                the tools not yet put back stay.
        """
        notes = []
        for app in AI_TOOLS_APPS:
            previous = self._point_away(app)
            notes.append(f"{app} → {previous or 'unset'}")
        self._session.is_own_store = True
        self._session.remove_store()
        return notes

    def has_records(self) -> bool:
        """Whether any tool of this account has a record."""
        return any(self.read_record(app) is not None for app in AI_TOOLS_APPS)

    def read_record(self, app: str) -> "dict | None":
        """The record kept for one tool, or None when there is none."""
        try:
            with open(self._record_path(app), "r", encoding="utf-8") as stream:
                record = json.load(stream)
        except (OSError, ValueError):
            return None
        return record if isinstance(record, dict) and record else None

    def _point_at_hub(
        self, app: str, base_url: str, api_key: str, config: dict
    ) -> bool:
        """Make the hub one tool's provider, the account's own settings kept.

        Returns:
            True when the tool was switched; False when it already stood on
            the hub as asked.

        Raises:
            ToolSwitchError: If cc-switch refuses, or if Claude Code's
                settings did not end up naming the hub.
        """
        record = self.read_record(app)
        self._session.is_own_store = record is None or bool(record.get("is_own_store"))
        if record is None:
            record = self._adopt_once(app)
        settings = wanted(app, base_url, api_key, config)
        if record.get("added") == settings and self._is_active_for(app):
            self._verify(app, base_url, api_key, config)
            return False

        self._drop_provider(app, record.get("previous", ""))
        arguments = [
            "provider",
            "add",
            "--id",
            AI_TOOLS_PROVIDER_ID,
            "--name",
            AI_TOOLS_PROVIDER_NAME,
            "--base-url=" + endpoint_for(app, base_url),
            "--api-key=" + api_key,
        ]
        arguments += model_flags(app, config)
        if self._common_snippet(app):
            arguments.append("--common-config")
        directory = self._session.path(AI_TOOLS_APP_DIRS[app])
        if not self._session.is_dir(directory):
            self._session.make_dir(directory)
        try:
            self._session.cc(arguments, app)
            self._session.cc(["use", AI_TOOLS_PROVIDER_ID], app)
        except subprocess.CalledProcessError as error:
            raise self._session.failure(refusal_words(error)) from error

        if app == "codex":
            effort = str(config.get(AI_TOOLS_CODEX_EFFORT_KEY, "") or "")
            if effort:
                path = self._app_file(app)
                self._session.write_text(
                    path,
                    merge_toml_top_level(
                        self._session.read_text(path),
                        {AI_TOOLS_CODEX_EFFORT_KEY: effort},
                    ),
                )
        for name in AI_TOOLS_APP_KEY_FILES[app]:
            path = self._kept_path(app, name)
            if self._session.is_file(path):
                self._session.set_mode(path, AI_TOOLS_KEY_FILE_MODE)
        self._verify(app, base_url, api_key, config)
        record["added"] = settings
        self._write_record(app, record)
        return True

    def _adopt_once(self, app: str) -> dict:
        """Take the tool as it stands into cc-switch, and start its record.

        The record keeps whether the tool's directory was there and each
        file a switch may write as it was, None for one that was absent.
        """
        is_present = self._session.is_file(self._app_file(app))
        is_dir_present = self._session.is_dir(
            self._session.path(AI_TOOLS_APP_DIRS[app])
        )
        kept = {}
        kept_modes = {}
        for name in AI_TOOLS_APP_KEPT_FILES[app]:
            path = self._kept_path(app, name)
            is_there = self._session.is_file(path)
            kept[name] = self._session.read_text(path) if is_there else None
            mode = self._session.mode_of(path) if is_there else None
            if mode is not None:
                kept_modes[name] = mode
        self._session.cc(["provider", "list"], app, is_checked=False)
        if is_present:
            self._adopt(app)
        current = self._current_provider(app)
        record = {
            "is_present": is_present,
            "is_dir_present": is_dir_present,
            "kept": kept,
            "kept_modes": kept_modes,
            "is_own_store": True,
            "previous": "" if current == AI_TOOLS_PROVIDER_ID else current,
            "added": None,
        }
        self._write_record(app, record)
        return record

    def _verify(self, app: str, base_url: str, api_key: str, config: dict) -> None:
        """Read a tool's file back and refuse when it does not name the hub.

        Raises:
            ToolSwitchError: When Claude Code's settings do not carry the
                hub's endpoint, key and model, or Codex's or Gemini's file
                does not name the hub's endpoint.
        """
        if app != "claude":
            text = self._session.read_text(self._app_file(app))
            if endpoint_for(app, base_url) not in text:
                raise self._session.failure(
                    "the settings file did not take the hub's endpoint"
                )
            return
        try:
            settings = json.loads(self._session.read_text(self._app_file(app)) or "{}")
        except ValueError:
            settings = {}
        env = settings.get("env", {}) if isinstance(settings, dict) else {}
        env = env if isinstance(env, dict) else {}
        model = str(config.get("default", "") or "")
        if (
            env.get("ANTHROPIC_BASE_URL") != base_url
            or env.get("ANTHROPIC_AUTH_TOKEN") != api_key
            or (model and env.get("ANTHROPIC_MODEL") != model)
        ):
            raise self._session.failure(
                "the settings file did not take the hub's endpoint"
            )

    def _point_away(self, app: str) -> str:
        """Return one tool to the provider it had, take the hub's out, and put its files back.

        Returns:
            The provider switched back to, empty when there was none.

        Raises:
            ToolSwitchError: When cc-switch cannot run, the hub's provider
                stays in it, or a file cannot be put back; the record stays.
        """
        record = self.read_record(app) or {}
        self._session.is_own_store = not record or bool(record.get("is_own_store"))
        if self._session.is_own_store:
            self._session.prepare_store()
        previous = str(record.get("previous", "") or "")
        returned_to = self._drop_provider(app, previous)
        kept = record.get("kept")
        if isinstance(kept, dict):
            self._put_back(app, kept, record.get("kept_modes") or {})
            if record.get("is_dir_present") is False:
                self._session.remove_empty_dir(
                    self._session.path(AI_TOOLS_APP_DIRS[app])
                )
        else:
            path = self._app_file(app)
            if record and not record.get("is_present") and self._session.is_file(path):
                self._session.remove(path)
        with contextlib.suppress(OSError):
            os.remove(self._record_path(app))
        return returned_to

    def _put_back(self, app: str, kept: dict, modes: dict) -> None:
        """Put each file a switch may write back as it was before the first switch.

        A file that was there gets its own text again, byte for byte, and
        its own mode where one was kept; one that was absent is taken away.

        Raises:
            ToolSwitchError: When a file cannot be written.
        """
        for name, original in kept.items():
            path = self._kept_path(app, name)
            is_there = self._session.is_file(path)
            if original is None:
                if is_there:
                    self._session.remove(path)
                continue
            if not is_there or self._session.read_text(path) != original:
                self._session.write_text(path, original)
            mode = modes.get(name)
            if isinstance(mode, int) and self._session.mode_of(path) != mode:
                self._session.set_mode(path, mode)

    def _kept_path(self, app: str, name: str) -> str:
        """One file a switch may write, below the account's home."""
        return self._session.path(AI_TOOLS_APP_DIRS[app], name)

    def _drop_provider(self, app: str, previous: str) -> str:
        """Remove the hub's provider, switching away first if it is current.

        Returns:
            The provider switched to, empty when no switch was needed.

        Raises:
            ToolSwitchError: If the provider is still there afterwards.
        """
        if not self._has_provider(app):
            return ""
        returned_to = ""
        if self._is_active_for(app):
            returned_to = previous or AI_TOOLS_OFFICIAL_PROVIDERS.get(app, "")
            if returned_to:
                self._session.cc(["use", returned_to], app, is_checked=False)
        printed = self._session.cc_answering(
            ["provider", "delete", AI_TOOLS_PROVIDER_ID],
            app,
            prompt=AI_TOOLS_DELETE_PROMPT,
            answer=AI_TOOLS_DELETE_ANSWER,
        )
        if self._has_provider(app):
            raise self._session.failure(
                f"cc-switch kept the hub's provider: {console_words(printed)}"
            )
        return returned_to

    def _has_provider(self, app: str) -> bool:
        """Whether the hub's provider is in cc-switch's list for a tool.

        Raises:
            ToolSwitchError: When cc-switch cannot list, so nothing can be
                said of the hub's provider.
        """
        try:
            output = self._session.cc(["provider", "list"], app)
        except subprocess.CalledProcessError as error:
            raise self._session.failure(refusal_words(error)) from error
        for line in output.splitlines():
            if AI_TOOLS_TABLE_SEPARATOR not in line:
                continue
            cells = [cell.strip() for cell in line.split(AI_TOOLS_TABLE_SEPARATOR)]
            if len(cells) > 1 and cells[1] == AI_TOOLS_PROVIDER_ID:
                return True
        return False

    def _is_active_for(self, app: str) -> bool:
        """Whether cc-switch points one tool at the hub."""
        return self._current_provider(app) == AI_TOOLS_PROVIDER_ID

    def _current_provider(self, app: str) -> str:
        """The provider cc-switch has current for a tool, empty when none."""
        output = self._session.cc(["provider", "current"], app, is_checked=False)
        for line in output.splitlines():
            stripped = line.strip()
            if stripped.startswith("ID:"):
                return stripped[3:].strip()
        return ""

    def _adopt(self, app: str) -> None:
        """Hand cc-switch what the account already had, through its own stores."""
        self._session.cc(["mcp", "import"], app, is_checked=False)
        if self._common_snippet(app):
            return
        extracted = self._with_payload(
            self._live_payload(app), ["config", "common", "extract", "--file"], app
        )
        snippet = without_own_keys(app, extracted.strip())
        if not snippet:
            return
        self._with_payload(snippet, ["config", "common", "set", "--file"], app)

    def _with_payload(self, text: str, arguments: list, app: str) -> str:
        """Run one cc-switch call that reads a file, the file the account's own and gone afterwards."""
        path = self._session.payload_path()
        self._session.write_text(path, text)
        try:
            return self._session.cc(arguments + [path], app, is_checked=False)
        finally:
            self._session.remove_payload()

    def _live_payload(self, app: str) -> str:
        """A tool's live configuration in the shape cc-switch's extract reads."""
        text = self._session.read_text(self._app_file(app))
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

    def _common_snippet(self, app: str) -> str:
        """The common snippet cc-switch holds for a tool, empty when none."""
        output = self._session.cc(["config", "common", "show"], app, is_checked=False)
        lines = output.splitlines()
        for at, line in enumerate(lines):
            if line.strip().startswith("App:"):
                return "\n".join(lines[at + 1 :]).strip()
        return ""

    def _app_file(self, app: str) -> str:
        """Where one tool keeps the file switching replaces, below the account's home."""
        return self._session.path(*AI_TOOLS_APP_FILES[app])

    def _record_path(self, app: str) -> str:
        return os.path.join(self._record_dir, app + AI_TOOLS_RECORD_SUFFIX)

    def _write_record(self, app: str, record: dict) -> None:
        """Keep one tool's record, root's own, whole or not at all."""
        os.makedirs(self._record_dir, mode=0o700, exist_ok=True)
        handle, temporary = tempfile.mkstemp(dir=self._record_dir, prefix=".record_")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(record, stream, indent=2)
            os.chmod(temporary, 0o600)
            os.replace(temporary, self._record_path(app))
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(temporary)
            raise
