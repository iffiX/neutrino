# Sourced by every script here. One place for the account, the region, the
# names the resources carry, and where the run's state lives.
#
# Everything this harness creates is tagged and named `neutrino-integration`,
# so `down.sh` can find it all and so a glance at the console says what it is.

set -euo pipefail

export PATH="$HOME/.local/bin:$PATH"
export AWS_PROFILE="${AWS_PROFILE:-claude-1day}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"
export AWS_PAGER=""

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
STATE="$HERE/state"
NAME="neutrino-integration"

# Two keys because EC2 will not attach an ED25519 pair to a Windows AMI: the
# pair is what decrypts the Administrator password, and that path is RSA
# only. SSH is offered both and uses whichever the box took.
KEY_FILE="$STATE/id_aws"
RSA_KEY_FILE="$STATE/id_aws_rsa"
SSH_OPTS=(
    -i "$KEY_FILE"
    -i "$RSA_KEY_FILE"
    -o StrictHostKeyChecking=no
    -o UserKnownHostsFile=/dev/null
    -o LogLevel=ERROR
    -o ConnectTimeout=8
    -o ServerAliveInterval=15
)

# Each AMI's login: Debian's admin, the Windows built-in administrator (the
# account `administrators_authorized_keys` answers for), and the Mac's
# ec2-user.
HUB_USER=admin
WIN_USER=Administrator
MAC_USER=ec2-user

# What each script reads back from the `up.sh` that made it.
state() { cat "$STATE/$1" 2>/dev/null || true; }

hub_ip() { state hub_ip; }
win_ip() { state win_ip; }
mac_ip() { state mac_ip; }

ssh_hub() { ssh "${SSH_OPTS[@]}" "$HUB_USER@$(hub_ip)" "$@"; }
ssh_win() { ssh "${SSH_OPTS[@]}" "$WIN_USER@$(win_ip)" "$@"; }
ssh_mac() { ssh "${SSH_OPTS[@]}" "$MAC_USER@$(mac_ip)" "$@"; }
scp_hub() { scp "${SSH_OPTS[@]}" "$@"; }

# The tracked tree and nothing else: no .venv, no node_modules, no local
# dist/, so a rented box builds what a checkout would.
pack_tree() {
    (cd "$REPO" && git ls-files -z | tar --null -T - -czf "$STATE/src.tgz")
}

# The panel on the hub, one signed-in session per call.
panel_post() {
    local path="$1" body="$2" jar
    jar="$(mktemp)"
    curl -s -f -c "$jar" -X POST "http://$(hub_ip):$PANEL_PORT/api/auth/login" \
        -H 'content-type: application/json' \
        -d "{\"password\":\"$(state panel_password)\"}" -o /dev/null
    curl -s -f -b "$jar" -X POST "http://$(hub_ip):$PANEL_PORT$path" \
        -H 'content-type: application/json' -d "$body"
    rm -f "$jar"
}
panel_get() {
    local path="$1" jar
    jar="$(mktemp)"
    curl -s -f -c "$jar" -X POST "http://$(hub_ip):$PANEL_PORT/api/auth/login" \
        -H 'content-type: application/json' \
        -d "{\"password\":\"$(state panel_password)\"}" -o /dev/null
    curl -s -f -b "$jar" "http://$(hub_ip):$PANEL_PORT$path"
    rm -f "$jar"
}

# A link lives five minutes, so it is minted the moment a device is about to
# paste it and never earlier.
mint_link() {
    panel_post /api/devices/enrollment "{\"name\":\"$1\"}" \
        | python3 -c 'import json,sys; print(json.load(sys.stdin)["link"])'
}

# The join returns before the first beat lands, so the hub is given a minute
# to have heard one rather than being read the instant the agent said yes.
wait_device_online() {
    local name="$1" i
    for ((i = 0; i < 12; i++)); do
        panel_get /api/devices > "$STATE/devices.json"
        if python3 - "$STATE/devices.json" "$name" <<'PY'
import json, sys

view = json.load(open(sys.argv[1]))
rows = view.get("devices", view if isinstance(view, list) else [])
found = [row for row in rows if row.get("name") == sys.argv[2]]
if not found or not found[0].get("is_online"):
    sys.exit(1)
row = found[0]
print("  name={name}  online={online}  last_seen={seen}  address={address}".format(
    name=row["name"],
    online=row.get("is_online"),
    seen=row.get("last_seen"),
    address=row.get("ipv4_address"),
))
PY
        then
            return 0
        fi
        sleep 5
    done
    echo "the hub never listed $name as online" >&2
    python3 -c 'import json,sys; print(json.dumps(json.load(open(sys.argv[1])), indent=1)[:1500])' \
        "$STATE/devices.json" >&2
    return 1
}

# Waits until a host answers SSH, printing a dot per try. A Windows box takes
# minutes: OpenSSH is pulled from Windows Update by the user-data script.
wait_ssh() {
    local user="$1" host="$2" tries="${3:-90}"
    local i
    for ((i = 0; i < tries; i++)); do
        if ssh "${SSH_OPTS[@]}" "$user@$host" 'echo ok' 2>/dev/null | grep -q ok; then
            echo
            return 0
        fi
        printf '.'
        sleep 10
    done
    echo
    echo "$host never answered SSH" >&2
    return 1
}

# The panel's own port and the agent channel's, as the hub installs them.
PANEL_PORT=8080
AGENT_PORT=8443
