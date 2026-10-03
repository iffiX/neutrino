"""The setup token kept under the state root, the setup lock, and a session
that takes the next answers after a run that failed."""

import os
import stat

from neutrino_hub.platforms.base import HubPlatform
from neutrino_hub.web import setup_app
from neutrino_hub.web.setup_app import (
    SetupLock,
    WebSetupSession,
    ensure_setup_token,
    remove_setup_token,
)


def test_a_missing_token_is_made_readable_by_root_alone(tmp_path):
    path = tmp_path / "state" / "setup_token"

    token = ensure_setup_token(path)

    assert len(token) >= 32
    assert path.read_text().strip() == token
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


def test_a_kept_token_is_read_back_rather_than_made_again(tmp_path):
    path = tmp_path / "setup_token"

    assert ensure_setup_token(path) == ensure_setup_token(path)


def test_the_token_goes_once_the_box_is_set_up(tmp_path, monkeypatch):
    path = tmp_path / "setup_token"
    monkeypatch.setattr(setup_app, "WEB_SETUP_TOKEN_PATH", path)
    ensure_setup_token()

    remove_setup_token()
    remove_setup_token()

    assert not path.exists()


def test_one_process_holds_the_lock_and_another_is_refused(tmp_path):
    path = tmp_path / "setup.lock"
    first = SetupLock(path=path, platform=HubPlatform())
    second = SetupLock(path=path, platform=HubPlatform())

    assert first.acquire()
    assert first.acquire()
    assert not second.acquire()

    first.release()

    assert second.acquire()
    second.release()


def test_answers_take_the_lock_and_clear_the_last_run():
    taken = []

    class Lock:
        def acquire(self):
            taken.append(True)
            return True

    session = WebSetupSession(context={}, setup_lock=Lock())
    session.step("render_all", "failed", "it broke")

    assert session.answer({"password": "x"})
    assert taken == [True]
    state = session.state()
    assert (state["state"], state["steps"]) == ("running", [])


def test_after_a_failed_run_the_next_answers_are_waited_for():
    session = WebSetupSession(context={})
    session.answer({"password": "x"})
    session.step("render_all", "failed", "it broke")

    session.forget_answers()

    assert session.wait(0) == {}
    assert session.state()["state"] == "failed"
