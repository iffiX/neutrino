"""Who the control channel says is asking.

An identity comes from the connection's kernel peer credentials, read
through the platform contract.
"""

from neutrino_agent.control.identity import peer_identity


class FakePeerPlatform:
    def __init__(self, raw: dict):
        self.raw = raw

    def read_peer_identity(self, connection) -> dict:
        return self.raw


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
