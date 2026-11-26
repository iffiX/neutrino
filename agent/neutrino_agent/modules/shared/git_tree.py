"""The git tree a tag's archive holds, as the SHA-1 git computes over it.

A repository's host makes the archive of a tag on request and can compress
it again, so its bytes are not fixed; the tree of the tag's commit is. The
tree is computed over the archive's members with the one top directory the
host wraps them in dropped: a file is a blob of mode ``100755`` when its
owner may run it and ``100644`` otherwise, a symbolic link a blob of mode
``120000`` holding its target, and a folder a tree of its entries in git's
order. A member of another kind is a mode git does not record.

Pure: reads the archive.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import hashlib
import tarfile

# The modes git records for a file, a file its owner runs, a link and a tree.
GIT_MODE_FILE = b"100644"
GIT_MODE_EXECUTABLE = b"100755"
GIT_MODE_LINK = b"120000"
GIT_MODE_TREE = b"40000"
# The owner's execute bit, which makes a file ``100755``.
OWNER_EXECUTE = 0o100


def _blob(data: bytes) -> bytes:
    """The SHA-1 git names a blob by. Pure."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).digest()


def _order(entry: tuple) -> bytes:
    """The key git sorts a tree's entries by: the name, a folder's with ``/`` after it. Pure."""
    return entry[0].encode("utf-8")


def _tree(entries: dict) -> bytes:
    """The SHA-1 of one tree, its entries in git's order. Pure."""
    ordered = []
    for name, held in entries.items():
        if isinstance(held, dict):
            ordered.append((name + "/", GIT_MODE_TREE, name, _tree(held)))
        else:
            ordered.append((name, held[0], name, held[1]))
    ordered.sort(key=_order)
    body = b"".join(
        mode + b" " + name.encode("utf-8") + b"\0" + digest
        for _key, mode, name, digest in ordered
    )
    return hashlib.sha1(b"tree %d\0" % len(body) + body).digest()


def archive_tree(path: str) -> str:
    """The git tree a tarball holds below its one top directory.

    Args:
        path: The tarball.

    Returns:
        The tree's SHA-1 in hex.

    Raises:
        ValueError: For a member that is neither a file, a folder nor a
            symbolic link, or one that sits above the top directory.
        tarfile.TarError: When the tarball cannot be read.
        OSError: When it cannot be opened.
    """
    root: dict = {}
    with tarfile.open(path, "r:*") as archive:
        for member in archive:
            parts = [part for part in member.name.split("/") if part]
            if not parts or any(part in (".", "..") for part in parts):
                raise ValueError(f"the archive names {member.name!r}")
            parts = parts[1:]
            if not parts or member.isdir():
                continue
            if member.issym():
                held = (GIT_MODE_LINK, _blob(member.linkname.encode("utf-8")))
            elif member.isfile():
                stream = archive.extractfile(member)
                data = stream.read() if stream is not None else b""
                mode = (
                    GIT_MODE_EXECUTABLE
                    if member.mode & OWNER_EXECUTE
                    else GIT_MODE_FILE
                )
                held = (mode, _blob(data))
            else:
                raise ValueError(f"git records no mode of {member.name!r}")
            folder = root
            for part in parts[:-1]:
                folder = folder.setdefault(part, {})
                if not isinstance(folder, dict):
                    raise ValueError(f"the archive names {member.name!r} twice")
            folder[parts[-1]] = held
    return _tree(root).hex()
