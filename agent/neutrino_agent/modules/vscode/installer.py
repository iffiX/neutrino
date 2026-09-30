"""Putting VS Code's CLI and its files on disk, the same on every system.

The CLI comes from the hub's package stream as the archive Microsoft
publishes, a tarball on Linux and a zip on Windows and macOS, with the one
executable inside. It is unpacked into the module's own directory, readable
and runnable by every account.

Not pure: writes files.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import os
import shutil
import tarfile
import zipfile

from neutrino_agent.exceptions import InstallError
from neutrino_agent.modules.vscode.constants import (
    VSCODE_PACKAGE_TAR,
    VSCODE_PACKAGE_ZIP,
)


def unpack_cli(path: str, *, package_kind: str, directory: str, name: str) -> str:
    """Take the CLI out of its archive into its directory.

    Args:
        path: The archive on disk.
        package_kind: ``tar`` or ``zip``.
        directory: Where the CLI goes; made readable by every account.
        name: The CLI's file name inside the archive.

    Returns:
        The CLI's path.

    Raises:
        InstallError: When the kind is unknown, the archive cannot be read,
            or it holds no file of that name.
    """
    try:
        payload = _read_member(path, package_kind, name)
    except (OSError, tarfile.TarError, zipfile.BadZipFile) as error:
        raise InstallError(f"cannot read the VS Code archive: {error}") from error
    os.makedirs(directory, mode=0o755, exist_ok=True)
    target = os.path.join(directory, name)
    temporary = target + ".new"
    with open(temporary, "wb") as stream:
        stream.write(payload)
    os.chmod(temporary, 0o755)
    os.replace(temporary, target)
    return target


def remove_cli(directory: str) -> None:
    """Delete the CLI's directory and everything in it.

    Args:
        directory: The module's own directory.
    """
    shutil.rmtree(directory, ignore_errors=True)


def write_if_changed(path: str, text: str, mode: int) -> bool:
    """Write a file whole unless it already holds this text.

    Args:
        path: The file.
        text: What it holds afterwards.
        mode: Its permission bits.

    Returns:
        Whether it changed.

    Raises:
        OSError: When the file cannot be written.
    """
    try:
        with open(path, "r", encoding="utf-8") as stream:
            if stream.read() == text:
                return False
    except OSError:
        pass
    temporary = path + ".new"
    with open(temporary, "w", encoding="utf-8") as stream:
        stream.write(text)
    os.chmod(temporary, mode)
    os.replace(temporary, path)
    return True


def _read_member(path: str, package_kind: str, name: str) -> bytes:
    """The bytes of the one file of that name, wherever it sits in the archive."""
    if package_kind == VSCODE_PACKAGE_TAR:
        with tarfile.open(path, "r:*") as archive:
            for member in archive.getmembers():
                if member.isfile() and os.path.basename(member.name) == name:
                    return archive.extractfile(member).read()
    elif package_kind == VSCODE_PACKAGE_ZIP:
        with zipfile.ZipFile(path) as archive:
            for member in archive.namelist():
                if member.rsplit("/", 1)[-1] == name:
                    return archive.read(member)
    else:
        raise InstallError(f"unknown package kind {package_kind!r}")
    raise InstallError(f"the VS Code archive holds no {name}")
