"""The panel's sign-in tokens and the sessions a client's sign-in opens.

A token is 32 random bytes in base64url, spent by its first use, dead after
``WEB_PANEL_TOKEN_TTL_S``, and a client holds at most ``WEB_PANEL_TOKENS_MAX``:
a ninth pushes out the oldest. A session a client opened carries its id and
is listed apart from the ones the password opened.
"""

import base64

from neutrino_hub.web import auth
from neutrino_hub.web.auth import PanelTokenStore, SessionStore
from neutrino_hub.web.constants import WEB_PANEL_TOKEN_TTL_S, WEB_PANEL_TOKENS_MAX


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_a_token_is_32_random_bytes_and_spends_once_for_its_client():
    tokens = PanelTokenStore(clock=Clock())

    token = tokens.mint("client-a")

    assert len(base64.urlsafe_b64decode(token + "=")) == 32
    assert tokens.spend(token) == ("client-a", "")
    assert tokens.spend(token) == ("", "unknown")
    assert tokens.spend("never-minted") == ("", "unknown")


def test_a_token_after_its_time_is_expired_and_gone():
    clock = Clock()
    tokens = PanelTokenStore(clock=clock)
    late = tokens.mint("client-a")
    in_time = tokens.mint("client-a")

    clock.now += WEB_PANEL_TOKEN_TTL_S
    assert tokens.spend(in_time) == ("client-a", "")
    clock.now += 1

    assert tokens.spend(late) == ("", "expired")
    assert tokens.spend(late) == ("", "unknown")


def test_a_ninth_token_pushes_out_the_clients_oldest_and_no_one_elses():
    tokens = PanelTokenStore(clock=Clock())
    other = tokens.mint("client-b")
    minted = [tokens.mint("client-a") for _ in range(WEB_PANEL_TOKENS_MAX + 1)]

    assert tokens.spend(minted[0]) == ("", "unknown")
    assert [tokens.spend(token)[0] for token in minted[1:]] == ["client-a"] * (
        WEB_PANEL_TOKENS_MAX
    )
    assert tokens.spend(other) == ("client-b", "")


def store(tmp_path, monkeypatch) -> SessionStore:
    monkeypatch.setattr(auth, "WEB_LOGIN_LOCKOUT_STATE_PATH", tmp_path / "lockout")
    return SessionStore(password_hash="", session_ttl_hours=1)


def test_a_clients_session_is_valid_and_listed_with_its_client(tmp_path, monkeypatch):
    sessions = store(tmp_path, monkeypatch)

    token = sessions.open_for_client("client-a")

    assert sessions.is_valid(token)
    assert sessions.client_sessions() == [(token, "client-a")]
    sessions.logout(token)
    assert not sessions.is_valid(token)
    assert sessions.client_sessions() == []
