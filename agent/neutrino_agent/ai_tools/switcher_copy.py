"""The copy of cc-switch the agent fetches from the hub and runs as each account.

The hub serves cc-switch's release archive on the ``package`` stream. The
agent unpacks it whole into ``bin`` under the records' directory, writes
the version it was fetched for beside it, seals the tree as root's own with
no write bit, and opens it to every account to read and run. A copy is
replaced whole, through a staging directory beside it.

Not pure: writes files.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import os
import shutil
import tempfile

from neutrino_agent.ai_tools.constants import (
    AI_TOOLS_BIN_DIR_NAME,
    AI_TOOLS_CC_SWITCH_KIND,
    AI_TOOLS_CC_SWITCH_KINDS,
    AI_TOOLS_CC_SWITCH_NAME,
    AI_TOOLS_CC_SWITCH_NAMES,
    AI_TOOLS_VERSION_NAME,
)
from neutrino_agent.modules.unpacked_tree import (
    extract_archive,
    remove_tree,
    seal_tree,
)


def binary_path(root: str, os_name: str) -> str:
    """Where the copy's program is.

    Args:
        root: The records' directory, ``ai_tools`` under the state root.
        os_name: ``linux``, ``darwin`` or ``windows``.

    Returns:
        ``bin/cc-switch``, ``bin\\cc-switch.exe`` on Windows, under the root.
    """
    name = AI_TOOLS_CC_SWITCH_NAMES.get(os_name, AI_TOOLS_CC_SWITCH_NAME)
    return os.path.join(root, AI_TOOLS_BIN_DIR_NAME, name)


def installed_version(root: str) -> str:
    """The version the copy was fetched for; empty when none is written."""
    try:
        with open(
            os.path.join(root, AI_TOOLS_BIN_DIR_NAME, AI_TOOLS_VERSION_NAME),
            "r",
            encoding="utf-8",
        ) as stream:
            return stream.read().strip()
    except OSError:
        return ""


def install_copy(
    archive: str, *, root: str, os_name: str, version: str, open_to_accounts
) -> str:
    """Unpack the archive the hub sent as the copy, replacing any copy there.

    Args:
        archive: The release archive on disk.
        root: The records' directory.
        os_name: ``linux``, ``darwin`` or ``windows``.
        version: The version the state named, written beside the program;
            empty when the state named none.
        open_to_accounts: The platform's call that lets every account read
            and run what is under one directory.

    Returns:
        The program's path.

    Raises:
        ValueError: When the archive holds no program of the system's name,
            or its kind is unknown or a member would land outside it.
        tarfile.TarError: When a tarball cannot be read.
        zipfile.BadZipFile: When a zip cannot be read.
        OSError: When the directory cannot be written or opened.
    """
    os.makedirs(root, mode=0o755, exist_ok=True)
    os.chmod(root, 0o755)
    target = os.path.join(root, AI_TOOLS_BIN_DIR_NAME)
    name = os.path.basename(binary_path(root, os_name))
    staging = tempfile.mkdtemp(prefix=".unpack_", dir=root)
    try:
        extract_archive(
            archive,
            AI_TOOLS_CC_SWITCH_KINDS.get(os_name, AI_TOOLS_CC_SWITCH_KIND),
            staging,
        )
        if not os.path.isfile(os.path.join(staging, name)):
            raise ValueError(f"the archive holds no {name}")
        os.chmod(os.path.join(staging, name), 0o755)
        with open(
            os.path.join(staging, AI_TOOLS_VERSION_NAME), "w", encoding="utf-8"
        ) as stream:
            stream.write(version)
        remove_tree(target)
        os.replace(staging, target)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    seal_tree(target)
    open_to_accounts(target)
    return os.path.join(target, name)


def remove_copy(root: str) -> list:
    """Delete the copy and its version.

    Args:
        root: The records' directory.

    Returns:
        The directory removed, or nothing when there was none.
    """
    target = os.path.join(root, AI_TOOLS_BIN_DIR_NAME)
    if not os.path.isdir(target):
        return []
    remove_tree(target)
    return [target]
