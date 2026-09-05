"""Who the control channel says is asking.

An identity comes from kernel peer credentials or from a token minted to
one; a token never minted here answers as nobody.
"""

from neutrino_agent.control.identity import (
    ControlIdentity,
    ControlTokenStore,
    peer_identity,
)


class FakePeerPlatform:
    def __init__(self, raw: dict):
        self.raw = raw

    def read_peer_identity(self, connection) -> dict:
        return self.raw


def test_a_minted_token_answers_as_its_identity():
    store = ControlTokenStore()
    alice = ControlIdentity(account="alice", uid=1000, is_privileged=False)
    root = ControlIdentity(account="root", uid=0, is_privileged=True)

    alice_token = store.mint(alice)
    root_token = store.mint(root)

    assert store.identity_of(alice_token) is alice
    assert store.identity_of(root_token) is root


def test_a_token_never_minted_answers_as_nobody():
    store = ControlTokenStore()
    store.mint(ControlIdentity(account="alice", uid=1000, is_privileged=False))

    assert store.identity_of("") is None
    assert store.identity_of("never-minted") is None


def test_peer_identity_wraps_what_the_platform_reports():
    platform = FakePeerPlatform(
        {"account": "alice", "uid": 1000, "is_privileged": False}
    )

    identity = peer_identity(platform, object())

    assert identity.account == "alice"
    assert identity.uid == 1000
    assert identity.is_privileged is False
    assert identity.to_dict() == {
        "account": "alice",
        "uid": 1000,
        "is_privileged": False,
    }


def test_peer_identity_keeps_privilege_for_uid_zero():
    platform = FakePeerPlatform({"account": "root", "uid": 0, "is_privileged": True})

    assert peer_identity(platform, object()).is_privileged is True


def test_a_tokens_pulse_keeps_it_alive_and_silence_expires_it():
    now = [0.0]
    store = ControlTokenStore(idle_ttl_s=10, clock=lambda: now[0])
    alice = ControlIdentity(account="alice", uid=1000, is_privileged=False)
    token = store.mint(alice)

    now[0] = 8.0
    assert store.identity_of(token) is alice
    now[0] = 17.0
    assert store.is_alive(token) is True

    now[0] = 28.0
    assert store.is_alive(token) is False
    assert store.identity_of(token) is None


def test_an_unclaimed_token_waits_forever_for_its_first_page():
    """A person may take minutes to paste the printed URL; a token that
    dies while they type is a session lying about a closed window."""
    now = [0.0]
    store = ControlTokenStore(idle_ttl_s=10, clock=lambda: now[0])
    token = store.mint(ControlIdentity(account="alice", uid=1000, is_privileged=False))

    now[0] = 3600.0
    assert store.is_alive(token) is True
    assert store.is_claimed(token) is False
    assert store.identity_of(token) is not None
    assert store.is_claimed(token) is True


def test_watching_a_token_is_not_its_pulse():
    now = [0.0]
    store = ControlTokenStore(idle_ttl_s=10, clock=lambda: now[0])
    token = store.mint(ControlIdentity(account="alice", uid=1000, is_privileged=False))

    now[0] = 1.0
    assert store.identity_of(token) is not None
    now[0] = 8.0
    assert store.is_alive(token) is True
    now[0] = 12.0
    assert store.is_alive(token) is False


def test_a_revoked_token_answers_as_nobody():
    store = ControlTokenStore()
    token = store.mint(ControlIdentity(account="alice", uid=1000, is_privileged=False))

    store.revoke(token)

    assert store.identity_of(token) is None
    assert store.is_alive(token) is False
    store.revoke("never-minted")
