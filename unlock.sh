#!/bin/bash
# Clears the panel's login lockout and every fail2ban SSH ban.
#
# The lockout is a file on tmpfs; deleting it is the whole unlock, and the
# panel notices on the next login attempt without a restart.
set -e

if [ "$(id -u)" -ne 0 ]; then
    echo "run as root: sudo ./unlock.sh" >&2
    exit 1
fi

rm -f /run/neutrino/login_lockout.json
if command -v fail2ban-client >/dev/null 2>&1; then
    fail2ban-client unban --all >/dev/null 2>&1 || true
fi
echo "unlocked: panel login is open again and SSH bans are cleared"
