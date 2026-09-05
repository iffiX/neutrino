"""What the hub accepts as a vendor's package."""

import pytest

from neutrino_hub.modules.devices.vendor_fetch import (
    VendorFetchError,
    fetch_vendor_package,
    looks_like_package,
)


def test_a_challenge_page_is_not_a_package():
    """The gate this exists for answers 200 with html, so the status line
    proves nothing and the bytes are what is judged."""
    page = b"<!DOCTYPE html><html><body><script>window._x = 1</script>"

    assert looks_like_package(page, "deb") is False
    assert looks_like_package(page, "rpm") is False
    assert looks_like_package(page, "exe") is False


def test_each_kind_knows_its_own_opening():
    assert looks_like_package(b"!<arch>\ndebian-binary", "deb") is True
    assert looks_like_package(b"\xed\xab\xee\xdb\x03\x00", "rpm") is True
    assert looks_like_package(b"MZ\x90\x00", "exe") is True
    assert looks_like_package(b"PK\x03\x04", "zip_binary") is True
    assert looks_like_package(b"\x1f\x8b\x08", "tar_binary") is True


def test_an_unknown_kind_is_not_evidence_of_a_page():
    """Refusing what this does not recognise would fail installs that work."""
    assert looks_like_package(b"anything at all", "flatpak") is True


def test_a_hub_without_the_fetcher_says_so(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def refuse(name, *arguments, **keywords):
        if name.startswith("curl_cffi"):
            raise ImportError("no curl_cffi here")
        return real_import(name, *arguments, **keywords)

    monkeypatch.setattr(builtins, "__import__", refuse)

    with pytest.raises(VendorFetchError) as raised:
        fetch_vendor_package("https://vendor/x.deb", package_kind="deb")

    assert raised.value.code == "vendor_fetch_unavailable"
