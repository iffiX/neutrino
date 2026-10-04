"""Putting code-server's release on the machine, the same on Linux and macOS.

The release comes from the hub's package stream as the tarball coder
publishes, with one ``code-server-<version>-<system>-<arch>`` directory
inside that carries its own Node.js. It is unpacked whole as ``release``
under the module's own directory, owned by root and read-only, one copy per
machine, and never put on a ``PATH``. Each account's run directory, which
holds the socket its code-server listens on, sits beside it.

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
import zipfile

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.code_server.constants import (
    CODE_SERVER_FLAGS,
    CODE_SERVER_LAUNCHER_PARTS,
    CODE_SERVER_NODE_PARTS,
    CODE_SERVER_PACKAGE_JSON,
    CODE_SERVER_RELEASE_DIR_NAME,
    CODE_SERVER_RELEASE_PREFIX,
    CODE_SERVER_RUN_DIR_NAME,
    CODE_SERVER_SOCKET_NAME,
    CODE_SERVER_SOCKET_PATH_MAX,
)
from neutrino_agent.modules.unpacked_tree import (
    extract_archive,
    remove_tree,
    seal_tree,
)

# What a failed install of the release reports.
CODE_DOWNLOAD_FAILED = "code_server_download_failed"


def unpack_release(path: str, *, package_kind: str, root: str) -> str:
    """Put the release's one directory under the module's root as ``release``.

    A release the root already holds is replaced, and what lands is owned by
    the agent's own account and read-only.

    Args:
        path: The archive on disk.
        package_kind: ``tar``.
        root: The module's directory.

    Returns:
        The release directory.

    Raises:
        ModuleApplyError: ``code_server_download_failed`` when the kind is
            unknown, the archive cannot be read, or it holds no release.
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
                CODE_DOWNLOAD_FAILED, {"detail": str(error)[:200]}
            ) from error
        names = [
            name
            for name in os.listdir(staging)
            if name.startswith(CODE_SERVER_RELEASE_PREFIX)
            and os.path.isdir(os.path.join(staging, name))
        ]
        unpacked = os.path.join(staging, names[0]) if len(names) == 1 else ""
        if not unpacked or not os.path.isfile(
            os.path.join(unpacked, *CODE_SERVER_LAUNCHER_PARTS)
        ):
            raise ModuleApplyError(
                CODE_DOWNLOAD_FAILED,
                {"detail": "the archive holds no single code-server release"},
            )
        target = release_dir(root)
        remove_tree(target)
        os.replace(unpacked, target)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    seal_tree(target)
    return target


def remove_release(root: str) -> None:
    """Delete the module's directory: the release and every run directory.

    Args:
        root: The module's directory.
    """
    remove_tree(root)


def release_dir(root: str) -> str:
    """The release directory under the module's root."""
    return os.path.join(root, CODE_SERVER_RELEASE_DIR_NAME)


def launcher_path(root: str) -> str:
    """The ``code-server`` launcher of the release under the module's root."""
    return os.path.join(release_dir(root), *CODE_SERVER_LAUNCHER_PARTS)


def node_path(root: str) -> str:
    """The Node.js the release carries."""
    return os.path.join(release_dir(root), *CODE_SERVER_NODE_PARTS)


def installed_version(root: str) -> str:
    """The code-server version the release under the module's root is.

    Args:
        root: The module's directory.

    Returns:
        The version its ``package.json`` names, empty when there is none.
    """
    path = os.path.join(release_dir(root), CODE_SERVER_PACKAGE_JSON)
    try:
        with open(path, "r", encoding="utf-8") as stream:
            return str(json.load(stream).get("version", "") or "")
    except (OSError, ValueError, AttributeError):
        return ""


def run_dir(root: str, account: str) -> str:
    """One account's run directory, which holds its socket."""
    return os.path.join(root, CODE_SERVER_RUN_DIR_NAME, account)


def socket_path(root: str, account: str) -> str:
    """The socket one account's code-server listens on."""
    return os.path.join(run_dir(root, account), CODE_SERVER_SOCKET_NAME)


def check_socket_path(root: str, account: str, os_name: str) -> None:
    """Refuse an account whose socket path the system cannot bind.

    Args:
        root: The module's directory.
        account: The account.
        os_name: ``linux`` or ``darwin``.

    Raises:
        ModuleApplyError: ``account_invalid {account}`` when the path is
            longer than the system's socket address holds.
    """
    limit = CODE_SERVER_SOCKET_PATH_MAX.get(os_name, 0)
    if limit and len(os.fsencode(socket_path(root, account))) > limit:
        raise ModuleApplyError("account_invalid", {"account": account})


def prepare_run_dir(root: str, account: str, uid: int, gid: int, chown=None) -> str:
    """Make one account's run directory, the account's own and mode 0700.

    Args:
        root: The module's directory.
        account: The account.
        uid: The account's user id.
        gid: The account's group id.
        chown: Changes a file's owner as :func:`os.chown` does, which it
            is when none is given.

    Returns:
        The directory.

    Raises:
        OSError: When it cannot be made or handed over.
    """
    parent = os.path.join(root, CODE_SERVER_RUN_DIR_NAME)
    os.makedirs(parent, mode=0o755, exist_ok=True)
    os.chmod(parent, 0o755)
    directory = run_dir(root, account)
    os.makedirs(directory, mode=0o700, exist_ok=True)
    os.chmod(directory, 0o700)
    (chown or os.chown)(directory, uid, gid)
    return directory


def remove_run_dir(root: str, account: str) -> None:
    """Delete one account's run directory and its socket.

    Args:
        root: The module's directory.
        account: The account.
    """
    shutil.rmtree(run_dir(root, account), ignore_errors=True)


def server_arguments(root: str, account: str) -> list:
    """What one account's code-server is started with.

    Args:
        root: The module's directory.
        account: The account.

    Returns:
        The launcher, ``--socket`` with the account's socket, and the flags
        every instance runs with.
    """
    return [
        launcher_path(root),
        "--socket",
        socket_path(root, account),
        *CODE_SERVER_FLAGS,
    ]
