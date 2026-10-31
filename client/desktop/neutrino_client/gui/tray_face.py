"""The tray's face for the state of the hubs joined.

Pure: reads the resident's hub rows.
"""

from neutrino_client.constants import (
    CLIENT_TRAY_FACE_CONNECTED,
    CLIENT_TRAY_FACE_CONNECTING,
    CLIENT_TRAY_FACE_IDLE,
    CLIENT_TRAY_FACE_UNREACHABLE,
)
from neutrino_client.core.session import (
    CONNECTION_CONNECTED,
    CONNECTION_CONNECTING,
    CONNECTION_WAITING,
)

# Each connection's face, the worst first. Any other connection is idle.
FACES_WORST_FIRST = (
    (CONNECTION_WAITING, CLIENT_TRAY_FACE_UNREACHABLE),
    (CONNECTION_CONNECTING, CLIENT_TRAY_FACE_CONNECTING),
    (CONNECTION_CONNECTED, CLIENT_TRAY_FACE_CONNECTED),
)


def tray_face(hubs: list) -> str:
    """The face of the worst connection among the hubs.

    Args:
        hubs: The resident's hub rows, each with its ``connection``.

    Returns:
        A face of ``CLIENT_TRAY_FACES``, the idle one with no hub joined.
    """
    connections = {hub["connection"] for hub in hubs}
    for connection, face in FACES_WORST_FIRST:
        if connection in connections:
            return face
    return CLIENT_TRAY_FACE_IDLE
