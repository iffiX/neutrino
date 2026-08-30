"""The login lockout ladder: five free failures, then 30s up to a day."""

import time

from neutrino_hub.web import auth
from neutrino_hub.web.auth import SessionStore, hash_password


def make_store(tmp_path, monkeypatch) -> SessionStore:
    monkeypatch.setattr(
        auth, "WEB_LOGIN_LOCKOUT_STATE_PATH", tmp_path / "login_lockout.json"
    )
    return SessionStore(password_hash=hash_password("right"), session_ttl_hours=1)


def test_five_failures_are_free_and_the_sixth_locks(tmp_path, monkeypatch):
    store = make_store(tmp_path, monkeypatch)

    for _ in range(5):
        assert store.login("wrong") is None
        assert store.lockout_remaining_s() == 0
    assert store.login("wrong") is None
    assert 0 < store.lockout_remaining_s() <= 30


def test_each_further_failure_locks_for_the_next_step(tmp_path, monkeypatch):
    store = make_store(tmp_path, monkeypatch)
    for _ in range(6):
        store.login("wrong")

    # The lock expires; the very next failure takes the next step.
    store._locked_until = time.time() - 1
    assert store.login("wrong") is None
    assert 30 < store.lockout_remaining_s() <= 60


def test_the_right_password_resets_everything(tmp_path, monkeypatch):
    store = make_store(tmp_path, monkeypatch)
    for _ in range(4):
        store.login("wrong")

    assert store.login("right") is not None
    for _ in range(5):
        assert store.login("wrong") is None
        assert store.lockout_remaining_s() == 0


def test_deleting_the_state_file_is_the_whole_unlock(tmp_path, monkeypatch):
    store = make_store(tmp_path, monkeypatch)
    for _ in range(6):
        store.login("wrong")
    assert store.lockout_remaining_s() > 0

    (tmp_path / "login_lockout.json").unlink()
    assert store.lockout_remaining_s() == 0
    assert store.login("right") is not None


def test_the_lockout_survives_a_restart(tmp_path, monkeypatch):
    store = make_store(tmp_path, monkeypatch)
    for _ in range(6):
        store.login("wrong")

    reborn = make_store(tmp_path, monkeypatch)
    assert reborn.lockout_remaining_s() > 0
