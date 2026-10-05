"""The pinned cc-switch files the mainland release carries, with the
downloads faked.

What is asserted is the list the release takes: every pinned file under the
name upstream gives it, fetched from its pinned url, and the licence beside
them; and that a download which is not the pinned file stops the build.
"""

import io

import pytest

from shared import cc_switch_assets
from shared.constants import (
    PACKAGING_CC_SWITCH_ASSETS,
    PACKAGING_CC_SWITCH_VERSION,
)


@pytest.fixture
def fetched(monkeypatch):
    """Every pinned download answered with its own name; the urls asked for."""
    asked = []

    def fetch(url, digest):
        asked.append((url, digest))
        return url.rsplit("/", 1)[-1].encode()

    monkeypatch.setattr(cc_switch_assets, "_fetch", fetch)
    return asked


def test_the_release_takes_every_pinned_file_under_its_upstream_name(tmp_path, fetched):
    written = cc_switch_assets.write_release_files(tmp_path)

    names = sorted(path.name for path in written)
    expected = sorted(
        f"cc-switch-cli-v{PACKAGING_CC_SWITCH_VERSION}-{asset}"
        for asset, _digest in PACKAGING_CC_SWITCH_ASSETS.values()
    ) + [f"cc-switch-cli-v{PACKAGING_CC_SWITCH_VERSION}-LICENSE.txt"]
    assert names == sorted(expected)
    assert sorted(digest for _url, digest in fetched) == sorted(
        digest for _asset, digest in PACKAGING_CC_SWITCH_ASSETS.values()
    )
    for url, _digest in fetched:
        assert url.startswith(
            "https://github.com/SaladDay/cc-switch-cli/releases/download/"
            f"v{PACKAGING_CC_SWITCH_VERSION}/"
        )
        assert (tmp_path / url.rsplit("/", 1)[-1]).read_bytes() == (
            url.rsplit("/", 1)[-1].encode()
        )


def test_the_licence_goes_beside_them(tmp_path, fetched):
    cc_switch_assets.write_release_files(tmp_path)

    licence = (tmp_path / cc_switch_assets.license_name()).read_text()
    assert "MIT License" in licence
    assert f"tree/v{PACKAGING_CC_SWITCH_VERSION}" in licence


def test_a_download_that_is_not_the_pinned_file_stops_the_build(monkeypatch, tmp_path):
    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(
        cc_switch_assets.urllib.request,
        "urlopen",
        lambda url, timeout: Response(b"not the release"),
    )

    with pytest.raises(SystemExit) as refused:
        cc_switch_assets.write_release_files(tmp_path)

    assert "not the pinned" in str(refused.value)
