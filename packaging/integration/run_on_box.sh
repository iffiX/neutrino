#!/usr/bin/env bash
# Take one machine from nothing to a tested hub, and back.
#
#   run_on_box.sh <package file> [server|side_gateway|router]
#
# The package file keeps its release name, neutrino-hub_<version>_<arch>.deb
# for a deb: `nhub update --package` reads the version off the name. Push it
# to /tmp/$(basename "$PACKAGE") rather than to a shorter name.
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
ran() {
    [ "$1" -eq 0 ] && return
    FAILURES=$((FAILURES + 1))
    printf '   [this phase failed: exit %s]\n' "$1"
}

# Turn the panel's HTTPS on or off through its own Settings route, and wait
# for the HTTPS port to serve or close. The first argument is the scheme
# wanted; both ports come from the box's settings.
PANEL_AUTHORITY=/etc/neutrino/hub/web/panel_tls/authority.pem
panel_scheme() {
    local wanted="$1" current verb jar base status ports http_port https_port
    current=$(python3 -c "import json; s=json.load(open('/etc/neutrino/hub/web/settings.json')); print('https' if s.get('is_https_enabled') else 'http')")
    [ "$current" = "$wanted" ] && return 0
    ports=$(python3 -c "import json; s=json.load(open('/etc/neutrino/hub/web/settings.json')); print(s.get('listen_port', 8080), s.get('https_listen_port', 443))")
    http_port=${ports% *}
    https_port=${ports#* }
    base="http://127.0.0.1:$http_port"
    [ "$current" = https ] && base="https://127.0.0.1:$https_port"
    verb=enable
    [ "$wanted" = http ] && verb=disable
    jar=$(mktemp)
    curl -s -f --cacert "$PANEL_AUTHORITY" -c "$jar" -X POST \
        "$base/api/hub/auth/login" \
        -H 'content-type: application/json' \
        -d "{\"password\":\"$PASSWORD\"}" -o /dev/null || return 1
    curl -s -f --cacert "$PANEL_AUTHORITY" -b "$jar" -X POST \
        "$base/api/hub/setting/https/$verb" -o /dev/null || return 1
    rm -f "$jar"
    # The panel answers loopback over plain HTTP whatever the switch says, so
    # the HTTPS port is what shows the switch: it serves once HTTPS is on, and
    # once it is off it sends a caller back to the HTTP port or is closed.
    for _ in $(seq 1 60); do
        status=$(curl -s -o /dev/null -w '%{http_code}' --cacert "$PANEL_AUTHORITY" \
            "https://127.0.0.1:$https_port/api/hub/display")
        [ "$wanted" = https ] && [ "$status" = 200 ] && return 0
        if [ "$wanted" = http ] && { [ "$status" = 301 ] || [ "$status" = 000 ]; }; then
            status=$(curl -s -o /dev/null -w '%{http_code}' \
                "http://127.0.0.1:$http_port/api/hub/display")
            [ "$status" = 200 ] && return 0
        fi
        sleep 1
    done
    echo "  the HTTP port never answered as $wanted wants"
    return 1
}

phase "the machine as it arrived"
python3 -c "import sys; sys.path.insert(0, '$HERE'); import machine_state; machine_state.write_snapshot('$BEFORE')"
INTERFACE="$(python3 -c "import sys; sys.path.insert(0, '$HERE'); import machine_state; print(machine_state.first_interface())")"
CIDR="$(ip -4 -o addr show dev "$INTERFACE" scope global | awk '{print $4; exit}')"
GATEWAY="$(ip -4 route show default | awk '{print $3; exit}')"
printf '  %-22s %s\n' "interface" "$INTERFACE $CIDR via $GATEWAY"

phase "install"
# The log is kept rather than discarded: an install that fails takes every
# check after it with it, and "it failed" on its own says nothing about why.
# A package beside SHA256SUMS and install.sh is installed the way a person
# installs it, through the one-command script; a package on its own goes in
# through the package manager.
ASSET_DIR="$(cd "$(dirname "$PACKAGE")" && pwd)"
if [ -f "$ASSET_DIR/SHA256SUMS" ] && [ -f "$ASSET_DIR/install.sh" ]; then
    if command -v dnf >/dev/null; then
        dnf -q -y install epel-release > /tmp/install.log 2>&1
    fi
    NEUTRINO_ASSET_DIR="$ASSET_DIR" sh "$ASSET_DIR/install.sh" hub \
        </dev/null >> /tmp/install.log 2>&1
elif command -v apt-get >/dev/null; then
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

# The same package again, this time through the unit the panel hands an
# update to: it installs, gates, and rolls back when the gate cannot pass.
phase "the hub updating itself"
NEUTRINO_PACKAGE="$PACKAGE" python3 -m pytest "$HERE/test_panel_update.py" -q
ran $?

# Once more with the panel on HTTPS: the gate reaches the panel by the scheme
# the settings say, trusting the hub's own authority.
phase "the hub updating itself, the panel on HTTPS"
panel_scheme https
ran $?
NEUTRINO_PACKAGE="$PACKAGE" python3 -m pytest "$HERE/test_panel_update.py" -q
ran $?
panel_scheme http
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
phase "the panel, every page"
python3 -m pytest "$HERE" -q --ignore="$HERE/test_install_footprint.py" \
    --ignore="$HERE/test_reset_hands_back.py" \
    --ignore="$HERE/test_reinstall.py" --ignore="$HERE/test_panel_update.py" \
    --ignore="$HERE/test_mode_matrix.py" \
    --ignore="$HERE/test_install_a_module.py" \
    --ignore="$HERE/test_device_lifecycle.py" \
    --ignore="$HERE/test_agent_removal.py" \
    --ignore="$HERE/test_agent_channel.py"
ran $?

# The three walks below rewire the box into a router serving the spare wire
# and drive a second machine, so nothing may still be asking about this one.
# The channel walk proves the pinned transport, the lifecycle walk the state
# machine that rides it, and the module walk what the two carry. All three
# reach the second machine with id_lab beside them, and all three fail naming
# it when it is not there.
phase "the agent channel, pinned end to end"
python3 -m pytest "$HERE/test_agent_channel.py" -q
ran $?

phase "the device lifecycle, end to end"
python3 -m pytest "$HERE/test_device_lifecycle.py" -q
ran $?

# Last of the three, because it is the slowest: a module installs on the
# second machine, which means that machine's own package manager reaching
# its own archive with the lines coming back up the channel.
phase "installing a module on a managed machine"
python3 -m pytest "$HERE/test_install_a_module.py" -q
ran $?

# The agent's package removed from the same machine and installed again:
# the modules' units go, the share stays and is reported once.
phase "removing the agent from a managed machine"
python3 -m pytest "$HERE/test_agent_removal.py" -q
ran $?

# The walks above leave the box a router whose resolver file is the hub's.
# A reset after them has to give the machine a resolver that answers.
phase "reset, after the box has been a router"
nhub reset all > /tmp/reset2.log 2>&1
ran $?
python3 -m pytest "$HERE/test_reset_hands_back.py" -q -k still_resolves
ran $?

echo
if [ "$FAILURES" -eq 0 ]; then
    echo "every phase passed"
else
    echo "$FAILURES phases failed"
fi
exit "$FAILURES"
