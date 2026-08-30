"""The live survey, with podman replaced by canned output."""

from neutrino_hub.modules.podman import ops
from neutrino_hub.modules.podman.ops import PodmanStatusReader


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
