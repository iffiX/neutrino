"""The pins of the two binaries the client carries, and how they are unpacked.

Nothing here reaches the network: the download is replaced by an archive
built in ``tmp_path``, so what is asserted is the pin table's completeness,
where each binary lands, and the refusals — a machine with no pin, and a
viewer that would not find the libraries carried beside it.
"""

import io
import tarfile
import zipfile

import pytest

import bundled
import payload

MACHINES = ("x86_64", "aarch64")


def _tarball(name: str) -> bytes:
    """A gzip tarball holding one executable file."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        member = tarfile.TarInfo(name)
        member.size = 3
        member.mode = 0o755
        archive.addfile(member, io.BytesIO(b"bin"))
    return buffer.getvalue()


def _zip(name: str) -> bytes:
    """A zip holding one executable file."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(name, "bin")
    return buffer.getvalue()


@pytest.fixture
def downloads(monkeypatch):
    """Every fetch answered from memory, and every url recorded.

    Returns:
        The urls asked for, in order.
    """
    asked = []

    def fetch(url, digest, what):
        asked.append(url)
        if url.endswith(".zip"):
            return _zip(bundled.CC_SWITCH_WINDOWS_BINARY_NAME)
        if url.endswith(".tar.gz"):
            return _tarball(bundled.CC_SWITCH_BINARY_NAME)
        return b"MZ"

    monkeypatch.setattr(bundled.payload, "fetch", fetch)
    return asked


@pytest.fixture
def unpacked_viewer(monkeypatch):
    """``dpkg-deb -x`` replaced by a tree that looks like upstream's own."""
    checked = []

    def run(command, cwd=None):
        into = payload.Path(command[-1])
        carried = into / bundled.RUSTDESK_UPSTREAM_DIR
        (carried / "lib").mkdir(parents=True)
        (carried / bundled.RUSTDESK_BINARY_NAME).write_text("")
        (carried / "lib" / "librustdesk.so").write_text("")

    def check_runpath(binary):
        checked.append(binary)

    monkeypatch.setattr(bundled.payload, "run", run)
    monkeypatch.setattr(bundled, "check_runpath", check_runpath)
    return checked


# --- the pins ---


@pytest.mark.parametrize("machine", MACHINES)
def test_every_linux_machine_has_both_binaries_pinned(machine):
    for assets in (bundled.CC_SWITCH_ASSETS, bundled.RUSTDESK_ASSETS):
        asset, digest = assets[("linux", machine)]
        assert asset
        assert len(digest) == 64
        assert digest == digest.lower()


def test_windows_has_both_binaries_pinned():
    for assets in (bundled.CC_SWITCH_ASSETS, bundled.RUSTDESK_ASSETS):
        asset, digest = assets[("windows", "x86_64")]
        assert asset
        assert len(digest) == 64


def test_the_linux_switcher_is_the_musl_build_and_windows_is_the_zip():
    assert bundled.CC_SWITCH_ASSETS[("linux", "x86_64")][0].endswith("-musl.tar.gz")
    assert bundled.CC_SWITCH_ASSETS[("linux", "aarch64")][0].endswith("-musl.tar.gz")
    assert bundled.CC_SWITCH_ASSETS[("windows", "x86_64")][0].endswith(".zip")


def test_the_viewer_is_the_flutter_build_and_never_the_old_frontend():
    for (os_name, _machine), (suffix, _digest) in bundled.RUSTDESK_ASSETS.items():
        assert "sciter" not in suffix
    assert bundled.RUSTDESK_ASSETS[("linux", "x86_64")][0].endswith(".deb")
    assert bundled.RUSTDESK_ASSETS[("windows", "x86_64")][0].endswith(".exe")


def test_the_urls_name_the_versions_the_pins_are_for():
    switcher = bundled.CC_SWITCH_URL.format(
        version=bundled.CC_SWITCH_VERSION,
        asset=bundled.CC_SWITCH_ASSETS[("linux", "x86_64")][0],
    )
    viewer = bundled.RUSTDESK_URL.format(
        version=bundled.RUSTDESK_VERSION,
        suffix=bundled.RUSTDESK_ASSETS[("linux", "x86_64")][0],
    )

    assert switcher.endswith(
        f"v{bundled.CC_SWITCH_VERSION}/cc-switch-cli-v{bundled.CC_SWITCH_VERSION}"
        "-linux-x64-musl.tar.gz"
    )
    assert viewer.endswith(f"{bundled.RUSTDESK_VERSION}-x86_64.deb")


@pytest.mark.parametrize("machine", ["armhf", "i386", "riscv64"])
def test_a_machine_with_no_pin_is_refused_by_name(machine, tmp_path):
    with pytest.raises(SystemExit) as refused:
        bundled.stage_linux_binaries(tmp_path, machine)

    assert machine in str(refused.value)


def test_an_architecture_with_no_windows_pin_is_refused_by_name(tmp_path, downloads):
    with pytest.raises(SystemExit) as refused:
        bundled.stage_windows_binaries(tmp_path, "arm64")

    assert "aarch64" in str(refused.value)


# --- what a staging lays down ---


def test_the_linux_staging_puts_both_where_the_runtime_looks(
    tmp_path, downloads, unpacked_viewer
):
    bundled.stage_linux_binaries(tmp_path, "amd64")

    prefix = tmp_path / "opt/neutrino_client"
    switcher = prefix / "bin/cc-switch"
    assert switcher.is_file()
    assert switcher.stat().st_mode & 0o111
    assert (prefix / "rustdesk" / "rustdesk").is_file()
    assert (prefix / "rustdesk" / "lib" / "librustdesk.so").is_file()


def test_the_linux_staging_checks_the_viewer_finds_its_own_libraries(
    tmp_path, downloads, unpacked_viewer
):
    bundled.stage_linux_binaries(tmp_path, "amd64")

    assert [path.name for path in unpacked_viewer] == ["rustdesk"]


def test_a_viewer_without_its_runpath_is_refused(tmp_path, monkeypatch):
    binary = tmp_path / "rustdesk"
    binary.write_text("")

    class Result:
        returncode = 0
        stdout = "Library runpath: [/usr/lib]"
        stderr = ""

    def run(command, capture_output=False, text=False):
        return Result()

    monkeypatch.setattr(bundled.subprocess, "run", run)

    with pytest.raises(SystemExit) as refused:
        bundled.check_runpath(binary)

    assert bundled.RUSTDESK_EXPECTED_RUNPATH in str(refused.value)


def test_the_windows_staging_puts_both_under_bin(tmp_path, downloads):
    bundled.stage_windows_binaries(tmp_path, "x64")

    assert (tmp_path / "bin" / "cc-switch.exe").is_file()
    assert (tmp_path / "bin" / "rustdesk.exe").read_bytes() == b"MZ"


def test_an_archive_carrying_no_binary_is_refused(tmp_path, monkeypatch):
    def fetch(url, digest, what):
        return _tarball("something-else")

    monkeypatch.setattr(bundled.payload, "fetch", fetch)

    with pytest.raises(SystemExit) as refused:
        bundled._stage_cc_switch(tmp_path / "bin" / "cc-switch", "linux", "x86_64")

    assert "cc-switch" in str(refused.value)


def test_the_install_paths_are_the_ones_the_runtime_resolver_reads():
    """The build and ``neutrino_client.bundled`` name the same two paths."""
    from neutrino_client.constants import (
        CLIENT_BUNDLED_PATHS_LINUX,
        CLIENT_BUNDLED_PATHS_WINDOWS,
        CLIENT_INSTALL_PREFIX_LINUX,
    )

    assert str(payload.INSTALL_PREFIX) == CLIENT_INSTALL_PREFIX_LINUX
    assert CLIENT_BUNDLED_PATHS_LINUX["cc-switch"] == bundled.CC_SWITCH_INSTALL_PATH
    assert CLIENT_BUNDLED_PATHS_LINUX["rustdesk"] == (
        f"{bundled.RUSTDESK_INSTALL_DIR}/{bundled.RUSTDESK_BINARY_NAME}"
    )
    assert CLIENT_BUNDLED_PATHS_WINDOWS["cc-switch"] == (
        f"bin\\{bundled.CC_SWITCH_WINDOWS_BINARY_NAME}"
    )
    assert CLIENT_BUNDLED_PATHS_WINDOWS["rustdesk"] == (
        f"bin\\{bundled.RUSTDESK_WINDOWS_BINARY_NAME}"
    )
