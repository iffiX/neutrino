"""Putting the AI gateway in place on macOS and Windows.

What these pin: the package carries the binary, so nothing is downloaded and
no unit is written; the gateway is applied and registered with the process
controller once, and a missing binary is named.
"""

import pytest

from neutrino_hub.modules.cliproxyapi import provisioner
from neutrino_hub.modules.cliproxyapi.provisioner import CliproxyApiProvisioner


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
    elsewhere, carried, fake_controller
):
    result = CliproxyApiProvisioner().deprovision()

    assert result.message == "removed; logins kept"
    assert fake_controller.verbs() == [("disable", "cliproxyapi")]
    assert carried.is_file()
