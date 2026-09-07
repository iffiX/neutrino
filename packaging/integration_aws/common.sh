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

# The Debian AMI's login; the Windows one is the built-in administrator, which
# is the account `administrators_authorized_keys` answers for.
HUB_USER=admin
WIN_USER=Administrator

# What each script reads back from `up.sh`.
state() { cat "$STATE/$1" 2>/dev/null || true; }

hub_ip() { state hub_ip; }
win_ip() { state win_ip; }

ssh_hub() { ssh "${SSH_OPTS[@]}" "$HUB_USER@$(hub_ip)" "$@"; }
ssh_win() { ssh "${SSH_OPTS[@]}" "$WIN_USER@$(win_ip)" "$@"; }
scp_hub() { scp "${SSH_OPTS[@]}" "$@"; }

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
