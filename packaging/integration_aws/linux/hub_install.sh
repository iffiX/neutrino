#!/usr/bin/env bash
# Runs on the hub, as the Debian AMI's admin account. Installs the package
# that was pushed beside it, sets the box up as a server, and mints one
# enrollment link, which is the last line it prints.
#
# Environment: NEUTRINO_PANEL_PASSWORD, NEUTRINO_VAULT_PASSPHRASE, and
# NEUTRINO_DEVICE_NAME for what the joining machine will be called.

set -euo pipefail

PACKAGE="${1:-/tmp/hub.deb}"
PANEL="http://127.0.0.1:8080"

echo "== install"
sudo DEBIAN_FRONTEND=noninteractive apt-get -qq update
sudo DEBIAN_FRONTEND=noninteractive apt-get -qq install -y "$PACKAGE" > /tmp/install.log 2>&1 \
    || { tail -20 /tmp/install.log; exit 1; }
nhub --version

echo "== setup, server mode"
cat > /tmp/answers.json <<JSON
{
  "password": "$NEUTRINO_PANEL_PASSWORD",
  "vault_passphrase": "$NEUTRINO_VAULT_PASSPHRASE",
  "network": { "mode": "server" }
}
JSON
sudo nhub setup --yes --stdin < /tmp/answers.json > /tmp/setup.log 2>&1 \
    || { tail -30 /tmp/setup.log; exit 1; }
rm -f /tmp/answers.json
grep -E "panel is at|enroll" /tmp/setup.log || true

echo "== enrollment link"
COOKIES="$(mktemp)"
for _ in $(seq 1 30); do
    if curl -s -f -c "$COOKIES" -X POST "$PANEL/api/auth/login" \
        -H 'content-type: application/json' \
        -d "{\"password\":\"$NEUTRINO_PANEL_PASSWORD\"}" > /dev/null; then
        break
    fi
    sleep 1
done
LINK="$(curl -s -f -b "$COOKIES" -X POST "$PANEL/api/devices/enrollment" \
    -H 'content-type: application/json' \
    -d "{\"name\":\"${NEUTRINO_DEVICE_NAME:-}\"}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["link"])')"
rm -f "$COOKIES"
echo "$LINK"
