"""The live survey, with podman replaced by canned output."""

import pytest

from neutrino_hub.modules.podman import ops, provisioner
from neutrino_hub.modules.podman.ops import PodmanStatusReader
from neutrino_hub.utils.subprocess_run import CommandError


class FakeResult:
    def __init__(self, stdout):
        self.stdout = stdout
        self.is_success = True


def test_a_declared_but_never_started_container_still_appears(monkeypatch):
    """With autostart off a declared container exists only as a unit until its
    first start; invisible would also mean unstartable."""
    monkeypatch.setattr(
        ops,
        "run",
        lambda *a, **k: FakeResult(
            '[{"Names": ["webdav"], "Image": "nginx", "Status": "Up", '
            '"State": "running"}]'
        ),
    )

    states = PodmanStatusReader().survey(declared_names=["webdav", "python"])

    by_name = {state.name: state for state in states}
    assert by_name["python"].status == "not created yet"
    assert by_name["python"].is_declared is True
    assert by_name["python"].is_running is False
    assert by_name["webdav"].is_running is True


# --- which podman a distribution is allowed to offer ---


def _controller(version: str):
    """A package manager offering one version of podman."""

    class Controller:
        family = "debian"

        def available_version(self, package):
            return version

    return Controller()


def test_a_podman_without_quadlet_is_still_installed():
    """`PodmanUnitRenderer` exists precisely for these, and refusing them read
    the module's own floor as podman's: Debian 12 has 4.3.1 and Ubuntu 22.04
    has 3.4.4, and neither could install podman at all."""
    note = provisioner._require_podman(_controller("4.3.1+ds1-8+deb12u1+b3"))

    assert "plain systemd units" in note
    assert "4.3.1" in note


def test_a_podman_with_quadlet_says_so():
    note = provisioner._require_podman(_controller("4.9.3-1"))

    assert "Quadlet" in note
    assert "4.9.3-1" in note


def test_a_distribution_with_no_podman_is_refused():
    """The one refusal left: nothing to install is nothing to install."""
    with pytest.raises(CommandError):
        provisioner._require_podman(_controller(""))
