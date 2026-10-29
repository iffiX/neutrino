"""Putting the AI gateway in place on macOS and Windows.

What these pin: the package carries the binary, so nothing is downloaded and
no unit is written; the gateway is applied and registered with the process
controller once, and a missing binary is named.
"""

import hashlib
import io
import tarfile

import pytest

from neutrino_hub.exceptions import DownloadFailedError
from neutrino_hub.modules.cliproxyapi import provisioner
from neutrino_hub.modules.cliproxyapi.provisioner import CliproxyApiProvisioner
from tests.conftest import FakeSourceFetcher


class RecordingApplier:
    applies: list = []

    def apply(self):
        RecordingApplier.applies.append("apply")
        return "applied"


def refuse(command, **keywords):
    raise AssertionError(f"ran {command}")


@pytest.fixture
def carried(tmp_path, monkeypatch):
    binary = tmp_path / "bin" / "cli-proxy-api"
    binary.parent.mkdir()
    binary.write_text("")
    monkeypatch.setattr(provisioner, "CLIPROXYAPI_BINARY_PATH", binary)
    monkeypatch.setattr(provisioner, "CLIPROXYAPI_DIR", tmp_path / "cliproxyapi")
    monkeypatch.setattr(
        provisioner, "CLIPROXYAPI_AUTH_DIR", tmp_path / "cliproxyapi" / "auth"
    )
    monkeypatch.setattr(provisioner, "UTILS_GENERATED_DIR", tmp_path / "generated")
    monkeypatch.setattr(provisioner, "CliproxyApiConfigApplier", RecordingApplier)
    monkeypatch.setattr(provisioner, "run", refuse)
    RecordingApplier.applies = []
    return binary


def test_elsewhere_the_carried_gateway_is_registered_once(
    elsewhere, carried, fake_controller, tmp_path
):
    first = CliproxyApiProvisioner().provision()
    second = CliproxyApiProvisioner().provision()

    assert first.is_changed and not second.is_changed
    assert fake_controller.verbs() == [("enable", "cliproxyapi")]
    assert RecordingApplier.applies == ["apply", "apply"]
    assert (tmp_path / "cliproxyapi" / "auth").is_dir()


def test_elsewhere_a_missing_binary_is_named(elsewhere, carried, fake_controller):
    carried.unlink()

    with pytest.raises(FileNotFoundError, match="cli-proxy-api"):
        CliproxyApiProvisioner().provision()
    assert fake_controller.verbs() == []


def test_elsewhere_a_removal_disables_the_child_and_keeps_the_binary(
    elsewhere, carried, fake_controller, tmp_path
):
    rendered = tmp_path / "generated" / "cliproxyapi.yaml"
    rendered.parent.mkdir()
    rendered.write_text("")

    result = CliproxyApiProvisioner().deprovision()

    assert result.message == "removed; logins kept"
    assert fake_controller.verbs() == [("disable", "cliproxyapi")]
    assert carried.is_file()
    assert not rendered.exists()


# --- what a checkout fetches on Linux ---


def a_release(payload: bytes = b"the gateway") -> bytes:
    """A release tarball shaped like the vendor's."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as bundle:
        info = tarfile.TarInfo("cli-proxy-api")
        info.size = len(payload)
        bundle.addfile(info, io.BytesIO(payload))
    return buffer.getvalue()


@pytest.fixture
def checkout(tmp_path, monkeypatch):
    archive = a_release()
    fetcher = FakeSourceFetcher({provisioner.download_url("amd64"): archive})
    binary = tmp_path / "bin" / "cli-proxy-api"
    binary.parent.mkdir()
    monkeypatch.setattr(provisioner, "SourceFetcher", lambda: fetcher)
    monkeypatch.setattr(provisioner, "CLIPROXYAPI_BINARY_PATH", binary)
    monkeypatch.setattr(
        provisioner,
        "CLIPROXYAPI_ASSETS",
        {("linux", "amd64"): ("asset", hashlib.sha256(archive).hexdigest())},
    )
    return fetcher, binary


def test_a_checkout_fetches_the_pinned_release_through_the_fetcher(checkout):
    fetcher, binary = checkout

    CliproxyApiProvisioner()._download_binary("amd64")

    url = provisioner.download_url("amd64")
    assert fetcher.asked == [("file", url.rsplit("/", 1)[-1], [url])]
    assert binary.read_bytes() == b"the gateway"
    assert binary.stat().st_mode & 0o777 == 0o755


def test_a_release_that_is_not_what_is_pinned_is_refused(checkout, monkeypatch):
    _, binary = checkout
    monkeypatch.setattr(
        provisioner, "CLIPROXYAPI_ASSETS", {("linux", "amd64"): ("asset", "0" * 64)}
    )

    with pytest.raises(DownloadFailedError):
        CliproxyApiProvisioner()._download_binary("amd64")
    assert not binary.exists()
