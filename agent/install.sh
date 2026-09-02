#!/usr/bin/env bash
#
# One-shot installer for the neutrino_agent agent.
#
#   sudo ./install.sh                        # then join from the agent's page
#   sudo ./install.sh --enroll '<link>'      # join right away
#   sudo ./install.sh --gateway-url <url> --token <token>
#   sudo ./install.sh --gateway-url <url> --token-stdin   # token on stdin, first line
#
# The gateway runs this for you from its Devices tab when it can reach the
# machine over SSH. When it cannot — a laptop, anything behind someone else's
# NAT — install with no arguments and paste an enrollment link into the
# agent's own page at http://127.0.0.1:8765. Re-running is safe: it overwrites
# the installed copy and restarts the service.

set -euo pipefail

# Colour only when someone is watching a terminal. The gateway drives this
# script over SSH into a plain log panel, where escape codes are just noise;
# NO_COLOR is honoured as well (https://no-color.org).
if [[ -t 1 && -z ${NO_COLOR:-} ]]; then
    BOLD=$'\033[1m'; DIM=$'\033[2m'; GREEN=$'\033[32m'; RED=$'\033[31m'
    BLUE=$'\033[36m'; YELLOW=$'\033[33m'; RESET=$'\033[0m'
else
    BOLD=""; DIM=""; GREEN=""; RED=""; BLUE=""; YELLOW=""; RESET=""
fi

INSTALL_DIR="/opt/neutrino_agent"
CONFIG_DIR="/etc/neutrino_agent"
UNIT_NAME="neutrino_agent.service"
TOTAL_STEPS=8
STEP=0

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GATEWAY_URL=""
TOKEN=""
ENROLL_LINK=""
IS_TOKEN_ON_STDIN=0

step() {
    STEP=$((STEP + 1))
    printf '  %s[%d/%d]%s %s ... ' "${BLUE}" "${STEP}" "${TOTAL_STEPS}" "${RESET}" "$1"
}
ok()      { printf '%sOK%s%s\n'   "${GREEN}"  "${RESET}" "${1:+ ${DIM}($1)${RESET}}"; }
skipped() { printf '%salready set%s%s\n' "${YELLOW}" "${RESET}" "${1:+ ${DIM}($1)${RESET}}"; }
fail() {
    printf '%sFAILED%s\n\n      %s%s%s\n\n' "${RED}" "${RESET}" "${RED}" "$1" "${RESET}" >&2
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --gateway-url) GATEWAY_URL="$2"; shift 2 ;;
        --token)       TOKEN="$2";       shift 2 ;;
        --token-stdin) IS_TOKEN_ON_STDIN=1; shift ;;
        --enroll)      ENROLL_LINK="$2"; shift 2 ;;
        -h|--help)     sed -n '2,11p' "${BASH_SOURCE[0]}"; exit 0 ;;
        *)             fail "unknown option: $1" ;;
    esac
done

# The token stays off the command line; --token-stdin wins over --token.
if [[ ${IS_TOKEN_ON_STDIN} -eq 1 ]]; then
    IFS= read -r TOKEN || true
    [[ -n ${TOKEN} ]] || fail "--token-stdin was given but stdin carried no token"
fi

[[ ${EUID} -eq 0 ]]     || fail "run this with sudo: sudo ./install.sh ..."
[[ -n ${GATEWAY_URL} ]] || fail "--gateway-url is required"
[[ -n ${TOKEN} ]]       || fail "--token is required"

printf '\n  %sneutrino_agent%s  %sinstalling to %s%s\n\n' \
    "${BOLD}" "${RESET}" "${DIM}" "${INSTALL_DIR}" "${RESET}"

step "Checking python3"
PYTHON_BIN="$(command -v python3 || true)"
[[ -n ${PYTHON_BIN} ]] || fail "python3 is not installed (apt-get install -y python3)"
PYTHON_VERSION="$(${PYTHON_BIN} -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
${PYTHON_BIN} -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' \
    || fail "python 3.9 or newer is required (found ${PYTHON_VERSION})"
ok "python ${PYTHON_VERSION}"

step "Checking systemd"
command -v systemctl >/dev/null 2>&1 || fail "systemd is required"
ok

step "Installing agent files"
mkdir -p "${INSTALL_DIR}"
rm -rf "${INSTALL_DIR}/neutrino_agent" "${INSTALL_DIR}/scripts"
cp -r "${SOURCE_DIR}/neutrino_agent" "${INSTALL_DIR}/"
ok "$(find "${INSTALL_DIR}" -name '*.py' | wc -l) files"

step "Writing ${CONFIG_DIR}/agent.json"
mkdir -p "${CONFIG_DIR}"
if [[ -n ${GATEWAY_URL} && -n ${TOKEN} ]]; then
    cat > "${CONFIG_DIR}/agent.json" <<EOF
{
  "gateway_url": "${GATEWAY_URL}",
  "token": "${TOKEN}"
}
EOF
    chmod 600 "${CONFIG_DIR}/agent.json"
    ok "gateway ${GATEWAY_URL}"
elif [[ -f ${CONFIG_DIR}/agent.json ]]; then
    skipped "keeping the gateway this machine already joined"
else
    printf '{}\n' > "${CONFIG_DIR}/agent.json"
    chmod 600 "${CONFIG_DIR}/agent.json"
    ok "no gateway yet"
fi

step "Adding the desktop launcher"
if [[ -d ${SOURCE_DIR}/desktop ]]; then
    install -Dm644 "${SOURCE_DIR}/desktop/neutrino_agent.png" \
        /usr/share/icons/hicolor/256x256/apps/neutrino_agent.png
    install -Dm644 "${SOURCE_DIR}/desktop/neutrino_agent_48.png" \
        /usr/share/icons/hicolor/48x48/apps/neutrino_agent.png
    install -Dm644 "${SOURCE_DIR}/desktop/neutrino_agent.desktop" \
        /usr/share/applications/neutrino_agent.desktop
    # Best effort: a headless box has neither cache to update.
    gtk-update-icon-cache -f /usr/share/icons/hicolor >/dev/null 2>&1 || true
    update-desktop-database /usr/share/applications >/dev/null 2>&1 || true
    ok "search for Neutrino Agent"
else
    skipped "no desktop files in this package"
fi

step "Installing the systemd unit"
if cmp -s "${SOURCE_DIR}/systemd/${UNIT_NAME}" "/etc/systemd/system/${UNIT_NAME}"; then
    skipped "unchanged"
else
    cp "${SOURCE_DIR}/systemd/${UNIT_NAME}" "/etc/systemd/system/${UNIT_NAME}"
    systemctl daemon-reload
    ok
fi

step "Joining a gateway"
if [[ -n ${ENROLL_LINK} ]]; then
    PYTHONPATH="${INSTALL_DIR}" "${PYTHON_BIN}" -c \
        "from neutrino_agent import enrollment; \
         print(enrollment.enroll('''${ENROLL_LINK}''')['gateway_url'])" \
        >/tmp/neutrino_agent_check 2>&1 \
        || { printf '%sFAILED%s\n\n' "${RED}" "${RESET}" >&2
             sed 's/^/      /' /tmp/neutrino_agent_check >&2
             fail "that enrollment link was not accepted"; }
    ok "joined $(cat /tmp/neutrino_agent_check)"
elif PYTHONPATH="${INSTALL_DIR}" "${PYTHON_BIN}" \
        -m neutrino_agent.cli status >/tmp/neutrino_agent_check 2>&1; then
    ok "heartbeat accepted"
else
    skipped "join from http://127.0.0.1:8765"
fi

step "Enabling and starting the service"
systemctl enable "${UNIT_NAME}" >/dev/null 2>&1
systemctl restart "${UNIT_NAME}"
ok "$(systemctl is-active "${UNIT_NAME}")"

printf '\n  %sInstalled.%s ' "${BOLD}" "${RESET}"
if PYTHONPATH="${INSTALL_DIR}" "${PYTHON_BIN}" -c \
        'from neutrino_agent import enrollment; raise SystemExit(0 if enrollment.is_configured() else 1)'
then
    printf 'The device appears in the gateway panel within a few seconds.\n'
else
    printf 'Open %shttp://127.0.0.1:8765%s and paste the gateway'"'"'s link to join.\n' \
        "${BLUE}" "${RESET}"
fi
printf '  %sLogs: journalctl -u %s -f%s\n\n' "${DIM}" "${UNIT_NAME}" "${RESET}"
