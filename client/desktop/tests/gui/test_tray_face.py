"""The tray's face for the state of the hubs joined."""

import pytest

from neutrino_client.constants import CLIENT_TRAY_FACES
from neutrino_client.core.session import CONNECTION_STATES
from neutrino_client.gui.tray_face import tray_face


def _hubs(*connections):
    return [{"connection": connection} for connection in connections]


def test_no_hub_joined_is_the_sleeping_face():
    assert tray_face([]) == "sleep"


@pytest.mark.parametrize(
    "connection, face",
    [
        ("connected", "wink"),
        ("connecting", "waiting"),
        ("waiting", "error"),
        ("replaced", "sleep"),
        ("disabled", "sleep"),
    ],
)
def test_one_hub_shows_its_connection(connection, face):
    assert tray_face(_hubs(connection)) == face


@pytest.mark.parametrize(
    "connections, face",
    [
        (("connected", "connecting"), "waiting"),
        (("connected", "waiting"), "error"),
        (("connecting", "waiting"), "error"),
        (("replaced", "connected"), "wink"),
    ],
)
def test_the_worst_connection_decides_among_several_hubs(connections, face):
    assert tray_face(_hubs(*connections)) == face


def test_every_connection_has_a_face_the_packages_carry():
    for connection in CONNECTION_STATES:
        assert tray_face(_hubs(connection)) in CLIENT_TRAY_FACES
