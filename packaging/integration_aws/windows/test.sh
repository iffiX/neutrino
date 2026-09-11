#!/usr/bin/env bash
# The Windows client against the Linux hub: install the built msi, join with
# a link minted this minute, run the resident, and check both ends agree,
# the client by its own status and the hub by listing the person as online.

source "$(dirname "$0")/../common.sh"

MSI="$(state msi_name)"
[ -n "$MSI" ] || { echo "no msi built; run windows/push.sh first" >&2; exit 1; }
[ -n "$(hub_ip)" ] || { echo "no hub in state/; run up.sh first" >&2; exit 1; }

echo "== a fresh client link"
LINK="$(mint_client_link aws-windows)"
echo "$LINK" > "$STATE/client_link"

echo "== windows side"
scp "${SSH_OPTS[@]}" "$HERE/windows/test.ps1" "$WIN_USER@$(win_ip):C:/neutrino/" > /dev/null
ssh_win "powershell -ExecutionPolicy Bypass -File C:\\neutrino\\test.ps1 -Msi C:\\neutrino\\dist\\$MSI -Link '$LINK'"

echo
echo "== hub side"
wait_client_online aws-windows
echo "hub side passed"

echo "== quit"
ssh_win "\"C:\\Program Files\\Neutrino Client\\nclient.exe\" quit"
