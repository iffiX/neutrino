"""The shared folders' access lists on Linux, written on open descriptors.

What these pin, on real files: the data directory passes the default
account with ``--x`` and ``data/`` lists with ``r-x``; a write folder and
every folder under it hold ``rwx`` for the account and the service's
account, each also a default entry, with the mask ``rwx``; a read folder
holds ``r-x`` for the account alone, also a default entry; a file moved in
with mode 600 gets read and write for both in a write folder, and read in
a read folder; a link keeps its own entries and its target outside is left
as it is; with no default account no account's entry is written; an entry
another account held goes.
"""

import os
import struct

import pytest

from neutrino_agent.modules.comfyui.linux_access import (
    LinuxFolderAccess,
    encode,
    file_permissions,
)

ACCOUNT = 60001
SERVICE = os.getuid() if hasattr(os, "getuid") else 0


def decoded(path, attribute="system.posix_acl_access"):
    """``{(tag, id): permissions}`` of one access list."""
    try:
        raw = os.getxattr(path, attribute, follow_symlinks=False)
    except OSError:
        return {}
    entries = {}
    for at in range(4, len(raw), 8):
        tag, permissions, uid = struct.unpack("<HHI", raw[at : at + 8])
        entries[(tag, uid if uid != 0xFFFFFFFF else None)] = permissions
    return entries


def named(path, attribute="system.posix_acl_access"):
    return {
        uid: rights
        for (tag, uid), rights in decoded(path, attribute).items()
        if tag == 2
    }


def mask(path, attribute="system.posix_acl_access"):
    return decoded(path, attribute).get((0x10, None))


@pytest.fixture
def tree(tmp_path):
    data = tmp_path / "comfyui_data"
    base = data / "data"
    for name in ("models", "input", "output", "user", "custom_nodes"):
        os.makedirs(base / name)
    try:
        os.setxattr(str(base), "system.posix_acl_access", encode(7, 5, 0, {}))
    except OSError:
        pytest.skip("the file system keeps no access list")
    return data


def test_each_folder_gets_its_entries(tree):
    base = tree / "data"
    os.makedirs(base / "models" / "checkpoints")
    left = LinuxFolderAccess(
        data_dir=str(tree), base_dir=str(base), service_uid=SERVICE
    ).write(ACCOUNT)
    assert left == []
    assert named(str(tree)) == {ACCOUNT: 1}
    assert named(str(base)) == {ACCOUNT: 5}
    for folder in (base / "models", base / "models" / "checkpoints", base / "output"):
        assert named(str(folder)) == {SERVICE: 7, ACCOUNT: 7}
        assert named(str(folder), "system.posix_acl_default") == {
            SERVICE: 7,
            ACCOUNT: 7,
        }
        assert (
            mask(str(folder)) == 7
            and mask(str(folder), "system.posix_acl_default") == 7
        )
    for folder in (base / "user", base / "custom_nodes"):
        assert named(str(folder)) == {ACCOUNT: 5}
        assert named(str(folder), "system.posix_acl_default") == {ACCOUNT: 5}


def test_a_file_moved_in_gets_the_entries_and_a_link_keeps_its_own(tree, tmp_path):
    base = tree / "data"
    moved = base / "models" / "moved.safetensors"
    moved.write_bytes(b"m")
    os.chmod(moved, 0o600)
    node = base / "custom_nodes" / "node.py"
    node.write_text("x")
    outside = tmp_path / "outside.txt"
    outside.write_text("o")
    os.symlink(str(outside), base / "input" / "link")
    LinuxFolderAccess(
        data_dir=str(tree), base_dir=str(base), service_uid=SERVICE
    ).write(ACCOUNT)
    assert named(str(moved)) == {SERVICE: 6, ACCOUNT: 6}
    assert named(str(node)) == {ACCOUNT: 4}
    assert named(str(outside)) == {}
    assert os.path.islink(base / "input" / "link")


def test_no_default_account_writes_no_accounts_entry_and_takes_an_old_one_away(tree):
    base = tree / "data"
    access = LinuxFolderAccess(
        data_dir=str(tree), base_dir=str(base), service_uid=SERVICE
    )
    access.write(ACCOUNT)
    access.write(None)
    assert ACCOUNT not in named(str(tree))
    assert ACCOUNT not in named(str(base / "models"))
    assert named(str(base / "models")) == {SERVICE: 7}
    assert ACCOUNT not in named(str(base / "user"))


def test_a_files_rights_follow_its_folder_and_its_owners_execute_bit():
    assert file_permissions(0o600, True) == 6
    assert file_permissions(0o700, True) == 7
    assert file_permissions(0o644, False) == 4
    assert file_permissions(0o755, False) == 5
