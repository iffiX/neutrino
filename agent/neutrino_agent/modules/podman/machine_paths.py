"""Folders of the computer in a container's volumes, as a Podman machine sees them.

On Windows a folder on a drive is written ``C:\\data`` and the machine
reaches it at ``/mnt/c/data``, WSL's own mount of the drive. On macOS a
folder under ``/Users``, ``/private`` or ``/var/folders`` has the same path
in the machine, which Podman shares into it. Any other folder has no path
in the machine.

Pure: strings in, strings out.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import re

# A Windows folder on a drive: the letter, its colon and a separator.
WINDOWS_DRIVE_PATTERN = re.compile(r"^[A-Za-z]:[\\/]")

# WSL's mount of a drive inside the machine, and the path under it.
WINDOWS_MOUNT_PATTERN = re.compile(r"^/mnt/([a-z])(/.*)?\Z")

# The folders of a Mac that Podman shares into its machine.
DARWIN_SHARED_ROOTS = ("/Users", "/private", "/var/folders")


def split_volume(volume: str, *, os_name: str) -> tuple:
    """A volume's source and what follows it.

    Args:
        volume: The volume as the configuration writes it.
        os_name: The computer's system; on ``windows`` a source that
            starts with a drive letter keeps its colon.

    Returns:
        ``(source, rest)``: ``rest`` is the destination with its options,
        empty when the volume names no destination.
    """
    start = 2 if os_name == "windows" and WINDOWS_DRIVE_PATTERN.match(volume) else 0
    index = volume.find(":", start)
    if index < 0:
        return volume, ""
    return volume[:index], volume[index + 1 :]


def is_shared_source(source: str, *, os_name: str) -> bool:
    """Whether a folder of the computer has a path inside the machine.

    Args:
        source: The folder, in the computer's own form.
        os_name: The computer's system.

    Returns:
        True for a folder on a Windows drive, for a folder under one of
        macOS's shared roots, and for any absolute path elsewhere.
    """
    if os_name == "windows":
        return WINDOWS_DRIVE_PATTERN.match(source) is not None
    if os_name == "darwin":
        return any(
            source == root or source.startswith(root + "/")
            for root in DARWIN_SHARED_ROOTS
        )
    return source.startswith("/")


def to_machine_source(source: str, *, os_name: str) -> str:
    """One folder of the computer as the machine names it.

    Args:
        source: The folder, in the computer's own form, or a named volume.

    Returns:
        ``/mnt/<drive>/<path>`` for a folder on a Windows drive; any other
        source as it is.
    """
    if os_name != "windows" or not WINDOWS_DRIVE_PATTERN.match(source):
        return source
    rest = source[2:].replace("\\", "/").rstrip("/")
    return f"/mnt/{source[0].lower()}{rest}"


def to_machine(volume: str, *, os_name: str) -> str:
    """One volume with its folder as the machine names it.

    Args:
        volume: The volume as the configuration writes it.
        os_name: The computer's system.

    Returns:
        The volume, ``C:\\data:/data`` written ``/mnt/c/data:/data``.
    """
    source, rest = split_volume(volume, os_name=os_name)
    return f"{to_machine_source(source, os_name=os_name)}:{rest}"


def to_host_source(source: str, *, os_name: str) -> str:
    """One mount's source as the computer names it, the reverse of :func:`to_machine_source`.

    Args:
        source: The source as Podman in the machine reports it.
        os_name: The computer's system.

    Returns:
        ``C:\\data`` for ``/mnt/c/data`` on Windows; any other source as it is.
    """
    if os_name != "windows":
        return source
    found = WINDOWS_MOUNT_PATTERN.match(source)
    if found is None:
        return source
    rest = (found.group(2) or "").replace("/", "\\") or "\\"
    return f"{found.group(1).upper()}:{rest}"
