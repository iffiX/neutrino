#!/usr/bin/env bash
# Install the hub on the AWS box and keep its enrollment link.
#
#   ./push_hub.sh [path/to/neutrino-hub_0.1.0_amd64.deb]
#
# The panel password and vault passphrase are generated once into state/ and
# reused, so a second run against the same box logs into the same panel.

source "$(dirname "$0")/../common.sh"

#   linux/push_hub.sh --upgrade [package]   a newer build over a set-up hub:
#                                            installs and applies, no setup
MODE=install
if [ "${1:-}" = "--upgrade" ]; then
    MODE=upgrade
    shift
fi
PACKAGE="${1:-$REPO/dist/neutrino-hub_0.1.0_amd64.deb}"
[ -f "$PACKAGE" ] || { echo "no package at $PACKAGE" >&2; exit 1; }
[ -n "$(hub_ip)" ] || { echo "no hub in state/; run up.sh first" >&2; exit 1; }

if [ "$MODE" = upgrade ]; then
    echo "== upgrading the hub on $(hub_ip)"
    scp_hub "$PACKAGE" "$HUB_USER@$(hub_ip):/tmp/hub.deb"
    ssh_hub 'sudo DEBIAN_FRONTEND=noninteractive apt-get -qq install -y /tmp/hub.deb > /tmp/upgrade.log 2>&1 || tail -20 /tmp/upgrade.log; systemctl is-active neutrino_hub_web'
    exit 0
fi

secret() {
    [ -f "$STATE/$1" ] || python3 -c 'import secrets; print(secrets.token_urlsafe(18))' > "$STATE/$1"
    cat "$STATE/$1"
}
PASSWORD="$(secret panel_password)"
PASSPHRASE="$(secret vault_passphrase)"

echo "== pushing $(basename "$PACKAGE") to $(hub_ip)"
scp_hub "$PACKAGE" "$HUB_USER@$(hub_ip):/tmp/hub.deb"
scp_hub "$HERE/linux/hub_install.sh" "$HUB_USER@$(hub_ip):/tmp/hub_install.sh"

echo "== installing"
LINK="$(ssh_hub "NEUTRINO_PANEL_PASSWORD='$PASSWORD' NEUTRINO_VAULT_PASSPHRASE='$PASSPHRASE' \
    NEUTRINO_DEVICE_NAME='aws-windows' bash /tmp/hub_install.sh /tmp/hub.deb" | tee /dev/stderr | tail -1)"
case "$LINK" in
    neutrino://enroll/*) ;;
    *) echo "no enrollment link came back" >&2; exit 1 ;;
esac
echo "$LINK" > "$STATE/enroll_link"

echo
echo "panel     http://$(hub_ip):$PANEL_PORT  (password in state/panel_password)"
echo "link      state/enroll_link"
