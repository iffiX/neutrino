#!/usr/bin/env bash
# Runs on the Mac. The installer is what ships, so it is what is tested:
# install it, see the LaunchDaemon load and run, see the agent answer as
# unenrolled, join the hub the link names, see it heartbeat.
#
#   bash test_remote.sh <pkg> <link>
#
# The binding is root's on macOS as on Linux, so status, connect and
# disconnect all run under sudo; ec2-user has it without a password.

set -uo pipefail

PKG="$1"
LINK="$2"
LABEL=com.neutrino.agent

step() { echo; echo "== $*"; }
fail() { echo "FAILED: $*"; exit 1; }

step "install $PKG"
sudo installer -pkg "$PKG" -target / || fail "installer refused the pkg"

step "the LaunchDaemon"
sudo launchctl print "system/$LABEL" | grep -E "state|pid|program" | head -5 \
    || fail "launchd does not know $LABEL"
command -v nagent > /dev/null || fail "no nagent on PATH after the install"

# Uninstalling keeps the binding, so a Mac from an earlier walk comes back
# already joined; the walk starts from unenrolled by leaving first.
if sudo nagent status > /dev/null 2>&1; then
    step "leave the hub a previous walk joined"
    sudo nagent disconnect || fail "nagent disconnect failed"
fi

step "status before joining (expects exit 1: unenrolled)"
sudo nagent status
[ $? -eq 1 ] || fail "nagent status did not exit 1"

step "join the hub"
sudo nagent connect "$LINK" --yes || fail "nagent connect failed"

step "status after joining (expects exit 0: heartbeat ok)"
for _ in $(seq 1 12); do
    if sudo nagent status; then
        echo "mac side passed"
        exit 0
    fi
    sleep 5
done
fail "the agent never reported a good heartbeat"
