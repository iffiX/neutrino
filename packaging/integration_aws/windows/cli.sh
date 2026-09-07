#!/usr/bin/env bash
# nagent's whole verb tree on the Windows box, against the hub: the checks
# in packaging/integration/test_agent_cli.py, told where this run's machines
# are. The device must have joined (windows/test.sh) first.
#
#   windows/cli.sh [pytest args...]

source "$(dirname "$0")/../common.sh"

[ -n "$(win_ip)" ] || { echo "no windows box in state/; run up.sh first" >&2; exit 1; }
[ -n "$(hub_ip)" ] || { echo "no hub in state/; run up.sh first" >&2; exit 1; }

export NEUTRINO_PANEL_URL="http://$(hub_ip):$PANEL_PORT"
export NEUTRINO_PANEL_PASSWORD="$(state panel_password)"
export NEUTRINO_DEVICE_HOST="$(win_ip)"
export NEUTRINO_DEVICE_USER="$WIN_USER"
export NEUTRINO_DEVICE_KEY="$RSA_KEY_FILE"
export NEUTRINO_DEVICE_PLATFORM=windows
export NEUTRINO_DEVICE_NAME=aws-windows

cd "$REPO/packaging/integration"
exec python3 -m pytest test_agent_cli.py -q -p no:cacheprovider "$@"
