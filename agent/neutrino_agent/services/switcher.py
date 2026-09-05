"""Finding, installing and pointing cc-switch at the hub.

cc-switch is what people already use to keep several AI providers on one
machine and flip between them, so the agent adds the hub to it as one more
provider rather than competing with it. Detection never runs the binary: the
desktop app is a GUI with no argument parsing, so asking it for its version
opens a window; what is inspected instead is where the binary sits and which
package owns it. The CLI fork and the desktop app share one store, so a
provider registered through either shows up in both.

Both publish x86_64 and aarch64 only — Jetson, DGX Spark and a 64-bit
Raspberry Pi are covered, a 32-bit Raspberry Pi is not.

Each tool is configured with its own knobs, drawn from the person's staged
choices: Claude Code's four role slots, Codex's model and reasoning effort
written into ``config.toml``, Gemini's one model. Activating keeps a copy of
each file as it stood beforehand — permission rules, model choice,
everything — and deactivating puts that copy back verbatim, deleting the
file again when there was none. A machine is therefore left exactly as it
was found, and a config that cannot be copied aside is a refusal to activate
rather than something overwritten.

The agent settles what activation means: it writes the tool's configuration
itself and reads it back, rather than trusting cc-switch's exit code, so
what the page shows is what the tool would actually do.

Not pure: installs a binary and runs it.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import zipfile

from neutrino_agent.modules.downloader import download, resolve_github_asset
from neutrino_agent.modules.installers import InstallError


class NoTargetUserError(InstallError):
    """Raised when an account action names no reported human account."""

    code = "no_target_user"


# Where the agent puts the CLI, and where its own installer puts it.
SWITCHER_INSTALL_DIR = "/usr/local/bin"
SWITCHER_CLI_PATHS = (
    "/usr/local/bin/cc-switch",
    "/usr/local/bin/cc-switch.exe",
    os.path.expanduser("~/.local/bin/cc-switch"),
)

# What the desktop app leaves behind, per platform. Present means installed;
# none of these is executed.
SWITCHER_DESKTOP_MARKERS = (
    "/usr/lib/cc-switch",
    "/opt/cc-switch",
    "/Applications/CC Switch.app",
    "C:\\Program Files\\CC Switch",
)

# How each platform obtains the CLI. The typed ai entry carries endpoint and
# models only, so the tool that applies them is the agent's own business.
SWITCHER_RELEASES = {
    "linux-amd64": {
        "github_repo": "SaladDay/cc-switch-cli",
        "asset_pattern": "linux-x64.tar.gz",
        "package_kind": "tar_binary",
        "binary": "cc-switch",
    },
    "linux-arm64": {
        "github_repo": "SaladDay/cc-switch-cli",
        "asset_pattern": "linux-arm64.tar.gz",
        "package_kind": "tar_binary",
        "binary": "cc-switch",
    },
    "darwin": {
        "github_repo": "SaladDay/cc-switch-cli",
        "asset_pattern": "darwin-universal.tar.gz",
        "package_kind": "tar_binary",
        "binary": "cc-switch",
    },
    "windows-amd64": {
        "github_repo": "SaladDay/cc-switch-cli",
        "asset_pattern": "windows-x64.zip",
        "package_kind": "zip_binary",
        "binary": "cc-switch.exe",
    },
}

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

# Claude Code's four role slots, each an env key of its own. All are set,
# because a role left unset falls back to a Claude model the hub has never
# heard of.
CLAUDE_SLOT_KEYS = {
    "default": "ANTHROPIC_MODEL",
    "opus": "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "sonnet": "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "haiku": "ANTHROPIC_DEFAULT_HAIKU_MODEL",
}

# Codex's own knobs, written into config.toml as top-level keys.
CODEX_CONFIG_KEYS = ("model", "model_reasoning_effort")

GEMINI_MODEL_KEY = "GEMINI_MODEL"

# Where a tool's configuration is kept while the hub has replaced it, one
# file per tool below the account's own home, holding the file's text and
# mode as they stood before activation.
SWITCHER_ORIGINAL_DIR = ".neutrino_agent/original"

# What cc-switch draws its provider table with; its list has no
# machine-readable form, so the identifiers are read out of the columns.
TABLE_SEPARATOR = "\u2506"

COMMAND_TIMEOUT_S = 120

_PLATFORM = None


def _platform():
    """This machine's platform, created once on first use."""
    global _PLATFORM
    if _PLATFORM is None:
        from neutrino_agent.platforms.detect import detect_platform

        _PLATFORM = detect_platform()
    return _PLATFORM


def _require_target(run_as: str) -> None:
    """Refuse to act on an account that is empty or not a reported person.

    One symmetric guard: activation and deactivation check it alike, so a
    cleanup can never be skipped by the same gap that let the setup
    mis-target.

    Args:
        run_as: The account an action names.

    Raises:
        NoTargetUserError: When the account is empty or not among the
            platform's human accounts.
    """
    if not run_as or run_as not in _platform().human_accounts():
        raise NoTargetUserError(f"no target account {run_as!r} on this machine")


def release_entry(platform_keys: list) -> dict:
    """The CLI release this machine installs.

    Args:
        platform_keys: The machine's manifest keys, most specific first.

    Returns:
        The release block, empty when no build exists for this machine.
    """
    for key in platform_keys:
        if key in SWITCHER_RELEASES:
            return dict(SWITCHER_RELEASES[key])
    return {}


def find_cli() -> "str | None":
    """The cc-switch CLI, if this machine has one.

    Only the CLI can be driven; the desktop app has no command line. Looked
    for where the agent installs it and where the vendor's own installer does,
    then on the path — skipping anything a package manager says belongs to the
    desktop app, since that binary opens a window rather than parsing
    arguments.

    Returns:
        The path to a usable CLI, or None.
    """
    for candidate in SWITCHER_CLI_PATHS:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    found = shutil.which("cc-switch")
    if found and not _is_desktop_owned(found):
        return found
    return None


def find_desktop() -> bool:
    """Whether the cc-switch desktop app is installed.

    Returns:
        True when any of its install locations exists.
    """
    return any(os.path.exists(marker) for marker in SWITCHER_DESKTOP_MARKERS)


def is_installed() -> bool:
    """Whether this machine has cc-switch at all, in either form."""
    return find_cli() is not None or find_desktop()


def install_cli(entry: dict) -> str:
    """Download and install the cc-switch CLI for this platform.

    Args:
        entry: The release block — where to get it and what the binary
            inside is called.

    Returns:
        The path it was installed to.

    Raises:
        InstallError: If the archive cannot be fetched or unpacked, or no
            build exists for this machine.
        DownloadError: If the release asset cannot be resolved.
    """
    if not entry:
        raise InstallError("no cc-switch build for this machine")
    url = resolve_github_asset(entry["github_repo"], entry.get("asset_pattern", ""))
    binary_name = entry.get("binary", "cc-switch")
    kind = entry.get("package_kind", "tar_binary")
    destination = os.path.join(SWITCHER_INSTALL_DIR, binary_name)

    with tempfile.TemporaryDirectory() as workdir:
        archive = os.path.join(workdir, "switcher.archive")
        download(url, archive, is_impersonated=True)
        extracted = _extract_binary(archive, workdir, binary_name, kind)
        os.makedirs(SWITCHER_INSTALL_DIR, exist_ok=True)
        shutil.move(extracted, destination)
    os.chmod(destination, 0o755)
    return destination


def uninstall_cli() -> None:
    """Remove the CLI the agent installed, leaving the desktop app alone.

    Raises:
        InstallError: If the file is there and cannot be removed.
    """
    for candidate in SWITCHER_CLI_PATHS:
        if os.path.isfile(candidate):
            try:
                os.unlink(candidate)
            except OSError as error:
                raise InstallError(f"could not remove {candidate}: {error}")


def activate(
    *, base_url: str, api_key: str, run_as: str, tool_configs: "dict | None" = None
) -> str:
    """Register the hub in cc-switch and switch every tool to it.

    Each tool's configuration is copied aside first, as it stands, and a tool
    whose configuration cannot be copied is left untouched rather than
    replaced. Deactivating puts those copies back.

    Args:
        base_url: The hub's AI endpoint.
        api_key: This account's gateway key on this device.
        run_as: The account whose cc-switch store to write, since the agent
            runs as root and the store lives in a person's home.
        tool_configs: Each tool's staged choices — ``claude`` slot names,
            ``codex`` model and reasoning effort, ``gemini`` model. None or
            a missing key leaves that tool's model choices unwritten.

    Returns:
        A short message naming the tools that took it.

    Raises:
        NoTargetUserError: If ``run_as`` is empty or not a reported account.
        InstallError: If cc-switch refuses for every tool.
    """
    _require_target(run_as)
    configs = tool_configs or {}
    done = []
    problems = []
    for app in SWITCHER_APPS:
        try:
            # Making it current and settling the tool's configuration both
            # belong to the step below; switching again afterwards would hand
            # the file back to whatever cc-switch has stored.
            _add_provider(app, base_url, api_key, run_as, configs.get(app) or {})
            done.append(app)
        except InstallError as error:
            problems.append(f"{app}: {error}")
    if not done:
        raise InstallError("; ".join(problems)[:300])
    note = ", ".join(done)
    return f"{note}" if not problems else f"{note} ({len(problems)} not set up here)"


def deactivate(*, run_as: str, base_url: str = "") -> str:
    """Put every tool back the way activation found it.

    The hub's entry is taken out of cc-switch — which refuses to delete
    whichever provider is current, so this switches away first — and then each
    tool's configuration is restored from the copy activation kept: the whole
    file as it stood, or no file at all when there was none. That is what makes
    deactivating safe to press; a machine that had permission rules and a model
    of its own gets them back exactly.

    Without such a copy — activated by an older agent, or never activated here
    — only the hub's own keys are taken out and the rest of the file is left
    alone.

    cc-switch itself stays installed either way.

    Args:
        run_as: The account whose store and configuration to edit.
        base_url: The hub's endpoint, so the tools can be checked afterwards
            for still naming it.

    Returns:
        What happened, in the words the page shows.

    Raises:
        NoTargetUserError: If ``run_as`` is empty or not a reported account.
    """
    _require_target(run_as)
    notes = []
    for app in SWITCHER_APPS:
        fallback = _drop_provider(app, run_as)
        if _restore_original(app, run_as):
            notes.append(f"{app} → as it was")
        else:
            _strip_hub_keys(app, run_as)
            notes.append(f"{app} → {fallback or 'unset'}")
        # Whatever was switched to, deactivated has to mean not calling the
        # hub: a fallback provider carrying this endpoint would otherwise
        # leave the machine pointed here with the switch reported as done.
        if _points_at_hub(app, run_as, base_url):
            _strip_hub_keys(app, run_as)
    return ", ".join(notes)


def is_active(
    *, run_as: str, base_url: str, api_key: str = "", model: str = ""
) -> bool:
    """Whether this machine's Claude Code actually calls the hub.

    Read from the tool's own configuration rather than from cc-switch's idea
    of which provider is selected. The two can disagree — a settings file
    restored from a backup, an edit made by hand — and what matters is where
    the requests go, so that is what is checked. A disagreement then heals
    itself: the reconcile sees it is not pointed here and points it again.

    Args:
        run_as: The account whose configuration to read.
        base_url: The hub's AI endpoint.
        api_key: This device's current key. Checked as well when given, so a
            key that has since been rotated counts as not pointed here and
            gets written again.
        model: The default-slot model to expect. Checked too, so a changed
            choice is applied rather than left behind.

    Returns:
        True when Claude Code's settings name that endpoint, key and model.
    """
    if not base_url:
        return False
    env = _read_json(run_as, SWITCHER_APP_FILES["claude"]).get("env", {})
    if env.get("ANTHROPIC_BASE_URL") != base_url:
        return False
    if api_key and env.get("ANTHROPIC_AUTH_TOKEN") != api_key:
        return False
    return not model or env.get("ANTHROPIC_MODEL") == model


def is_active_for(app: str, *, run_as: str) -> bool:
    """Whether cc-switch points one tool at the hub.

    Args:
        app: The tool, in cc-switch's vocabulary.
        run_as: The account whose store to read.

    Returns:
        True when the hub is that tool's current provider.
    """
    try:
        output = _run(["provider", "current"], app, run_as)
    except InstallError:
        return False
    return SWITCHER_PROVIDER_ID in output or SWITCHER_PROVIDER_NAME in output


def _drop_provider(app: str, run_as: str) -> str:
    """Remove the hub's provider, switching away from it first if need be.

    cc-switch refuses to delete whichever provider is current, so a hub entry
    that is in use has to be stood down before it can go — to another provider
    when the machine has one, which is what the person would have picked.

    Args:
        app: Which tool's providers to act on.
        run_as: The account whose store to edit.

    Returns:
        The provider switched to, or empty when there was none to switch to.
    """
    fallback = ""
    if is_active_for(app, run_as=run_as):
        fallback = _other_provider(app, run_as)
        if fallback:
            _run(["use", fallback], app, run_as, is_checked=False)
    _run(["provider", "delete", SWITCHER_PROVIDER_ID], app, run_as, is_checked=False)
    return fallback


def _other_provider(app: str, run_as: str) -> str:
    """Another provider in the store to fall back to, if there is one.

    ``provider list`` prints a table and has no machine-readable form, so the
    identifiers are read out of its second column.

    Args:
        app: Which tool's providers to look at.
        run_as: The account whose store to read.

    Returns:
        A provider id that is not the hub's, or empty when there is none.
    """
    try:
        output = _run(["provider", "list"], app, run_as)
    except InstallError:
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


def _points_at_hub(app: str, run_as: str, base_url: str) -> bool:
    """Whether a tool's configuration still names this hub.

    Compared against the hub's own address rather than merely having one: a
    fallback provider pointing at somebody else's relay is the person's
    business and is left exactly as it is.

    Args:
        app: Which tool, in cc-switch's vocabulary.
        run_as: The account whose configuration to read.
        base_url: This hub's AI endpoint.

    Returns:
        True when that tool would still call this hub.
    """
    if app != "claude" or not base_url:
        return False
    env = _read_json(run_as, SWITCHER_APP_FILES["claude"]).get("env", {})
    return env.get("ANTHROPIC_BASE_URL") == base_url


def _capture_original(app: str, run_as: str) -> None:
    """Keep a copy of a tool's configuration as it stands before the hub.

    Taken once and kept until deactivate puts it back, so re-applying a
    changed model or a rotated key does not overwrite the copy with the hub's
    own settings. A tool with no configuration yet is recorded as having none,
    which is what restoring it means later.

    Args:
        app: Which tool, in cc-switch's vocabulary.
        run_as: The account whose configuration to copy.

    Raises:
        InstallError: If the copy cannot be stored. Activation replaces that
            file, so refusing is the only way not to lose what is in it.
    """
    relative = SWITCHER_APP_FILES.get(app, "")
    if not relative or _original(app, run_as) is not None:
        return
    mode = _file_mode(run_as, relative)
    envelope = {
        "is_present": mode != "",
        "mode": mode,
        "text": _read_text(run_as, relative),
    }
    _write_json(run_as, _original_path(app), envelope)
    if _original(app, run_as) is None:
        raise InstallError(
            "could not keep a copy of this machine's own configuration, "
            "so it was left untouched"
        )


def _restore_original(app: str, run_as: str) -> bool:
    """Put a tool's configuration back to the copy activation kept.

    Args:
        app: Which tool, in cc-switch's vocabulary.
        run_as: The account whose configuration to write.

    Returns:
        True when there was a copy to put back.
    """
    snapshot = _original(app, run_as)
    if snapshot is None:
        return False
    relative = SWITCHER_APP_FILES.get(app, "")
    if snapshot.get("is_present"):
        _write_text(
            run_as, relative, snapshot.get("text", ""), snapshot.get("mode", "")
        )
    else:
        _remove_file(run_as, relative)
    _remove_file(run_as, _original_path(app))
    return True


def _original(app: str, run_as: str) -> "dict | None":
    """The copy kept for one tool, or None when there is none."""
    snapshot = _read_json(run_as, _original_path(app))
    return snapshot or None


def _original_path(app: str) -> str:
    """Where one tool's copy lives, below the account's home."""
    return f"{SWITCHER_ORIGINAL_DIR}/{app}.json"


def _strip_hub_keys(app: str, run_as: str) -> None:
    """Remove only the hub's own entries from a tool's configuration."""
    if app != "claude":
        return
    data = _read_json(run_as, SWITCHER_APP_FILES["claude"])
    env = dict(data.get("env", {}))
    for key in CLAUDE_ENV_KEYS:
        env.pop(key, None)
    if env:
        data["env"] = env
    else:
        data.pop("env", None)
    _write_json(run_as, SWITCHER_APP_FILES["claude"], data)


def _is_desktop_owned(path: str) -> bool:
    """Whether a package manager says this binary belongs to the desktop app."""
    if not shutil.which("dpkg"):
        return False
    try:
        result = subprocess.run(
            ["dpkg", "-S", os.path.realpath(path)],
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and "cc-switch-cli" not in result.stdout


def _add_provider(
    app: str, base_url: str, api_key: str, run_as: str, config: dict
) -> None:
    """Make the hub this tool's provider, applying the staged choices.

    A provider in cc-switch is the whole of a tool's configuration, so
    Claude's is built from what is already there. The file is copied aside
    and read first, before anything is switched or deleted, because
    switching to any other provider replaces it — reading it afterwards
    would read the replacement. Codex and Gemini let cc-switch write the
    endpoint, then get the chosen model settled into their own file.

    Args:
        app: Which tool, in cc-switch's vocabulary.
        base_url: The hub's AI endpoint.
        api_key: This account's gateway key.
        run_as: The account whose store and configuration to write.
        config: The tool's staged choices.

    Raises:
        InstallError: If the existing configuration cannot be copied aside,
            if cc-switch refuses, or if the settings file did not end up
            naming the hub.
    """
    _capture_original(app, run_as)
    if app == "claude":
        existing = _read_json(run_as, SWITCHER_APP_FILES["claude"])
        settings = json.dumps(
            {**existing, "env": _hub_env(existing, base_url, api_key, config)}
        )
    else:
        settings = ""

    _drop_provider(app, run_as)

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
        _run(arguments, app, run_as)
    except InstallError:
        # The entry survived a replacement — it was current with nothing to
        # fall back to. cc-switch keeps its own, now stale, copy; what the
        # tool reads is settled below either way.
        if not settings:
            raise
    _use_provider(app, run_as)

    if app == "claude":
        _write_json(run_as, SWITCHER_APP_FILES["claude"], json.loads(settings))
        if not is_active(
            run_as=run_as,
            base_url=base_url,
            api_key=api_key,
            model=str(config.get("default", "")),
        ):
            raise InstallError("the settings file did not take the hub's endpoint")
    elif app == "codex":
        _settle_codex_config(run_as, config)
    elif app == "gemini":
        _settle_gemini_config(run_as, config)


def _hub_env(existing: dict, base_url: str, api_key: str, config: dict) -> dict:
    """The tool's environment with the hub's endpoint in place of any other.

    Every role slot with a chosen model is named: Claude Code asks for a
    model by name, and a hub fronting anything but Anthropic serves names of
    its own, so a slot left unset means requests asking for a model that is
    not there.

    Args:
        existing: The tool's current environment.
        base_url: The hub's AI endpoint.
        api_key: This account's gateway key.
        config: The staged slot choices — ``default``, ``opus``, ``sonnet``,
            ``haiku``.

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


def _settle_codex_config(run_as: str, config: dict) -> None:
    """Write the chosen model and reasoning effort into Codex's config.toml.

    Args:
        run_as: The account whose configuration to edit.
        config: The staged choices — ``model``, ``model_reasoning_effort``.
    """
    values = {}
    for key in CODEX_CONFIG_KEYS:
        value = str(config.get(key, "") or "")
        if value:
            values[key] = value
    if not values:
        return
    relative = SWITCHER_APP_FILES["codex"]
    text = _read_text(run_as, relative)
    _write_text(run_as, relative, _merge_toml_top_level(text, values))


def _settle_gemini_config(run_as: str, config: dict) -> None:
    """Write the chosen model into Gemini's env file.

    Args:
        run_as: The account whose configuration to edit.
        config: The staged choices — ``model``.
    """
    model = str(config.get("model", "") or "")
    if not model:
        return
    relative = SWITCHER_APP_FILES["gemini"]
    text = _read_text(run_as, relative)
    _write_text(run_as, relative, _merge_env_line(text, GEMINI_MODEL_KEY, model))


def _merge_toml_top_level(text: str, values: dict) -> str:
    """A TOML text with the given top-level keys set, the rest untouched.

    Existing assignments of those keys above the first section header are
    dropped; the new ones go at the top, so they stay top-level whatever
    sections follow.

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


def _use_provider(app: str, run_as: str) -> None:
    _run(["use", SWITCHER_PROVIDER_ID], app, run_as)


def _run(arguments: list, app: str, run_as: str, *, is_checked: bool = True) -> str:
    """Run the cc-switch CLI as the target account.

    The store lives in the person's home, not root's, so the platform steps
    the command down to them.

    Args:
        arguments: Arguments after the app selector.
        app: Which tool's configuration to act on.
        run_as: The account to run as; empty runs as the agent itself.
        is_checked: Whether a non-zero exit is an error.

    Returns:
        Standard output.

    Raises:
        InstallError: If the command fails while checked.
    """
    binary = find_cli()
    if binary is None:
        raise InstallError("the cc-switch command line is not installed")
    command = [binary, "--app", app] + arguments
    try:
        result = _platform().run_as_account(
            run_as, command, timeout_s=COMMAND_TIMEOUT_S
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise InstallError(f"cc-switch could not run: {error}")
    if is_checked and result.returncode != 0:
        output = (result.stderr or result.stdout or "").strip()
        raise InstallError(output[-200:] or "cc-switch refused")
    return result.stdout or ""


def _extract_binary(archive: str, workdir: str, binary_name: str, kind: str) -> str:
    """Pull the one binary out of a release archive.

    Args:
        archive: The downloaded file.
        workdir: Where to unpack.
        binary_name: What the binary is called inside.
        kind: ``tar_binary`` or ``zip_binary``.

    Returns:
        Path to the extracted binary.

    Raises:
        InstallError: If the archive has no such binary.
    """
    target = os.path.join(workdir, "unpacked")
    os.makedirs(target, exist_ok=True)
    try:
        if kind == "zip_binary":
            with zipfile.ZipFile(archive) as bundle:
                bundle.extractall(target)
        else:
            with tarfile.open(archive) as bundle:
                bundle.extractall(target)
    except (OSError, tarfile.TarError, zipfile.BadZipFile) as error:
        raise InstallError(f"could not unpack cc-switch: {error}")

    for root, _, names in os.walk(target):
        if binary_name in names:
            return os.path.join(root, binary_name)
    raise InstallError(f"no {binary_name} inside the archive")


def _file_mode(run_as: str, relative: str) -> str:
    """A file's permission bits as an octal string, empty when it is not there.

    Args:
        run_as: The account whose home to look in.
        relative: Path below that account's home.

    Returns:
        Something like ``600``, or empty.
    """
    return _platform().read_account_file_mode(account=run_as, relative=relative)


def _read_text(run_as: str, relative: str) -> str:
    """Read a file from the target account's home, empty when absent."""
    return _platform().read_account_file(account=run_as, relative=relative)


def _read_json(run_as: str, relative: str) -> dict:
    """Read a JSON file from the target account's home, empty when unusable."""
    try:
        data = json.loads(_read_text(run_as, relative) or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _write_text(run_as: str, relative: str, text: str, mode: str = "") -> None:
    """Write a file into the target account's home, as that account.

    The agent runs as root and these files live in a person's home, so the
    platform writes them as the account — otherwise a file it creates is
    owned by root and the tool that reads it next cannot write.

    Args:
        run_as: The account to write as.
        relative: Path below that account's home.
        text: What to write.
        mode: Permission bits to set, as an octal string; empty leaves them.
    """
    _platform().write_account_file(
        account=run_as, relative=relative, text=text, mode=mode
    )


def _write_json(run_as: str, relative: str, data: dict) -> None:
    """Write a JSON file into the target account's home, as that account."""
    _write_text(run_as, relative, json.dumps(data, indent=2))


def _remove_file(run_as: str, relative: str) -> None:
    """Delete a file from the target account's home, absent being fine."""
    _platform().remove_account_file(account=run_as, relative=relative)
