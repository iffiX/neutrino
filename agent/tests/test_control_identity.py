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
