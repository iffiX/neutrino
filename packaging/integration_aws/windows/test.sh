#!/usr/bin/env bash
# The Windows agent against the Linux hub: install the built msi, join with
# a link minted this minute, and check both ends agree, the agent by its own
# status and the hub by listing the device as online.
#
# The link is minted here rather than taken from push_hub.sh because a link
# lives five minutes: a join secret nobody pasted is not left lying around.

source "$(dirname "$0")/../common.sh"

MSI="$(state msi_name)"
[ -n "$MSI" ] || { echo "no msi built; run windows/push.sh first" >&2; exit 1; }
[ -n "$(hub_ip)" ] || { echo "no hub in state/; run up.sh first" >&2; exit 1; }

PANEL="http://$(hub_ip):$PANEL_PORT"
PASSWORD="$(state panel_password)"

# One signed-in session per call, the cookie jar deleted after.
panel_post() {
    local path="$1" body="$2" jar
    jar="$(mktemp)"
    curl -s -f -c "$jar" -X POST "$PANEL/api/auth/login" \
        -H 'content-type: application/json' -d "{\"password\":\"$PASSWORD\"}" -o /dev/null
    curl -s -f -b "$jar" -X POST "$PANEL$path" -H 'content-type: application/json' -d "$body"
    rm -f "$jar"
}
panel_get() {
    local path="$1" jar
    jar="$(mktemp)"
    curl -s -f -c "$jar" -X POST "$PANEL/api/auth/login" \
        -H 'content-type: application/json' -d "{\"password\":\"$PASSWORD\"}" -o /dev/null
    curl -s -f -b "$jar" "$PANEL$path"
    rm -f "$jar"
}

echo "== a fresh enrollment link"
LINK="$(panel_post /api/devices/enrollment '{"name":"aws-windows"}' \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["link"])')"
echo "$LINK" > "$STATE/enroll_link"

echo "== windows side"
scp "${SSH_OPTS[@]}" "$HERE/windows/test.ps1" "$WIN_USER@$(win_ip):C:/neutrino/" > /dev/null
ssh_win "powershell -ExecutionPolicy Bypass -File C:\\neutrino\\test.ps1 -Msi C:\\neutrino\\dist\\$MSI -Link '$LINK'"

echo
echo "== hub side"
# The join returns before the first beat lands, so the hub is given a minute
# to have heard one rather than being read the instant the agent said yes.
for _ in $(seq 1 12); do
    panel_get /api/devices > "$STATE/devices.json"
    if python3 - "$STATE/devices.json" <<'PY'
import json, sys

view = json.load(open(sys.argv[1]))
rows = view.get("devices", view if isinstance(view, list) else [])
found = [row for row in rows if row.get("name") == "aws-windows"]
if not found or not found[0].get("is_online"):
    sys.exit(1)
row = found[0]
print("  name={name}  online={online}  last_seen={seen}  address={address}".format(
    name=row["name"],
    online=row.get("is_online"),
    seen=row.get("last_seen"),
    address=row.get("ipv4_address"),
))
print("hub side passed")
PY
    then
        exit 0
    fi
    sleep 5
done
echo "the hub never listed aws-windows as online"
python3 -c 'import json,sys; print(json.dumps(json.load(open(sys.argv[1])), indent=1)[:1500])' "$STATE/devices.json"
exit 1
