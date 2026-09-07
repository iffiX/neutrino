#!/usr/bin/env bash
# The Windows agent against the Linux hub: install the built msi, join with
# a link minted this minute, and check both ends agree, the agent by its own
# status and the hub by listing the device as online.

source "$(dirname "$0")/../common.sh"

MSI="$(state msi_name)"
[ -n "$MSI" ] || { echo "no msi built; run windows/push.sh first" >&2; exit 1; }
[ -n "$(hub_ip)" ] || { echo "no hub in state/; run up.sh first" >&2; exit 1; }

echo "== a fresh enrollment link"
LINK="$(mint_link aws-windows)"
echo "$LINK" > "$STATE/enroll_link"

echo "== windows side"
scp "${SSH_OPTS[@]}" "$HERE/windows/test.ps1" "$WIN_USER@$(win_ip):C:/neutrino/" > /dev/null
ssh_win "powershell -ExecutionPolicy Bypass -File C:\\neutrino\\test.ps1 -Msi C:\\neutrino\\dist\\$MSI -Link '$LINK'"

echo
echo "== hub side"
wait_device_online aws-windows
echo "hub side passed"
