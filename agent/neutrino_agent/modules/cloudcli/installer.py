"""Putting Node.js on the machine and CloudCLI in an account, the same on every system.

Node.js comes from the hub's package stream as the archive nodejs.org
publishes, a tarball on Linux and macOS and a zip on Windows, with one
``node-v<version>-<system>-<arch>`` directory inside. It is unpacked whole
under the module's own directory, owned by root and read-only, one copy per
machine, and never put on a ``PATH``. CloudCLI itself is installed by npm
into each account's own app directory, as that account; the commands for
that are built here, and the appliers run them.

Not pure: writes files.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import json
import os
import shutil
import tarfile
import tempfile
import urllib.parse
import zipfile

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.cloudcli.config import jwt_secret
from neutrino_agent.modules.cloudcli.constants import (
    CLOUDCLI_ACCOUNT_PARTS,
    CLOUDCLI_FAILURE_DETAIL_CHARS,
    CLOUDCLI_FAILURE_LINES,
    CLOUDCLI_APP_DIR_NAME,
    CLOUDCLI_DATABASE_NAME,
    CLOUDCLI_NATIVE_MODULES,
    CLOUDCLI_NODE_PARTS,
    CLOUDCLI_NODE_PREFIX,
    CLOUDCLI_NPM_CACHE_NAME,
    CLOUDCLI_NPM_PARTS,
    CLOUDCLI_NPM_USERCONFIG_NAME,
    CLOUDCLI_PACKAGE,
    CLOUDCLI_PACKAGE_PARTS,
    CLOUDCLI_SERVER_PARTS,
    CLOUDCLI_SYSTEM_PATH,
    CLOUDCLI_UPSTREAM_HOST,
    CLOUDCLI_VERSION,
    CLOUDCLI_WINDOWS_SERVICE_PATH,
)
from neutrino_agent.modules.unpacked_tree import (
    extract_archive,
    remove_tree,
    seal_tree,
)

# The words in npm's output that say a native module could not get its
# binary: prebuild-install gave up, and node-gyp could not build it either.
NATIVE_FAILURE_WORDS = ("gyp", "prebuild")
# The lines of npm's output that are its tools' own account of a failure.
FAILURE_LINE_WORDS = ("prebuild-install", "gyp err", "npm error", "npm err!")
# The registry npm uses when the state names none.
NPM_DEFAULT_REGISTRY_HOST = "registry.npmjs.org"
# The exit status the native check ends with, the module's name printed.
NATIVE_CHECK_EXIT = 3
NATIVE_CHECK_SCRIPT = (
    "const load = require('module').createRequire(process.cwd() + '/'); "
    "for (const name of [%s]) { try { load(name) } catch (error) "
    "{ console.log(name); process.exit(%d) } }"
    % (",".join("'%s'" % name for name in CLOUDCLI_NATIVE_MODULES), NATIVE_CHECK_EXIT)
)


def unpack_node(path: str, *, package_kind: str, root: str) -> str:
    """Put the Node.js archive's one directory under the module's root.

    Any other Node.js the root holds is removed, and what lands is owned by
    the agent's own account and read-only.

    Args:
        path: The archive on disk.
        package_kind: ``tar`` or ``zip``.
        root: The module's directory.

    Returns:
        The Node.js directory.

    Raises:
        ModuleApplyError: ``cloudcli_node_download_failed`` when the kind is
            unknown, the archive cannot be read, or it holds no Node.js.
        OSError: When the root cannot be written.
    """
    os.makedirs(root, mode=0o755, exist_ok=True)
    os.chmod(root, 0o755)
    staging = tempfile.mkdtemp(prefix=".unpack_", dir=root)
    try:
        try:
            extract_archive(path, package_kind, staging)
        except (OSError, tarfile.TarError, zipfile.BadZipFile, ValueError) as error:
            raise ModuleApplyError(
                "cloudcli_node_download_failed", {"detail": str(error)[:200]}
            ) from error
        names = [
            name
            for name in os.listdir(staging)
            if name.startswith(CLOUDCLI_NODE_PREFIX)
            and os.path.isdir(os.path.join(staging, name))
        ]
        if len(names) != 1:
            raise ModuleApplyError(
                "cloudcli_node_download_failed",
                {"detail": "the archive holds no single Node.js directory"},
            )
        for held in os.listdir(root):
            if held.startswith(CLOUDCLI_NODE_PREFIX):
                remove_tree(os.path.join(root, held))
        target = os.path.join(root, names[0])
        os.replace(os.path.join(staging, names[0]), target)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    seal_tree(target)
    return target


def node_dir(root: str) -> str:
    """The Node.js directory under the module's root.

    Args:
        root: The module's directory.

    Returns:
        Its path, empty when none is there.
    """
    try:
        names = sorted(
            name for name in os.listdir(root) if name.startswith(CLOUDCLI_NODE_PREFIX)
        )
    except OSError:
        return ""
    return os.path.join(root, names[-1]) if names else ""


def node_path(directory: str, os_name: str) -> str:
    """The interpreter inside one Node.js directory."""
    return os.path.join(directory, *CLOUDCLI_NODE_PARTS[os_name])


def npm_path(directory: str, os_name: str) -> str:
    """npm's script inside one Node.js directory."""
    return os.path.join(directory, *CLOUDCLI_NPM_PARTS[os_name])


def remove_node(root: str) -> None:
    """Delete the module's directory and the Node.js in it.

    Args:
        root: The module's directory.
    """
    remove_tree(root)


def account_dir(home: str, os_name: str, join=os.path.join) -> str:
    """One account's CloudCLI directory, under its home.

    Args:
        home: The account's home.
        os_name: The system.
        join: How the system joins a path.

    Returns:
        The directory the app directory and the database live in.
    """
    return join(home, *CLOUDCLI_ACCOUNT_PARTS[os_name])


def app_dir(home: str, os_name: str, join=os.path.join) -> str:
    """One account's app directory, which npm installs CloudCLI into."""
    return join(account_dir(home, os_name, join), CLOUDCLI_APP_DIR_NAME)


def database_path(home: str, os_name: str, join=os.path.join) -> str:
    """Where one account's CloudCLI keeps its database."""
    return join(account_dir(home, os_name, join), CLOUDCLI_DATABASE_NAME)


def server_path(app: str, join=os.path.join) -> str:
    """The server script an app directory runs."""
    return join(app, *CLOUDCLI_PACKAGE_PARTS, *CLOUDCLI_SERVER_PARTS)


def installed_version(app: str) -> str:
    """The CloudCLI version an app directory holds.

    Args:
        app: The app directory.

    Returns:
        The version its ``package.json`` names, empty when there is none.
    """
    path = os.path.join(app, *CLOUDCLI_PACKAGE_PARTS, "package.json")
    try:
        with open(path, "r", encoding="utf-8") as stream:
            return str(json.load(stream).get("version", "") or "")
    except (OSError, ValueError, AttributeError):
        return ""


def is_app_ready(app: str) -> bool:
    """Whether an app directory holds CloudCLI at its pinned version and its native modules.

    Args:
        app: The app directory.

    Returns:
        True when the package names the pinned version and every native
        module has its ``package.json`` beside it or inside it.
    """
    if installed_version(app) != CLOUDCLI_VERSION:
        return False
    package = os.path.join(app, *CLOUDCLI_PACKAGE_PARTS)
    places = (os.path.join(app, "node_modules"), os.path.join(package, "node_modules"))
    return all(
        any(
            os.path.isfile(os.path.join(place, name, "package.json"))
            for place in places
        )
        for name in CLOUDCLI_NATIVE_MODULES
    )


def npm_environment(
    app: str, join=os.path.join, *, registry: str = "", extra: "dict | None" = None
) -> dict:
    """What npm runs with besides ``PATH`` and the account's own names.

    Args:
        app: The app directory.
        join: How the system joins a path.
        registry: The registry the hub's state names; empty for npm's own.
        extra: More ``npm_config_*`` settings the hub's state names.

    Returns:
        npm's cache inside the app directory, an empty file as the
        account's configuration, no audit, funding or update notes, the
        registry when one is named, and the state's other settings.
    """
    environment = {
        "npm_config_cache": join(app, CLOUDCLI_NPM_CACHE_NAME),
        "npm_config_userconfig": join(app, CLOUDCLI_NPM_USERCONFIG_NAME),
        "npm_config_audit": "false",
        "npm_config_fund": "false",
        "npm_config_update_notifier": "false",
    }
    if registry:
        environment["npm_config_registry"] = registry
    for name, value in (extra or {}).items():
        environment.setdefault(name, value)
    return environment


def npm_arguments(app: str) -> list:
    """npm's own arguments for one app directory."""
    return ["install", f"{CLOUDCLI_PACKAGE}@{CLOUDCLI_VERSION}", "--prefix", app]


def npm_failure(output: str, account: str) -> ModuleApplyError:
    """Which step an install that failed failed at, in the tools' own words.

    Args:
        output: What npm printed.
        account: The account it ran as.

    Returns:
        ``cloudcli_native_module_failed {account, module, detail}`` when a
        native module could not get its binary, else
        ``cloudcli_npm_install_failed {account, detail}``; ``detail`` is the
        last lines prebuild-install, node-gyp and npm wrote about it.
    """
    detail = failure_detail(output)
    lowered = output.lower()
    if any(word in lowered for word in NATIVE_FAILURE_WORDS):
        for name in CLOUDCLI_NATIVE_MODULES:
            if name in lowered:
                return ModuleApplyError(
                    "cloudcli_native_module_failed",
                    {"account": account, "module": name, "detail": detail},
                )
    return ModuleApplyError(
        "cloudcli_npm_install_failed", {"account": account, "detail": detail}
    )


def failure_detail(output: str) -> str:
    """The last lines an installer's tools wrote about a failure.

    Args:
        output: What npm printed.

    Returns:
        Up to four lines naming prebuild-install, node-gyp or npm's own
        errors, joined by `` | ``; the output's last line when none does.
    """
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    named = [
        line
        for line in lines
        if any(word in line.lower() for word in FAILURE_LINE_WORDS)
    ]
    kept = named[-CLOUDCLI_FAILURE_LINES:] or lines[-1:]
    return " | ".join(kept)[-CLOUDCLI_FAILURE_DETAIL_CHARS:]


def registry_host(registry: str) -> str:
    """The host npm fetches from, for the install's log line.

    Args:
        registry: The registry the state names; empty for npm's own.

    Returns:
        The registry's host name.
    """
    return urllib.parse.urlsplit(registry).hostname or NPM_DEFAULT_REGISTRY_HOST


def service_environment(
    config,
    instance,
    *,
    upstream_port: int,
    home: str,
    os_name: str,
    node_dir: str = "",
    claude_path: str = "",
    join=os.path.join,
) -> dict:
    """The environment one instance's CloudCLI runs with, written from scratch.

    Args:
        config: The :class:`CloudcliConfig`, for the gateway.
        instance: The :class:`CloudcliInstance`.
        upstream_port: The loopback port CloudCLI listens on.
        home: The account's home.
        os_name: The system.
        node_dir: The directory Node.js is in; it leads ``PATH``.
        claude_path: The account's own ``claude``; its directory follows
            Node's on ``PATH``. Empty on Windows, where the task keeps the
            account's own ``PATH`` after Node's directory.
        join: How the system joins a path.

    Returns:
        ``HOST``, ``SERVER_PORT``, ``JWT_SECRET``, ``DATABASE_PATH``, the
        gateway's three, ``PATH`` with a Node directory or a ``claude``,
        and with a ``claude`` also ``HOME`` and ``CLAUDE_CLI_PATH``.
    """
    environment = {
        "HOST": CLOUDCLI_UPSTREAM_HOST,
        "SERVER_PORT": str(int(upstream_port)),
        "JWT_SECRET": jwt_secret(instance.token_secret),
        "DATABASE_PATH": database_path(home, os_name, join),
        **config.environment(),
    }
    if os_name == "windows":
        if node_dir:
            environment["PATH"] = ";".join([node_dir, *CLOUDCLI_WINDOWS_SERVICE_PATH])
        return environment
    leading = [node_dir] if node_dir else []
    if claude_path:
        environment["HOME"] = home
        leading.append(os.path.dirname(claude_path))
        environment["CLAUDE_CLI_PATH"] = claude_path
    if leading:
        environment["PATH"] = ":".join([*leading, *CLOUDCLI_SYSTEM_PATH])
    return environment


def claude_of(output: str) -> str:
    """The ``claude`` a login shell's ``command -v`` printed.

    Args:
        output: What the shell printed, a profile's own lines included.

    Returns:
        The last line that is an absolute path, empty when there is none.
    """
    for line in reversed(output.splitlines()):
        line = line.strip()
        if line.startswith("/"):
            return line
    return ""
