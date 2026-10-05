"""``nagent step-down``: drop to an account and run one program as it.

    nagent step-down --uid <uid> --gid <gid> -- <program> [arguments]

On macOS the agent runs this under ``launchctl asuser`` to put a program in
an account's session as that account: it sets the account's group as its
only supplementary group, then its group, then its user, and replaces
itself with the program. It opens no socket and reads no state; only root
can drop, and anyone else is refused by the system.
"""

import os
import sys

# What the verb exits with when the drop or the start fails, as a shell
# does for a program it cannot run.
STEP_DOWN_FAILED = 126


def main(*, uid: int, gid: int, argv: list) -> int:
    """Drop to the account and run the program in this process.

    Args:
        uid: The account's uid.
        gid: The account's primary group.
        argv: The program, by its full path, and its arguments.

    Returns:
        2 when no program is named, 126 when the drop or the start fails;
        nothing on success, since the program replaces this process.
    """
    if not argv:
        print("nagent step-down needs a program after --", file=sys.stderr)
        return 2
    if uid == 0:
        print("nagent step-down drops to an account, not to root", file=sys.stderr)
        return 2
    try:
        drop(uid, gid)
        os.execv(argv[0], argv)
    except OSError as error:
        print(f"nagent step-down: {argv[0]}: {error}", file=sys.stderr)
        return STEP_DOWN_FAILED
    return STEP_DOWN_FAILED


def drop(uid: int, gid: int) -> None:
    """Give up root for one account: groups, then group, then user.

    Args:
        uid: The account's uid.
        gid: The account's primary group, its only supplementary group too.

    Raises:
        OSError: When the system refuses a step.
    """
    os.setgroups([gid])
    os.setgid(gid)
    os.setuid(uid)
