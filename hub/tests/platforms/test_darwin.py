"""The hub on macOS: its one LaunchDaemon driven through a fake launchctl."""

import subprocess

import pytest

from neutrino_hub.platforms import darwin
from neutrino_hub.platforms.darwin import DarwinHubPlatform
from tests.conftest import FakeLaunchd, completed

TARGET = "system/com.neutrino.hub"
PLIST = "/Library/LaunchDaemons/com.neutrino.hub.plist"


@pytest.fixture
def launchd(monkeypatch):
    fake = FakeLaunchd()
    monkeypatch.setattr(darwin.subprocess, "run", fake)
    return fake


def test_a_job_that_is_not_loaded_reads_stopped(launchd):
    assert DarwinHubPlatform().service_state() == "stopped"
    assert launchd.calls == [["launchctl", "print", TARGET]]


def test_a_running_job_reads_running(launchd):
    launchd.is_running = True

    assert DarwinHubPlatform().service_state() == "running"


def test_starting_bootstraps_the_plist_then_kickstarts_the_job(launchd):
    DarwinHubPlatform().start_service()

    assert launchd.calls == [
        ["launchctl", "bootstrap", "system", PLIST],
        ["launchctl", "kickstart", TARGET],
    ]
    assert launchd.is_running


def test_a_refused_start_is_raised(launchd):
    launchd.is_refusing = True

    with pytest.raises(subprocess.CalledProcessError):
        DarwinHubPlatform().start_service()


def test_stopping_boots_the_job_out(launchd):
    launchd.is_running = True

    DarwinHubPlatform().stop_service()

    assert launchd.calls[-1] == ["launchctl", "bootout", TARGET]
    assert not launchd.is_running


def test_stopping_a_stopped_job_asks_nothing_more(launchd):
    DarwinHubPlatform().stop_service()

    assert launchd.calls == [["launchctl", "print", TARGET]]


def test_restarting_a_running_job_kills_and_kickstarts_it(launchd):
    launchd.is_running = True

    DarwinHubPlatform().restart_service()

    assert launchd.calls[-1] == ["launchctl", "kickstart", "-k", TARGET]


def test_restarting_a_stopped_job_starts_it(launchd):
    DarwinHubPlatform().restart_service()

    assert launchd.calls[-1] == ["launchctl", "kickstart", TARGET]


def test_a_page_opens_through_open(monkeypatch):
    calls = []

    def fake_run(command, **keywords):
        calls.append(command)
        return completed("")

    monkeypatch.setattr(darwin.subprocess, "run", fake_run)

    assert DarwinHubPlatform().open_browser("http://127.0.0.1:8080/")
    assert calls == [["open", "http://127.0.0.1:8080/"]]


def test_the_agent_package_installs_with_installer():
    assert DarwinHubPlatform().agent_install_command("/cache/agent.pkg") == [
        "installer",
        "-pkg",
        "/cache/agent.pkg",
        "-target",
        "/",
    ]


def test_netbird_answers_on_the_hubs_own_socket(monkeypatch):
    from pathlib import Path

    monkeypatch.setattr(
        "neutrino_hub.utils.constants.UTILS_RUNTIME_ROOT", Path("/var/run/neutrino_hub")
    )

    assert DarwinHubPlatform().netbird_daemon_address() == (
        "unix:///var/run/neutrino_hub/netbird.sock"
    )


def test_the_agent_command_is_the_link_its_package_makes():
    assert DarwinHubPlatform().agent_command() == "/usr/local/bin/nagent"
