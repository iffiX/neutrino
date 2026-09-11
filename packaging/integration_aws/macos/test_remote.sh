#!/usr/bin/env bash
# Runs on the Mac. The installer is what ships, so it is what is tested:
# install it, see the compiled client answer as unbound, join the hub the
# link names, run the resident, see it connected.
#
#   bash test_remote.sh <pkg> <link>
#
# The client is the person's, so nothing here runs under sudo but the
# installer itself.

set -uo pipefail

PKG="$1"
LINK="$2"

step() { echo; echo "== $*"; }
fail() { echo "FAILED: $*"; exit 1; }

step "a resident left by an earlier walk"
nclient quit > /dev/null 2>&1 || true

step "install $PKG"
sudo installer -pkg "$PKG" -target / || fail "installer refused the pkg"
[ -x "/Applications/Neutrino Client.app/Contents/MacOS/nclient" ] || fail "no app under /Applications"
command -v nclient > /dev/null || fail "no nclient on PATH after the install"

step "what landed"
find "/Applications/Neutrino Client.app" -type f | wc -l | sed 's/^/files /'
if find "/Applications/Neutrino Client.app" -name "*.py" -o -name "*.pyc" | grep -q .; then
    fail "the payload carries Python source or bytecode"
fi

# A removal keeps the binding, so a Mac from an earlier walk comes back
# already joined; the walk starts from unbound by leaving first.
if nclient status > /dev/null 2>&1; then
    step "leave the hub a previous walk joined"
    nclient disconnect || fail "nclient disconnect failed"
fi

step "status before joining (expects exit 1: unbound)"
nclient status
[ $? -eq 1 ] || fail "nclient status did not exit 1"

step "join the hub"
nclient connect "$LINK" --yes || fail "nclient connect failed"

step "run the resident"
nohup nclient gui --hidden > "$HOME/neutrino/resident.log" 2>&1 &

step "status after joining (expects exit 0: bound, running, connected)"
for _ in $(seq 1 12); do
    if nclient status; then
        echo "mac side passed"
        exit 0
    fi
    sleep 5
done
cat "$HOME/neutrino/resident.log"
fail "the client never reported itself connected"
