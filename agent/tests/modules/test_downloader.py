"""The downloader's validation, which is what stands between a blocked
download and an installer being handed a web page."""

import pytest

from neutrino_agent.modules.downloader import DownloadError, verify_package

# The real shape of what ToDesk's CDN answers a plain fetcher with: HTTP 200,
# two kilobytes, and HTML.
CHALLENGE_PAGE = b"<!doctype html><html><body>checking...</body></html>" * 20


def test_challenge_page_is_refused(tmp_path):
    path = tmp_path / "package.deb"
    path.write_bytes(CHALLENGE_PAGE)
    with pytest.raises(DownloadError) as caught:
        verify_package(str(path), "deb")
    assert "challenge" in str(caught.value)


def test_real_deb_passes(tmp_path):
    path = tmp_path / "package.deb"
    path.write_bytes(b"!<arch>\n" + b"\0" * (200 * 1024))
    verify_package(str(path), "deb")


def test_wrong_kind_is_refused(tmp_path):
    # An rpm served where a deb was expected: big enough, wrong magic.
    path = tmp_path / "package.deb"
    path.write_bytes(b"\xed\xab\xee\xdb" + b"\0" * (200 * 1024))
    with pytest.raises(DownloadError) as caught:
        verify_package(str(path), "deb")
    assert "does not look like a deb" in str(caught.value)


def test_windows_and_mac_kinds(tmp_path):
    msi = tmp_path / "package.msi"
    msi.write_bytes(b"\xd0\xcf\x11\xe0" + b"\0" * (200 * 1024))
    verify_package(str(msi), "msi")

    exe = tmp_path / "package.exe"
    exe.write_bytes(b"MZ\x90\x00" + b"\0" * (200 * 1024))
    verify_package(str(exe), "exe")

    # A dmg has no one magic number, so only the size floor applies.
    dmg = tmp_path / "package.dmg"
    dmg.write_bytes(b"x\xdac`" + b"\0" * (200 * 1024))
    verify_package(str(dmg), "dmg")


def test_missing_file_is_refused(tmp_path):
    with pytest.raises(DownloadError):
        verify_package(str(tmp_path / "nothing.deb"), "deb")
