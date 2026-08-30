#!/usr/bin/env bash
#
# One-shot installer for Neutrino Hub.
#
#   sudo ./install.sh
#
# Installs every dependency, writes the systemd units, renders the generated
# configuration from config/, and enables everything at boot. Re-running is
# safe: each step checks the system first and reports "already set" instead of
# repeating work.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -t 1 && -z ${NO_COLOR:-} ]]; then
    BOLD=$'\033[1m'; RED=$'\033[31m'; DIM=$'\033[2m'; RESET=$'\033[0m'
else
    BOLD=""; RED=""; DIM=""; RESET=""
fi

fail() {
    printf '\n  %sinstall failed:%s %s\n\n' "${RED}${BOLD}" "${RESET}" "$1" >&2
    exit 1
}

if [[ ${EUID} -ne 0 ]]; then
    fail "run this with sudo: sudo ./install.sh"
fi

PYTHON_BIN="$(command -v python3 || true)"
[[ -n ${PYTHON_BIN} ]] || fail "python3 is not installed"

PYTHON_VERSION="$(${PYTHON_BIN} -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
${PYTHON_BIN} -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
    || fail "python 3.11 or newer is required (found ${PYTHON_VERSION})"

printf '\n  %sNeutrino Hub%s  %sinstalling from %s%s\n' \
    "${BOLD}" "${RESET}" "${DIM}" "${REPO_ROOT}" "${RESET}"
printf '  %spython %s · %s%s\n' "${DIM}" "${PYTHON_VERSION}" "${PYTHON_BIN}" "${RESET}"

if ! ping -c1 -W3 1.1.1.1 >/dev/null 2>&1; then
    printf '  %swarning: no upstream connectivity; package installs may fail%s\n' \
        "${DIM}" "${RESET}"
fi

export PYTHONPATH="${REPO_ROOT}/hub${PYTHONPATH:+:${PYTHONPATH}}"
exec "${PYTHON_BIN}" -m neutrino_hub.cli.install "$@"
