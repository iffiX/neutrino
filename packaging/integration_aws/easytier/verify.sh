#!/usr/bin/env bash
# Prove from this machine that a node behind the campus firewall reaches the
# rendezvous node.
#
#   ./verify.sh
#
# Runs easytier-core here in the foreground for as long as it takes to answer,
# with no address and no DHCP, so no TUN device is created and nothing about
# this machine's networking changes. Prints what the peer and node views say,
# then stops, leaving nothing behind.

source "$(dirname "$0")/lane.sh"

RPC_PORT="${ET_RPC_PORT:-15899}"
LOCAL="$STATE/easytier"
[ -n "$(et_ip)" ] || { echo "no rendezvous node in state/; run up.sh first" >&2; exit 1; }
[ -f "$ET_NETWORK_FILE" ] || { echo "no network in state/; run up.sh first" >&2; exit 1; }

if [ ! -x "$LOCAL/easytier-core" ]; then
    echo "== fetching $ET_VERSION"
    mkdir -p "$LOCAL"
    curl -fsSL "$ET_URL" -o "$LOCAL/easytier.zip"
    echo "$ET_SHA256  $LOCAL/easytier.zip" | sha256sum -c -
    unzip -qo -j "$LOCAL/easytier.zip" \
        'easytier-linux-x86_64/easytier-core' 'easytier-linux-x86_64/easytier-cli' -d "$LOCAL"
    rm -f "$LOCAL/easytier.zip"
fi

echo "== joining $(et_network_name) through $(et_ip):$ET_PORT"
(
    # The name and the secret reach the process as its own environment, which
    # is the process's alone; a command line would be world-readable.
    set -a
    # shellcheck disable=SC1090
    . "$ET_NETWORK_FILE"
    set +a
    exec "$LOCAL/easytier-core" \
        --peers "tcp://$(et_ip):$ET_PORT" \
        --rpc-portal "127.0.0.1:$RPC_PORT" \
        --hostname "$(hostname)-verify" \
        --console-log-level warn
) > "$STATE/easytier_verify.log" 2>&1 &
CORE_PID=$!
trap 'kill "$CORE_PID" 2>/dev/null; wait "$CORE_PID" 2>/dev/null; true' EXIT

cli() { "$LOCAL/easytier-cli" -p "127.0.0.1:$RPC_PORT" -o json "$@" 2>/dev/null; }
peers() { cli peer; }

# `node` answers with the running config, network secret and all, so nothing
# from the cli reaches a terminal or a log unfiltered.
redact() {
    (
        set -a
        # shellcheck disable=SC1090
        . "$ET_NETWORK_FILE"
        set +a
        python3 -c 'import os, sys; sys.stdout.write(sys.stdin.read().replace(os.environ["ET_NETWORK_SECRET"], "<redacted>"))'
    )
}

for _ in $(seq 1 30); do
    if peers | grep -q neutrino-rendezvous; then
        break
    fi
    kill -0 "$CORE_PID" 2>/dev/null || { echo "the node stopped:" >&2; cat "$STATE/easytier_verify.log" >&2; exit 1; }
    sleep 2
done

echo "== peer"
peers | redact
echo "== node"
cli node | redact

peers | grep -q neutrino-rendezvous || { echo "the rendezvous node never appeared" >&2; exit 1; }
