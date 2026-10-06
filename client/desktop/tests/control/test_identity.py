"""The control identity: read from the platform, same person or not."""

from neutrino_client.control.identity import ControlIdentity, peer_identity
from tests.conftest import OTHER_USER, SAME_USER, FakeClientPlatform


def test_the_identity_round_trips_the_platforms_answer():
    platform = FakeClientPlatform()
    platform.peer = dict(SAME_USER)

    identity = peer_identity(platform, object())

    assert isinstance(identity, ControlIdentity)
    assert identity.to_dict() == dict(SAME_USER, is_elevated=False)


def test_an_elevated_caller_is_marked():
    platform = FakeClientPlatform()
    platform.peer = dict(SAME_USER, is_elevated=True)

    assert peer_identity(platform, object()).is_elevated is True


def test_another_account_is_not_the_same_user():
    platform = FakeClientPlatform()
    platform.peer = dict(OTHER_USER)

    assert peer_identity(platform, object()).is_same_user is False


def test_a_shapeless_answer_reads_as_nobody():
    platform = FakeClientPlatform()
    platform.peer = {}

    identity = peer_identity(platform, object())

    assert identity.to_dict() == {
        "account": "",
        "uid": -1,
        "is_same_user": False,
        "is_elevated": False,
    }
