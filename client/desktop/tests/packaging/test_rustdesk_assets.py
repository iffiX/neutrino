"""The RustDesk pins, and where the Windows executable is staged; the
download is stood in for."""

import pytest

from shared import rustdesk_assets


def test_every_pin_is_a_flutter_asset_of_the_pinned_release():
    for (os_name, machine), (suffix, digest) in rustdesk_assets.RUSTDESK_ASSETS.items():
        url = rustdesk_assets.asset_url(os_name, machine)
        assert url.endswith(
            f"/{rustdesk_assets.RUSTDESK_VERSION}/rustdesk-1.4.9{suffix}"
        )
        assert "sciter" not in url
        assert len(digest) == 64
        assert digest == digest.lower()


def test_the_download_is_checked_against_its_pin(monkeypatch):
    asked = []

    def fetch(url, digest):
        asked.append((url, digest))
        return b"MZ"

    monkeypatch.setattr(rustdesk_assets, "_fetch", fetch)

    assert rustdesk_assets.download("windows", "x86_64") == b"MZ"
    assert asked == [
        (
            rustdesk_assets.asset_url("windows", "x86_64"),
            rustdesk_assets.RUSTDESK_ASSETS[("windows", "x86_64")][1],
        )
    ]


def test_the_windows_executable_takes_the_name_asked_for(monkeypatch, tmp_path):
    monkeypatch.setattr(rustdesk_assets, "_fetch", lambda url, digest: b"MZ")

    written = rustdesk_assets.stage_windows_exe(
        tmp_path / "bin", name="rustdesk-1.4.9-x86_64.exe"
    )

    assert written == tmp_path / "bin" / "rustdesk-1.4.9-x86_64.exe"
    assert written.read_bytes() == b"MZ"


def test_a_machine_with_no_pin_is_refused_by_name():
    with pytest.raises(SystemExit) as refused:
        rustdesk_assets.asset_url("windows", "aarch64")

    assert "aarch64" in str(refused.value)
    assert "x86_64" in str(refused.value)
