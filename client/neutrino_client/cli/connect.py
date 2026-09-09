"""``nclient connect``: join the hub an enrollment link names.

The enrollment runs here and writes the binding; a running resident adopts
it on its next poll. When none is running the hint says how to open one.
"""

import sys

from neutrino_client.cli import wording
from neutrino_client.core import enrollment


def main(link: str, *, is_forced: bool) -> int:
    """Join the hub the link names.

    Args:
        link: The enrollment link.
        is_forced: Replace an existing binding without asking.

    Returns:
        Process exit status.
    """
    link = link.strip()
    if not link:
        try:
            link = input("paste the enrollment link: ").strip()
        except EOFError:
            link = ""
    if not link:
        print(wording.word_code("link_missing"), file=sys.stderr)
        return 1
    bound_to = enrollment.load_config().get("gateway_url", "")
    if bound_to and not is_forced:
        answer = input(f"this person is bound to {bound_to}; replace it? [y/N] ")
        if answer.strip().lower() not in ("y", "yes"):
            print("nothing changed")
            return 1
    try:
        enrollment.enroll(link)
    except enrollment.EnrollmentError as error:
        print(wording.word_code(error.code, error.params), file=sys.stderr)
        return 1
    print(f"joined {enrollment.load_config().get('gateway_url', '')}")
    if not is_resident_running():
        print(wording.word_code("resident_not_running"), file=sys.stderr)
    return 0


def is_resident_running() -> bool:
    """Whether a resident answers on this person's control socket."""
    try:
        socket_path = wording.detect_platform().control_socket_path()
    except wording.PlatformUnsupportedError:
        return False
    try:
        status, _state = wording.client.request(
            socket_path=socket_path, method="GET", path="/api/state", timeout_s=2
        )
    except (OSError, ValueError):
        return False
    return status == 200
