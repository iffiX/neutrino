"""Believing a restart of xray.

Two things say a configuration is good and neither of them is: ``xray run
-test`` builds the whole server without binding a single listener, and the unit
is ``Type=simple``, so systemd reports the restart done at fork. A port
something else holds passes both, and the panel used to report the apply a
success with no proxy running at all.
"""

import pytest

from neutrino_hub.modules.xray import apply as apply_module
from neutrino_hub.modules.xray.apply import XrayConfigApplier
from neutrino_hub.utils.subprocess_run import CommandResult

JOURNAL = "failed to listen on 0.0.0.0:1080: address already in use"


def _answering(monkeypatch, *, state: str, journal: str = JOURNAL):
    monkeypatch.setattr(apply_module.time, "sleep", lambda seconds: None)

    def fake_run(command, **kwargs):
        output = state if command[0] == "systemctl" else journal
        return CommandResult(command=command, exit_code=0, stdout=output, stderr="")

    monkeypatch.setattr(apply_module, "run", fake_run)
    return XrayConfigApplier()


def test_a_service_that_stayed_up_is_believed(monkeypatch):
    _answering(monkeypatch, state="active").confirm_running()


def test_a_service_that_died_after_the_restart_fails_the_apply(monkeypatch):
    with pytest.raises(RuntimeError):
        _answering(monkeypatch, state="failed").confirm_running()


def test_the_reason_it_died_is_carried_out_of_its_journal(monkeypatch):
    """The port it could not take is named there and nowhere else."""
    with pytest.raises(RuntimeError) as failure:
        _answering(monkeypatch, state="failed").confirm_running()

    assert "address already in use" in str(failure.value)


def test_an_empty_journal_still_reports_the_failure(monkeypatch):
    with pytest.raises(RuntimeError) as failure:
        _answering(monkeypatch, state="failed", journal="").confirm_running()

    assert "no reason" in str(failure.value)
