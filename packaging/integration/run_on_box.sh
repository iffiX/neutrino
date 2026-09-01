#!/usr/bin/env bash
# Take one machine from nothing to a tested hub, and back.
#
#   run_on_box.sh <package file> [server|side_gateway|router]
#
# Run on the machine under test, as root. It records what the machine's
# network is, installs the package, sets the box up in the named mode, runs
# every check in this directory against it, resets, and checks again. The exit
# status is the number of phases that failed.
#
# The mode is the whole variable. A guest mode — server or side_gateway — has
# to leave the machine addressing itself, and that is what the footprint
# checks are for; router takes the machine over on purpose and skips them.
set -uo pipefail

PACKAGE="${1:?usage: run_on_box.sh <package file> [mode]}"
MODE="${2:-side_gateway}"
HERE="$(cd "$(dirname "$0")" && pwd)"
BEFORE=/tmp/neutrino_before.json
PASSWORD=integration-test-pw
FAILURES=0

phase() { printf '\n== %s ==\n' "$1"; }
ran() { [ "$1" -eq 0 ] || FAILURES=$((FAILURES + 1)); }

phase "the machine as it arrived"
python3 -c "import sys; sys.path.insert(0, '$HERE'); import machine_state; machine_state.write_snapshot('$BEFORE')"
INTERFACE="$(python3 -c "import sys; sys.path.insert(0, '$HERE'); import machine_state; print(machine_state.first_interface())")"
CIDR="$(ip -4 -o addr show dev "$INTERFACE" scope global | awk '{print $4; exit}')"
GATEWAY="$(ip -4 route show default | awk '{print $3; exit}')"
printf '  %-22s %s\n' "interface" "$INTERFACE $CIDR via $GATEWAY"

phase "install"
# The log is kept rather than discarded: an install that fails takes every
# check after it with it, and "it failed" on its own says nothing about why.
if command -v apt-get >/dev/null; then
    DEBIAN_FRONTEND=noninteractive apt-get -qq install -y "$PACKAGE" > /tmp/install.log 2>&1
elif command -v dnf >/dev/null; then
    dnf -q -y install epel-release > /tmp/install.log 2>&1
    dnf -q -y install "$PACKAGE" >> /tmp/install.log 2>&1
else
    pacman -U --noconfirm "$PACKAGE" > /tmp/install.log 2>&1
fi
if ! command -v nhub >/dev/null; then
    tail -12 /tmp/install.log | sed 's/^/  /'
    echo "the package did not install"
    exit 1
fi

phase "set up as a $MODE"
if [ "$MODE" = server ]; then
    cat > /tmp/answers.json <<JSON
{ "password": "$PASSWORD", "network": { "mode": "server" } }
JSON
elif [ "$MODE" = side_gateway ]; then
    cat > /tmp/answers.json <<JSON
{
  "password": "$PASSWORD",
  "network": {
    "mode": "side_gateway",
    "lan": ["$INTERFACE"],
    "address": "${CIDR%/*}",
    "prefix_len": ${CIDR#*/},
    "upstream_gateway": "$GATEWAY"
  }
}
JSON
else
    cat > /tmp/answers.json <<JSON
{
  "password": "$PASSWORD",
  "network": {
    "mode": "router",
    "wan": ["$INTERFACE"],
    "lan": []
  }
}
JSON
fi
nhub setup --yes --stdin < /tmp/answers.json > /tmp/setup.log 2>&1
ran $?

export NEUTRINO_PANEL_PASSWORD="$PASSWORD"
export NEUTRINO_BEFORE_STATE="$BEFORE"
export NEUTRINO_SETUP_MODE="$MODE"

phase "the machine is still its own"
python3 -m pytest "$HERE/test_install_footprint.py" -q
ran $?

phase "the panel, every page"
python3 -m pytest "$HERE" -q --ignore="$HERE/test_install_footprint.py" \
    --ignore="$HERE/test_reset_hands_back.py"
ran $?

phase "reset"
nhub reset all > /tmp/reset.log 2>&1
ran $?
python3 -m pytest "$HERE/test_reset_hands_back.py" -q
ran $?

echo
if [ "$FAILURES" -eq 0 ]; then
    echo "every phase passed"
else
    echo "$FAILURES phases failed"
fi
exit "$FAILURES"
