"""What a config backup is allowed to write when it is unpacked.

Restore runs as root, so an archive is hostile input even though the person
uploading it is signed in: backups get passed around, and one built elsewhere
can name any path it likes. A member whose name merely starts with `config/`
proves nothing — `config/../../etc/passwd` starts that way — so what these
pin is that the destination is checked after the path resolves.
"""

import tarfile

import pytest
from fastapi import HTTPException

from neutrino_hub.web.routers.settings import _checked_member


def member(name: str, kind: bytes = tarfile.REGTYPE) -> tarfile.TarInfo:
    """One archive entry of a given name and type."""
    entry = tarfile.TarInfo(name)
    entry.type = kind
    entry.size = 0
    return entry


@pytest.mark.parametrize(
    "name",
    [
        "config",
        "config/",
        "config/xray/nodes.json",
        "config/credentials/vault.json",
        "config/sub/../still_inside.json",
    ],
)
def test_paths_inside_config_are_accepted(name):
    assert _checked_member(member(name)).name == name


@pytest.mark.parametrize(
    "name",
    [
        "config/../../etc/passwd",
        "config/../../../root/.ssh/authorized_keys",
        "config/../.gitignore",
        "/etc/passwd",
        "../etc/passwd",
        "etc/passwd",
        "",
    ],
)
def test_paths_that_would_land_outside_config_are_refused(name):
    with pytest.raises(HTTPException) as raised:
        _checked_member(member(name))
    assert raised.value.status_code == 400


@pytest.mark.parametrize(
    "kind",
    [
        tarfile.SYMTYPE,
        tarfile.LNKTYPE,
        tarfile.CHRTYPE,
        tarfile.BLKTYPE,
        tarfile.FIFOTYPE,
    ],
)
def test_only_files_and_directories_are_unpacked(kind):
    with pytest.raises(HTTPException) as raised:
        _checked_member(member("config/anything", kind))
    assert raised.value.status_code == 400


def test_a_directory_inside_config_is_accepted():
    assert _checked_member(member("config/xray", tarfile.DIRTYPE)).isdir()
