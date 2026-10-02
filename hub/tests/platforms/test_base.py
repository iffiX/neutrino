"""What every platform shares: the lock on a Unix file, the command that
runs ``nhub`` itself, and the refusals a system class must answer."""

import os
import sys

import pytest

from neutrino_hub.platforms import base
from neutrino_hub.platforms.base import HubPlatform


def test_the_lock_is_held_once(tmp_path):
    path = tmp_path / "router.lock"
    first = os.open(path, os.O_RDWR | os.O_CREAT)
    second = os.open(path, os.O_RDWR)
    try:
        platform = HubPlatform()
        assert platform.try_lock(first)
        assert not platform.try_lock(second)
        platform.unlock(first)
        assert platform.try_lock(second)
    finally:
        os.close(first)
        os.close(second)


def test_a_checkout_runs_nhub_through_its_interpreter():
    assert HubPlatform().hub_command("apply", "--skip-apply") == [
        sys.executable,
        "-m",
        "neutrino_hub.cli.entry",
        "apply",
        "--skip-apply",
    ]


def test_the_compiled_binary_runs_itself(monkeypatch):
    monkeypatch.setattr(base, "is_compiled", lambda: True)

    assert HubPlatform().hub_command("apply") == [sys.executable, "apply"]


@pytest.mark.parametrize(
    "verb", ["service_state", "start_service", "stop_service", "restart_service"]
)
def test_the_one_service_is_not_the_bases_to_drive(verb):
    with pytest.raises(NotImplementedError):
        getattr(HubPlatform(), verb)()


def test_no_controller_and_no_browser_without_a_system_class():
    with pytest.raises(NotImplementedError):
        HubPlatform().process_controller()
    assert not HubPlatform().open_browser("http://127.0.0.1/")
