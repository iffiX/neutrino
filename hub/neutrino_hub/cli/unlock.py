"""Clear the panel's login lockout and every fail2ban SSH ban.

    sudo nhub unlock

The lockout is a file on tmpfs, and the panel notices it is gone on the next
login attempt without a restart.
"""

import argparse
import os
import sys

from neutrino_hub.utils.subprocess_run import run
from neutrino_hub.web.constants import WEB_LOGIN_LOCKOUT_STATE_PATH

# --- config ---
UNLOCK_FAIL2BAN_BINARY = "fail2ban-client"


def main() -> int:
    """Open login again.

    Returns:
        Process exit status: 0 on success, 1 when not run as root.
    """
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args()

    if os.geteuid() != 0:
        print("error: unlock must run as root (sudo nhub unlock)", file=sys.stderr)
        return 1

    WEB_LOGIN_LOCKOUT_STATE_PATH.unlink(missing_ok=True)
    # Not every box runs fail2ban, and one that does not is already unlocked.
    run([UNLOCK_FAIL2BAN_BINARY, "unban", "--all"], is_checked=False)
    print("unlocked: panel login is open again and SSH bans are cleared")
    return 0


if __name__ == "__main__":
    sys.exit(main())
