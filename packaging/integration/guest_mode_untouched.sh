#!/usr/bin/env bash
# Install the hub on somebody else's machine and prove it stayed theirs.
#
#   guest_mode_untouched.sh <package file> [server|side_gateway]
#
# Run on the machine under test, as root. It records what the machine's
# network is, installs the package, sets the box up in a guest mode, and
# checks that every one of those facts is still what it was — then resets and
# checks again. Every check prints `ok` or `FAIL`, and the exit status is the
# number that failed.
#
# Both guest modes are worth running. `side_gateway` forwards for the devices
# that name it; `server` gives no port a role at all, and the thing to prove
# there is that a box which routes nothing polices nothing either.
#
# The same script is what the release matrix runs per distribution and what
# the lab runs in a VM: which manager a machine arrives running is the whole
# variable, and a guest mode is supposed to make it not matter. Why the guest
# modes touch nothing is in docs/standard/design/network.md.
set -u

PACKAGE="${1:?usage: guest_mode_untouched.sh <package file> [mode]}"
MODE="${2:-side_gateway}"
FAILURES=0
CONFIG_TREES="/etc/netplan /etc/NetworkManager/system-connections /etc/systemd/network /etc/network"

check() {
    if [ "$2" = "$3" ]; then
        printf '  ok    %-46s %s\n' "$1" "$2"
    else
        printf '  FAIL  %-46s got %s, wanted %s\n' "$1" "$2" "$3"
        FAILURES=$((FAILURES + 1))
    fi
}

report() { printf '  --    %-46s %s\n' "$1" "$2"; }

# systemctl exits non-zero for most of its answers, so only what it said is
# read and the status ignored.
active() { systemctl is-active "$1" 2>/dev/null | head -1; }
enabled() { systemctl is-enabled "$1" 2>/dev/null | head -1; }

# One line standing for a whole configuration tree: every file's name and
# checksum, so a mirror file regenerating itself shows up as loudly as a
# deletion. Missing trees hash to the same thing as empty ones, which is what
# "unchanged" means for a machine that never had them.
tree_state() {
    for tree in $CONFIG_TREES; do
        [ -d "$tree" ] || continue
        find "$tree" -type f -exec md5sum {} + 2>/dev/null | sort
    done | md5sum | cut -d' ' -f1
}

# Whether the input chain lets everything through on one interface. Anchored
# on the accept that closes the set, so a narrower rule naming the same
# interface is not read as the interface answering.
answers_on() {
    # Either spelling: nft prints a one-element anonymous set as a bare
    # match, so the braces are there with two interfaces and gone with one.
    nft list chain inet neutrino input 2>/dev/null |
        grep -cE "iifname (\{[^}]*\"$1\"[^}]*\}|\"$1\") accept$"
}

network_state() {
    ip -4 -o addr show scope global | awk '{print $2, $4}' | sort
    ip -4 route show default | sort
}

echo "== before =="
MANAGER=none
for unit in NetworkManager systemd-networkd networking dhcpcd connman netctl iwd; do
    if [ "$(active $unit)" = active ]; then
        MANAGER="$unit"
        report "managed by" "$unit"
    fi
done
[ "$MANAGER" = none ] && report "managed by" "nothing this knows about"

INTERFACE="$(ip -4 -o addr show scope global | awk '{print $2; exit}')"
CIDR="$(ip -4 -o addr show dev "$INTERFACE" scope global | awk '{print $4; exit}')"
GATEWAY="$(ip -4 route show default | awk '{print $3; exit}')"
BEFORE_TREES="$(tree_state)"
BEFORE_NETWORK="$(network_state)"
BEFORE_RESOLV="$(md5sum /etc/resolv.conf 2>/dev/null | cut -d' ' -f1)"
report "interface" "$INTERFACE $CIDR via $GATEWAY"

echo "== install and set up as a $MODE =="
# Kept rather than discarded: an install that fails takes every check after it
# with it, and "package installed: no" on its own says nothing about why.
if command -v apt-get >/dev/null; then
    DEBIAN_FRONTEND=noninteractive apt-get -qq install -y "$PACKAGE" > /tmp/install.log 2>&1
elif command -v dnf >/dev/null; then
    dnf -q -y install epel-release > /tmp/install.log 2>&1
    dnf -q -y install "$PACKAGE" >> /tmp/install.log 2>&1
else
    pacman -U --noconfirm "$PACKAGE" > /tmp/install.log 2>&1
fi
if ! command -v nhub >/dev/null; then
    echo "  --    the install said:"
    sed "s/^/          /" /tmp/install.log | tail -12
fi
check "package installed" "$(command -v nhub >/dev/null && echo yes || echo no)" yes

if [ "$MODE" = server ]; then
    # Nothing to answer: a server gives no port a job, and every port keeps
    # answering exactly as it did before the hub arrived.
    cat > /tmp/answers.json <<JSON
{
  "password": "integration-test-pw",
  "network": { "mode": "server" }
}
JSON
else
    cat > /tmp/answers.json <<JSON
{
  "password": "integration-test-pw",
  "network": {
    "mode": "side_gateway",
    "lan": ["$INTERFACE"],
    "address": "${CIDR%/*}",
    "prefix_len": ${CIDR#*/},
    "upstream_gateway": "$GATEWAY"
  }
}
JSON
fi
nhub setup --stdin < /tmp/answers.json > /tmp/setup.log 2>&1
check "setup exit" "$?" 0

echo "== the machine is still its own =="
if [ "$MANAGER" != none ]; then
    check "$MANAGER still running" "$(active $MANAGER)" active
    check "$MANAGER not masked" \
        "$([ "$(enabled $MANAGER)" = masked ] && echo masked || echo no)" no
fi
check "addresses and routes unchanged" \
    "$([ "$(network_state)" = "$BEFORE_NETWORK" ] && echo yes || echo no)" yes
check "network config trees unchanged" "$(tree_state)" "$BEFORE_TREES"
check "resolv.conf unchanged" \
    "$(md5sum /etc/resolv.conf 2>/dev/null | cut -d' ' -f1)" "$BEFORE_RESOLV"
check "nothing written into NetworkManager" \
    "$(ls /etc/NetworkManager/conf.d 2>/dev/null | grep -c neutrino)" 0
check "cloud-init left alone" \
    "$(ls /etc/cloud/cloud.cfg.d 2>/dev/null | grep -c neutrino)" 0
# The interface roles step must say so rather than silently doing nothing:
# a guest mode that reports "already as configured" reads like a machine that
# happened to match, not one that was never touched.
check "setup said the machine addresses its own" \
    "$(grep -q 'addresses its own' /tmp/setup.log && echo yes || echo no)" yes
# The engines an owner mode drives. A guest machine runs none of them: its
# addresses come from whatever put them there, and a supplicant or a lease
# client of ours on one of its radios is exactly the takeover this mode
# promises not to do.
check "no supplicant of ours running" \
    "$(systemctl list-units --state=active 'neutrino_hub_supplicant@*' --no-legend 2>/dev/null | wc -l)" 0
check "no lease client of ours running" \
    "$(systemctl list-units --state=active 'neutrino_hub_dhcpcd@*' --no-legend 2>/dev/null | wc -l)" 0
# Nothing was stood down, so there is no note saying anything was.
check "nothing was stood down" \
    "$([ -f /var/lib/neutrino/stood_down.json ] && echo yes || echo no)" no
# Named one by one rather than counting what is masked: a stock Ubuntu 24.04
# arrives with nine of its own masked — cryptdisks, hwclock, sudo.service,
# x11-common — and counting them says nothing about what the hub did.
masked_managers=0
for unit in NetworkManager systemd-networkd systemd-networkd.socket networking \
            dhcpcd connman netctl iwd systemd-resolved; do
    [ "$(enabled $unit)" = masked ] && masked_managers=$((masked_managers + 1))
done
check "no manager of this machine's was masked" "$masked_managers" 0

echo "== and the hub is doing its job on it =="
for unit in neutrino_hub_web neutrino_hub_router neutrino_hub_xray neutrino_hub_dnsmasq; do
    check "${unit#neutrino_hub_} running" "$(active $unit)" active
done
# The port this is being read over has to still answer. A guest mode that
# firewalls the one interface a machine has is a machine nobody can reach.
check "the interface it arrived on still answers" "$(answers_on "$INTERFACE")" 1
if [ "$MODE" = server ]; then
    # It routes nothing, so it is not the firewall for whatever docker or
    # libvirt forwards across it — and a drop policy there cuts them off
    # without saying so.
    check "forwarded traffic is left alone" \
        "$(nft list chain inet neutrino forward 2>/dev/null | grep -c 'policy accept')" 1
    check "nothing is masqueraded" \
        "$(nft list table inet neutrino 2>/dev/null | grep -c 'masquerade')" 0
else
    check "forwarding on" "$(sysctl -n net.ipv4.ip_forward)" 1
    check "masquerading for the devices that name it" \
        "$(nft list table inet neutrino 2>/dev/null | grep -q masquerade && echo yes || echo no)" yes
fi
check "still resolves" \
    "$(getent hosts github.com >/dev/null 2>&1 && echo yes || echo no)" yes
check "panel answers" \
    "$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 http://127.0.0.1:8080/)" 200

echo "== reset changes nothing either =="
nhub reset all > /tmp/reset.log 2>&1
check "reset exit" "$?" 0
if [ "$MANAGER" != none ]; then
    check "$MANAGER still running" "$(active $MANAGER)" active
fi
check "addresses and routes unchanged" \
    "$([ "$(network_state)" = "$BEFORE_NETWORK" ] && echo yes || echo no)" yes
check "network config trees unchanged" "$(tree_state)" "$BEFORE_TREES"
check "resolves after reset" \
    "$(getent hosts github.com >/dev/null 2>&1 && echo yes || echo no)" yes

echo
if [ "$FAILURES" -eq 0 ]; then
    echo "the machine is untouched"
else
    echo "$FAILURES checks failed"
fi
exit "$FAILURES"
