"""Unpacking the CLI from the archive Microsoft publishes, and writing its files.

What these pin: the one file of the CLI's name comes out of a tarball or a
zip wherever it sits, runnable by every account; an archive without it, an
unknown kind or a broken archive is an install error; a file already
holding the text is left alone.
"""

import io
import os
import stat
import tarfile
import zipfile

import pytest

from neutrino_agent.exceptions import InstallError
from neutrino_agent.modules.vscode.installer import (
    remove_cli,
    unpack_cli,
    write_if_changed,
)


def tarball(path, members: dict) -> str:
    with tarfile.open(path, "w:gz") as archive:
        for name, payload in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
    return str(path)


def test_the_cli_comes_out_of_a_tarball(tmp_path):
    archive = tarball(tmp_path / "cli.tar.gz", {"code": b"\x7fELF", "LICENSE": b"x"})

    target = unpack_cli(
        archive, package_kind="tar", directory=str(tmp_path / "vscode"), name="code"
    )

    assert target == str(tmp_path / "vscode" / "code")
    assert open(target, "rb").read() == b"\x7fELF"
    assert stat.S_IMODE(os.stat(target).st_mode) == 0o755


def test_the_cli_comes_out_of_a_zip_wherever_it_sits(tmp_path):
    archive = tmp_path / "cli.zip"
    with zipfile.ZipFile(archive, "w") as packed:
        packed.writestr("bin/code.exe", b"MZ")

    target = unpack_cli(
        str(archive), package_kind="zip", directory=str(tmp_path / "v"), name="code.exe"
    )

    assert open(target, "rb").read() == b"MZ"


@pytest.mark.parametrize("package_kind", ["deb", "tar"])
def test_an_archive_without_the_cli_or_of_another_kind_is_refused(
    tmp_path, package_kind
):
    archive = tarball(tmp_path / "cli.tar.gz", {"README": b"x"})

    with pytest.raises(InstallError):
        unpack_cli(
            archive, package_kind=package_kind, directory=str(tmp_path), name="code"
        )


def test_a_broken_archive_is_refused(tmp_path):
    archive = tmp_path / "cli.zip"
    archive.write_bytes(b"not a zip")

    with pytest.raises(InstallError):
        unpack_cli(str(archive), package_kind="zip", directory=str(tmp_path), name="c")


def test_a_file_is_written_only_when_its_text_changes(tmp_path):
    path = str(tmp_path / "ann.token")

    assert write_if_changed(path, "t1", 0o600) is True
    assert write_if_changed(path, "t1", 0o600) is False
    assert write_if_changed(path, "t2", 0o600) is True
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


def test_removing_the_cli_takes_its_directory(tmp_path):
    directory = tmp_path / "vscode"
    directory.mkdir()
    (directory / "code").write_bytes(b"x")

    remove_cli(str(directory))

    assert not directory.exists()
