#!/usr/bin/env bash
# Walk one machine through every mode, every switch between them, and the
# proxy in each — then hand it back.
#
#   run_mode_matrix.sh <package file> [--client]
#
# Run on the machine under test, as root; `setup_vms.sh` builds the machine it
# wants — three ports, the last one served. --client says a client VM is
# listening on the served wire, which turns the lease check from a skip into
# an assertion. The exit status is the number of phases that failed.
set -uo pipefail

PACKAGE="${1:?usage: run_mode_matrix.sh <package file> [--client]}"
HERE="$(cd "$(dirname "$0")" && pwd)"
BEFORE=/tmp/neutrino_before.json
PASSWORD=integration-test-pw
FAILURES=0

phase() { printf '\n== %s ==\n' "$1"; }
ran() { [ "$1" -eq 0 ] || FAILURES=$((FAILURES + 1)); }

phase "the machine as it arrived"
python3 -c "import sys; sys.path.insert(0, '$HERE'); import machine_state; machine_state.write_snapshot('$BEFORE')"

phase "install"
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
if ! python3 -m pytest --version >/dev/null 2>&1; then
    if command -v apt-get >/dev/null; then
        DEBIAN_FRONTEND=noninteractive apt-get -qq install -y python3-pytest >> /tmp/install.log 2>&1
    elif command -v dnf >/dev/null; then
        dnf -q -y install python3-pytest >> /tmp/install.log 2>&1
    else
        pacman -S --noconfirm python-pytest >> /tmp/install.log 2>&1
    fi
fi
python3 -m pytest --version >/dev/null 2>&1 || { echo "no pytest on this box"; exit 1; }

phase "set up as a server"
cat > /tmp/answers.json <<JSON
{ "password": "$PASSWORD", "network": { "mode": "server" } }
JSON
nhub setup --yes --stdin < /tmp/answers.json > /tmp/setup.log 2>&1
ran $?

export NEUTRINO_PANEL_PASSWORD="$PASSWORD"
export NEUTRINO_BEFORE_STATE="$BEFORE"
if [ "${2:-}" = "--client" ]; then
    export NEUTRINO_LAN_CLIENT=1
fi

phase "the matrix: every mode, every switch, the proxy in each"
python3 -m pytest "$HERE/test_mode_matrix.py" -q
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
