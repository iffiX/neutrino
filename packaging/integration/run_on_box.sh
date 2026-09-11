#!/usr/bin/env bash
# Take one machine from nothing to a tested hub, and back.
#
#   run_on_box.sh <package file> [server|side_gateway|router]
#
# Run on the machine under test, as root. It records what the machine's
# network is, installs the package, and then walks the box through the phases
# below. The exit status is the number of phases that failed.
#
# The order is the argument. A fresh install is measured against the machine
# it landed on, then handed back and measured again — both of those are about
# a box nobody has reconfigured. Only then is the box set up a second time and
# driven through every page, because that walk leaves it as a router with a
# served network and nothing after it could still ask what the machine was.
#
# The mode is the other variable. server and side_gateway have to leave the
# machine addressing itself, and that is what the footprint checks are for;
# router takes the machine over on purpose and skips them.
set -uo pipefail

PACKAGE="${1:?usage: run_on_box.sh <package file> [mode]}"
MODE="${2:-side_gateway}"
HERE="$(cd "$(dirname "$0")" && pwd)"
BEFORE=/tmp/neutrino_before.json
PASSWORD=integration-test-pw
VAULT_PASSPHRASE='Integration-Vault-Pw-16!'
FAILURES=0

# The phase header carries whether the box can still resolve a name. Every
# phase after the first can take that away — a mode change, a proxy pointed at
# a node that is not there — and a failure two phases later reads as the
# feature's fault unless the header already said the network had gone.
phase() {
    printf '\n== %s ==' "$1"
    if getent hosts deb.debian.org >/dev/null 2>&1; then printf '\n'; else
        printf '   [this box cannot resolve names]\n'
    fi
}
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

# The checks below are pytest, and a machine under test is a machine with
# nothing on it. Installed from the distribution rather than pip: the system
# Python is externally managed on every one of these.
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

write_answers() {
if [ "$MODE" = server ]; then
    cat > /tmp/answers.json <<JSON
{
  "password": "$PASSWORD",
  "vault_passphrase": "$VAULT_PASSPHRASE",
  "network": { "mode": "server" }
}
JSON
elif [ "$MODE" = side_gateway ]; then
    cat > /tmp/answers.json <<JSON
{
  "password": "$PASSWORD",
  "vault_passphrase": "$VAULT_PASSPHRASE",
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
  "vault_passphrase": "$VAULT_PASSPHRASE",
  "network": {
    "mode": "router",
    "wan": ["$INTERFACE"],
    "lan": []
  }
}
JSON
fi
}

export NEUTRINO_PANEL_PASSWORD="$PASSWORD"
export NEUTRINO_VAULT_PASSPHRASE="$VAULT_PASSPHRASE"
export NEUTRINO_BEFORE_STATE="$BEFORE"
export NEUTRINO_SETUP_MODE="$MODE"

phase "set up as a $MODE"
write_answers
nhub setup --stdin < /tmp/answers.json > /tmp/setup.log 2>&1
ran $?

phase "the machine is still its own"
python3 -m pytest "$HERE/test_install_footprint.py" -q
ran $?

# Before the reset, because it needs a box that is set up and working: what
# it measures is a package landing on one somebody is using.
phase "the same version, installed over itself"
NEUTRINO_PACKAGE="$PACKAGE" python3 -m pytest "$HERE/test_reinstall.py" -q
ran $?

phase "reset"
nhub reset all > /tmp/reset.log 2>&1
ran $?
python3 -m pytest "$HERE/test_reset_hands_back.py" -q
ran $?

phase "set up again, on the box that was just handed back"
write_answers
nhub setup --stdin < /tmp/answers.json > /tmp/setup2.log 2>&1
ran $?

# Last, and it leaves the box a router with a served network on whatever it
# has: every check after this one would be asking about a machine this walk
# has already reconfigured.
# Before the page walk, which leaves the box a router: an install is a
# package manager reaching the internet, and it needs the way out the box
# arrived with.
phase "installing a module through the panel"
python3 -m pytest "$HERE/test_install_a_module.py" -q
ran $?

phase "the panel, every page"
python3 -m pytest "$HERE" -q --ignore="$HERE/test_install_footprint.py" \
    --ignore="$HERE/test_reset_hands_back.py" \
    --ignore="$HERE/test_reinstall.py" --ignore="$HERE/test_mode_matrix.py" \
    --ignore="$HERE/test_install_a_module.py" \
    --ignore="$HERE/test_device_lifecycle.py" \
    --ignore="$HERE/test_agent_channel.py"
ran $?

# The two walks below rewire the box into a router serving the spare wire and
# drive a second machine, so nothing may still be asking about this one. The
# channel walk proves the pinned transport; the lifecycle walk proves the
# state machine that rides it. Both reach the second machine with
# id_lab beside them, and both fail naming it when it is not there.
phase "the agent channel, pinned end to end"
python3 -m pytest "$HERE/test_agent_channel.py" -q
ran $?

phase "the device lifecycle, end to end"
python3 -m pytest "$HERE/test_device_lifecycle.py" -q
ran $?

echo
if [ "$FAILURES" -eq 0 ]; then
    echo "every phase passed"
else
    echo "$FAILURES phases failed"
fi
exit "$FAILURES"
