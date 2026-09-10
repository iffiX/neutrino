"""``nagent sync``: ask the hub for this machine's desired state now.

The running service holds the socket, so the ask goes through its control
channel; the hub answers on the socket and the service applies what comes.
"""

from neutrino_agent.control import client
from neutrino_agent.cli.status import word_error
from neutrino_agent.exceptions import PlatformUnsupportedError
from neutrino_agent.platforms.detect import detect_platform

SYNC_UNBOUND = "this machine has joined no gateway"
SYNC_NO_SERVICE = "the agent service is not running; start it first"


def main() -> int:
    """Ask the running service to request the hub's state.

    Returns:
        Process exit status: 0 when the request went up, 1 otherwise.
    """
    try:
        socket_path = detect_platform().control_socket_path()
    except PlatformUnsupportedError:
        print(SYNC_NO_SERVICE)
        return 1
    try:
        status, reply = client.request(
            socket_path=socket_path, method="POST", path="/api/sync", body={}
        )
    except (OSError, ValueError):
        print(SYNC_NO_SERVICE)
        return 1
    if status == 200:
        if not reply.get("is_connected"):
            print(SYNC_UNBOUND)
            return 1
        print("asked the hub for this machine's state")
        return 0
    print(word_error(reply))
    return 1
