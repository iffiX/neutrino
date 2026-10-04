"""code-server's release on the machine, against a fake release archive.

What these pin: the release's one directory lands as ``release``, read-only,
and a new one replaces the one before; an archive that is not a release is
the module's own download failure; the version is read from the release;
each account's run directory is its own and mode 0700; a socket path the
system cannot bind is refused; and an instance runs with ``--auth none`` on
its socket and nothing that phones home.
"""

import io
import os
import stat
import tarfile

import pytest

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.code_server import installer


def release_archive(path, version="4.140.0", *, top=None) -> str:
    top = top or f"code-server-{version}-linux-amd64"
    members = {
        f"{top}/bin/code-server": b"#!/bin/sh\n",
        f"{top}/lib/node": b"\x7fELF",
        f"{top}/package.json": (
            '{"name": "code-server", "version": "%s"}' % version
        ).encode(),
    }
    with tarfile.open(path, "w:gz") as archive:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o755
            archive.addfile(info, io.BytesIO(data))
    return str(path)


def test_the_release_lands_as_release_read_only(tmp_path):
    root = str(tmp_path / "code_server")

    target = installer.unpack_release(
        release_archive(tmp_path / "a.tar.gz"), package_kind="tar", root=root
    )

    assert target == os.path.join(root, "release")
    assert os.path.isfile(installer.launcher_path(root))
    assert os.path.isfile(installer.node_path(root))
    assert stat.S_IMODE(os.stat(target).st_mode) == 0o555
    assert installer.installed_version(root) == "4.140.0"
    assert sorted(os.listdir(root)) == ["release"]


def test_a_new_release_replaces_the_one_before(tmp_path):
    root = str(tmp_path / "code_server")
    installer.unpack_release(
        release_archive(tmp_path / "a.tar.gz"), package_kind="tar", root=root
    )

    installer.unpack_release(
        release_archive(tmp_path / "b.tar.gz", "4.141.0"), package_kind="tar", root=root
    )

    assert installer.installed_version(root) == "4.141.0"


@pytest.mark.parametrize("kind", ["tar", "zip", "rar"])
def test_an_archive_that_is_not_one_is_a_failed_download(tmp_path, kind):
    junk = tmp_path / "junk"
    junk.write_bytes(b"not an archive")

    with pytest.raises(ModuleApplyError) as caught:
        installer.unpack_release(str(junk), package_kind=kind, root=str(tmp_path / "r"))

    assert caught.value.code == "code_server_download_failed"


def test_an_archive_without_one_release_is_refused(tmp_path):
    archive = release_archive(tmp_path / "a.tar.gz", top="node-v22")

    with pytest.raises(ModuleApplyError) as caught:
        installer.unpack_release(archive, package_kind="tar", root=str(tmp_path / "r"))

    assert caught.value.code == "code_server_download_failed"
    assert installer.installed_version(str(tmp_path / "r")) == ""


def test_removing_the_module_takes_the_release_and_the_run_directories(tmp_path):
    root = str(tmp_path / "code_server")
    installer.unpack_release(
        release_archive(tmp_path / "a.tar.gz"), package_kind="tar", root=root
    )
    installer.prepare_run_dir(root, "ann", os.getuid(), os.getgid())

    installer.remove_release(root)

    assert not os.path.exists(root)


def test_an_account_s_run_directory_is_its_own_and_closed(tmp_path):
    owners = []
    root = str(tmp_path / "code_server")

    directory = installer.prepare_run_dir(
        root, "ann", 1001, 1002, chown=lambda path, uid, gid: owners.append((uid, gid))
    )

    assert directory == os.path.join(root, "run", "ann")
    assert stat.S_IMODE(os.stat(directory).st_mode) == 0o700
    assert stat.S_IMODE(os.stat(os.path.join(root, "run")).st_mode) == 0o755
    assert owners == [(1001, 1002)]
    installer.remove_run_dir(root, "ann")
    assert not os.path.exists(directory)


def test_a_socket_path_the_system_cannot_bind_is_refused():
    root = "/var/lib/neutrino/agent/code_server"
    mac = "/Library/Application Support/Neutrino/agent/state/code_server"

    installer.check_socket_path(root, "a" * 50, "linux")
    installer.check_socket_path(mac, "a" * 20, "darwin")
    for base, account, os_name in (
        (root, "a" * 51, "linux"),
        (mac, "a" * 21, "darwin"),
    ):
        with pytest.raises(ModuleApplyError) as caught:
            installer.check_socket_path(base, account, os_name)
        assert caught.value.code == "account_invalid"
        assert caught.value.params == {"account": account}


def test_an_instance_runs_without_its_own_login_on_its_socket():
    arguments = installer.server_arguments("/m", "ann")

    assert arguments == [
        "/m/release/bin/code-server",
        "--socket",
        "/m/run/ann/code_server.sock",
        "--auth",
        "none",
        "--socket-mode",
        "600",
        "--disable-telemetry",
        "--disable-update-check",
    ]
