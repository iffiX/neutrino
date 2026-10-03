"""What every hub package carries beside the hub, with the downloads faked.

The pins are the hub modules' own tables; what is asserted is that each
system and machine a package is built for has one, that the Linux rows are
the files the Linux constants name, and which files the staging takes out
of each archive for each system.
"""

import io
import re
import tarfile
import zipfile

import pytest

from shared import hub_assets

SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _zip(names):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        for name, payload in names.items():
            bundle.writestr(name, payload)
    return buffer.getvalue()


def _tarball(names):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as bundle:
        for name, payload in names.items():
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            bundle.addfile(info, io.BytesIO(payload))
    return buffer.getvalue()


def _archive(url):
    """What each upstream archive holds, shaped the way its release ships it."""
    exe = ".exe" if "windows" in url else ""
    if "Xray" in url:
        return _zip({f"xray{exe}": b"xray", "geoip.dat": b"db", "wintun.dll": b"x"})
    if "CLIProxyAPI" in url:
        names = {f"cli-proxy-api{exe}": b"gateway", "LICENSE": b"l"}
        return _zip(names) if url.endswith(".zip") else _tarball(names)
    if "netbird" in url:
        return _tarball({f"netbird{exe}": b"client", "LICENSE": b"l"})
    if "tun2socks" in url:
        member = url.rsplit("/", 1)[-1].removesuffix(".zip")
        return _zip({f"{member}{exe}": b"tunnel", "README.md": b"r"})
    if "easytier" in url:
        top = url.rsplit("/", 1)[-1].rsplit("-v", 1)[0]
        return _zip(
            {
                f"{top}/easytier-core{exe}": b"engine",
                f"{top}/easytier-cli{exe}": b"cli",
                f"{top}/easytier-web{exe}": b"console",
                f"{top}/wintun.dll": b"tun",
                f"{top}/Packet.dll": b"npcap",
            }
        )
    return b"database"


@pytest.fixture
def fetched(monkeypatch):
    """Every pinned download answered locally; the URLs asked for, in order."""
    asked = []

    def fetch(url, digest, what):
        asked.append(url)
        assert SHA256.match(digest)
        return _archive(url)

    monkeypatch.setattr(hub_assets, "fetch", fetch)
    return asked


@pytest.mark.parametrize("program", sorted(hub_assets.HUB_ASSET_PROGRAMS))
def test_every_system_a_hub_is_built_for_has_a_pin(program):
    systems = hub_assets.HUB_ASSET_SYSTEMS.get(program, ("linux", "darwin", "windows"))
    for os_name, machine in (
        ("linux", "amd64"),
        ("linux", "arm64"),
        ("darwin", "amd64"),
        ("darwin", "arm64"),
        ("windows", "amd64"),
    ):
        if os_name not in systems:
            continue
        url, digest = hub_assets.pinned(program, os_name, machine)

        assert url.startswith("https://github.com/")
        assert SHA256.match(digest)


def test_the_linux_rows_are_the_files_the_linux_constants_name():
    """A Linux package carries what the panel reports and a checkout fetches."""
    from neutrino_hub.modules.easytier import constants as easytier
    from neutrino_hub.modules.netbird import constants as netbird
    from neutrino_hub.modules.xray import constants as xray
    from neutrino_hub.modules.cliproxyapi import constants as cliproxyapi

    for machine in ("amd64", "arm64"):
        assert hub_assets.pinned("xray", "linux", machine) == (
            xray.XRAY_DOWNLOAD_URL.format(
                version=xray.XRAY_VERSION,
                asset_arch=xray.XRAY_ASSET_ARCHITECTURES[machine],
            ),
            xray.XRAY_SHA256[machine],
        )
        assert hub_assets.pinned("netbird", "linux", machine) == (
            netbird.NETBIRD_DOWNLOAD_URL.format(
                version=netbird.NETBIRD_VERSION,
                asset_arch=netbird.NETBIRD_ASSET_ARCHITECTURES[machine],
            ),
            netbird.NETBIRD_SHA256[machine],
        )
        assert hub_assets.pinned("easytier", "linux", machine) == (
            easytier.EASYTIER_DOWNLOAD_URL.format(
                version=easytier.EASYTIER_VERSION,
                asset_arch=easytier.EASYTIER_ASSET_ARCHITECTURES[machine],
            ),
            easytier.EASYTIER_SHA256[machine],
        )
        url, _digest = hub_assets.pinned("cliproxyapi", "linux", machine)
        assert url == cliproxyapi.CLIPROXYAPI_DOWNLOAD_URL.format(
            version=cliproxyapi.CLIPROXYAPI_VERSION,
            asset_arch=cliproxyapi.CLIPROXYAPI_ASSET_ARCHITECTURES[machine],
        )


def test_every_asset_that_names_a_version_names_its_own():
    """xray's and tun2socks's assets name no version; every other release
    names its own."""
    for program in ("cliproxyapi", "netbird", "easytier"):
        module, prefix, _files = hub_assets.HUB_ASSET_PROGRAMS[program]
        version, assets = hub_assets._runtime(
            module, f"{prefix}_VERSION", f"{prefix}_ASSETS"
        )
        for name, _digest in assets.values():
            assert version in name, (program, name)


def test_a_system_nothing_is_pinned_for_stops_the_build():
    with pytest.raises(SystemExit) as refused:
        hub_assets.pinned("netbird", "windows", "arm64")

    assert "windows amd64" in str(refused.value)


def test_linux_takes_the_five_programs_and_nothing_beside_them(tmp_path, fetched):
    written = hub_assets.stage_programs(tmp_path, "linux", "amd64")

    assert sorted(path.name for path in written) == [
        "cli-proxy-api",
        "easytier-cli",
        "easytier-core",
        "netbird",
        "xray",
    ]
    assert (tmp_path / "easytier-core").read_bytes() == b"engine"
    assert (tmp_path / "xray").stat().st_mode & 0o777 == 0o755
    assert not (tmp_path / "easytier-web").exists()
    assert not (tmp_path / "geoip.dat").exists()
    assert any("easytier-linux-x86_64" in url for url in fetched)


def test_an_intel_mac_takes_the_x86_64_builds(tmp_path, fetched):
    hub_assets.stage_programs(tmp_path, "darwin", "amd64")

    assert fetched == [
        "https://github.com/XTLS/Xray-core/releases/download/"
        "v26.3.27/Xray-macos-64.zip",
        "https://github.com/router-for-me/CLIProxyAPI/releases/download/"
        "v7.2.146/CLIProxyAPI_7.2.146_darwin_amd64.tar.gz",
        "https://github.com/netbirdio/netbird/releases/download/"
        "v0.78.1/netbird_0.78.1_darwin_amd64.tar.gz",
        "https://github.com/EasyTier/EasyTier/releases/download/"
        "v2.6.4/easytier-macos-x86_64-v2.6.4.zip",
        "https://github.com/xjasonlyu/tun2socks/releases/download/"
        "v2.7.0/tun2socks-darwin-amd64.zip",
    ]
    assert (tmp_path / "netbird").read_bytes() == b"client"


@pytest.mark.parametrize("machine", ["amd64", "arm64"])
def test_a_mac_takes_tun2socks_under_its_plain_name(tmp_path, fetched, machine):
    """The archive names the program after the system and machine; the
    package carries it as ``tun2socks``, the name the start line uses."""
    written = hub_assets.stage_programs(tmp_path, "darwin", machine)

    assert (tmp_path / "tun2socks").read_bytes() == b"tunnel"
    assert (tmp_path / "tun2socks").stat().st_mode & 0o777 == 0o755
    assert not (tmp_path / f"tun2socks-darwin-{machine}").exists()
    assert not (tmp_path / "README.md").exists()
    assert [path.name for path in written] == hub_assets.carried_names("darwin")


def test_the_tun2socks_pins_are_the_tun_modules_own():
    from neutrino_hub.modules.tun import constants as tun

    for (os_name, machine), (asset, digest) in tun.TUN_ASSETS.items():
        assert hub_assets.pinned("tun2socks", os_name, machine) == (
            tun.TUN_RELEASE_URL.format(version=tun.TUN_VERSION, asset=asset),
            digest,
        )
    assert sorted(tun.TUN_ASSETS) == [
        ("darwin", "amd64"),
        ("darwin", "arm64"),
        ("windows", "amd64"),
    ]


def test_windows_takes_the_executables_and_easytiers_tun_driver(tmp_path, fetched):
    """wintun.dll comes out of EasyTier's archive, never xray's, and Npcap's
    Packet.dll stays behind."""
    written = hub_assets.stage_programs(tmp_path, "windows", "amd64")

    assert [path.name for path in written] == hub_assets.carried_names("windows")
    assert hub_assets.carried_names("windows") == [
        "xray.exe",
        "cli-proxy-api.exe",
        "netbird.exe",
        "easytier-core.exe",
        "easytier-cli.exe",
        "wintun.dll",
        "tun2socks.exe",
    ]
    assert (tmp_path / "wintun.dll").read_bytes() == b"tun"
    assert (tmp_path / "tun2socks.exe").read_bytes() == b"tunnel"
    assert not (tmp_path / "Packet.dll").exists()


def test_an_archive_without_the_program_stops_the_build(tmp_path, monkeypatch):
    monkeypatch.setattr(
        hub_assets, "fetch", lambda url, digest, what: _zip({"README.md": b""})
    )

    with pytest.raises(SystemExit) as refused:
        hub_assets.stage_programs(tmp_path, "darwin", "arm64")

    assert "carries no xray" in str(refused.value)


def test_the_databases_are_the_pinned_pair(tmp_path, fetched):
    written = hub_assets.stage_geodata(tmp_path)

    assert sorted(path.name for path in written) == ["geoip.dat", "geosite.dat"]
    assert (tmp_path / "geoip.dat").stat().st_mode & 0o777 == 0o644


def test_a_download_that_is_not_what_was_pinned_stops_the_build(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *details):
            return False

        def read(self):
            return b"something else"

    monkeypatch.setattr(
        hub_assets.urllib.request, "urlopen", lambda *a, **k: Response()
    )

    with pytest.raises(SystemExit) as refused:
        hub_assets.fetch("https://example.invalid/netbird.tar.gz", "0" * 64, "netbird")

    assert "not the pinned" in str(refused.value)
