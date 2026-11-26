"""The tree hash git computes over a commit's files, read from an archive of them.

A ``git-tree:<hex>`` digest names an archive of a tag that a repository's host
makes on request by the SHA-1 git computes over the tag commit's tree. The
hash covers each file's name, mode and bytes, so it holds however the host
compresses the archive (module_install.md, "Artifacts").

Pure: reads the archive and nothing else.
"""

import hashlib
import tarfile
from pathlib import Path

GIT_TREE_PREFIX = "git-tree:"
# The modes a tree entry names: a file, an executable file, a symbolic link
# and a folder.
FILE_MODE = b"100644"
EXECUTABLE_MODE = b"100755"
LINK_MODE = b"120000"
TREE_MODE = b"40000"
# The permission bits git records no file with, and the bits that make a
# file executable.
SPECIAL_MODE_BITS = 0o7000
EXECUTABLE_BITS = 0o111


def is_git_tree(digest: str) -> bool:
    """Whether a digest names a git tree.

    Args:
        digest: The digest as a manifest names it.

    Returns:
        True for ``git-tree:<hex>``.
    """
    return str(digest or "").startswith(GIT_TREE_PREFIX)


def tar_gz_tree_hex(path: Path) -> str:
    """The git tree hash of a gzip tarball's files.

    An archive whose members all sit under one top directory is read without
    it, as the agent unpacks it.

    Args:
        path: The archive.

    Returns:
        The tree's SHA-1, 40 hex characters.

    Raises:
        ValueError: For an archive that does not read as a gzip tarball, and
            for a member git records no mode for: a hard link, a device, a
            FIFO, or a file with the setuid, setgid or sticky bit.
        OSError: When the archive cannot be read.
    """
    try:
        with tarfile.open(path, "r:gz") as archive:
            members = archive.getmembers()
            top = _top_directory(members)
            root: dict = {}
            for member in members:
                parts = _parts(member.name, top)
                if not parts or member.isdir():
                    continue
                entry = _entry(archive, member)
                folder = root
                for part in parts[:-1]:
                    folder = folder.setdefault(part, {})
                    if not isinstance(folder, dict):
                        raise ValueError(f"{member.name} sits under a file")
                folder[parts[-1]] = entry
    except (tarfile.TarError, EOFError) as error:
        raise ValueError(f"{path} is no gzip tarball: {error}") from error
    return _tree(root).hex()


def _top_directory(members: list) -> str:
    """The one directory every member sits under, empty when there is none."""
    names = [_parts(member.name, "") for member in members]
    tops = {parts[0] for parts in names if parts}
    if len(tops) != 1:
        return ""
    top = tops.pop()
    for member, parts in zip(members, names):
        if parts == [top] and not member.isdir():
            return ""
    return top


def _parts(name: str, top: str) -> list:
    """A member's path inside the tree, as its parts."""
    parts = [part for part in name.split("/") if part and part != "."]
    if top and parts and parts[0] == top:
        parts = parts[1:]
    return parts


def _entry(archive: tarfile.TarFile, member: tarfile.TarInfo) -> tuple:
    """One member as a tree entry, its mode and its blob's SHA-1.

    Raises:
        ValueError: For a member git records no mode for.
    """
    if member.issym():
        return LINK_MODE, _blob(member.linkname.encode("utf-8", "surrogateescape"))
    if not member.isfile() or member.mode & SPECIAL_MODE_BITS:
        raise ValueError(f"{member.name} has a mode git does not record")
    stream = archive.extractfile(member)
    data = stream.read() if stream is not None else b""
    mode = EXECUTABLE_MODE if member.mode & EXECUTABLE_BITS else FILE_MODE
    return mode, _blob(data)


def _blob(data: bytes) -> bytes:
    """The SHA-1 git names a file's bytes by."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).digest()


def _tree(folder: dict) -> bytes:
    """The SHA-1 git names a folder's tree by, its entries in git's order."""
    entries = []
    for name, held in folder.items():
        encoded = name.encode("utf-8", "surrogateescape")
        if isinstance(held, dict):
            entries.append((encoded + b"/", TREE_MODE, encoded, _tree(held)))
        else:
            entries.append((encoded, held[0], encoded, held[1]))
    entries.sort(key=_sort_key)
    body = b"".join(mode + b" " + name + b"\0" + sha for _, mode, name, sha in entries)
    return hashlib.sha1(b"tree %d\0" % len(body) + body).digest()


def _sort_key(entry: tuple) -> bytes:
    """Where an entry sorts: by its name, a tree's with ``/`` after it."""
    return entry[0]
