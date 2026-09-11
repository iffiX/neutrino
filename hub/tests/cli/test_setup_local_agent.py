"""The setup step that gives the hub box its own agent.

A hub hosts no module itself, so the machine it runs on is a device like any
other and has to carry an agent. Nothing here installs anything: the package
manager, the cache and the agent command are fakes, and what is pinned is
that the package comes from the hub's own cache rather than a download, that
the join uses a link minted for it, and that a machine this hub has no agent
for is said out loud instead of failing the run.
"""

import pytest

from neutrino_hub.cli import setup


class FakeReporter:
    """Records the step's outcome."""

    def __init__(self):
        self.started: list = []
        self.done_notes: list = []
        self.failures: list = []

    def start(self, description: str, code: str = "", params: dict | None = None):
        self.started.append((description, code))

    def done(self, note: str = ""):
        self.done_notes.append(note)

    def failed(self, note: str = ""):
        self.failures.append(note)


class FakeCache:
    """The agent packages this hub carries."""

    def __init__(self, *, is_served: bool = True):
        self._is_served = is_served

    def serves(self, *, family: str, architecture: str) -> bool:
        return self._is_served

    def package(self, *, family: str, architecture: str) -> str:
        return f"/var/lib/neutrino/agent_cache/neutrino-agent_0.2.0_{architecture}.deb"


class FakePackageManager:
    """The machine's package manager, as far as the step drives it."""

    def __init__(self):
        self.installed: list = []

    def install(self, packages: tuple) -> None:
        self.installed.append(packages)


@pytest.fixture
def box(monkeypatch):
    """A Debian amd64 hub whose panel hands out a link."""
    manager = FakePackageManager()
    commands: list = []
    monkeypatch.setattr(setup, "is_dev_root_set", lambda: False)
    monkeypatch.setattr(setup, "distribution_family", lambda: "debian")
    monkeypatch.setattr(setup, "machine_architecture", lambda: "amd64")
    monkeypatch.setattr(setup, "AgentPackageCache", FakeCache)
    monkeypatch.setattr(setup.package_manager, "current", lambda: manager)
    monkeypatch.setattr(
        setup, "_enrollment_link", lambda password: ("neutrino://x", "")
    )
    monkeypatch.setattr(
        setup, "run", lambda command, **kwargs: commands.append(command)
    )
    return manager, commands


def test_the_agent_comes_from_the_hubs_own_cache_and_joins_this_hub(box):
    manager, commands = box
    reporter = FakeReporter()

    setup._install_local_agent("panel-password", reporter)

    assert manager.installed == [
        ("/var/lib/neutrino/agent_cache/neutrino-agent_0.2.0_amd64.deb",)
    ]
    assert commands == [["nagent", "connect", "neutrino://x", "--yes"]]
    assert reporter.done_notes == ["installed and joined"]
    assert reporter.started[0][1] == setup.SETUP_STEP_LOCAL_AGENT


def test_a_machine_this_hub_has_no_agent_for_is_said_and_the_run_goes_on(
    box, monkeypatch
):
    manager, commands = box
    monkeypatch.setattr(setup, "AgentPackageCache", lambda: FakeCache(is_served=False))
    reporter = FakeReporter()

    setup._install_local_agent("panel-password", reporter)

    assert manager.installed == []
    assert commands == []
    assert reporter.failures


def test_a_family_with_no_agent_build_is_not_asked_for_one(box, monkeypatch):
    manager, commands = box
    monkeypatch.setattr(setup, "distribution_family", lambda: "arch")
    reporter = FakeReporter()

    setup._install_local_agent("panel-password", reporter)

    assert manager.installed == []
    assert reporter.failures


def test_a_panel_that_hands_out_no_link_leaves_the_agent_installed(box, monkeypatch):
    manager, commands = box
    monkeypatch.setattr(
        setup, "_enrollment_link", lambda password: ("", "the panel did not answer")
    )
    reporter = FakeReporter()

    setup._install_local_agent("panel-password", reporter)

    assert manager.installed
    assert commands == []
    assert reporter.failures == ["the panel did not answer"]


def test_a_development_root_installs_nothing(box, monkeypatch):
    manager, _ = box
    monkeypatch.setattr(setup, "is_dev_root_set", lambda: True)
    reporter = FakeReporter()

    setup._install_local_agent("panel-password", reporter)

    assert manager.installed == []
    assert reporter.started == []


def test_a_refusal_from_the_package_manager_is_reported(box, monkeypatch):
    manager, _ = box

    def refuse(packages):
        raise OSError("dpkg is locked")

    monkeypatch.setattr(manager, "install", refuse)
    reporter = FakeReporter()

    setup._install_local_agent("panel-password", reporter)

    assert reporter.failures
    assert reporter.done_notes == []
