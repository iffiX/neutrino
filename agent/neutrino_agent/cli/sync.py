"""``nagent sync``: send this machine's report to the hub now.

The running service holds the socket, so the ask goes through its control
channel; the hub compares the report's hash with its own state and pushes
the state when they differ.
"""

from neutrino_agent.control import client
from neutrino_agent.cli.status import word_error
from neutrino_agent.exceptions import PlatformUnsupportedError
from neutrino_agent.platforms.detect import detect_platform

SYNC_UNBOUND = "this machine has joined no gateway"
SYNC_NO_SERVICE = "the agent service is not running; start it first"


def main() -> int:
    """Ask the running service to send a report now.

    Returns:
        Process exit status: 0 when the report went up, 1 otherwise.
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
        print("sent this machine's report to the hub")
        return 0
    print(word_error(reply))
    return 1
