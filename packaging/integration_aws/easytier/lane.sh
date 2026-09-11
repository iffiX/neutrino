# Sourced by every script in this lane. The rendezvous node's names, the
# pinned release, and where its network credentials live.
#
# The node is a middle box and nothing else: it takes no address on the
# virtual network and creates no TUN device, so all it does for a network is
# introduce two members of it that cannot accept an inbound connection.

source "$(dirname "${BASH_SOURCE[0]}")/../common.sh"

LANE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

ET_ROLE=easytier
ET_NAME="$NAME-$ET_ROLE"
ET_USER=admin
ET_TYPE="${ET_TYPE:-t3.nano}"
ET_ZONE="${ET_ZONE:-us-east-1a}"

# The release both ends run. Upstream publishes no checksum file, so the hash
# is ours, taken from the asset we read; the install refuses any other bytes.
ET_VERSION=v2.6.4
ET_URL="https://github.com/EasyTier/EasyTier/releases/download/$ET_VERSION/easytier-linux-x86_64-$ET_VERSION.zip"  # scan: allow
ET_SHA256=61b659eaedba658fa66fe47d17e1426cdd77e5d02fa15fed447bb4357c09dfd6

# The default listeners, stated rather than assumed: tcp and udp on one port.
ET_PORT=11010
ET_UNIT=easytier_rendezvous

# The network name and secret, generated here and never on the node. Mode
# 0600 in state/, which is gitignored.
ET_NETWORK_FILE="$STATE/easytier_network"

et_id() { state easytier_id; }
et_ip() { state easytier_ip; }
ssh_et() { ssh "${SSH_OPTS[@]}" "$ET_USER@$(et_ip)" "$@"; }
scp_et() { scp "${SSH_OPTS[@]}" "$@"; }

# The name is public, the secret is not; nothing here ever reads the second
# line out of the file.
et_network_name() { sed -n 's/^ET_NETWORK_NAME=//p' "$ET_NETWORK_FILE"; }
ET_PEER_CIDRS="172.58.0.0/15"   # scan: allow  T-Mobile mobile egress, the Windows test machine
