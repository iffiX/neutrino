#!/usr/bin/env bash
# Take a machine's network over, and give it back.
#
#   owner_mode_round_trip.sh <package file> <wan interface> <lan interface>
#
# Run on the machine under test, as root, on a box with two ports: the first is
# how it is reached, the second is what it becomes the router of. Every check
# prints `ok` or `FAIL`, and the exit status is the number that failed.
#
# What this is for is the half `guest_mode_untouched.sh` cannot reach. There
# the promise is that nothing changed; here it is that the hub drives the
# machine itself — its own supplicant, its own lease client, its own resolver —
# and that handing it back stops all of that without taking an address off
# anything. Why it is built that way is docs/standard/design/network.md.
set -u

PACKAGE="${1:?usage: owner_mode_round_trip.sh <package> <wan> <lan>}"
WAN="${2:?which interface is the uplink}"
LAN="${3:?which interface is the served network}"
LAN_ADDRESS=192.168.77.1
FAILURES=0

check() {
    if [ "$2" = "$3" ]; then
        printf '  ok    %-46s %s\n' "$1" "$2"
    else
        printf '  FAIL  %-46s got %s, wanted %s\n' "$1" "$2" "$3"
        FAILURES=$((FAILURES + 1))
    fi
}

report() { printf '  --    %-46s %s\n' "$1" "$2"; }

active() { systemctl is-active "$1" 2>/dev/null | head -1; }
enabled() { systemctl is-enabled "$1" 2>/dev/null | head -1; }
yesno() { if "$@" >/dev/null 2>&1; then echo yes; else echo no; fi; }

address_of() {
    ip -4 -o addr show dev "$1" scope global 2>/dev/null | awk '{print $4; exit}'
}

echo "== before =="
MANAGER=none
for unit in NetworkManager systemd-networkd networking dhcpcd connman iwd; do
    if [ "$(active $unit)" = active ]; then
        MANAGER="$unit"
        report "managed by" "$unit"
    fi
done
BEFORE_WAN="$(address_of "$WAN")"
report "uplink" "$WAN $BEFORE_WAN"
report "to serve on" "$LAN"

echo "== install and set up as a router =="
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
check "package installed" "$(yesno command -v nhub)" yes
# Nothing that manages a network may arrive with the package, whichever mode
# the box is about to be set up as.
check "installing started no manager of its own" \
    "$(systemctl list-units --state=active 'neutrino_hub_*' --no-legend 2>/dev/null | wc -l)" 0

# Whether the input chain lets everything through on one interface. Anchored
# on the accept that closes the set, so the narrower rule that lets a closed
# uplink take a lease is not read as the interface answering.
answers_on() {
    # Either spelling: nft prints a one-element anonymous set as a bare
    # match, so the braces are there with two interfaces and gone with one.
    nft list chain inet neutrino input 2>/dev/null |
        grep -cE "iifname (\{[^}]*\"$1\"[^}]*\}|\"$1\") accept$"
}

cat > /tmp/answers.json <<JSON
{
  "password": "integration-test-pw",
  "network": {
    "mode": "router",
    "wan": ["$WAN"],
    "lan": ["$LAN"],
    "address": "$LAN_ADDRESS",
    "prefix_len": 24
  }
}
JSON
nhub setup --stdin < /tmp/answers.json > /tmp/setup.log 2>&1
check "setup exit" "$?" 0

echo "== the hub is driving it =="
if [ "$MANAGER" != none ]; then
    check "$MANAGER stopped" "$(active $MANAGER)" inactive
    # Masked, not merely disabled: systemd-networkd is TriggeredBy its own
    # socket and comes straight back from a disable.
    check "$MANAGER masked" "$(enabled $MANAGER)" masked
    check "what was stood down is written down" \
        "$(yesno test -s /var/lib/neutrino/stood_down.json)" yes
fi
check "the served network has its address" "$(address_of "$LAN")" "$LAN_ADDRESS/24"
check "the uplink still has one" "$(yesno test -n "$(address_of "$WAN")")" yes
check "a lease client is running on the uplink" \
    "$(active neutrino_hub_dhcpcd@$WAN.service)" active
check "the box resolves at its own dnsmasq" \
    "$(grep -c "nameserver $LAN_ADDRESS" /etc/resolv.conf)" 1
check "resolv.conf is a file, not somebody's symlink" \
    "$(yesno test -f /etc/resolv.conf -a ! -L /etc/resolv.conf)" yes
for unit in neutrino_hub_web neutrino_hub_router neutrino_hub_xray neutrino_hub_dnsmasq; do
    check "${unit#neutrino_hub_} running" "$(active $unit)" active
done
check "forwarding on" "$(sysctl -n net.ipv4.ip_forward)" 1
check "masquerading out of the uplink" \
    "$(yesno grep -q masquerade <(nft list table inet neutrino 2>/dev/null))" yes
# The served network answers because that is where the panel, the leases and
# DNS are reached; the uplink does not, because remote access arrives over the
# overlay and opening an uplink opens everything.
check "the served network answers" "$(answers_on "$LAN")" 1
check "the uplink answers nothing" "$(answers_on "$WAN")" 0
check "the uplink can still take a lease" \
    "$(nft list chain inet neutrino input 2>/dev/null | grep -c "\"$WAN\".*dport 68")" 1
check "still resolves" "$(yesno getent hosts github.com)" yes
check "panel answers" \
    "$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 http://127.0.0.1:8080/)" 200

echo "== and hands it back =="
BEFORE_RESET_LAN="$(address_of "$LAN")"
nhub reset all > /tmp/reset.log 2>&1
check "reset exit" "$?" 0
if [ "$MANAGER" != none ]; then
    check "$MANAGER unmasked" \
        "$([ "$(enabled $MANAGER)" = masked ] && echo masked || echo no)" no
    check "$MANAGER running again" "$(active $MANAGER)" active
    check "the note of what was stood down is gone" \
        "$(yesno test -e /var/lib/neutrino/stood_down.json)" no
fi
check "no lease client of ours left" \
    "$(systemctl list-units --state=active 'neutrino_hub_dhcpcd@*' --no-legend 2>/dev/null | wc -l)" 0
check "no supplicant of ours left" \
    "$(systemctl list-units --state=active 'neutrino_hub_supplicant@*' --no-legend 2>/dev/null | wc -l)" 0
# The one that locks somebody out of a box they are holding. A reset stops what
# the hub started; it does not un-configure an interface.
#
# The uplink is checked for an address rather than for the same address: the
# manager that is started again takes its own lease, under its own client
# identity, and lands wherever that lease was — usually the address the machine
# held before the hub ever ran. What is being pinned here is that the reset
# leaves the interface addressed by somebody.
check "the uplink still holds an address" \
    "$(yesno test -n "$(address_of "$WAN")")" yes
check "the served network kept its address" "$(address_of "$LAN")" "$BEFORE_RESET_LAN"
check "resolves after reset" "$(yesno getent hosts github.com)" yes

echo
if [ "$FAILURES" -eq 0 ]; then
    echo "round trip clean"
else
    echo "$FAILURES checks failed"
fi
exit "$FAILURES"
