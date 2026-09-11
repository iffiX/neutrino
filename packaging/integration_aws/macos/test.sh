#!/usr/bin/env bash
# The macOS client against the Linux hub: install the built pkg, join with a
# link minted this minute, run the resident, and check both ends agree.

source "$(dirname "$0")/../common.sh"

PKG="$(state pkg_name)"
[ -n "$PKG" ] || { echo "no pkg built; run macos/push.sh first" >&2; exit 1; }
[ -n "$(hub_ip)" ] || { echo "no hub in state/; run up.sh first" >&2; exit 1; }

echo "== a fresh client link"
LINK="$(mint_client_link aws-mac)"
echo "$LINK" > "$STATE/client_link_mac"

echo "== mac side"
scp "${SSH_OPTS[@]}" "$HERE/macos/test_remote.sh" "$MAC_USER@$(mac_ip):neutrino/" > /dev/null
ssh_mac "bash ~/neutrino/test_remote.sh ~/neutrino/dist/$PKG '$LINK'"

echo
echo "== hub side"
wait_client_online aws-mac
echo "hub side passed"

echo "== quit"
ssh_mac "nclient quit"
