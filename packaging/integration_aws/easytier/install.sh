#!/usr/bin/env bash
# Runs on the rendezvous node, as root, put there by up.sh.
#
#   install.sh <url> <sha256> <unit> <port>
#
# Installs the pinned release and the unit. The network name and secret are
# not arguments and are not written here: they arrive afterwards in
# /etc/easytier/network.env, which this only creates empty and root-only.

set -euo pipefail

URL="$1"
SHA256="$2"
UNIT="$3"
PORT="$4"

export DEBIAN_FRONTEND=noninteractive
apt-get -qq update
apt-get -qq install -y curl unzip

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
curl -fsSL "$URL" -o "$WORK/easytier.zip"
echo "$SHA256  $WORK/easytier.zip" | sha256sum -c -
# Only the two binaries a node needs; the archive also carries the web
# console, which this box has no business running.
unzip -qo -j "$WORK/easytier.zip" \
    'easytier-linux-x86_64/easytier-core' 'easytier-linux-x86_64/easytier-cli' \
    -d "$WORK"
install -m 755 "$WORK/easytier-core" "$WORK/easytier-cli" /usr/local/bin/

install -d -m 750 /etc/easytier
[ -f /etc/easytier/network.env ] || install -m 600 /dev/null /etc/easytier/network.env

# The secret stays out of the unit text and out of the command line: the
# binary reads ET_NETWORK_NAME and ET_NETWORK_SECRET from the environment,
# which is root-only, while a command line is world-readable in /proc.
cat > "/etc/systemd/system/$UNIT.service" <<EOF
[Unit]
Description=EasyTier rendezvous node for neutrino integration
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
EnvironmentFile=/etc/easytier/network.env
ExecStart=/usr/local/bin/easytier-core \\
    --private-mode true \\
    --relay-network-whitelist \${ET_NETWORK_NAME} \\
    --hostname neutrino-rendezvous \\
    -l tcp://0.0.0.0:$PORT \\
    -l udp://0.0.0.0:$PORT \\
    --rpc-portal 127.0.0.1:15888
Restart=always
RestartSec=3
LimitNOFILE=1048576

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
echo "installed $(/usr/local/bin/easytier-core --version)"
