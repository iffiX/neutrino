"""Staging the hub's own package and handing its install to the system.

The package's maintainer script restarts the panel, which is the process that
would be running the install, so the panel only stages: it makes room, takes
the package down and checks its digest, keeps the running version's package
beside it as the rollback, writes the script below and starts it apart from
itself: a transient systemd unit on Linux, a job given to ``launchctl
submit`` on macOS, a PowerShell with no window on Windows. The script
installs, reads the version installed, holds a health gate, and installs the
rollback when the box left the version it started from and the target does
not come up; every turn it takes is a line in the state file's steps, which
the panel reads when it is back.
"""

import hashlib
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Callable

import psutil

from neutrino_hub import HUB_PACKAGE_ASSET
from neutrino_hub.exceptions import AgentArtifactFetchError, HubUpdateError
from neutrino_hub.modules.devices.agent_package import (
    AGENT_PACKAGE_FAMILY_OF_OS,
    AGENT_PACKAGE_FAMILY_OF_PLATFORM,
    AgentPackageCache,
)
from neutrino_hub.modules.devices.constants import AGENT_PACKAGE_CACHE_DIR
from neutrino_hub.modules.hub_update.constants import (
    HUB_UPDATE_AGENT_COMMAND,
    HUB_UPDATE_AGENT_COMMAND_DARWIN,
    HUB_UPDATE_AGENT_COMMAND_WINDOWS,
    HUB_UPDATE_AGENT_PATTERNS,
    HUB_UPDATE_AGENT_START_S,
    HUB_UPDATE_AGENT_UPDATE_UNIT,
    HUB_UPDATE_AGENT_WAIT_S,
    HUB_UPDATE_CREATION_FLAGS_WINDOWS,
    HUB_UPDATE_FAMILY_OF_OS,
    HUB_UPDATE_JOB_DARWIN,
    HUB_UPDATE_MSI_BUSY_CODE,
    HUB_UPDATE_MSI_INSTALLED_CODES,
    HUB_UPDATE_MSI_MUTEX,
    HUB_UPDATE_NHUB_DARWIN,
    HUB_UPDATE_NHUB_NAME_WINDOWS,
    HUB_UPDATE_PID_NAME,
    HUB_UPDATE_PLIST_DARWIN,
    HUB_UPDATE_PROGRAM_FILES_DEFAULT,
    HUB_UPDATE_SCRIPT_NAME_WINDOWS,
    HUB_UPDATE_SERVICE_DARWIN,
    HUB_UPDATE_SERVICE_WINDOWS,
    HUB_UPDATE_DIR_MODE,
    HUB_UPDATE_DIR_NAME,
    HUB_UPDATE_DNF_LOCK_TEXT,
    HUB_UPDATE_FETCH_LIMIT_BYTES,
    HUB_UPDATE_FETCH_TIMEOUT_S,
    HUB_UPDATE_GATE_POLL_S,
    HUB_UPDATE_GATE_TIMEOUT_S,
    HUB_UPDATE_GATE_UNITS,
    HUB_UPDATE_HEADERS,
    HUB_UPDATE_HEALTH_PATH,
    HUB_UPDATE_LAUNCH_TIMEOUT_S,
    HUB_UPDATE_LOCK_TIMEOUT_S,
    HUB_UPDATE_LOG_NAME,
    HUB_UPDATE_LOW_MEMORY_BYTES,
    HUB_UPDATE_MEMINFO_PATH,
    HUB_UPDATE_OUTPUT_LIMIT_BYTES,
    HUB_UPDATE_PACKAGE_MODE,
    HUB_UPDATE_PACMAN_LOCK_PATH,
    HUB_UPDATE_PANEL_AUTHORITY_PATH,
    HUB_UPDATE_PANEL_SETTINGS_PATH,
    HUB_UPDATE_PANEL_UNIT,
    HUB_UPDATE_REASON_GATE_FAILED,
    HUB_UPDATE_REASON_INSTALL_FAILED,
    HUB_UPDATE_REASON_LAUNCH_FAILED,
    HUB_UPDATE_REASON_PACKAGE_FETCH_FAILED,
    HUB_UPDATE_REASON_PACKAGE_MISSING,
    HUB_UPDATE_REASON_PACKAGE_NAME_MISMATCH,
    HUB_UPDATE_REASON_PACKAGE_SHA256_MISMATCH,
    HUB_UPDATE_REASON_ROLLBACK_FETCH_FAILED,
    HUB_UPDATE_REASON_SPACE_SHORT,
    HUB_UPDATE_RELEASE_REUSE_S,
    HUB_UPDATE_SCRIPT_MODE,
    HUB_UPDATE_SCRIPT_NAME,
    HUB_UPDATE_SHED_UNITS,
    HUB_UPDATE_STAGE_FAILED,
    HUB_UPDATE_STAGE_INSTALLED,
    HUB_UPDATE_STAGE_INSTALLING,
    HUB_UPDATE_STAGE_ROLLED_BACK,
    HUB_UPDATE_STAGE_ROLLING_BACK,
    HUB_UPDATE_STAGES_IN_UNIT,
    HUB_UPDATE_STAGES_SETTLED,
    HUB_UPDATE_STATE_NAME,
    HUB_UPDATE_STEP_DONE,
    HUB_UPDATE_STEP_INSTALLING,
    HUB_UPDATE_STEP_WAITING,
    HUB_UPDATE_UNIT,
    HUB_UPDATE_UNIT_ENVIRONMENT,
    HUB_UPDATE_UNIT_MEMORY_HIGH,
    HUB_UPDATE_UNPACK_MULTIPLE,
)
from neutrino_hub.modules.hub_update.release import (
    HubRelease,
    HubReleaseChecker,
    asset_name,
    version_of_asset,
)
from neutrino_hub.modules.hub_update.state import (
    HubUpdateRecord,
    HubUpdateStateFile,
    append_step,
    stamp_now,
)
from neutrino_hub.platforms.constants import PLATFORM_OS_DARWIN
from neutrino_hub.platforms.detect import hub_os
from neutrino_hub.system.machine import distribution_family, machine_architecture
from neutrino_hub.system.systemd_ctl import held_unit_state
from neutrino_hub.utils import constants
from neutrino_hub.utils.subprocess_run import run
from neutrino_hub.utils.tls_trust import public_ssl_context

DOWNLOAD_CHUNK_BYTES = 1024 * 1024
PROGRESS_STEPS = 4
# A size in the steps, as the panel's card shows it: steps of 1024, one
# decimal below ten in any unit but bytes, the number and the unit joined by
# a no-break space so a line never breaks between them.
SIZE_UNITS = ("B", "KB", "MB", "GB", "TB", "PB")
SIZE_STEP = 1024
SIZE_SPACE = "\u00a0"
UNIT_ACTIVE_STATES = ("active", "activating")
PACKAGE_SUFFIXES = (".deb", ".rpm", ".zst", ".xz", ".msi", ".pkg")
# The exact digest of a file already on disk decides whether it downloads
# again; a file with no digest to check against is fetched again.
DIGEST_CHUNK_BYTES = 1024 * 1024

# What each family runs to install a package file, and to put the previous
# one back. `--reinstall` makes a same-version file go through its maintainer
# scripts, `--allow-downgrades` lets the rollback take the same line, and the
# lock timeout waits out an unattended upgrade holding dpkg. pacman has no
# such wait and refuses at once while its lock is held, so its line waits for
# the lock first, as long. dnf5 refuses at once too, saying another
# transaction holds the rpm lock, so its lines run again each second while
# that is what it said, as long. `$PACE` is the script's own: it puts the
# package manager below every other process for the disk and the processor,
# because a package unpacking on a slow card has held PID 1 past its hardware
# watchdog.
PACMAN_LOCK_WAIT = (
    "waited=0; while [ -e @PACMAN_LOCK@ ] && [ $waited -lt @LOCK@ ]; "
    "do sleep 1; waited=$((waited + 1)); done; "
)
DNF_LOCK_WAIT = (
    "waited=0; while :; do out=$(@COMMAND@ 2>&1); code=$?; "
    '[ -z "$out" ] || printf \'%s\\n\' "$out"; '
    "[ $code != 0 ] && [ $waited -lt @LOCK@ ] || break; "
    'case "$out" in *@DNF_LOCK@*) ;; *) break ;; esac; '
    "sleep 1; waited=$((waited + 1)); done; (exit $code)"
)
INSTALL_COMMANDS = {
    "debian": (
        "$PACE apt-get install -y --reinstall --allow-downgrades "
        "-o DPkg::Lock::Timeout=@LOCK@ @PATH@",
        "$PACE apt-get install -y --reinstall --allow-downgrades "
        "-o DPkg::Lock::Timeout=@LOCK@ @PATH@",
    ),
    "rhel": (
        DNF_LOCK_WAIT.replace("@COMMAND@", "$PACE dnf install -y @PATH@"),
        "$PACE rpm -Uvh --oldpackage @PATH@",
    ),
    "arch": (
        PACMAN_LOCK_WAIT + "$PACE pacman -U --noconfirm @PATH@",
        PACMAN_LOCK_WAIT + "$PACE pacman -U --noconfirm @PATH@",
    ),
    # macOS's installer takes an older package as readily as a newer one.
    "pkg": (
        "installer -pkg @PATH@ -target /",
        "installer -pkg @PATH@ -target /",
    ),
    # msiexec's arguments; the PowerShell takes the newer version away before
    # it puts the older one back, which the installer refuses as a downgrade.
    "msi": (
        "/i @PATH@ /qn /norestart",
        "/i @PATH@ /qn /norestart",
    ),
}
# dnf5 answers a reinstall of a version other than the one installed with
# "Nothing to do" and exit 0, so a reinstall is asked for only when the
# version stays the same.
REINSTALL_COMMANDS = {
    "rhel": DNF_LOCK_WAIT.replace("@COMMAND@", "$PACE dnf reinstall -y @PATH@")
}
# What a family's script runs before each install: on arch, a step saying it
# waits, when pacman's lock is held.
LOCK_STEPS = {"arch": "[ ! -e @PACMAN_LOCK@ ] || step @STEP_WAITING@"}
# The program each family's install runs, as the steps name it.
MANAGER_NAMES = {
    "debian": "apt-get",
    "rhel": "dnf",
    "arch": "pacman",
    "pkg": "installer",
    "msi": "msiexec",
}
# The program a family's rollback runs, where it is not the install's.
ROLLBACK_MANAGER_NAMES = {"rhel": "rpm"}
# Where each family's script is written, and in what language it is rendered.
SCRIPT_NAMES = {"msi": HUB_UPDATE_SCRIPT_NAME_WINDOWS}
# How a family's script is encoded where it is not plain UTF-8: Windows
# PowerShell reads a script with no byte order mark in the system's ANSI code
# page.
SCRIPT_ENCODINGS = {"msi": "utf-8-sig"}

SCRIPT = r"""#!/bin/sh
# Written by neutrino_hub.modules.hub_update; runs as the transient unit
# @UNIT@. Do not edit.
umask 022
STATE=@STATE@
LOG=@LOG@
FROM=@FROM@
TO=@TO@
PACKAGE=@PACKAGE@
ROLLBACK=@ROLLBACK@
PORT=@PORT@
HTTPS_PORT=@HTTPS_PORT@
HEALTH_PATH=@HEALTH_PATH@
UNITS=@UNITS@
STARTED=@STARTED@
GATE_TIMEOUT=@GATE_TIMEOUT@
POLL=@POLL@
MEMINFO=@MEMINFO@
LOW_MEMORY_KB=@LOW_MEMORY_KB@
SHED=@SHED@
PYTHON=@PYTHON@
AGENT_COMMAND=@AGENT_COMMAND@
AGENT_UNIT=@AGENT_UNIT@
AGENT_START=@AGENT_START@
AGENT_WAIT=@AGENT_WAIT@
MANAGER=@MANAGER@
ROLLBACK_MANAGER=@ROLLBACK_MANAGER@
STEPS=@STEPS@
STAGE=@STAGE_INSTALLING@
REASON=''
STOPPED=''
PACE='nice -n 10'
command -v ionice >/dev/null 2>&1 && PACE="ionice -c 2 -n 7 $PACE"

write_state() {
    finished=''
    case "$STAGE" in
        @STAGES_SETTLED@) finished=$(date -u +%Y-%m-%dT%H:%M:%SZ) ;;
    esac
    {
        printf '{"stage": "%s", "from_version": "%s", "to_version": "%s", "started_at": "%s", "finished_at": "%s", "reason": "%s", "steps": [' \
            "$STAGE" "$FROM" "$TO" "$STARTED" "$finished" "$REASON"
        [ -z "$STEPS" ] || printf '%s\n' "$STEPS" | tr -d '\000-\011\013-\037' \
            | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' -e 's/^/"/' -e 's/$/"/' | paste -s -d , -
        printf '], "output": "'
        tail -c @OUTPUT_LIMIT@ "$LOG" | awk '{ sub(/\r$/, ""); gsub(/\r/, "\n"); print }' \
            | tr '\t' ' ' | tr -d '\000-\010\013-\037' \
            | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' -e 's/$/\\n/' | tr -d '\n'
        printf '"}\n'
    } > "$STATE.tmp"
    chmod 600 "$STATE.tmp"
    mv -f "$STATE.tmp" "$STATE"
}

step() {
    if [ -n "$STEPS" ]; then
        STEPS="$STEPS
$1"
    else
        STEPS=$1
    fi
    write_state
}

finish() {
    STAGE=$1
    REASON=$2
    step @STEP_DONE@
    [ "$STAGE" = @STAGE_INSTALLED@ ] && exit 0
    exit 1
}

why() {
    if [ "$1" != 0 ]; then
        echo "${3:-$MANAGER} exited $1"
    else
        echo "found version ${2:-none}"
    fi
}

is_running() {
    systemctl list-units --all --plain --no-legend --full "$1.service" 2>/dev/null \
        | awk -v unit="$1.service" '{ for (i = 1; i + 2 <= NF; i++) if ($i == unit) state = $(i + 2) }
            END { exit !(state == "active" || state == "activating" || state == "reloading" || state == "deactivating") }'
}

shed() {
    available=$(awk '/^MemAvailable:/ {print $2}' "$MEMINFO" 2>/dev/null)
    [ -n "$available" ] && [ "$available" -lt "$LOW_MEMORY_KB" ] || return 0
    for unit in $SHED; do
        systemctl is-active --quiet "$unit" || continue
        systemctl stop "$unit" && STOPPED="$STOPPED $unit"
    done
    echo "memory: ${available} kB available; stopped$STOPPED before the unpack" >> "$LOG"
}

unshed() {
    for unit in $STOPPED; do
        systemctl start "$unit" >> "$LOG" 2>&1
    done
    STOPPED=''
}

install_agent() {
    if ! command -v "$AGENT_COMMAND" >/dev/null 2>&1; then
        step 'no agent on this machine'
        return 0
    fi
    AGENT=''
    [ -z "$PYTHON" ] || AGENT=$("$PYTHON" -c 'from neutrino_hub.modules.hub_update.installer import local_agent_package; print(local_agent_package())' 2>> "$LOG")
    if [ -z "$AGENT" ]; then
        echo "agent: this hub carries no agent for this machine" >> "$LOG"
        step 'agent update failed: no agent package for this machine'
        return 0
    fi
    WANTED=$(basename "$AGENT" | sed -E 's/^neutrino-agent[_-]([^_-]+)[_-].*$/\1/')
    INSTALLED=$("$AGENT_COMMAND" --version 2>/dev/null | tail -n 1)
    if [ "$INSTALLED" != "$WANTED" ]; then
        deadline=$(( $(date +%s) + AGENT_START ))
        while ! is_running "$AGENT_UNIT" && [ "$(date +%s)" -lt "$deadline" ]; do
            sleep 1
        done
        deadline=$(( $(date +%s) + AGENT_WAIT ))
        while is_running "$AGENT_UNIT" && [ "$(date +%s)" -lt "$deadline" ]; do
            sleep "$POLL"
        done
        INSTALLED=$("$AGENT_COMMAND" --version 2>/dev/null | tail -n 1)
    fi
    if [ -n "$INSTALLED" ] && [ "$INSTALLED" = "$WANTED" ]; then
        step "agent already $WANTED"
        return 0
    fi
    echo "agent: reinstalling $AGENT" >> "$LOG"
    @LOCK_STEP@
    ( @AGENT_INSTALL@ ) >> "$LOG" 2>&1
    code=$?
    INSTALLED=$("$AGENT_COMMAND" --version 2>/dev/null | tail -n 1)
    if [ "$INSTALLED" != "$WANTED" ]; then
        step "agent update failed: $(why "$code" "$INSTALLED")"
    elif [ "$code" = 0 ]; then
        step "agent updated to $WANTED"
    else
        step "agent already $WANTED"
    fi
}

gate() {
    deadline=$(( $(date +%s) + GATE_TIMEOUT ))
    while :; do
        ok=1
        report=''
        for unit in $UNITS; do
            systemctl is-active --quiet "$unit" \
                || { ok=0; report="$report $unit=$(systemctl is-active "$unit")"; }
        done
        first="http://127.0.0.1:$PORT"
        second="https://127.0.0.1:$HTTPS_PORT"
        grep -Eq '"is_https_enabled": *true' @SETTINGS@ 2>/dev/null \
            && { first="https://127.0.0.1:$HTTPS_PORT"; second="http://127.0.0.1:$PORT"; }
        curl -fsS -m 5 --cacert @AUTHORITY@ -o /dev/null "$first$HEALTH_PATH" 2>/dev/null \
            || curl -fsS -m 5 --cacert @AUTHORITY@ -o /dev/null "$second$HEALTH_PATH" 2>/dev/null \
            || { ok=0; report="$report panel=failed"; }
        seen=$(nhub --version 2>/dev/null)
        [ "$seen" = "$1" ] || { ok=0; report="$report version=$seen"; }
        [ "$ok" = 1 ] && return 0
        sleep "$POLL"
        [ "$(date +%s)" -lt "$deadline" ] || break
    done
    echo "gate: timed out after ${GATE_TIMEOUT}s:$report" >> "$LOG"
    return 1
}

: > "$LOG"
sync
shed
@LOCK_STEP@
( @INSTALL@ ) >> "$LOG" 2>&1
code=$?
unshed
seen=$(nhub --version 2>/dev/null | tail -n 1)
if [ "$code" = 0 ] && [ "$seen" = "$TO" ]; then
    step "installed $TO"
    if gate "$TO"; then
        step 'panel answers'
        install_agent
        finish @STAGE_INSTALLED@ ''
    fi
    REASON=@REASON_GATE_FAILED@
    step "panel did not answer in $GATE_TIMEOUT s"
else
    REASON=@REASON_INSTALL_FAILED@
    step "install failed: $(why "$code" "$seen")"
    if [ "$seen" = "$FROM" ]; then
        step "nothing changed, still $FROM"
        finish @STAGE_ROLLED_BACK@ "$REASON"
    fi
fi
if [ -z "$ROLLBACK" ]; then
    step "rollback failed: no package of $FROM"
    finish @STAGE_FAILED@ "$REASON"
fi
STAGE=@STAGE_ROLLING_BACK@
write_state
@LOCK_STEP@
( @ROLLBACK_INSTALL@ ) >> "$LOG" 2>&1
code=$?
seen=$(nhub --version 2>/dev/null | tail -n 1)
if [ "$code" != 0 ] || [ "$seen" != "$FROM" ]; then
    step "rollback failed: $(why "$code" "$seen" "$ROLLBACK_MANAGER")"
    finish @STAGE_FAILED@ "$REASON"
fi
if gate "$FROM"; then
    step "rolled back to $FROM"
    finish @STAGE_ROLLED_BACK@ "$REASON"
fi
step "rollback failed: panel did not answer in $GATE_TIMEOUT s"
finish @STAGE_FAILED@ "$REASON"
"""


SCRIPT_DARWIN = r"""#!/bin/sh
# Written by neutrino_hub.modules.hub_update; runs as the launchd job
# @UNIT@. Do not edit. launchd runs a submitted job again whenever it
# exits, so every end removes the job once the state file says how it went.
umask 022
STATE=@STATE@
LOG=@LOG@
FROM=@FROM@
TO=@TO@
ROLLBACK=@ROLLBACK@
PORT=@PORT@
HTTPS_PORT=@HTTPS_PORT@
HEALTH_PATH=@HEALTH_PATH@
STARTED=@STARTED@
GATE_TIMEOUT=@GATE_TIMEOUT@
POLL=@POLL@
JOB=@JOB@
SERVICE=@SERVICE@
PLIST=@PLIST@
NHUB=@NHUB@
AGENT_COMMAND=@AGENT_COMMAND@
AGENT_CACHE=@AGENT_CACHE@
AGENT_PATTERN=@AGENT_PATTERN@
AGENT_JOB=@AGENT_JOB@
AGENT_START=@AGENT_START@
AGENT_WAIT=@AGENT_WAIT@
MANAGER=@MANAGER@
STEPS=@STEPS@
STAGE=@STAGE_INSTALLING@
REASON=''

write_state() {
    finished=''
    case "$STAGE" in
        @STAGES_SETTLED@) finished=$(date -u +%Y-%m-%dT%H:%M:%SZ) ;;
    esac
    {
        printf '{"stage": "%s", "from_version": "%s", "to_version": "%s", "started_at": "%s", "finished_at": "%s", "reason": "%s", "steps": [' \
            "$STAGE" "$FROM" "$TO" "$STARTED" "$finished" "$REASON"
        [ -z "$STEPS" ] || printf '%s\n' "$STEPS" | tr -d '\000-\011\013-\037' \
            | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' -e 's/^/"/' -e 's/$/"/' | paste -s -d , -
        printf '], "output": "'
        tail -c @OUTPUT_LIMIT@ "$LOG" | awk '{ sub(/\r$/, ""); gsub(/\r/, "\n"); print }' \
            | tr '\t' ' ' | tr -d '\000-\010\013-\037' \
            | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' -e 's/$/\\n/' | tr -d '\n'
        printf '"}\n'
    } > "$STATE.tmp"
    chmod 600 "$STATE.tmp"
    mv -f "$STATE.tmp" "$STATE"
}

step() {
    if [ -n "$STEPS" ]; then
        STEPS="$STEPS
$1"
    else
        STEPS=$1
    fi
    write_state
}

finish() {
    STAGE=$1
    REASON=$2
    step @STEP_DONE@
    launchctl remove "$JOB"
    exit 0
}

why() {
    if [ "$1" != 0 ]; then
        echo "$MANAGER exited $1"
    else
        echo "found version ${2:-none}"
    fi
}

start_service() {
    launchctl print "$SERVICE" >/dev/null 2>&1 \
        || launchctl bootstrap system "$PLIST" >> "$LOG" 2>&1
    launchctl kickstart "$SERVICE" >> "$LOG" 2>&1 || true
}

agent_updating() {
    launchctl print "$AGENT_JOB" 2>/dev/null | grep -q 'state = running'
}

install_agent() {
    if [ ! -x "$AGENT_COMMAND" ]; then
        step 'no agent on this machine'
        return 0
    fi
    AGENT=''
    for found in "$AGENT_CACHE"/$AGENT_PATTERN; do
        [ -f "$found" ] && AGENT=$found
    done
    if [ -z "$AGENT" ]; then
        echo "agent: this hub carries no agent for this machine" >> "$LOG"
        step 'agent update failed: no agent package for this machine'
        return 0
    fi
    INSTALLED=$("$AGENT_COMMAND" --version 2>/dev/null | tail -n 1)
    if [ "$INSTALLED" != "$TO" ]; then
        deadline=$(( $(date +%s) + AGENT_START ))
        while ! agent_updating && [ "$(date +%s)" -lt "$deadline" ]; do
            sleep 1
        done
        deadline=$(( $(date +%s) + AGENT_WAIT ))
        while agent_updating && [ "$(date +%s)" -lt "$deadline" ]; do
            sleep "$POLL"
        done
        INSTALLED=$("$AGENT_COMMAND" --version 2>/dev/null | tail -n 1)
    fi
    if [ "$INSTALLED" = "$TO" ]; then
        step "agent already $TO"
        return 0
    fi
    echo "agent: reinstalling $AGENT" >> "$LOG"
    ( @AGENT_INSTALL@ ) >> "$LOG" 2>&1
    code=$?
    INSTALLED=$("$AGENT_COMMAND" --version 2>/dev/null | tail -n 1)
    if [ "$INSTALLED" != "$TO" ]; then
        step "agent update failed: $(why "$code" "$INSTALLED")"
    elif [ "$code" = 0 ]; then
        step "agent updated to $TO"
    else
        step "agent already $TO"
    fi
}

gate() {
    deadline=$(( $(date +%s) + GATE_TIMEOUT ))
    while :; do
        ok=1
        report=''
        launchctl print "$SERVICE" 2>/dev/null | grep -q 'state = running' \
            || { ok=0; report="$report service=stopped"; }
        first="http://127.0.0.1:$PORT"
        second="https://127.0.0.1:$HTTPS_PORT"
        grep -Eq '"is_https_enabled": *true' @SETTINGS@ 2>/dev/null \
            && { first="https://127.0.0.1:$HTTPS_PORT"; second="http://127.0.0.1:$PORT"; }
        curl -fsS -m 5 --cacert @AUTHORITY@ -o /dev/null "$first$HEALTH_PATH" 2>/dev/null \
            || curl -fsS -m 5 --cacert @AUTHORITY@ -o /dev/null "$second$HEALTH_PATH" 2>/dev/null \
            || { ok=0; report="$report panel=failed"; }
        seen=$("$NHUB" --version 2>/dev/null)
        [ "$seen" = "$1" ] || { ok=0; report="$report version=$seen"; }
        [ "$ok" = 1 ] && return 0
        sleep "$POLL"
        [ "$(date +%s)" -lt "$deadline" ] || break
    done
    echo "gate: timed out after ${GATE_TIMEOUT}s:$report" >> "$LOG"
    return 1
}

: > "$LOG"
( @INSTALL@ ) >> "$LOG" 2>&1
code=$?
start_service
seen=$("$NHUB" --version 2>/dev/null | tail -n 1)
if [ "$code" = 0 ] && [ "$seen" = "$TO" ]; then
    step "installed $TO"
    if gate "$TO"; then
        step 'panel answers'
        install_agent
        finish @STAGE_INSTALLED@ ''
    fi
    REASON=@REASON_GATE_FAILED@
    step "panel did not answer in $GATE_TIMEOUT s"
else
    REASON=@REASON_INSTALL_FAILED@
    step "install failed: $(why "$code" "$seen")"
    if [ "$seen" = "$FROM" ]; then
        step "nothing changed, still $FROM"
        finish @STAGE_ROLLED_BACK@ "$REASON"
    fi
fi
if [ -z "$ROLLBACK" ]; then
    step "rollback failed: no package of $FROM"
    finish @STAGE_FAILED@ "$REASON"
fi
STAGE=@STAGE_ROLLING_BACK@
write_state
( @ROLLBACK_INSTALL@ ) >> "$LOG" 2>&1
code=$?
start_service
seen=$("$NHUB" --version 2>/dev/null | tail -n 1)
if [ "$code" != 0 ] || [ "$seen" != "$FROM" ]; then
    step "rollback failed: $(why "$code" "$seen")"
    finish @STAGE_FAILED@ "$REASON"
fi
if gate "$FROM"; then
    step "rolled back to $FROM"
    finish @STAGE_ROLLED_BACK@ "$REASON"
fi
step "rollback failed: panel did not answer in $GATE_TIMEOUT s"
finish @STAGE_FAILED@ "$REASON"
"""

# Put in place of the macOS script once its update has ended, so a job an
# earlier hub submitted, which launchd keeps running again, removes itself.
SCRIPT_DARWIN_RETIRED = """#!/bin/sh
# Written by neutrino_hub.modules.hub_update; removes the launchd job
# @UNIT@ once its update has ended. Do not edit.
launchctl remove @UNIT@
"""

SCRIPT_WINDOWS = r"""# Written by neutrino_hub.modules.hub_update; runs apart from the hub's
# service. Do not edit.
$ErrorActionPreference = 'Continue'
$State = @STATE@
$Log = @LOG@
$From = @FROM@
$To = @TO@
$Package = @PACKAGE@
$Rollback = @ROLLBACK@
$Port = @PORT@
$HttpsPort = @HTTPS_PORT@
$HealthPath = @HEALTH_PATH@
$Started = @STARTED@
$GateTimeout = @GATE_TIMEOUT@
$Poll = @POLL@
$Service = @SERVICE@
$Nhub = @NHUB@
$Settings = @SETTINGS@
$Authority = @AUTHORITY@
$AgentCommand = @AGENT_COMMAND@
$AgentCache = @AGENT_CACHE@
$AgentPattern = @AGENT_PATTERN@
$AgentStart = @AGENT_START@
$AgentWait = @AGENT_WAIT@
$Installed = @INSTALLED_CODES@
$Settled = @STAGES_SETTLED@
$Steps = New-Object System.Collections.Generic.List[string]
$Steps.AddRange([string[]]@STEPS@)
$Stage = @STAGE_INSTALLING@
$Reason = ''

function Write-UpdateState {
    $output = ''
    if (Test-Path -LiteralPath $Log) {
        $output = [string](Get-Content -LiteralPath $Log -Raw)
        if ($output.Length -gt @OUTPUT_LIMIT@) {
            $output = $output.Substring($output.Length - @OUTPUT_LIMIT@)
        }
        $output = $output.Replace("`r`n", "`n").Replace("`r", "`n")
    }
    $finished = ''
    if ($Settled -contains $script:Stage) {
        $finished = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    }
    $record = [ordered]@{
        stage = $script:Stage; from_version = $From; to_version = $To
        started_at = $Started; finished_at = $finished; reason = $script:Reason
        steps = [string[]]$script:Steps.ToArray(); output = $output
    }
    [IO.File]::WriteAllText("$State.tmp", ($record | ConvertTo-Json -Compress))
    Move-Item -Force -LiteralPath "$State.tmp" -Destination $State
}

function Add-Step($Line) {
    $script:Steps.Add($Line)
    Write-UpdateState
}

function Complete-Update($Stage, $Reason) {
    $script:Stage = $Stage
    $script:Reason = $Reason
    Add-Step @STEP_DONE@
    if ($Stage -eq @STAGE_INSTALLED@) { exit 0 }
    exit 1
}

function Invoke-Msi($Arguments) {
    $run = Start-Process -FilePath msiexec.exe -Wait -PassThru -WindowStyle Hidden `
        -ArgumentList $Arguments
    Add-Content -LiteralPath $Log -Value "msiexec $Arguments exited $($run.ExitCode)"
    return $run.ExitCode
}

function Get-Version($Command) {
    try {
        return [string](& $Command --version 2>$null | Select-Object -Last 1)
    } catch {
        return ''
    }
}

function Get-Why($Code, $Seen) {
    if ($Installed -notcontains $Code) { return "msiexec exited $Code" }
    if (-not $Seen) { $Seen = 'none' }
    return "found version $Seen"
}

function Start-Hub {
    Start-Service -Name $Service -ErrorAction SilentlyContinue
}

function Test-Installer {
    $held = $null
    try {
        if (-not [Threading.Mutex]::TryOpenExisting(@MSI_MUTEX@, [ref]$held)) { return $false }
        $held.Dispose()
    } catch [UnauthorizedAccessException] {
    }
    return $true
}

function Wait-Installer {
    $deadline = (Get-Date).AddSeconds($AgentWait)
    while (((Get-Date) -lt $deadline) -and (Test-Installer)) {
        Start-Sleep -Seconds $Poll
    }
}

function Install-Agent {
    if (-not (Test-Path -LiteralPath $AgentCommand)) {
        Add-Step 'no agent on this machine'
        return
    }
    $found = Get-ChildItem -Path $AgentCache -Filter $AgentPattern -ErrorAction SilentlyContinue |
        Select-Object -Last 1
    if (-not $found) {
        Add-Content -LiteralPath $Log -Value 'agent: this hub carries no agent for this machine'
        Add-Step 'agent update failed: no agent package for this machine'
        return
    }
    if ((Get-Version $AgentCommand) -ne $To) {
        $deadline = (Get-Date).AddSeconds($AgentStart)
        while (((Get-Date) -lt $deadline) -and -not (Test-Installer)) {
            Start-Sleep -Seconds 1
        }
        Wait-Installer
    }
    if ((Get-Version $AgentCommand) -eq $To) {
        Add-Step "agent already $To"
        return
    }
    Add-Content -LiteralPath $Log -Value "agent: reinstalling $($found.FullName)"
    $arguments = "/i `"$($found.FullName)`" /qn /norestart"
    $code = Invoke-Msi $arguments
    if ($code -eq @MSI_BUSY@) {
        Wait-Installer
        if ((Get-Version $AgentCommand) -eq $To) {
            Add-Step "agent already $To"
            return
        }
        $code = Invoke-Msi $arguments
    }
    $seen = Get-Version $AgentCommand
    if ($seen -ne $To) {
        Add-Step "agent update failed: $(Get-Why $code $seen)"
    } elseif ($Installed -contains $code) {
        Add-Step "agent updated to $To"
    } else {
        Add-Step "agent already $To"
    }
}

function Test-Gate($Version) {
    $deadline = (Get-Date).AddSeconds($GateTimeout)
    $report = ''
    do {
        $ok = $true
        $report = ''
        $running = Get-Service -Name $Service -ErrorAction SilentlyContinue
        if (-not $running -or $running.Status -ne 'Running') {
            $ok = $false
            $report += ' service=stopped'
        }
        $first = "http://127.0.0.1:$Port"
        $second = "https://127.0.0.1:$HttpsPort"
        if ((Test-Path -LiteralPath $Settings) -and
            ((Get-Content -LiteralPath $Settings -Raw) -match '"is_https_enabled": *true')) {
            $first = "https://127.0.0.1:$HttpsPort"
            $second = "http://127.0.0.1:$Port"
        }
        & curl.exe -fsS -m 5 --cacert $Authority -o NUL "$first$HealthPath" 2>$null
        if ($LASTEXITCODE -ne 0) {
            & curl.exe -fsS -m 5 --cacert $Authority -o NUL "$second$HealthPath" 2>$null
            if ($LASTEXITCODE -ne 0) {
                $ok = $false
                $report += ' panel=failed'
            }
        }
        $seen = Get-Version $Nhub
        if ($seen -ne $Version) {
            $ok = $false
            $report += " version=$seen"
        }
        if ($ok) { return $true }
        Start-Sleep -Seconds $Poll
    } while ((Get-Date) -lt $deadline)
    Add-Content -LiteralPath $Log -Value "gate: timed out after $($GateTimeout)s:$report"
    return $false
}

[IO.File]::WriteAllText($Log, '')
$code = Invoke-Msi @INSTALL@
Start-Hub
$seen = Get-Version $Nhub
if (($Installed -contains $code) -and $seen -eq $To) {
    Add-Step "installed $To"
    if (Test-Gate $To) {
        Add-Step 'panel answers'
        Install-Agent
        Complete-Update @STAGE_INSTALLED@ ''
    }
    $Reason = @REASON_GATE_FAILED@
    Add-Step "panel did not answer in $GateTimeout s"
} else {
    $Reason = @REASON_INSTALL_FAILED@
    Add-Step "install failed: $(Get-Why $code $seen)"
    if ($seen -eq $From) {
        Add-Step "nothing changed, still $From"
        Complete-Update @STAGE_ROLLED_BACK@ $Reason
    }
}
if (-not $Rollback) {
    Add-Step "rollback failed: no package of $From"
    Complete-Update @STAGE_FAILED@ $Reason
}
$Stage = @STAGE_ROLLING_BACK@
Write-UpdateState
Invoke-Msi "/x `"$Package`" /qn /norestart" | Out-Null
$code = Invoke-Msi @ROLLBACK_INSTALL@
Start-Hub
$seen = Get-Version $Nhub
if (($Installed -notcontains $code) -or $seen -ne $From) {
    Add-Step "rollback failed: $(Get-Why $code $seen)"
    Complete-Update @STAGE_FAILED@ $Reason
}
if (Test-Gate $From) {
    Add-Step "rolled back to $From"
    Complete-Update @STAGE_ROLLED_BACK@ $Reason
}
Add-Step "rollback failed: panel did not answer in $GateTimeout s"
Complete-Update @STAGE_FAILED@ $Reason
"""


@dataclass(frozen=True)
class HubUpdatePlan:
    """Everything the install unit is told.

    Attributes:
        from_version: The version running now.
        to_version: The version the package installs.
        package: The package file, digest checked, under the update directory.
        rollback: The running version's own package beside it, or None when
            no release carries one.
        family: The distribution family, which names the package manager,
            or ``pkg`` on macOS and ``msi`` on Windows.
        port: The panel's HTTP port, which the gate probes while HTTPS is
            off.
        https_port: The panel's HTTPS port, which the gate probes while
            HTTPS is on.
        units: The units the gate holds for: the panel, and those of the
            router's that were running when the plan was made.
        started_at: When the update started, as an ISO stamp.
        python: The hub's own interpreter, which names this machine's agent
            package in the cache once the new hub is installed; empty leaves
            the agent alone.
        steps: The staging's lines, as the record keeps them.
    """

    from_version: str
    to_version: str
    package: Path
    rollback: Path | None
    family: str
    port: int
    https_port: int
    units: tuple[str, ...]
    started_at: str
    python: str = ""
    steps: tuple[str, ...] = ()


class HubUpdateStagingSteps:
    """The lines a staging says, kept as the record's steps as they are told."""

    def __init__(self, on_progress: Callable[[str], None] | None = None):
        """Set up the lines.

        Args:
            on_progress: Told each line as it is said, when given.
        """
        self.steps: list[str] = []
        self._on_progress = on_progress

    def say(self, line: str) -> None:
        """Keep one line and tell it.

        Args:
            line: The line.
        """
        append_step(self.steps, line)
        if self._on_progress is not None:
            self._on_progress(line)


def handed_over_steps(plan: "HubUpdatePlan") -> list[str]:
    """The steps a record holds once the install is handed over.

    Args:
        plan: The plan handed over.

    Returns:
        The staging's lines and the hand-over's own.
    """
    return [*plan.steps, HUB_UPDATE_STEP_INSTALLING]


def space_needed(
    asset_size: int,
    *,
    is_rollback_fetched: bool,
    state_root: Path | None = None,
    static_root: Path | None = None,
) -> dict[Path, int]:
    """How many bytes each root must have free for an update.

    Args:
        asset_size: The package's size.
        is_rollback_fetched: Whether the rollback package has to come down
            too.
        state_root: Where packages land; None is the hub's.
        static_root: Where the package unpacks; None is the hub's.

    Returns:
        Bytes needed by root; the two roots merged into one entry when they
        are on the same filesystem.
    """
    state = state_root or constants.UTILS_STATE_ROOT
    static = static_root or constants.UTILS_STATIC_ROOT
    packages = asset_size * (2 if is_rollback_fetched else 1)
    unpacked = asset_size * HUB_UPDATE_UNPACK_MULTIPLE
    if _device_of(state) == _device_of(static):
        return {state: packages + unpacked}
    return {state: packages, static: unpacked}


def check_space(
    asset_size: int,
    *,
    is_rollback_fetched: bool,
    disk_usage: Callable[[Path], "shutil._ntuple_diskusage"] = shutil.disk_usage,
) -> None:
    """Refuse an update the disk has no room for.

    Args:
        asset_size: The package's size.
        is_rollback_fetched: Whether the rollback package has to come down
            too.
        disk_usage: How a root's usage is read.

    Raises:
        HubUpdateError: ``disk_space_short``, naming the root, what it needs and
            what it has.
    """
    for root, needed in space_needed(
        asset_size, is_rollback_fetched=is_rollback_fetched
    ).items():
        free = disk_usage(_existing_parent(root)).free
        if free < needed:
            raise HubUpdateError(
                HUB_UPDATE_REASON_SPACE_SHORT,
                path=str(root),
                needed_bytes=needed,
                free_bytes=free,
            )


def free_bytes(
    asset_size: int,
    *,
    is_rollback_fetched: bool,
    disk_usage: Callable[[Path], "shutil._ntuple_diskusage"] = shutil.disk_usage,
) -> tuple[int, int]:
    """What an update needs and what the tightest root has, for showing.

    Args:
        asset_size: The package's size.
        is_rollback_fetched: Whether the rollback package has to come down
            too.
        disk_usage: How a root's usage is read.

    Returns:
        ``(needed, free)`` for the root with the least room to spare.
    """
    tightest = None
    for root, needed in space_needed(
        asset_size, is_rollback_fetched=is_rollback_fetched
    ).items():
        free = disk_usage(_existing_parent(root)).free
        if tightest is None or free - needed < tightest[1] - tightest[0]:
            tightest = (needed, free)
    return tightest or (0, 0)


def install_commands(
    family: str, path: Path, *, is_reinstall: bool = False
) -> tuple[str, str]:
    """What installs a package file on this family, and what puts one back.

    Args:
        family: The distribution family, or ``pkg`` or ``msi``.
        path: The package file.
        is_reinstall: Whether the file is the version already installed.

    Returns:
        The install command line, and the rollback's; for ``msi``, msiexec's
        arguments as PowerShell strings.

    Raises:
        ValueError: If no package manager is known for the family.
    """
    if family not in INSTALL_COMMANDS:
        raise ValueError(f"no package manager is known for {family}")
    if family == "msi":
        windows_path = f'"{path}"'
        return tuple(
            _powershell_quote(line.replace("@PATH@", windows_path))
            for line in INSTALL_COMMANDS[family]
        )
    install, rollback = INSTALL_COMMANDS[family]
    if is_reinstall:
        install = REINSTALL_COMMANDS.get(family, install)
    return tuple(_filled(line, shlex.quote(str(path))) for line in (install, rollback))


def agent_install_command(family: str) -> str:
    """What installs the agent package the script finds, on this family.

    Args:
        family: The distribution family.

    Returns:
        The install command line, naming the file as ``"$AGENT"``.

    Raises:
        ValueError: If no package manager is known for the family.
    """
    if family not in INSTALL_COMMANDS:
        raise ValueError(f"no package manager is known for {family}")
    return _filled(INSTALL_COMMANDS[family][0], '"$AGENT"')


def update_family() -> str:
    """Which family this hub updates itself as.

    Returns:
        ``pkg`` on macOS, ``msi`` on Windows, else the distribution family.
    """
    return HUB_UPDATE_FAMILY_OF_OS.get(hub_os(), "") or distribution_family()


def local_agent_package() -> str:
    """This machine's own agent package, as the hub's cache holds it.

    Returns:
        The file's path; empty when the cache holds none for this machine or
        it cannot be had.
    """
    family = AGENT_PACKAGE_FAMILY_OF_OS.get(hub_os(), "")
    family = family or AGENT_PACKAGE_FAMILY_OF_PLATFORM.get(distribution_family(), "")
    architecture = machine_architecture()
    cache = AgentPackageCache()
    if not family or not cache.serves(family=family, architecture=architecture):
        return ""
    try:
        return str(cache.package(family=family, architecture=architecture))
    except (OSError, ValueError, AgentArtifactFetchError):
        return ""


def render_script(
    plan: HubUpdatePlan,
    *,
    directory: Path,
    gate_timeout_s: int = HUB_UPDATE_GATE_TIMEOUT_S,
    poll_s: float = HUB_UPDATE_GATE_POLL_S,
    output_limit_bytes: int = HUB_UPDATE_OUTPUT_LIMIT_BYTES,
    meminfo_path: str = HUB_UPDATE_MEMINFO_PATH,
    low_memory_bytes: int = HUB_UPDATE_LOW_MEMORY_BYTES,
    agent_command: str = HUB_UPDATE_AGENT_COMMAND,
    agent_start_s: int = HUB_UPDATE_AGENT_START_S,
    agent_wait_s: int = HUB_UPDATE_AGENT_WAIT_S,
) -> str:
    """The script the update runs: the transient unit's shell on Linux, the
    launchd job's shell on macOS, the PowerShell on Windows. Pure.

    On Linux, with less available memory than ``low_memory_bytes``, it stops
    the panel and the AI gateway before the package unpacks and starts them
    after. Right after the package step it reads the version installed: a
    box still on the version it started from is left as it is, one on
    another version that is not the target is rolled back. Once the new hub
    passes its gate, an agent not on the target is given ``agent_start_s``
    to start its own update and ``agent_wait_s`` to end it; the script then
    reinstalls the machine's own agent from the hub's cache unless it is
    already there, and an install that failed with the agent on the target
    is taken for one that was not needed. On arch it says it waits before
    each install while pacman's lock is held.

    Args:
        plan: What to install and what to hold for.
        directory: Where the state file and the log are written.
        gate_timeout_s: How long the gate holds before it gives up. The gate
            looks at least once, however short this is.
        poll_s: How often the gate looks.
        output_limit_bytes: How much of the log's tail the state file keeps.
        meminfo_path: Where the kernel says how much memory is available.
        low_memory_bytes: Below this, the panel and the AI gateway stop for
            the unpack.
        agent_command: The command whose presence says the machine has an
            agent of its own.
        agent_start_s: How long the agent is given to start its own update.
        agent_wait_s: How long the agent's own update is waited out.

    Returns:
        The script's text.

    Raises:
        ValueError: If no package manager is known for the plan's family.
    """
    if plan.family in HUB_UPDATE_FAMILY_OF_OS.values():
        return _render_system_script(
            plan,
            directory=directory,
            gate_timeout_s=gate_timeout_s,
            poll_s=poll_s,
            output_limit_bytes=output_limit_bytes,
            agent_start_s=agent_start_s,
            agent_wait_s=agent_wait_s,
        )
    install, _ = install_commands(
        plan.family,
        plan.package,
        is_reinstall=plan.from_version == plan.to_version,
    )
    rollback_install = ""
    if plan.rollback is not None:
        _, rollback_install = install_commands(plan.family, plan.rollback)
    values = {
        "@UNIT@": HUB_UPDATE_UNIT,
        "@STATE@": shlex.quote(str(directory / HUB_UPDATE_STATE_NAME)),
        "@LOG@": shlex.quote(str(directory / HUB_UPDATE_LOG_NAME)),
        "@FROM@": shlex.quote(plan.from_version),
        "@TO@": shlex.quote(plan.to_version),
        "@PACKAGE@": shlex.quote(str(plan.package)),
        "@ROLLBACK@": shlex.quote(str(plan.rollback) if plan.rollback else ""),
        "@PORT@": shlex.quote(str(plan.port)),
        "@HTTPS_PORT@": shlex.quote(str(plan.https_port)),
        "@UNITS@": shlex.quote(" ".join(plan.units)),
        "@STARTED@": shlex.quote(plan.started_at),
        "@GATE_TIMEOUT@": str(int(gate_timeout_s)),
        "@POLL@": str(poll_s),
        "@OUTPUT_LIMIT@": str(int(output_limit_bytes)),
        "@HEALTH_PATH@": shlex.quote(HUB_UPDATE_HEALTH_PATH),
        "@SETTINGS@": shlex.quote(str(HUB_UPDATE_PANEL_SETTINGS_PATH)),
        "@AUTHORITY@": shlex.quote(str(HUB_UPDATE_PANEL_AUTHORITY_PATH)),
        "@LOCK_STEP@": _filled(LOCK_STEPS.get(plan.family, ""), ""),
        "@INSTALL@": install,
        "@AGENT_INSTALL@": agent_install_command(plan.family),
        "@MEMINFO@": shlex.quote(meminfo_path),
        "@LOW_MEMORY_KB@": str(int(low_memory_bytes) // 1024),
        "@SHED@": shlex.quote(" ".join(HUB_UPDATE_SHED_UNITS)),
        "@PYTHON@": shlex.quote(plan.python),
        "@AGENT_COMMAND@": shlex.quote(agent_command),
        "@AGENT_UNIT@": shlex.quote(HUB_UPDATE_AGENT_UPDATE_UNIT),
        "@AGENT_START@": str(int(agent_start_s)),
        "@AGENT_WAIT@": str(int(agent_wait_s)),
        "@MANAGER@": shlex.quote(MANAGER_NAMES[plan.family]),
        "@ROLLBACK_MANAGER@": shlex.quote(
            ROLLBACK_MANAGER_NAMES.get(plan.family, MANAGER_NAMES[plan.family])
        ),
        "@STEPS@": shlex.quote("\n".join(handed_over_steps(plan))),
        "@STAGES_SETTLED@": "|".join(HUB_UPDATE_STAGES_SETTLED),
        "@STEP_DONE@": shlex.quote(HUB_UPDATE_STEP_DONE),
        "@ROLLBACK_INSTALL@": rollback_install or "false",
        "@STAGE_INSTALLING@": HUB_UPDATE_STAGE_INSTALLING,
        "@STAGE_INSTALLED@": HUB_UPDATE_STAGE_INSTALLED,
        "@STAGE_ROLLING_BACK@": HUB_UPDATE_STAGE_ROLLING_BACK,
        "@STAGE_ROLLED_BACK@": HUB_UPDATE_STAGE_ROLLED_BACK,
        "@STAGE_FAILED@": HUB_UPDATE_STAGE_FAILED,
        "@REASON_GATE_FAILED@": HUB_UPDATE_REASON_GATE_FAILED,
        "@REASON_INSTALL_FAILED@": HUB_UPDATE_REASON_INSTALL_FAILED,
    }
    text = SCRIPT
    for token, value in values.items():
        text = text.replace(token, value)
    return text


def script_name(family: str) -> str:
    """What the install script of a family is called.

    Args:
        family: The plan's family.

    Returns:
        ``update.ps1`` for ``msi``, ``update.sh`` for every other.
    """
    return SCRIPT_NAMES.get(family, HUB_UPDATE_SCRIPT_NAME)


def launchd_job_state(job: str = HUB_UPDATE_JOB_DARWIN) -> str:
    """Whether the macOS install job is running, in systemd's words.

    Args:
        job: The job, as ``launchctl print`` names it.

    Returns:
        ``active`` while launchd says it runs, else ``inactive``.
    """
    try:
        result = subprocess.run(
            ["launchctl", "print", job],
            capture_output=True,
            text=True,
            timeout=HUB_UPDATE_LAUNCH_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError):
        return "inactive"
    if result.returncode == 0 and "state = running" in result.stdout:
        return "active"
    return "inactive"


def retire_finished_job(
    *,
    system: str | None = None,
    state: HubUpdateStateFile | None = None,
    directory: Path | None = None,
) -> bool:
    """On macOS, make a finished update's script remove its launchd job.

    A job submitted by an earlier hub runs its script again each time it
    exits. Once the record says the update ended, the script is replaced,
    atomically, by one that only removes the job.

    Args:
        system: The system the hub runs on; None reads it.
        state: The update's record; None is the one under the state root.
        directory: Where the script lives; None is the update directory.

    Returns:
        Whether the script was replaced.

    Raises:
        OSError: If the script is there and cannot be replaced.
    """
    if (system or hub_os()) != PLATFORM_OS_DARWIN:
        return False
    record = (state or HubUpdateStateFile()).load()
    if record is None or record.stage not in HUB_UPDATE_STAGES_SETTLED:
        return False
    directory = directory or constants.UTILS_STATE_ROOT / HUB_UPDATE_DIR_NAME
    script = directory / HUB_UPDATE_SCRIPT_NAME
    retired = SCRIPT_DARWIN_RETIRED.replace("@UNIT@", HUB_UPDATE_UNIT)
    try:
        if script.read_text(encoding="utf-8") == retired:
            return False
    except FileNotFoundError:
        return False
    handle, temporary = tempfile.mkstemp(dir=directory, prefix=".tmp_")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as sink:
            sink.write(retired)
        os.chmod(temporary, HUB_UPDATE_SCRIPT_MODE)
        os.replace(temporary, script)
    except OSError:
        Path(temporary).unlink(missing_ok=True)
        raise
    return True


def windows_script_state(pid_file: Path) -> str:
    """Whether the Windows install script is running, in systemd's words.

    Args:
        pid_file: Where the hub wrote the script's process id.

    Returns:
        ``active`` while a PowerShell of that id runs, else ``inactive``.
    """
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
        name = psutil.Process(pid).name().lower()
    except (OSError, ValueError, psutil.Error):
        return "inactive"
    return "active" if "powershell" in name else "inactive"


class HubUpdateInstaller:
    """Stages one update and hands it to the system to install."""

    def __init__(
        self,
        *,
        checker: HubReleaseChecker,
        state: HubUpdateStateFile,
        directory: Path | None = None,
        asset: str = HUB_PACKAGE_ASSET,
        family: str | None = None,
        open_url: Callable[[str], object] | None = None,
        run_command: Callable[..., object] = run,
        unit_state_of: Callable[[str], str] | None = None,
        disk_usage: Callable[[Path], "shutil._ntuple_diskusage"] = shutil.disk_usage,
        start_detached: Callable[[list], int] | None = None,
    ):
        """Set up an installer.

        Args:
            checker: What reads the releases.
            state: The state file both sides write.
            directory: Where packages, the script and the log live; None is
                the update directory under the state root, resolved at each
                call.
            asset: The name the build stamped, with ``{version}`` open.
            family: The distribution family, or ``pkg`` or ``msi``; None
                reads the machine's.
            open_url: How a download is opened, answering a stream with a
                ``read(size)``; None opens it over the network.
            run_command: How the unit or the launchd job is started.
            unit_state_of: How the install's state is read, in systemd's
                words; None reads it from systemd, launchd or the Windows
                script's process, by the family.
            disk_usage: How a root's usage is read.
            start_detached: How the Windows script is started apart from the
                service, answering its process id; None starts it with no
                window and outside the service's job.
        """
        self._checker = checker
        self._state = state
        self._directory = directory
        self._asset = asset
        self._family = family
        self._open_url = _open_url if open_url is None else open_url
        self._run = run_command
        self._unit_state = unit_state_of
        self._disk_usage = disk_usage
        self._start_detached = start_detached or _start_detached

    @property
    def checker(self) -> HubReleaseChecker:
        """What reads the releases."""
        return self._checker

    @property
    def state(self) -> HubUpdateStateFile:
        """The state file both sides write."""
        return self._state

    @property
    def directory(self) -> Path:
        """Where packages, the script and the log live now."""
        return self._directory or constants.UTILS_STATE_ROOT / HUB_UPDATE_DIR_NAME

    def is_unit_active(self) -> bool:
        """Whether the install unit is running now.

        Returns:
            True while systemd, launchd or the Windows process table reports
            it active or activating.
        """
        return self._state_of(HUB_UPDATE_UNIT) in UNIT_ACTIVE_STATES

    def settled_record(self, *, is_task_running: bool) -> HubUpdateRecord | None:
        """The record, with a run that died without writing marked as such.

        The install is asked about only while the record says it runs.

        Args:
            is_task_running: Whether a staging task is running now.

        Returns:
            The record as it stands, or None when there is none.
        """
        record = self._state.load()
        is_in_unit = record is not None and record.stage in HUB_UPDATE_STAGES_IN_UNIT
        return self._state.settle(
            is_unit_active=self.is_unit_active() if is_in_unit else False,
            is_task_running=is_task_running,
        )

    def is_rollback_available(self, current: str) -> bool:
        """Whether the running version's package can be at hand.

        Args:
            current: The version running.

        Returns:
            True when its package is already in the directory, or a release
            of that version carries it.

        Raises:
            OSError: If GitHub had to be asked and could not be reached.
            ValueError: If the release read is not shaped like one, or this
                hub carries no stamp.
        """
        if self._rollback_path(current).is_file():
            return True
        release = self._checker.for_version(
            current, max_age_s=HUB_UPDATE_RELEASE_REUSE_S
        )
        return release is not None and release.has_package

    def is_rollback_present(self, current: str) -> bool:
        """Whether the running version's package is in the directory.

        Args:
            current: The version running.

        Returns:
            True when it is there, so no download would be needed.
        """
        try:
            return self._rollback_path(current).is_file()
        except ValueError:
            return False

    def prepare(
        self,
        release: HubRelease,
        *,
        current: str,
        port: int,
        https_port: int,
        on_progress: Callable[[str], None] | None = None,
        started_at: str = "",
    ) -> HubUpdatePlan:
        """Stage a release: room, the package, its digest, the rollback.

        Args:
            release: What to install.
            current: The version running.
            port: The panel's HTTP port, for the gate.
            https_port: The panel's HTTPS port, for the gate.
            on_progress: Told one line per step taken, when given.
            started_at: When the update was asked for; empty is now.

        Returns:
            The plan the unit is handed.

        Raises:
            HubUpdateError: ``disk_space_short``, ``package_fetch_failed``,
                ``package_sha256_mismatch`` or ``rollback_fetch_failed``;
                nothing half-written remains.
        """
        started_at = started_at or stamp_now()
        staging = HubUpdateStagingSteps(on_progress)
        directory = self._ready_directory()
        rollback_name = asset_name(current, asset=self._asset)
        is_rollback_fetched = not (directory / rollback_name).is_file()
        check_space(
            release.asset_size,
            is_rollback_fetched=is_rollback_fetched,
            disk_usage=self._disk_usage,
        )
        self._prune(keep={release.asset_name, rollback_name})
        target = directory / release.asset_name
        try:
            digest = self._checker.digest_of(release)
        except (OSError, ValueError) as error:
            raise HubUpdateError(
                HUB_UPDATE_REASON_PACKAGE_FETCH_FAILED, detail=str(error)[:200]
            ) from error
        if target.is_file() and _file_digest(target) == digest:
            staging.say(f"{release.asset_name} already here, checked")
        else:
            staging.say(
                f"downloading {release.asset_name}  {_size_text(release.asset_size)}"
            )
            received = self._download(
                release.asset_url, target, total=release.asset_size, say=staging.say
            )
            if received != digest:
                target.unlink(missing_ok=True)
                raise HubUpdateError(
                    HUB_UPDATE_REASON_PACKAGE_SHA256_MISMATCH, name=release.asset_name
                )
            staging.say("checked")
        rollback = self._ensure_rollback(current, say=staging.say)
        return HubUpdatePlan(
            from_version=current,
            to_version=release.version,
            package=target,
            rollback=rollback,
            family=self._family_now(),
            port=port,
            https_port=https_port,
            units=self._gate_units(),
            started_at=started_at,
            python=sys.executable,
            steps=tuple(staging.steps),
        )

    def plan_for_file(
        self,
        package: Path,
        *,
        current: str,
        port: int,
        https_port: int,
        on_progress: Callable[[str], None] | None = None,
        started_at: str = "",
    ) -> HubUpdatePlan:
        """Stage a package file somebody brought, its version read off its name.

        Args:
            package: The file.
            current: The version running.
            port: The panel's HTTP port, for the gate.
            https_port: The panel's HTTPS port, for the gate.
            on_progress: Told one line per step taken, when given.
            started_at: When the update was asked for; empty is now.

        Returns:
            The plan the unit is handed.

        Raises:
            HubUpdateError: ``package_missing`` when no file is at that path,
                ``package_name_mismatch`` when its name is not this box's
                package at any version, ``disk_space_short``,
                ``package_fetch_failed`` when the file cannot be read, or
                ``rollback_fetch_failed``.
        """
        started_at = started_at or stamp_now()
        staging = HubUpdateStagingSteps(on_progress)
        if not package.is_file():
            raise HubUpdateError(HUB_UPDATE_REASON_PACKAGE_MISSING, path=str(package))
        try:
            version = version_of_asset(package.name, asset=self._asset)
        except ValueError as error:
            raise HubUpdateError(
                HUB_UPDATE_REASON_PACKAGE_NAME_MISMATCH,
                name=package.name,
                expected=self._asset,
            ) from error
        directory = self._ready_directory()
        rollback_name = asset_name(current, asset=self._asset)
        target = directory / package.name
        try:
            size = package.stat().st_size
        except OSError as error:
            raise HubUpdateError(
                HUB_UPDATE_REASON_PACKAGE_FETCH_FAILED, detail=str(error)[:200]
            ) from error
        is_rollback_fetched = (
            rollback_name != package.name and not (directory / rollback_name).is_file()
        )
        check_space(
            size, is_rollback_fetched=is_rollback_fetched, disk_usage=self._disk_usage
        )
        self._prune(keep={package.name, rollback_name})
        if package.resolve() != target.resolve():
            # Linked where the file is on the same filesystem: a copy is
            # another whole package written to the card just before the
            # unpack writes the next one.
            try:
                target.unlink(missing_ok=True)
                try:
                    os.link(package, target)
                except OSError:
                    shutil.copyfile(package, target)
                os.chmod(target, HUB_UPDATE_PACKAGE_MODE)
            except OSError as error:
                target.unlink(missing_ok=True)
                raise HubUpdateError(
                    HUB_UPDATE_REASON_PACKAGE_FETCH_FAILED, detail=str(error)[:200]
                ) from error
        staging.say(f"{package.name} in place")
        rollback = None
        if rollback_name != package.name:
            rollback = self._ensure_rollback(current, say=staging.say)
        return HubUpdatePlan(
            from_version=current,
            to_version=version,
            package=target,
            rollback=rollback,
            family=self._family_now(),
            port=port,
            https_port=https_port,
            units=self._gate_units(),
            started_at=started_at,
            python=sys.executable,
            steps=tuple(staging.steps),
        )

    def launch(self, plan: HubUpdatePlan) -> None:
        """Write the script, start it, and record that it installs.

        The record says ``installing`` only once the script is started, and
        on Windows once its process id is written beside the record.

        Args:
            plan: What the unit is told.

        Raises:
            HubUpdateError: ``update_launch_failed`` when the system would not
                start the script; the state file says so.
        """
        directory = self._ready_directory()
        script = directory / script_name(plan.family)
        script.write_text(
            render_script(plan, directory=directory),
            encoding=SCRIPT_ENCODINGS.get(plan.family, "utf-8"),
        )
        os.chmod(script, HUB_UPDATE_SCRIPT_MODE)
        record = HubUpdateRecord(
            stage=HUB_UPDATE_STAGE_INSTALLING,
            from_version=plan.from_version,
            to_version=plan.to_version,
            started_at=plan.started_at,
            steps=handed_over_steps(plan),
        )
        try:
            pid = self._start(plan.family, script)
            if pid is not None:
                (directory / HUB_UPDATE_PID_NAME).write_text(str(pid), encoding="utf-8")
        except (OSError, subprocess.SubprocessError) as error:
            record.stage = HUB_UPDATE_STAGE_FAILED
            record.reason = HUB_UPDATE_REASON_LAUNCH_FAILED
            record.finished_at = stamp_now()
            record.output = str(error)[:200]
            self._state.save(record)
            raise HubUpdateError(
                HUB_UPDATE_REASON_LAUNCH_FAILED, detail=str(error)[:200]
            ) from error
        self._state.save(record)

    def _start(self, family: str, script: Path) -> int | None:
        """Start the script apart from the panel, the way the system does it.

        Returns:
            The process id of the Windows script; None elsewhere, where the
            system names the install by its label.
        """
        if family == "msi":
            return self._start_detached(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script),
                ]
            )
        if family == "pkg":
            # A job an earlier update submitted keeps its label until removed.
            try:
                self._run(
                    ["launchctl", "remove", HUB_UPDATE_UNIT],
                    timeout_s=HUB_UPDATE_LAUNCH_TIMEOUT_S,
                )
            except (OSError, subprocess.SubprocessError):
                pass
            self._run(
                ["launchctl", "submit", "-l", HUB_UPDATE_UNIT, "--", "/bin/sh"]
                + [str(script)],
                timeout_s=HUB_UPDATE_LAUNCH_TIMEOUT_S,
            )
            return None
        self._run(
            [
                "systemd-run",
                "--unit",
                HUB_UPDATE_UNIT,
                "--collect",
                f"--property=MemoryHigh={HUB_UPDATE_UNIT_MEMORY_HIGH}",
                *(f"--setenv={pair}" for pair in HUB_UPDATE_UNIT_ENVIRONMENT),
                "/bin/sh",
                str(script),
            ],
            timeout_s=HUB_UPDATE_LAUNCH_TIMEOUT_S,
        )
        return None

    def _family_now(self) -> str:
        """The family given, or the machine's own."""
        return self._family or update_family()

    def _state_of(self, unit: str) -> str:
        """The install's state, read the way the family's system keeps it."""
        if self._unit_state is not None:
            return self._unit_state(unit)
        family = self._family_now()
        if family == "pkg":
            return launchd_job_state()
        if family == "msi":
            return windows_script_state(self.directory / HUB_UPDATE_PID_NAME)
        return held_unit_state(unit)

    def _ready_directory(self) -> Path:
        directory = self.directory
        directory.mkdir(parents=True, exist_ok=True)
        os.chmod(directory, HUB_UPDATE_DIR_MODE)
        return directory

    def _rollback_path(self, current: str) -> Path:
        return self.directory / asset_name(current, asset=self._asset)

    def _prune(self, *, keep: set[str]) -> None:
        """Drop every package but the ones named, and an earlier run's files."""
        for entry in self.directory.iterdir():
            if entry.name in keep or not entry.is_file():
                continue
            if entry.name in (
                HUB_UPDATE_SCRIPT_NAME,
                HUB_UPDATE_SCRIPT_NAME_WINDOWS,
                HUB_UPDATE_LOG_NAME,
                HUB_UPDATE_PID_NAME,
            ) or (entry.suffix in PACKAGE_SUFFIXES or entry.name.startswith(".tmp_")):
                entry.unlink(missing_ok=True)

    def _ensure_rollback(
        self, current: str, *, say: Callable[[str], None]
    ) -> Path | None:
        """The running version's package, fetched when a release carries it.

        Raises:
            HubUpdateError: ``rollback_fetch_failed`` when a release carries
                it and it could not be taken down whole.
        """
        rollback = self._rollback_path(current)
        if rollback.is_file():
            say(f"rollback {rollback.name} already here, checked")
            say(f"rollback package {current} ready")
            return rollback
        try:
            previous = self._checker.for_version(
                current, max_age_s=HUB_UPDATE_RELEASE_REUSE_S
            )
            if previous is None or not previous.has_package:
                say(f"no rollback package for {current}")
                return None
            digest = self._checker.digest_of(previous)
            say(
                f"downloading rollback {previous.asset_name}  "
                f"{_size_text(previous.asset_size)}"
            )
            received = self._download(
                previous.asset_url, rollback, total=previous.asset_size, say=say
            )
        except (OSError, ValueError) as error:
            raise HubUpdateError(
                HUB_UPDATE_REASON_ROLLBACK_FETCH_FAILED, detail=str(error)[:200]
            ) from error
        except HubUpdateError as error:
            raise HubUpdateError(
                HUB_UPDATE_REASON_ROLLBACK_FETCH_FAILED, **error.params
            ) from error
        if received != digest:
            rollback.unlink(missing_ok=True)
            raise HubUpdateError(
                HUB_UPDATE_REASON_ROLLBACK_FETCH_FAILED, name=rollback.name
            )
        say("checked")
        say(f"rollback package {current} ready")
        return rollback

    def _gate_units(self) -> tuple[str, ...]:
        if self._family_now() in HUB_UPDATE_FAMILY_OF_OS.values():
            return ()
        running = tuple(
            unit for unit in HUB_UPDATE_GATE_UNITS if self._state_of(unit) == "active"
        )
        return (HUB_UPDATE_PANEL_UNIT,) + running

    def _download(
        self, url: str, destination: Path, *, total: int, say: Callable[[str], None]
    ) -> str:
        """Take one file down beside its destination, then move it there.

        Returns:
            The sha256 of what arrived.

        Raises:
            HubUpdateError: ``package_fetch_failed``; nothing remains.
        """
        digest = hashlib.sha256()
        received = 0
        next_step = 1
        handle, temporary = tempfile.mkstemp(dir=destination.parent, prefix=".tmp_")
        try:
            with os.fdopen(handle, "wb") as sink, self._open_url(url) as source:
                while True:
                    chunk = source.read(DOWNLOAD_CHUNK_BYTES)
                    if not chunk:
                        break
                    received += len(chunk)
                    if received > HUB_UPDATE_FETCH_LIMIT_BYTES:
                        raise HubUpdateError(
                            HUB_UPDATE_REASON_PACKAGE_FETCH_FAILED,
                            detail=f"past {HUB_UPDATE_FETCH_LIMIT_BYTES} bytes",
                        )
                    sink.write(chunk)
                    digest.update(chunk)
                    while total and received * PROGRESS_STEPS >= next_step * total:
                        say(f"{next_step * 100 // PROGRESS_STEPS}%")
                        next_step += 1
                sink.flush()
                os.fsync(sink.fileno())
            os.chmod(temporary, HUB_UPDATE_PACKAGE_MODE)
            os.replace(temporary, destination)
        except OSError as error:
            Path(temporary).unlink(missing_ok=True)
            raise HubUpdateError(
                HUB_UPDATE_REASON_PACKAGE_FETCH_FAILED, detail=str(error)[:200]
            ) from error
        except HubUpdateError:
            Path(temporary).unlink(missing_ok=True)
            raise
        return digest.hexdigest()


def _render_system_script(
    plan: HubUpdatePlan,
    *,
    directory: Path,
    gate_timeout_s: int,
    poll_s: float,
    output_limit_bytes: int,
    agent_start_s: int,
    agent_wait_s: int,
) -> str:
    """The macOS sh or the Windows PowerShell an update runs. Pure."""
    install, _ = install_commands(plan.family, plan.package)
    rollback_install = ""
    if plan.rollback is not None:
        _, rollback_install = install_commands(plan.family, plan.rollback)
    if plan.family == "msi":
        template = SCRIPT_WINDOWS
        quote = _powershell_quote
        program_files = os.environ.get("ProgramFiles", HUB_UPDATE_PROGRAM_FILES_DEFAULT)
        values = {
            "@SERVICE@": quote(HUB_UPDATE_SERVICE_WINDOWS),
            "@NHUB@": quote(
                str(constants.UTILS_STATIC_ROOT / HUB_UPDATE_NHUB_NAME_WINDOWS)
            ),
            "@AGENT_COMMAND@": quote(
                "\\".join((program_files, *HUB_UPDATE_AGENT_COMMAND_WINDOWS))
            ),
            "@INSTALLED_CODES@": _powershell_list(
                str(code) for code in HUB_UPDATE_MSI_INSTALLED_CODES
            ),
            "@STAGES_SETTLED@": _powershell_list(
                quote(stage) for stage in HUB_UPDATE_STAGES_SETTLED
            ),
            "@STEPS@": _powershell_list(
                quote(line) for line in handed_over_steps(plan)
            ),
            "@MSI_MUTEX@": quote(HUB_UPDATE_MSI_MUTEX),
            "@MSI_BUSY@": str(HUB_UPDATE_MSI_BUSY_CODE),
            "@ROLLBACK_INSTALL@": rollback_install or "''",
        }
    else:
        template = SCRIPT_DARWIN
        quote = shlex.quote
        values = {
            "@SERVICE@": quote(HUB_UPDATE_SERVICE_DARWIN),
            "@PLIST@": quote(HUB_UPDATE_PLIST_DARWIN),
            "@NHUB@": quote(HUB_UPDATE_NHUB_DARWIN),
            "@AGENT_COMMAND@": quote(HUB_UPDATE_AGENT_COMMAND_DARWIN),
            "@AGENT_INSTALL@": INSTALL_COMMANDS["pkg"][0].replace("@PATH@", '"$AGENT"'),
            "@AGENT_JOB@": quote(f"system/{HUB_UPDATE_AGENT_UPDATE_UNIT}"),
            "@JOB@": quote(HUB_UPDATE_UNIT),
            "@STAGES_SETTLED@": "|".join(HUB_UPDATE_STAGES_SETTLED),
            "@STEPS@": quote("\n".join(handed_over_steps(plan))),
            "@ROLLBACK_INSTALL@": rollback_install or "false",
        }
    values.update(
        {
            "@UNIT@": HUB_UPDATE_UNIT,
            "@STATE@": quote(str(directory / HUB_UPDATE_STATE_NAME)),
            "@LOG@": quote(str(directory / HUB_UPDATE_LOG_NAME)),
            "@FROM@": quote(plan.from_version),
            "@TO@": quote(plan.to_version),
            "@PACKAGE@": quote(str(plan.package)),
            "@ROLLBACK@": quote(str(plan.rollback) if plan.rollback else ""),
            "@PORT@": quote(str(plan.port)),
            "@HTTPS_PORT@": quote(str(plan.https_port)),
            "@HEALTH_PATH@": quote(HUB_UPDATE_HEALTH_PATH),
            "@STARTED@": quote(plan.started_at),
            "@GATE_TIMEOUT@": str(int(gate_timeout_s)),
            "@POLL@": str(poll_s),
            "@OUTPUT_LIMIT@": str(int(output_limit_bytes)),
            "@SETTINGS@": quote(str(HUB_UPDATE_PANEL_SETTINGS_PATH)),
            "@AUTHORITY@": quote(str(HUB_UPDATE_PANEL_AUTHORITY_PATH)),
            "@AGENT_CACHE@": quote(str(AGENT_PACKAGE_CACHE_DIR)),
            "@AGENT_PATTERN@": quote(
                HUB_UPDATE_AGENT_PATTERNS[plan.family].format(version=plan.to_version)
            ),
            "@AGENT_START@": str(int(agent_start_s)),
            "@AGENT_WAIT@": str(int(agent_wait_s)),
            "@MANAGER@": quote(MANAGER_NAMES[plan.family]),
            "@STEP_DONE@": quote(HUB_UPDATE_STEP_DONE),
            "@INSTALL@": install,
            "@STAGE_INSTALLING@": quote(HUB_UPDATE_STAGE_INSTALLING),
            "@STAGE_INSTALLED@": quote(HUB_UPDATE_STAGE_INSTALLED),
            "@STAGE_ROLLING_BACK@": quote(HUB_UPDATE_STAGE_ROLLING_BACK),
            "@STAGE_ROLLED_BACK@": quote(HUB_UPDATE_STAGE_ROLLED_BACK),
            "@STAGE_FAILED@": quote(HUB_UPDATE_STAGE_FAILED),
            "@REASON_GATE_FAILED@": quote(HUB_UPDATE_REASON_GATE_FAILED),
            "@REASON_INSTALL_FAILED@": quote(HUB_UPDATE_REASON_INSTALL_FAILED),
        }
    )
    text = template
    for token, value in values.items():
        text = text.replace(token, value)
    return text


def _start_detached(command: list) -> int:
    """Start the Windows script with no window and outside the service's job.

    A job that refuses breakaway refuses the start; the script is then
    started with no window alone.

    Args:
        command: The argument vector.

    Returns:
        The started process's id.

    Raises:
        OSError: When the process cannot be started at all.
    """
    refusal = OSError("no creation flags to try")
    for flags in HUB_UPDATE_CREATION_FLAGS_WINDOWS:
        try:
            return subprocess.Popen(
                command,
                creationflags=flags,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
            ).pid
        except OSError as error:
            refusal = error
    raise refusal


def _powershell_quote(text: str) -> str:
    """One value as a PowerShell literal string."""
    return "'" + text.replace("'", "''") + "'"


def _powershell_list(items) -> str:
    """Values already written as PowerShell, as one array."""
    return "@(" + ", ".join(items) + ")"


def _filled(line: str, path: str) -> str:
    """One shell command line with its file and the lock it waits for named.

    Args:
        line: A line of :data:`INSTALL_COMMANDS` or :data:`LOCK_STEPS`.
        path: The file, already quoted for the shell.

    Returns:
        The line to run.
    """
    return (
        line.replace("@PATH@", path)
        .replace("@LOCK@", str(HUB_UPDATE_LOCK_TIMEOUT_S))
        .replace("@PACMAN_LOCK@", shlex.quote(HUB_UPDATE_PACMAN_LOCK_PATH))
        .replace("@DNF_LOCK@", shlex.quote(HUB_UPDATE_DNF_LOCK_TEXT))
        .replace("@STEP_WAITING@", shlex.quote(HUB_UPDATE_STEP_WAITING))
    )


def _open_url(url: str):
    """Open one download over the network.

    Args:
        url: What to read.

    Returns:
        The response, read in chunks and closed by the caller.

    Raises:
        OSError: If it cannot be reached.
    """
    request = urllib.request.Request(url, headers=HUB_UPDATE_HEADERS)
    return urllib.request.urlopen(
        request, timeout=HUB_UPDATE_FETCH_TIMEOUT_S, context=public_ssl_context()
    )


def _file_digest(path: Path) -> str:
    """The sha256 of a file on disk, empty when it cannot be read."""
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            while True:
                chunk = source.read(DIGEST_CHUNK_BYTES)
                if not chunk:
                    break
                digest.update(chunk)
    except OSError:
        return ""
    return digest.hexdigest()


def _device_of(path: Path) -> int:
    """The filesystem a path is on, read from its nearest existing parent."""
    return _existing_parent(path).stat().st_dev


def _existing_parent(path: Path) -> Path:
    """The path itself, or the nearest ancestor that exists."""
    candidate = path
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate


def _size_text(size: int) -> str:
    """A byte count as the steps say it, the way the panel's card shows it.

    Args:
        size: The count; a negative one is shown as nothing.

    Returns:
        Such as ``156 MB`` or ``4.2 MB``, the space a no-break one, the
        number rounded half up.
    """
    value = float(max(size, 0))
    unit = 0
    while value >= SIZE_STEP and unit < len(SIZE_UNITS) - 1:
        value /= SIZE_STEP
        unit += 1
    places = Decimal("0.1") if value < 10 and unit > 0 else Decimal("1")
    number = Decimal(value).quantize(places, rounding=ROUND_HALF_UP)
    return f"{number}{SIZE_SPACE}{SIZE_UNITS[unit]}"
