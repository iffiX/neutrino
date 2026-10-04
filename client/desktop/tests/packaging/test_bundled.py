"""The pins of the binaries the client carries, and how they are unpacked.

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
from shared import rustdesk_assets

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


def _zip(*names: str) -> bytes:
    """A zip holding files by their paths inside it."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name in names:
            archive.writestr(name, "bin")
    return buffer.getvalue()


def _easytier_zip(url: str) -> bytes:
    """An EasyTier release: one directory holding the daemon, the CLI and more."""
    top = url.rsplit("/", 1)[-1].split("-v")[0]
    suffix = ".exe" if "windows" in url else ""
    names = [f"{top}/easytier-core{suffix}", f"{top}/easytier-cli{suffix}"]
    names.append(f"{top}/easytier-web{suffix}")
    if "windows" in url:
        names += [f"{top}/Packet.dll", f"{top}/wintun.dll", f"{top}/WinDivert64.sys"]
    return _zip(*names)


@pytest.fixture
def downloads(monkeypatch):
    """Every fetch answered from memory, and every url recorded.

    Returns:
        The urls asked for, in order.
    """
    asked = []

    def fetch(url, digest, what=""):
        asked.append(url)
        if "tun2socks" in url:
            return _zip("tun2socks-windows-amd64.exe")
        if "netbird" in url:
            return _tarball("netbird.exe" if "windows" in url else "netbird")
        if "easytier" in url:
            return _easytier_zip(url)
        if url.endswith(".zip"):
            return _zip(bundled.CC_SWITCH_WINDOWS_BINARY_NAME)
        if url.endswith(".tar.gz"):
            return _tarball(bundled.CC_SWITCH_BINARY_NAME)
        return b"MZ"

    monkeypatch.setattr(bundled.payload, "fetch", fetch)
    monkeypatch.setattr(rustdesk_assets, "_fetch", fetch)
    monkeypatch.setattr(bundled.hub_assets, "fetch", fetch)
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


@pytest.fixture
def attached_image(monkeypatch):
    """``hdiutil attach`` replaced by an app bundle at the mountpoint, and
    every hdiutil command recorded.

    Returns:
        The commands, in order.
    """
    commands = []

    def run(command):
        commands.append(list(command))
        if command[1] == "attach":
            app = payload.Path(command[-2]) / rustdesk_assets.RUSTDESK_APP_NAME
            binary = app / rustdesk_assets.RUSTDESK_APP_BINARY
            binary.parent.mkdir(parents=True)
            binary.write_text("")
            (app / "Contents" / "Info.plist").write_text("")

    monkeypatch.setattr(rustdesk_assets, "_run", run)
    return commands


# --- the pins ---


@pytest.mark.parametrize("machine", MACHINES)
def test_every_linux_machine_has_both_binaries_pinned(machine):
    for assets in (bundled.CC_SWITCH_ASSETS, rustdesk_assets.RUSTDESK_ASSETS):
        asset, digest = assets[("linux", machine)]
        assert asset
        assert len(digest) == 64
        assert digest == digest.lower()


def test_windows_has_both_binaries_pinned():
    for assets in (bundled.CC_SWITCH_ASSETS, rustdesk_assets.RUSTDESK_ASSETS):
        asset, digest = assets[("windows", "x86_64")]
        assert asset
        assert len(digest) == 64


@pytest.mark.parametrize("machine", ["aarch64", "x86_64"])
def test_both_mac_architectures_have_both_binaries_pinned(machine):
    for assets in (bundled.CC_SWITCH_ASSETS, rustdesk_assets.RUSTDESK_ASSETS):
        asset, digest = assets[("darwin", machine)]
        assert asset
        assert len(digest) == 64
        assert digest == digest.lower()


def test_the_linux_switcher_is_the_musl_build_and_windows_is_the_zip():
    assert bundled.CC_SWITCH_ASSETS[("linux", "x86_64")][0].endswith("-musl.tar.gz")
    assert bundled.CC_SWITCH_ASSETS[("linux", "aarch64")][0].endswith("-musl.tar.gz")
    assert bundled.CC_SWITCH_ASSETS[("windows", "x86_64")][0].endswith(".zip")
    assert bundled.CC_SWITCH_ASSETS[("darwin", "aarch64")][0] == "darwin-arm64.tar.gz"
    assert bundled.CC_SWITCH_ASSETS[("darwin", "x86_64")][0] == "darwin-x64.tar.gz"


def test_the_viewer_is_the_flutter_build_and_never_the_old_frontend():
    for (os_name, _machine), (
        suffix,
        _digest,
    ) in rustdesk_assets.RUSTDESK_ASSETS.items():
        assert "sciter" not in suffix
    assert rustdesk_assets.RUSTDESK_ASSETS[("linux", "x86_64")][0].endswith(".deb")
    assert rustdesk_assets.RUSTDESK_ASSETS[("windows", "x86_64")][0].endswith(".exe")
    assert rustdesk_assets.RUSTDESK_ASSETS[("darwin", "aarch64")][0] == "-aarch64.dmg"
    assert rustdesk_assets.RUSTDESK_ASSETS[("darwin", "x86_64")][0] == "-x86_64.dmg"


def test_the_urls_name_the_versions_the_pins_are_for():
    switcher = bundled.CC_SWITCH_URL.format(
        version=bundled.CC_SWITCH_VERSION,
        asset=bundled.CC_SWITCH_ASSETS[("linux", "x86_64")][0],
    )
    viewer = rustdesk_assets.RUSTDESK_URL.format(
        version=rustdesk_assets.RUSTDESK_VERSION,
        suffix=rustdesk_assets.RUSTDESK_ASSETS[("linux", "x86_64")][0],
    )

    assert switcher.endswith(
        f"v{bundled.CC_SWITCH_VERSION}/cc-switch-cli-v{bundled.CC_SWITCH_VERSION}"
        "-linux-x64-musl.tar.gz"
    )
    assert viewer.endswith(f"{rustdesk_assets.RUSTDESK_VERSION}-x86_64.deb")


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

    prefix = tmp_path / "opt/neutrino/client"
    switcher = prefix / "bin/cc-switch"
    assert switcher.is_file()
    assert switcher.stat().st_mode & 0o111
    assert (prefix / "rustdesk" / "rustdesk").is_file()
    assert (prefix / "rustdesk" / "lib" / "librustdesk.so").is_file()
    for relative in (
        "netbird/netbird",
        "easytier/easytier-core",
        "easytier/easytier-cli",
    ):
        assert (prefix / relative).stat().st_mode & 0o111, relative
    assert sorted(path.name for path in (prefix / "easytier").iterdir()) == [
        "easytier-cli",
        "easytier-core",
    ]


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
    assert (tmp_path / "bin" / "netbird.exe").is_file()
    for name in ("easytier-core.exe", "easytier-cli.exe", "wintun.dll"):
        assert (tmp_path / "bin" / name).is_file(), name
    for name in ("Packet.dll", "WinDivert64.sys", "easytier-web.exe"):
        assert not (tmp_path / "bin" / name).exists(), name


def test_the_windows_staging_carries_tun2socks_at_the_hubs_own_pin(tmp_path, downloads):
    bundled.stage_windows_binaries(tmp_path, "x64")

    assert (tmp_path / "bin" / "tun2socks.exe").read_text() == "bin"
    assert (tmp_path / "bin" / "tun2socks.exe").stat().st_mode & 0o111
    url, _digest = bundled.hub_assets.pinned("tun2socks", "windows", "amd64")
    assert url in downloads
    assert f"/v{bundled.hub_assets.pinned_version('tun2socks')}/" in url
    assert not (tmp_path / "bin" / "tun2socks-windows-amd64.exe").exists()


def test_the_macos_staging_puts_both_under_the_bundles_resources(
    tmp_path, downloads, attached_image
):
    contents = tmp_path / "Neutrino Client.app" / "Contents"

    bundled.stage_darwin_binaries(contents, "arm64")

    switcher = contents / "Resources" / "bin" / "cc-switch"
    assert switcher.is_file()
    assert switcher.stat().st_mode & 0o111
    app = contents / "Resources" / "rustdesk" / "RustDesk.app"
    assert (app / "Contents" / "MacOS" / "RustDesk").is_file()
    assert (app / "Contents" / "Info.plist").is_file()
    assert (contents / "Resources" / "netbird" / "netbird").is_file()
    assert (contents / "Resources" / "easytier" / "easytier-core").is_file()
    assert (contents / "Resources" / "easytier" / "easytier-cli").is_file()
    assert [url.rsplit("/", 1)[-1] for url in downloads] == [
        "cc-switch-cli-v5.10.4-darwin-arm64.tar.gz",
        "rustdesk-1.4.9-aarch64.dmg",
        "netbird_0.78.1_darwin_arm64.tar.gz",
        "easytier-macos-aarch64-v2.6.4.zip",
    ]


def test_an_intel_mac_takes_the_x86_64_builds(tmp_path, downloads, attached_image):
    bundled.stage_darwin_binaries(tmp_path / "Contents", "amd64")

    assert [url.rsplit("/", 1)[-1] for url in downloads] == [
        "cc-switch-cli-v5.10.4-darwin-x64.tar.gz",
        "rustdesk-1.4.9-x86_64.dmg",
        "netbird_0.78.1_darwin_amd64.tar.gz",
        "easytier-macos-x86_64-v2.6.4.zip",
    ]


def test_the_disk_image_is_attached_read_only_and_detached_again(
    tmp_path, downloads, attached_image
):
    bundled.stage_darwin_binaries(tmp_path / "Contents", "arm64")

    attach, detach = attached_image
    assert attach[:5] == ["hdiutil", "attach", "-nobrowse", "-readonly", "-mountpoint"]
    assert attach[-1].endswith("rustdesk-aarch64.dmg")
    assert detach == ["hdiutil", "detach", attach[-2]]


def test_a_disk_image_carrying_no_viewer_is_refused_and_still_detached(
    tmp_path, downloads, monkeypatch
):
    commands = []

    def run(command):
        commands.append(list(command))

    monkeypatch.setattr(rustdesk_assets, "_run", run)

    with pytest.raises(SystemExit) as refused:
        bundled.stage_darwin_binaries(tmp_path / "Contents", "arm64")

    assert "RustDesk.app" in str(refused.value)
    assert [command[1] for command in commands] == ["attach", "detach"]


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
        CLIENT_BUNDLED_PATHS_DARWIN,
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
        f"bin\\{rustdesk_assets.RUSTDESK_WINDOWS_BINARY_NAME}"
    )
    assert CLIENT_BUNDLED_PATHS_WINDOWS["tun2socks"] == "bin\\tun2socks.exe"
    assert "tun2socks" not in CLIENT_BUNDLED_PATHS_LINUX
    assert "tun2socks" not in CLIENT_BUNDLED_PATHS_DARWIN
    assert CLIENT_BUNDLED_PATHS_DARWIN["cc-switch"] == (
        f"{bundled.DARWIN_RESOURCES_DIR}/{bundled.CC_SWITCH_INSTALL_PATH}"
    )
    assert CLIENT_BUNDLED_PATHS_DARWIN["rustdesk"] == (
        f"{bundled.DARWIN_RESOURCES_DIR}/{bundled.RUSTDESK_INSTALL_DIR}/"
        f"{rustdesk_assets.RUSTDESK_APP_NAME}/{rustdesk_assets.RUSTDESK_APP_BINARY}"
    )


# --- NetBird and EasyTier ---


@pytest.mark.parametrize(
    "key",
    [
        ("linux", "x86_64"),
        ("linux", "aarch64"),
        ("windows", "x86_64"),
        ("darwin", "aarch64"),
        ("darwin", "x86_64"),
    ],
)
def test_every_platform_has_both_overlay_daemons_pinned(key):
    for assets in (bundled.NETBIRD_ASSETS, bundled.EASYTIER_ASSETS):
        asset, digest = assets[key]
        assert asset
        assert len(digest) == 64
        assert digest == digest.lower()


def test_the_overlay_urls_name_the_versions_the_pins_are_for():
    netbird = bundled.NETBIRD_URL.format(
        version=bundled.NETBIRD_VERSION,
        asset=bundled.NETBIRD_ASSETS[("windows", "x86_64")][0],
    )
    easytier = bundled.EASYTIER_URL.format(
        version=bundled.EASYTIER_VERSION,
        asset=bundled.EASYTIER_ASSETS[("darwin", "aarch64")][0],
    )

    assert netbird.endswith("v0.78.1/netbird_0.78.1_windows_amd64.tar.gz")
    assert easytier.endswith("v2.6.4/easytier-macos-aarch64-v2.6.4.zip")


def test_an_easytier_release_without_its_daemon_is_refused(tmp_path, monkeypatch):
    def fetch(url, digest, what):
        return _zip("easytier-linux-x86_64/easytier-cli")

    monkeypatch.setattr(bundled.payload, "fetch", fetch)

    with pytest.raises(SystemExit) as refused:
        bundled._stage_easytier(tmp_path / "easytier", "linux", "x86_64")

    assert "easytier-core" in str(refused.value)


def test_a_netbird_tarball_without_its_binary_is_refused(tmp_path, monkeypatch):
    def fetch(url, digest, what):
        return _tarball("README.md")

    monkeypatch.setattr(bundled.payload, "fetch", fetch)

    with pytest.raises(SystemExit) as refused:
        bundled._stage_netbird(tmp_path / "netbird", "linux", "x86_64")

    assert "carries no netbird" in str(refused.value)
