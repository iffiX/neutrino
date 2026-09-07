#!/usr/bin/env bash
# The macOS agent against the Linux hub: install the built pkg, join with a
# link minted this minute, and check both ends agree.

source "$(dirname "$0")/../common.sh"

PKG="$(state pkg_name)"
[ -n "$PKG" ] || { echo "no pkg built; run macos/push.sh first" >&2; exit 1; }
[ -n "$(hub_ip)" ] || { echo "no hub in state/; run up.sh first" >&2; exit 1; }

echo "== a fresh enrollment link"
LINK="$(mint_link aws-mac)"
echo "$LINK" > "$STATE/enroll_link"

echo "== mac side"
scp "${SSH_OPTS[@]}" "$HERE/macos/test_remote.sh" "$MAC_USER@$(mac_ip):neutrino/" > /dev/null
ssh_mac "bash ~/neutrino/test_remote.sh ~/neutrino/dist/$PKG '$LINK'"

echo
echo "== hub side"
wait_device_online aws-mac
echo "hub side passed"
