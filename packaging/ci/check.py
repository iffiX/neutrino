"""Install a built package where it runs, check it works, and take it away.

    python3 packaging/ci/check.py <target> <artifact>

Runs on: the host the target is for, as an administrator or with
passwordless sudo, since every check installs what it checks. The release
workflow runs it after each build; on a workstation it changes the machine
it runs on, so run it on a throwaway one.

The targets:

- ``agent_windows``: the .msi installs, the ``neutrino_agent`` service
  runs, ``nagent --version`` answers, RustDesk's files are in the agent's
  ``rustdesk`` folder with upstream's signature valid, and nothing of
  RustDesk's is registered or running: no ``RustDesk`` service, no uninstall
  entry, no ``Program Files\\RustDesk``, no process; removing it takes the
  service and the folder away, with a scheduled task and a firewall rule
  named as a module names them, and leaves a rule named as the hub names
  its own. Windows.
- ``client_windows``: the .msi installs, ``nclient --version`` answers,
  ``nclient status`` exits 1 unbound, the folder is on PATH, ``packet.dll``
  lies beside EasyTier's core, the EasyTier daemon runs, answers on its
  pipe and makes its state under ``Neutrino\\client\\state``, and removing
  it takes the folder and the daemon away. Windows.
- ``agent_macos``: the .pkg installs, its LaunchDaemon runs, ``nagent
  --version`` answers, its ``config`` is root's alone and its ``state`` open
  to every account, ``app/rustdesk/RustDesk.app`` passes ``codesign
  --verify --deep --strict`` and nothing of RustDesk's is loaded or running
  and nothing is under ``/Applications``, and ``nagent service uninstall
  --yes`` leaves no job,
  no ``nagent``, no receipt and no LaunchDaemon named as a module names
  them, and keeps one named as the hub names its own. macOS.
- ``client_macos``: the .pkg installs, ``nclient --version`` answers and
  ``nclient status`` exits 1 unbound. Where the runner's own account is at
  the screen, the app opened and the .pkg installed again leaves a new app
  running, and an install with the app quit opens none. macOS.
- ``hub_windows``: the .msi installs, ``nhub --version`` answers, the
  ``neutrino_hub`` service runs and serves the setup wizard on the panel's
  port, ``nhub setup --json`` sets a ``server`` hub up and installs its local
  agent, the service runs and the panel answers ``/api/hub/display``;
  ``nhub stop``, the hub and its agent are removed, and ``install.ps1``
  installs the same file again from a directory up to ``nhub --version``.
  Windows.
- ``hub_macos``: the same with the .pkg, its ``com.neutrino.hub`` job
  loaded and running, removed by hand, and
  ``install.sh``. macOS.
- ``client_android``: the apk installs on the running emulator, its main
  activity starts and its process is alive ten seconds later. Any host with
  ``adb`` and one emulator attached.
- ``linux``: a hub, agent or client .deb, .rpm or Arch package installs in a
  fresh container of its family and its command answers ``--version``; the
  hub's install prints the setup wizard's address with its token, and its
  agent cache holds the agent package of its own family and machine alone,
  none for Arch; the agent's RustDesk is at
  ``/usr/lib/neutrino/agent/rustdesk/rustdesk``, and no RustDesk unit and
  no ``/usr/bin/rustdesk`` came with it. Linux with podman or docker; another architecture needs QEMU registered with
  binfmt_misc.

Not pure: installs and removes packages.
"""

import argparse
import functools
import hashlib
import json
import os
import platform
import plistlib
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shared.constants import (  # noqa: E402
    PACKAGING_EARLIER_PACKAGES,
    PACKAGING_EARLIER_RELEASE_URL,
    PACKAGING_EARLIER_VERSION,
)

# Every check ends within this whole, and every command it runs within its
# own limit: past the whole, what the machine is doing is printed and the
# process ends, so a hung or a runaway step never outlives its job's runner.
CHECK_LIMIT_S = 25 * 60
CHECK_COMMAND_TIMEOUT_S = 5 * 60
CHECK_MSIEXEC_TIMEOUT_S = 15 * 60
# Every msiexec of a check runs with no interface and with the restart
# suppressed by the property too: ``/norestart`` is not applied to every
# form (``/f`` drops it), and a restart takes the runner away.
CHECK_MSIEXEC_QUIET = ("/quiet", "/norestart", "REBOOT=ReallySuppress")
# What msiexec answers when it finished but wants a restart, and the log
# lines that name what held a file.
CHECK_MSIEXEC_RESTART_CODES = (3010, 1641)
# The one restart an install over a released earlier package may want: that
# package's own removal stops its services without waiting for them, so a
# file of theirs can still be held when the new one is written.
CHECK_MSIEXEC_WANTED_RESTART = 3010
CHECK_EARLIER_RESTART_REASON = (
    "the earlier package's removal does not wait for its services, so Windows "
    "replaces a file they held at the next restart"
)
CHECK_MSIEXEC_HELD_PATTERNS = (
    "held in use",
    "in use by",
    "requires a system restart",
    "FilesInUse",
    "RESTART MANAGER",
)
# Where Windows keeps the files it is to replace at the next restart, and
# the mark of one of ours among them.
CHECK_PENDING_RENAMES_KEY = r"SYSTEM\CurrentControlSet\Control\Session Manager"
CHECK_PENDING_RENAMES_VALUE = "PendingFileRenameOperations"
CHECK_PENDING_RENAMES_MARK = "\\neutrino\\"
CHECK_SNAPSHOT_TIMEOUT_S = 60
CHECK_HEARTBEAT_S = 5 * 60
# The runner keeps its job only while it reaches GitHub. The watchdog dials
# this address every so often; after so many misses in a row it prints what
# the machine is doing, takes away what the check installed, and ends the
# check, so a package that cuts the network fails the step instead of
# losing the runner.
CHECK_NETWORK_PROBE = ("api.github.com", 443)
CHECK_NETWORK_EVERY_S = 30
CHECK_NETWORK_TIMEOUT_S = 5
CHECK_NETWORK_MISSES = 3
# What a Windows snapshot prints: the processes busiest by processor time and
# by memory, the client's services and tasks, the default routes and the
# adapters that are up, and the last lines of the client's logs.
CHECK_WINDOWS_SNAPSHOT = (
    "Get-Process | Sort-Object CPU -Descending | Select-Object -First 15 "
    "Name,Id,CPU,@{n='WorkingSetMB';e={[int]($_.WorkingSet64/1MB)}} | "
    "Format-Table -AutoSize | Out-String -Width 200; "
    "Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First 8 "
    "Name,Id,@{n='WorkingSetMB';e={[int]($_.WorkingSet64/1MB)}} | "
    "Format-Table -AutoSize | Out-String -Width 200; "
    "Get-Service Neutrino*, neutrino* -ErrorAction SilentlyContinue | "
    "Format-Table -AutoSize Name,Status | Out-String; "
    "Get-ScheduledTask -TaskName 'NeutrinoClientRelaunch_*' "
    "-ErrorAction SilentlyContinue | Format-Table -AutoSize TaskName,State | Out-String; "
    "Get-NetRoute -DestinationPrefix 0.0.0.0/0 -ErrorAction SilentlyContinue | "
    "Format-Table -AutoSize InterfaceAlias,NextHop,RouteMetric | Out-String; "
    "Get-NetAdapter -ErrorAction SilentlyContinue | Where-Object Status -eq 'Up' | "
    "Format-Table -AutoSize Name,InterfaceDescription | Out-String -Width 200; "
    'Get-ChildItem "$env:ProgramData\\Neutrino\\client\\log" -Filter *.log '
    "-ErrorAction SilentlyContinue | ForEach-Object { '--- ' + $_.Name; "
    "Get-Content $_.FullName -Tail 15 }"
)
CHECK_STARTED = time.monotonic()
# Where a check leaves what must outlive the machine it runs on: every
# progress line, each msiexec log, a snapshot after each phase, and what
# one phase hands the next. None writes nothing.
CHECK_EVIDENCE: "Path | None" = None
CHECK_PROGRESS_NAME = "progress.txt"
CHECK_STATE_NAME = "state.json"
# The Windows client check in phases, each one workflow step, so the step
# list alone says which phase a runner was lost in.
CLIENT_WINDOWS_PHASES = (
    "upgrade",
    "install",
    "installed",
    "repair",
    "marker",
    "remove",
)
# A line pushed off the machine as a commit status, best effort.
CHECK_STATUS_CONTEXT = "client_windows check"
CHECK_STATUS_TIMEOUT_S = 10
CHECK_STATUS_TEXT_CHARS = 140
# What takes away what a check has installed so far, run by the watchdog
# when the network is gone or the time is up.
CHECK_RESCUES: list = []

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALL_SCRIPTS_DIR = REPO_ROOT / "packaging" / "install"

# --- Windows ---
PROGRAM_FILES = Path(os.environ.get("ProgramFiles", "C:/Program Files"))
AGENT_WINDOWS_FOLDER = PROGRAM_FILES / "Neutrino" / "agent"
AGENT_WINDOWS_SERVICES = ("neutrino_agent",)
# Where the agent's 0.4.0 installed, which its upgrade takes away.
AGENT_WINDOWS_EARLIER_FOLDER = PROGRAM_FILES / "Neutrino Agent"
# The agent's copy of RustDesk, and what RustDesk's own install registers,
# which the agent's package does not.
AGENT_WINDOWS_RUSTDESK = AGENT_WINDOWS_FOLDER / "rustdesk" / "rustdesk.exe"
RUSTDESK_WINDOWS_FOLDER = PROGRAM_FILES / "RustDesk"
RUSTDESK_WINDOWS_SERVICE = "RustDesk"
RUSTDESK_WINDOWS_UNINSTALL_KEY = (
    "HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\RustDesk"
)
# Prints the copy's signature status, then whether RustDesk's uninstall
# entry exists, then whether a RustDesk process runs: one line, three words.
AGENT_WINDOWS_RUSTDESK_SCRIPT = (
    "$signature = (Get-AuthenticodeSignature -LiteralPath '{copy}').Status; "
    "$entry = Test-Path '{key}'; "
    "$running = [bool](Get-Process -Name rustdesk -ErrorAction SilentlyContinue); "
    "Write-Output (@($signature, $entry, $running) -join ' ')"
)
CLIENT_WINDOWS_FOLDER = PROGRAM_FILES / "Neutrino" / "client"
# Where the client's 0.4.0 installed, which its upgrade takes away.
CLIENT_WINDOWS_EARLIER_FOLDER = PROGRAM_FILES / "Neutrino Client"
PROGRAM_DATA = Path(os.environ.get("ProgramData", "C:/ProgramData"))
CLIENT_WINDOWS_EASYTIER_STATE = (
    PROGRAM_DATA / "Neutrino" / "client" / "state" / "easytier"
)
# The client's data folder, the folders under it whose access lists the check
# reads, and what an earlier build is made to have left there before the
# install: each readable by every person, as ProgramData's grants make it.
CLIENT_WINDOWS_DATA = PROGRAM_DATA / "Neutrino" / "client"
CLIENT_WINDOWS_DATA_FOLDERS = ("", "state", "log")
CLIENT_WINDOWS_DATA_NETBIRD = "state/netbird"
CLIENT_WINDOWS_DATA_LEFTOVERS = ("log/earlier_build.log", "state/earlier_build.txt")
# The relaunch tasks an upgrade starts, and the one the check plants in their
# name: run as SYSTEM, it writes a marker, which shows the installer's last
# step starts every such task. A runner has no signed-in person to start a
# client for.
CLIENT_WINDOWS_RELAUNCH_TASKS = "NeutrinoClientRelaunch_*"
CLIENT_WINDOWS_RELAUNCH_PLANTED = "NeutrinoClientRelaunch_cicheck"
CLIENT_WINDOWS_RELAUNCH_MARKER = Path(tempfile.gettempdir()) / "relaunch_marker.txt"
CLIENT_WINDOWS_RELAUNCH_WAIT_S = 60
# The repair, as the product's own reinstall runs it: the agent's self-update
# writes the same properties.
CLIENT_WINDOWS_REPAIR_PROPERTIES = ("REINSTALL=ALL", "REINSTALLMODE=vomus")
CLIENT_WINDOWS_EASYTIER_SERVICE = "NeutrinoClientEasytier"
# Every service a client package may register, stopped first by a rescue.
CLIENT_WINDOWS_SERVICES = (
    "NeutrinoClientNetbird",
    "NeutrinoClientEasytier",
    "NeutrinoClientFiles",
)
CLIENT_WINDOWS_EASYTIER_PIPE = "neutrino_client_easytier"
# What ``sc query`` exits with for a service that does not exist.
SERVICE_DOES_NOT_EXIST = 1060
# How long a service is given to start, or to go after removal.
SERVICE_WAIT_S = 120
SERVICE_POLL_S = 5
MACHINE_ENVIRONMENT_KEY = (
    r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"
)
HUB_WINDOWS_FOLDER = PROGRAM_FILES / "Neutrino" / "hub"
HUB_WINDOWS_SERVICE = "neutrino_hub"
# Where an installed hub keeps its configuration and the vault in it; nothing
# named config may stand under Program Files, where a checkout would keep it.
HUB_WINDOWS_CONFIG = PROGRAM_DATA / "Neutrino" / "hub" / "config"
HUB_WINDOWS_VAULT = HUB_WINDOWS_CONFIG / "credentials" / "vault.json"
# The accounts an access list must not name on the vault: every person on the
# machine, by their names in an English Windows and by their SIDs.
WINDOWS_EVERY_PERSON = (
    "BUILTIN\\Users",
    "Authenticated Users",
    "Everyone",
    "S-1-5-32-545",
    "S-1-5-11",
    "S-1-1-0",
)
UNINSTALL_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
# A task and a rule named as a module names them, which removing the agent
# takes away, and a rule named as the hub names its own, which it leaves.
AGENT_WINDOWS_ADDED_TASK = "neutrino_check_task"
AGENT_WINDOWS_ADDED_RULE = "neutrino_check_rule"
AGENT_WINDOWS_FOREIGN_RULE = "neutrino_hub_check_rule"
AGENT_WINDOWS_PLANT_SCRIPT = (
    "Register-ScheduledTask -TaskName {task} -User SYSTEM -Force "
    "-Action (New-ScheduledTaskAction -Execute cmd.exe -Argument '/c exit') "
    "| Out-Null; "
    "foreach ($rule in @('{rule}', '{foreign}')) {{ "
    "New-NetFirewallRule -Name $rule -DisplayName $rule -Direction Inbound "
    "-Action Allow -Protocol TCP -LocalPort 59999 | Out-Null }}"
)
AGENT_WINDOWS_FOUND_SCRIPT = (
    "$task = [bool](Get-ScheduledTask -TaskName {task} -ErrorAction "
    "SilentlyContinue); "
    "$rule = [bool](Get-NetFirewallRule -Name {rule} -ErrorAction "
    "SilentlyContinue); "
    "$foreign = [bool](Get-NetFirewallRule -Name {foreign} -ErrorAction "
    "SilentlyContinue); "
    'Write-Output "$task $rule $foreign"'
)

# --- macOS ---
AGENT_MACOS_JOB = "system/com.neutrino.agent"
CLIENT_MACOS_APP = "/Applications/Neutrino Client.app"
CLIENT_MACOS_PROGRAM = CLIENT_MACOS_APP + "/Contents/MacOS/nclient"
# How long the app is given to come up or to go, and how long an install
# with no app running is watched for one that opens.
CLIENT_MACOS_APP_WAIT_S = 60
CLIENT_MACOS_QUIET_S = 10
# The agent's two roots the postinstall makes, and their modes: what the
# hub decided is root's alone, what the machine accumulated is open to
# every account for the software the hub sends.
AGENT_MACOS_ROOT_MODES = {
    "/Library/Application Support/Neutrino/agent/config": 0o700,
    "/Library/Application Support/Neutrino/agent/state": 0o755,
}
AGENT_MACOS_LEFTOVERS = (
    "/Library/Application Support/Neutrino/agent",
    "/Library/Logs/Neutrino/agent",
    "/Applications/RustDesk.app",
    "/usr/local/bin/nagent",
    "/Library/LaunchDaemons/com.neutrino.agent.plist",
    "/Library/LaunchDaemons/com.carriez.RustDesk_service.plist",
    "/Library/LaunchAgents/com.carriez.RustDesk_server.plist",
)
AGENT_MACOS_PACKAGE_ID = "com.neutrino.agent"
AGENT_MACOS_COMMAND = "/usr/local/bin/nagent"
# The agent's copy of RustDesk, RustDesk's two jobs, which the package does
# not load, and where RustDesk's own install puts it, which the package
# leaves alone.
AGENT_MACOS_RUSTDESK_APP = (
    "/Library/Application Support/Neutrino/agent/app/rustdesk/RustDesk.app"
)
RUSTDESK_MACOS_JOBS = ("com.carriez.RustDesk_service", "com.carriez.RustDesk_server")
RUSTDESK_MACOS_STANDARD_APP = "/Applications/RustDesk.app"
RUSTDESK_MACOS_PLISTS = (
    "/Library/LaunchDaemons/com.carriez.RustDesk_service.plist",
    "/Library/LaunchAgents/com.carriez.RustDesk_server.plist",
)
# A LaunchDaemon named as a module names its jobs, which removing the agent
# takes away, and one named as the hub names its own, which it leaves.
AGENT_MACOS_ADDED_PLIST = Path("/Library/LaunchDaemons/com.neutrino.check.plist")
AGENT_MACOS_FOREIGN_PLIST = Path("/Library/LaunchDaemons/com.neutrino.hub_check.plist")
AGENT_MACOS_CHECK_PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" \
"http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>{label}</string>
<key>ProgramArguments</key><array><string>/usr/bin/true</string></array>
</dict></plist>
"""
HUB_MACOS_JOB = "system/com.neutrino.hub"
HUB_MACOS_COMMAND = "/usr/local/bin/nhub"
HUB_MACOS_PLIST = Path("/Library/LaunchDaemons/com.neutrino.hub.plist")
HUB_MACOS_LEFTOVERS = (
    "/Library/Application Support/Neutrino/hub",
    "/Library/Logs/Neutrino/hub",
    HUB_MACOS_COMMAND,
    str(HUB_MACOS_PLIST),
)
HUB_MACOS_PACKAGE_ID = "com.neutrino.hub"
HUB_MACOS_APP_INFO = Path("/Applications/Neutrino Hub.app/Contents/Info.plist")
# What the entry's first architecture is on each machine a runner is.
HUB_MACOS_APP_ARCHITECTURE = {"arm64": "arm64", "x86_64": "x86_64"}

# --- the hub, on both ---
# A server hub on the default ports with no proxy; setup installs the local
# agent from its own cache.
HUB_PANEL_URL = "http://127.0.0.1:8080/api/hub/display"
# Before setup the service serves the wizard there: the page, and its API
# refusing a request with no token.
HUB_WIZARD_PAGE_URL = "http://127.0.0.1:8080/"
HUB_WIZARD_API_URL = "http://127.0.0.1:8080/api/hub/setup/context"
HUB_WIZARD_REFUSAL = 403
HUB_PANEL_WAIT_S = 180
HUB_PANEL_POLL_S = 5

# --- Android ---
ANDROID_ACTIVITY = "io.github.iffix.neutrino/.MainActivity"
ANDROID_PACKAGE = "io.github.iffix.neutrino"
ANDROID_SETTLE_S = 10

# --- Linux ---
# The container each format installs in, and how it installs a local file.
LINUX_INSTALLS = {
    ".deb": (
        "debian:12",
        "apt-get -qq update && apt-get -q install -y {package}",
    ),
    ".rpm": ("fedora:41", "dnf -y install {package}"),
    ".pkg.tar.zst": (
        "archlinux:latest",
        "pacman -Sy --noconfirm >/dev/null && pacman -U --noconfirm {package}",
    ),
}
# The sentence the hub's post-install prints, which the package manager must
# let through for the address beside it to be seen.
HUB_INSTALLED_SENTENCE = "Neutrino Hub installed"
# Where an installed Linux hub carries its one agent package, and the prefix
# each file in it is listed under.
HUB_AGENT_CACHE_DIR = "/var/lib/neutrino/hub/agent_cache"
HUB_AGENT_CACHE_LINE = "agent cache: "
# The hub package kinds that carry an agent package of their own family.
HUB_AGENT_CARRYING_SUFFIXES = (".deb", ".rpm")
# What an installed agent package must hold of RustDesk, its copy, and
# what it must not, a unit or a name on the path: each one sentence on the
# error stream when it fails.
AGENT_LINUX_RUSTDESK = "/usr/lib/neutrino/agent/rustdesk/rustdesk"
AGENT_LINUX_RUSTDESK_ABSENT = (
    "/lib/systemd/system/rustdesk.service",
    "/usr/lib/systemd/system/rustdesk.service",
    "/etc/systemd/system/rustdesk.service",
    "/usr/bin/rustdesk",
)
AGENT_LINUX_RUSTDESK_CHECK = (
    f"{{ test -x {AGENT_LINUX_RUSTDESK} || "
    f'{{ echo "the agent\'s package laid down no {AGENT_LINUX_RUSTDESK}" >&2; '
    "exit 1; }; } && "
    f"for found in {' '.join(AGENT_LINUX_RUSTDESK_ABSENT)}; do "
    'if [ -e "$found" ]; then '
    'echo "the agent\'s package installed $found" >&2; exit 1; fi; done'
)
# The command each package puts on the path.
LINUX_COMMANDS = {
    "neutrino-hub": "nhub",
    "neutrino-agent": "nagent",
    "neutrino-client": "nclient",
}
# A package file's name: the package, then the machine after its version.
LINUX_PACKAGE_NAME = re.compile(
    r"^(neutrino-hub|neutrino-agent|neutrino-client)[_-][0-9][^_]*?[_.-]"
    r"(?:1[.-])?(amd64|x86_64|arm64|aarch64)\."
)
# The container platform for each spelling of a machine in a file name.
LINUX_PLATFORMS = {
    "amd64": "linux/amd64",
    "x86_64": "linux/amd64",
    "arm64": "linux/arm64",
    "aarch64": "linux/arm64",
}


def main() -> int:
    """Run one target's check.

    Returns:
        The process exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("target", choices=sorted(CHECKS), help="what was built")
    parser.add_argument("artifact", help="the package file")
    parser.add_argument(
        "--phase",
        choices=CLIENT_WINDOWS_PHASES,
        default="",
        help="client_windows only: run one phase; every phase in order without",
    )
    parser.add_argument(
        "--evidence-dir",
        default="",
        help="where progress, msiexec logs and snapshots are kept as they come",
    )
    arguments = parser.parse_args()
    global CHECK_EVIDENCE
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(line_buffering=True)
    if arguments.evidence_dir:
        CHECK_EVIDENCE = Path(arguments.evidence_dir).resolve()
        CHECK_EVIDENCE.mkdir(parents=True, exist_ok=True)
    threading.Thread(target=_watchdog, name="check_watchdog", daemon=True).start()
    artifact = Path(arguments.artifact).resolve()
    if not artifact.is_file():
        raise SystemExit(f"{artifact} is not a file")
    if arguments.phase:
        if arguments.target != "client_windows":
            raise SystemExit("--phase is for client_windows alone")
        run_client_windows_phase(artifact, arguments.phase)
        print(f"{arguments.target} {arguments.phase}: {artifact.name} passed")
        return 0
    CHECKS[arguments.target](artifact)
    print(f"{arguments.target}: {artifact.name} passed")
    return 0


def check_agent_windows(msi: Path) -> None:
    """Upgrade the released 0.4.0 agent with the agent's .msi and take it
    away, then install the .msi on its own, check both services, and remove
    it.

    Args:
        msi: The installer.

    Raises:
        SystemExit: When a step fails.
    """
    _require_host("win32", "Windows")
    _agent_windows_upgrade(msi)
    log = Path(tempfile.gettempdir()) / "agent_install.log"
    code = _msiexec("/i", msi, log)
    print(f"msiexec /i exited {code}")
    if code != 0:
        _print_log(log, ("return value 3", "Error "), 40)
        raise SystemExit(f"the agent did not install (exit {code})")
    _check_no_pending_rename()
    if AGENT_WINDOWS_FOLDER.is_dir():
        print(
            f"{AGENT_WINDOWS_FOLDER}: "
            f"{', '.join(sorted(p.name for p in AGENT_WINDOWS_FOLDER.iterdir()))}"
        )
    _check_rustdesk_windows()
    for service in AGENT_WINDOWS_SERVICES:
        state = _service_state(service)
        print(f"{service} {state}")
        if "RUNNING" not in state:
            raise SystemExit(f"{service} is not running")
    print(f"nagent {_answer([str(AGENT_WINDOWS_FOLDER / 'nagent.exe'), '--version'])}")
    names = {
        "task": AGENT_WINDOWS_ADDED_TASK,
        "rule": AGENT_WINDOWS_ADDED_RULE,
        "foreign": AGENT_WINDOWS_FOREIGN_RULE,
    }
    _powershell(AGENT_WINDOWS_PLANT_SCRIPT.format(**names))
    if _powershell(AGENT_WINDOWS_FOUND_SCRIPT.format(**names)) != "True True True":
        raise SystemExit("the task and the rules to remove were not made")

    log = Path(tempfile.gettempdir()) / "agent_remove.log"
    print(f"msiexec /x exited {_msiexec('/x', msi, log)}")
    _print_log(log, ("UninstallAdded", "return value 3"), 12)
    for service in AGENT_WINDOWS_SERVICES:
        if not _wait_for_service(service, is_running=False):
            raise SystemExit(f"{service} outlived the uninstaller")
        print(f"{service} is gone")
    if AGENT_WINDOWS_RUSTDESK.parent.exists():
        raise SystemExit(f"{AGENT_WINDOWS_RUSTDESK.parent} outlived the uninstaller")
    found = _powershell(AGENT_WINDOWS_FOUND_SCRIPT.format(**names))
    _powershell(f"Remove-NetFirewallRule -Name {AGENT_WINDOWS_FOREIGN_RULE}")
    if found != "False False True":
        raise SystemExit(
            f"after the removal the task, the rule and the hub's rule read {found}; "
            "expected False False True"
        )
    print("the module's task and rule are gone, the hub's rule stays")


def _agent_windows_upgrade(msi: Path) -> None:
    """Install the .msi over the released earlier agent, check that the
    earlier one and the RustDesk it installed are gone, and take the agent
    away again with whatever restart the upgrade left owed.

    Raises:
        SystemExit: When the earlier agent left no RustDesk, the upgrade
            fails, or something of the earlier one outlives it.
    """
    _install_earlier("agent_windows")
    if not RUSTDESK_WINDOWS_FOLDER.is_dir():
        raise SystemExit(
            f"the earlier agent left no {RUSTDESK_WINDOWS_FOLDER} for the upgrade "
            "to take away"
        )
    log = Path(tempfile.gettempdir()) / "agent_upgrade.log"
    code = _msiexec("/i", msi, log, is_restart_accepted=True)
    _print_log(log, ("RemoveOldRustDesk", "return value 3", "Error 2"), 40)
    if code not in (0, CHECK_MSIEXEC_WANTED_RESTART):
        raise SystemExit(
            f"the agent did not install over its {PACKAGING_EARLIER_VERSION} "
            f"(exit {code})"
        )
    if AGENT_WINDOWS_EARLIER_FOLDER.exists():
        raise SystemExit(f"{AGENT_WINDOWS_EARLIER_FOLDER} outlived the upgrade")
    if not _wait_for_earlier_rustdesk_gone():
        raise SystemExit(
            f"the upgrade left the earlier agent's {RUSTDESK_WINDOWS_FOLDER} "
            "or its service"
        )
    print(f"the agent installed over its {PACKAGING_EARLIER_VERSION}")
    _take_upgrade_away(msi, "agent_windows", AGENT_WINDOWS_FOLDER)


def _wait_for_earlier_rustdesk_gone() -> bool:
    """Wait for upstream's uninstall, which ends in a script of its own, to
    take the earlier agent's RustDesk service and folder away.

    Returns:
        Whether both were gone in time.
    """
    deadline = time.monotonic() + SERVICE_WAIT_S
    while time.monotonic() < deadline:
        if not (
            _service_exists(RUSTDESK_WINDOWS_SERVICE)
            or RUSTDESK_WINDOWS_FOLDER.exists()
        ):
            return True
        time.sleep(SERVICE_POLL_S)
    return False


def _check_rustdesk_windows() -> None:
    """Check that the agent's .msi laid RustDesk's files down and nothing more.

    Raises:
        SystemExit: When the copy is missing or its signature is not valid,
            or RustDesk's service, folder, uninstall entry or process is
            there.
    """
    problem = windows_rustdesk_problem(
        is_copy_there=AGENT_WINDOWS_RUSTDESK.is_file(),
        answer=(
            _powershell(
                AGENT_WINDOWS_RUSTDESK_SCRIPT.format(
                    copy=AGENT_WINDOWS_RUSTDESK, key=RUSTDESK_WINDOWS_UNINSTALL_KEY
                )
            )
            if AGENT_WINDOWS_RUSTDESK.is_file()
            else ""
        ),
        is_service_there=_service_exists(RUSTDESK_WINDOWS_SERVICE),
        is_standard_folder_there=RUSTDESK_WINDOWS_FOLDER.exists(),
    )
    if problem:
        raise SystemExit(problem)
    print(f"{AGENT_WINDOWS_RUSTDESK}: signature Valid, nothing registered or running")


def windows_rustdesk_problem(
    *,
    is_copy_there: bool,
    answer: str,
    is_service_there: bool,
    is_standard_folder_there: bool,
) -> str:
    """What is wrong with RustDesk after the agent's .msi installed.

    Args:
        is_copy_there: Whether ``rustdesk.exe`` is in the agent's folder.
        answer: What :data:`AGENT_WINDOWS_RUSTDESK_SCRIPT` printed: the
            copy's signature status, whether RustDesk's uninstall entry
            exists, and whether a RustDesk process runs.
        is_service_there: Whether a ``RustDesk`` service exists.
        is_standard_folder_there: Whether ``Program Files\\RustDesk`` exists.

    Returns:
        The one sentence naming the first fault, or an empty string.
    """
    if not is_copy_there:
        return f"the agent's .msi laid down no {AGENT_WINDOWS_RUSTDESK}"
    signature, entry, running = answer.split()
    if signature != "Valid":
        return f"{AGENT_WINDOWS_RUSTDESK}'s signature is {signature}, not Valid"
    if is_service_there:
        return "the agent's .msi registered RustDesk's service"
    if entry == "True":
        return "the agent's .msi left RustDesk's uninstall entry"
    if is_standard_folder_there:
        return f"the agent's .msi installed {RUSTDESK_WINDOWS_FOLDER}"
    if running == "True":
        return "a RustDesk process runs after the agent's .msi installed"
    return ""


def check_client_windows(msi: Path) -> None:
    """Install the client's .msi, use it, repair it, and remove it: every phase in order.

    Args:
        msi: The installer.

    Raises:
        SystemExit: When a step fails.
    """
    for phase in CLIENT_WINDOWS_PHASES:
        run_client_windows_phase(msi, phase)


def run_client_windows_phase(msi: Path, phase: str) -> None:
    """Run one phase of the Windows client check and leave its evidence.

    The phase before must have passed, as the state file records; whatever
    the phase comes to, a snapshot of the machine is left beside its
    msiexec log.

    Args:
        msi: The installer.
        phase: One of ``CLIENT_WINDOWS_PHASES``.

    Raises:
        SystemExit: When the phase before did not pass, or this one fails.
    """
    _require_host("win32", "Windows")
    index = CLIENT_WINDOWS_PHASES.index(phase)
    passed = _read_state().get("passed", [])
    if index and CLIENT_WINDOWS_PHASES[index - 1] not in passed:
        raise SystemExit(
            f"phase {phase} needs {CLIENT_WINDOWS_PHASES[index - 1]} to have passed"
        )
    if phase != "install":
        CHECK_RESCUES.append(
            functools.partial(
                _remove_windows_package, msi, services=CLIENT_WINDOWS_SERVICES
            )
        )
    _note(f"{phase}: starting")
    try:
        CLIENT_WINDOWS_PHASE_RUNS[phase](msi)
    finally:
        _keep_snapshot(f"{phase}.snapshot.txt")
    _write_state({"passed": [*passed, phase]})
    _note(f"{phase}: passed")


def _client_windows_upgrade(msi: Path) -> None:
    """Install over the released 0.4.0, check the earlier one is gone, and
    take the client away with whatever restart the upgrade left owed."""
    _note(f"upgrade: the client's {PACKAGING_EARLIER_VERSION} first")
    _install_earlier("client_windows")
    log = _phase_log("upgrade")
    code = _msiexec("/i", msi, log, is_restart_accepted=True)
    nclient = CLIENT_WINDOWS_FOLDER / "nclient.exe"
    if code not in (0, CHECK_MSIEXEC_WANTED_RESTART) or not nclient.is_file():
        _print_log(log, ("return value 3", "Error 19"), 25)
        raise SystemExit(
            f"the client did not install over its {PACKAGING_EARLIER_VERSION} "
            f"(exit {code})"
        )
    if CLIENT_WINDOWS_EARLIER_FOLDER.exists():
        raise SystemExit(f"{CLIENT_WINDOWS_EARLIER_FOLDER} outlived the upgrade")
    _note("upgrade: taking the client away")
    _take_upgrade_away(msi, "client_windows", CLIENT_WINDOWS_FOLDER)


def _client_windows_install(msi: Path) -> None:
    """Install over what an earlier build is made to have left."""
    _note("install: planting what an earlier build left")
    _plant_client_windows_leftovers()
    CHECK_RESCUES.append(
        functools.partial(
            _remove_windows_package, msi, services=CLIENT_WINDOWS_SERVICES
        )
    )
    log = _phase_log("install")
    code = _msiexec("/i", msi, log)
    nclient = CLIENT_WINDOWS_FOLDER / "nclient.exe"
    if code != 0 or not nclient.is_file():
        _print_log(
            log, ("return value 3", "Error 19", CLIENT_WINDOWS_EASYTIER_SERVICE), 25
        )
        raise SystemExit("the client did not install")
    _check_no_pending_rename()


def _client_windows_installed(msi: Path) -> None:
    """What the install left: the command, PATH, the daemon, the data tree."""
    nclient = CLIENT_WINDOWS_FOLDER / "nclient.exe"
    print(f"nclient {_answer([str(nclient), '--version'])}")
    _note("installed: nclient status")
    status = subprocess.run(
        [str(nclient), "status"], timeout=CHECK_COMMAND_TIMEOUT_S
    ).returncode
    if status != 1:
        raise SystemExit(f"nclient status exited {status}, expected 1")
    if "Neutrino\\client" not in _machine_path():
        raise SystemExit("the install is not on PATH")
    if not (CLIENT_WINDOWS_FOLDER / "bin" / "packet.dll").is_file():
        raise SystemExit("no packet.dll beside easytier-core.exe")
    if not _wait_for_service(CLIENT_WINDOWS_EASYTIER_SERVICE, is_running=True):
        raise SystemExit("the EasyTier daemon is not running")
    if CLIENT_WINDOWS_EASYTIER_PIPE not in os.listdir("\\\\.\\pipe\\"):
        raise SystemExit("the EasyTier daemon has no pipe")
    if not CLIENT_WINDOWS_EASYTIER_STATE.is_dir():
        raise SystemExit(f"no EasyTier state at {CLIENT_WINDOWS_EASYTIER_STATE}")
    _note("installed: the data tree's access lists")
    _check_client_windows_data()
    _note("installed: no relaunch task and no window")
    _check_client_windows_nothing_started()


def _check_client_windows_nothing_started() -> None:
    """An install over no running client left no relaunch task and started no window.

    Raises:
        SystemExit: When it did.
    """
    if _relaunch_tasks():
        raise SystemExit(f"the install left relaunch tasks: {_relaunch_tasks()}")
    windows = _answer(["tasklist", "/fi", "imagename eq nclientw.exe", "/fo", "csv"])
    if "nclientw.exe" in windows.lower():
        raise SystemExit("an install over no running client started one")


def _client_windows_repair(msi: Path) -> None:
    """Plant a relaunch task of SYSTEM's and run the repair, which starts it."""
    _note("repair: planting the relaunch task")
    CLIENT_WINDOWS_RELAUNCH_MARKER.unlink(missing_ok=True)
    _answer(
        [
            "schtasks",
            "/create",
            "/tn",
            CLIENT_WINDOWS_RELAUNCH_PLANTED,
            "/tr",
            f'cmd.exe /c echo started > "{CLIENT_WINDOWS_RELAUNCH_MARKER}"',
            "/sc",
            "once",
            "/st",
            "00:00",
            "/ru",
            "SYSTEM",
            "/f",
        ]
    )
    _note("repair: msiexec /i REINSTALL=ALL starting")
    code = _msiexec(
        "/i", msi, _phase_log("repair"), properties=CLIENT_WINDOWS_REPAIR_PROPERTIES
    )
    _note(f"repair: msiexec /i REINSTALL=ALL exited {code}")
    if code != 0:
        raise SystemExit(f"the reinstall exited {code}")
    _check_no_pending_rename()


def _client_windows_marker(msi: Path) -> None:
    """The planted task wrote its marker: the repair's last step started it."""
    _note("marker: waiting")
    deadline = time.monotonic() + CLIENT_WINDOWS_RELAUNCH_WAIT_S
    while not CLIENT_WINDOWS_RELAUNCH_MARKER.is_file():
        if time.monotonic() >= deadline:
            _print_log(_phase_log("repair"), ("RelaunchClients", "WixQuietExec"), 10)
            raise SystemExit("the repair did not start the relaunch task")
        time.sleep(SERVICE_POLL_S)
    CLIENT_WINDOWS_RELAUNCH_MARKER.unlink(missing_ok=True)
    print("the repair started the relaunch task")


def _client_windows_remove(msi: Path) -> None:
    """The removal takes the folder, the daemon and every relaunch task."""
    code = _msiexec("/x", msi, _phase_log("remove"))
    _note(f"remove: msiexec /x exited {code}")
    if CLIENT_WINDOWS_FOLDER.exists():
        raise SystemExit("the folder outlived the uninstaller")
    if _service_exists(CLIENT_WINDOWS_EASYTIER_SERVICE):
        raise SystemExit("the EasyTier daemon outlived the uninstaller")
    if _relaunch_tasks():
        raise SystemExit(
            f"relaunch tasks outlived the uninstaller: {_relaunch_tasks()}"
        )


CLIENT_WINDOWS_PHASE_RUNS = {
    "upgrade": _client_windows_upgrade,
    "install": _client_windows_install,
    "installed": _client_windows_installed,
    "repair": _client_windows_repair,
    "marker": _client_windows_marker,
    "remove": _client_windows_remove,
}


def _phase_log(phase: str) -> Path:
    """Where one phase's msiexec log goes: the evidence, else the temporary directory."""
    root = CHECK_EVIDENCE or Path(tempfile.gettempdir())
    return root / f"client_{phase}.msiexec.log"


def _read_state() -> dict:
    """What earlier phases handed on; empty without evidence or before the first."""
    if CHECK_EVIDENCE is None:
        return {"passed": list(_PASSED_HERE)}
    try:
        return json.loads((CHECK_EVIDENCE / CHECK_STATE_NAME).read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def _write_state(state: dict) -> None:
    """Hand the next phase what this one leaves."""
    _PASSED_HERE[:] = state.get("passed", [])
    if CHECK_EVIDENCE is not None:
        (CHECK_EVIDENCE / CHECK_STATE_NAME).write_text(json.dumps(state), "utf-8")


# The phases passed in this process, for a run with no evidence directory.
_PASSED_HERE: list = []


def _note(text: str) -> None:
    """One progress line, kept on disk at once and pushed off the machine, best effort."""
    _say(text)
    _push_status(text)


def _push_status(text: str) -> None:
    """Post one line as a commit status of this run's commit. Never raises.

    Needs ``GITHUB_TOKEN``, ``GITHUB_REPOSITORY`` and ``GITHUB_SHA``, and the
    job's ``statuses: write``; without them nothing is sent.
    """
    token = os.environ.get("GITHUB_TOKEN", "")
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    commit = os.environ.get("GITHUB_SHA", "")
    if not (token and repository and commit):
        return
    body = json.dumps(
        {
            "state": "pending",
            "context": CHECK_STATUS_CONTEXT,
            "description": text[:CHECK_STATUS_TEXT_CHARS],
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repository}/statuses/{commit}",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        },
    )
    try:
        urllib.request.urlopen(request, timeout=CHECK_STATUS_TIMEOUT_S).close()
    except Exception as error:  # noqa: BLE001 - best effort, never fails a step
        print(f"the status was not posted: {type(error).__name__}", flush=True)


def _keep_snapshot(name: str) -> None:
    """Write what the machine is doing into the evidence. Never raises."""
    if CHECK_EVIDENCE is None:
        return
    try:
        (CHECK_EVIDENCE / name).write_text(_snapshot(), "utf-8")
    except OSError as error:
        print(f"the snapshot was not kept: {error}", flush=True)


def _relaunch_tasks() -> list:
    """The names of the relaunch tasks that stand."""
    names = _powershell(
        f"Get-ScheduledTask -TaskName '{CLIENT_WINDOWS_RELAUNCH_TASKS}' "
        "-ErrorAction SilentlyContinue | ForEach-Object { $_.TaskName }"
    )
    return [name for name in names.splitlines() if name.strip()]


def _plant_client_windows_leftovers() -> None:
    """Leave what an earlier build would have, with ProgramData's grants on it."""
    for relative in CLIENT_WINDOWS_DATA_LEFTOVERS:
        path = CLIENT_WINDOWS_DATA / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("left by an earlier build\n", encoding="utf-8")


def _check_client_windows_data() -> None:
    """Every folder and file under the client's data folder is closed to people.

    Raises:
        SystemExit: When a folder the check names is missing, or an access
            list under the data folder names an account every person is in.
    """
    paths = [CLIENT_WINDOWS_DATA / relative for relative in CLIENT_WINDOWS_DATA_FOLDERS]
    netbird = CLIENT_WINDOWS_DATA / CLIENT_WINDOWS_DATA_NETBIRD
    if netbird.is_dir():
        paths.append(netbird)
    paths += [
        CLIENT_WINDOWS_DATA / relative for relative in CLIENT_WINDOWS_DATA_LEFTOVERS
    ]
    for path in paths:
        if not path.exists():
            raise SystemExit(f"no {path} after the install")
        access = _answer(["icacls", str(path)])
        print(access)
        named = [account for account in WINDOWS_EVERY_PERSON if account in access]
        if named:
            raise SystemExit(f"{path} is open to {', '.join(named)}")


def check_agent_macos(pkg: Path) -> None:
    """Install the agent's .pkg, check its job, and remove it.

    Args:
        pkg: The installer.

    Raises:
        SystemExit: When a step fails.
    """
    _require_host("darwin", "macOS")
    _sudo(["installer", "-pkg", str(pkg), "-target", "/"])
    job = _answer(["sudo", "launchctl", "print", AGENT_MACOS_JOB])
    if "state = running" not in job:
        raise SystemExit(f"{AGENT_MACOS_JOB} is not running")
    print(f"nagent {_answer(['/usr/local/bin/nagent', '--version'])}")
    problem = _macos_rustdesk_problem()
    if problem:
        raise SystemExit(problem)
    print(f"{AGENT_MACOS_RUSTDESK_APP}: signature valid, nothing loaded or running")
    for directory, mode in AGENT_MACOS_ROOT_MODES.items():
        found = os.stat(directory).st_mode & 0o777
        if found != mode:
            raise SystemExit(f"{directory} is mode {found:o}, expected {mode:o}")
    for plist in (AGENT_MACOS_ADDED_PLIST, AGENT_MACOS_FOREIGN_PLIST):
        written = Path(tempfile.gettempdir()) / plist.name
        written.write_text(AGENT_MACOS_CHECK_PLIST.format(label=plist.stem))
        _sudo(["cp", str(written), str(plist)])

    _sudo([AGENT_MACOS_COMMAND, "service", "uninstall", "--yes"])
    if not _wait_for_job_gone(AGENT_MACOS_JOB):
        raise SystemExit("the agent's job outlived its removal")
    is_forgotten = (
        subprocess.run(
            ["pkgutil", "--pkg-info", AGENT_MACOS_PACKAGE_ID], capture_output=True
        ).returncode
        != 0
    )
    is_added_gone = not AGENT_MACOS_ADDED_PLIST.exists()
    is_foreign_kept = AGENT_MACOS_FOREIGN_PLIST.exists()
    _sudo(["rm", "-f", str(AGENT_MACOS_FOREIGN_PLIST)])
    _sudo(["rm", "-rf", *AGENT_MACOS_LEFTOVERS])
    if Path(AGENT_MACOS_COMMAND).exists() or not is_forgotten:
        raise SystemExit("nagent or its receipt outlived nagent service uninstall")
    if not is_added_gone or not is_foreign_kept:
        raise SystemExit(
            "nagent service uninstall took the wrong LaunchDaemons: "
            f"the module's gone {is_added_gone}, the hub's kept {is_foreign_kept}"
        )


def _macos_rustdesk_problem() -> str:
    """What is wrong with RustDesk after the agent's .pkg installed.

    Returns:
        The one sentence naming the first fault, or an empty string.
    """
    if not Path(AGENT_MACOS_RUSTDESK_APP).is_dir():
        return f"the agent's .pkg laid down no {AGENT_MACOS_RUSTDESK_APP}"
    verified = subprocess.run(
        ["codesign", "--verify", "--deep", "--strict", AGENT_MACOS_RUSTDESK_APP],
        capture_output=True,
        text=True,
    )
    if verified.returncode != 0:
        return f"{AGENT_MACOS_RUSTDESK_APP}'s signature: {verified.stderr.strip()}"
    for job in RUSTDESK_MACOS_JOBS:
        if _is_job_loaded(f"system/{job}"):
            return f"the agent's .pkg loaded {job}"
    for plist in RUSTDESK_MACOS_PLISTS:
        if Path(plist).exists():
            return f"the agent's .pkg installed {plist}"
    if Path(RUSTDESK_MACOS_STANDARD_APP).exists():
        return f"the agent's .pkg installed {RUSTDESK_MACOS_STANDARD_APP}"
    running = subprocess.run(
        ["pgrep", "-f", "RustDesk.app/Contents/MacOS/"], capture_output=True
    )
    if running.returncode == 0:
        return "a RustDesk process runs after the agent's .pkg installed"
    return ""


def check_client_macos(pkg: Path) -> None:
    """Install the client's .pkg and use it.

    Args:
        pkg: The installer.

    Raises:
        SystemExit: When a step fails.
    """
    _require_host("darwin", "macOS")
    _sudo(["installer", "-pkg", str(pkg), "-target", "/"])
    print(f"nclient {_answer(['/usr/local/bin/nclient', '--version'])}")
    status = subprocess.run(["/usr/local/bin/nclient", "status"]).returncode
    if status != 1:
        raise SystemExit(f"nclient status exited {status}, expected 1")
    _check_client_macos_upgrade(pkg)


def _check_client_macos_upgrade(pkg: Path) -> None:
    """An upgrade over a running app leaves the new app running; an install
    with none running opens none.

    Checked only where this account is the one at the screen; elsewhere the
    install is the one asserted and the reopen is named as not checked.

    Args:
        pkg: The installer.

    Raises:
        SystemExit: When an upgrade leaves no new app, or an install opens
            one nobody had open.
    """
    if _console_uid() != os.getuid():
        print("this account is not at the screen: the reopen is not checked")
        return
    subprocess.run(["open", "-a", CLIENT_MACOS_APP])
    first = _wait_for_client_app(lambda pids: bool(pids))
    if not first:
        print("the app did not come up on this runner: the reopen is not checked")
        return
    _sudo(["installer", "-pkg", str(pkg), "-target", "/"])
    second = _wait_for_client_app(lambda pids: bool(pids) and not pids & first)
    if not second:
        raise SystemExit("after the upgrade no new client app runs")
    print(f"the client app ran as {sorted(first)} and runs as {sorted(second)}")
    subprocess.run([CLIENT_MACOS_PROGRAM, "quit"])
    if _wait_for_client_app(lambda pids: not pids) is None:
        raise SystemExit("the client app did not quit")
    _sudo(["installer", "-pkg", str(pkg), "-target", "/"])
    time.sleep(CLIENT_MACOS_QUIET_S)
    if _client_app_pids():
        raise SystemExit("an install with no client app running opened one")


def _console_uid() -> int:
    """The uid of the account at the screen, as the system configuration's
    console user names it; 0 for nobody. The owner of /dev/console answers
    only when scutil cannot be run."""
    try:
        printed = subprocess.run(
            ["/usr/sbin/scutil"],
            input="show State:/Users/ConsoleUser\n",
            capture_output=True,
            text=True,
        ).stdout
    except OSError:
        return os.stat("/dev/console").st_uid
    name = re.search(r"^\s*Name\s*:\s*(\S+)\s*$", printed, re.MULTILINE)
    uid = re.search(r"^\s*UID\s*:\s*(\d+)\s*$", printed, re.MULTILINE)
    if name is None or uid is None or name.group(1) in ("root", "loginwindow"):
        return 0
    return int(uid.group(1))


def _client_app_pids() -> set:
    """The client app's processes of this account."""
    result = subprocess.run(
        ["pgrep", "-U", str(os.getuid()), "-f", CLIENT_MACOS_PROGRAM],
        capture_output=True,
        text=True,
    )
    return {int(word) for word in result.stdout.split() if word.isdigit()}


def _wait_for_client_app(is_wanted) -> "set | None":
    """Wait until the client app's processes are what ``is_wanted`` takes.

    Returns:
        The processes then, or None when the wait ran out.
    """
    deadline = time.monotonic() + CLIENT_MACOS_APP_WAIT_S
    while True:
        pids = _client_app_pids()
        if is_wanted(pids):
            return pids
        if time.monotonic() >= deadline:
            return None
        time.sleep(1)


def check_hub_windows(msi: Path) -> None:
    """Install the hub's .msi, set it up, remove it, and install it by script.

    Args:
        msi: The installer.

    Raises:
        SystemExit: When a step fails.
    """
    _require_host("win32", "Windows")
    log = Path(tempfile.gettempdir()) / "hub_install.log"
    code = _msiexec("/i", msi, log)
    print(f"msiexec /i exited {code}")
    nhub = HUB_WINDOWS_FOLDER / "nhub.exe"
    if code != 0 or not nhub.is_file():
        _print_log(log, ("return value 3", "Error 19"), 25)
        raise SystemExit("the hub did not install")
    _check_no_pending_rename()
    print(f"nhub {_answer([str(nhub), '--version'])}")
    if not _service_exists(HUB_WINDOWS_SERVICE):
        raise SystemExit("the hub's service is not registered")
    if not _wait_for_service(HUB_WINDOWS_SERVICE, is_running=True):
        raise SystemExit("the hub's service is not running after install")
    _wait_for_wizard()

    _set_up_hub([str(nhub)])
    if not _wait_for_service(HUB_WINDOWS_SERVICE, is_running=True):
        raise SystemExit("the hub's service is not running after setup")
    _wait_for_panel()
    _check_hub_windows_config()
    _answer([str(nhub), "stop", "--yes"])

    log = Path(tempfile.gettempdir()) / "hub_remove.log"
    print(f"msiexec /x exited {_msiexec('/x', msi, log)}")
    if not _wait_for_service(HUB_WINDOWS_SERVICE, is_running=False):
        raise SystemExit("the hub's service outlived the uninstaller")
    if nhub.exists():
        raise SystemExit("the hub's program outlived the uninstaller")
    _remove_windows_product("Neutrino Agent")

    _run_install_script(
        msi,
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(INSTALL_SCRIPTS_DIR / "install.ps1"),
            "hub",
        ],
    )
    print(f"nhub by install.ps1 {_answer([str(nhub), '--version'])}")


def _check_hub_windows_config() -> None:
    """The set-up hub's configuration is under ProgramData and closed to people.

    Raises:
        SystemExit: When the vault is elsewhere, a configuration directory
            stands under Program Files, or the vault's access list names an
            account every person is in.
    """
    if not HUB_WINDOWS_VAULT.is_file():
        raise SystemExit(f"the hub wrote no vault at {HUB_WINDOWS_VAULT}")
    neutrino = PROGRAM_FILES / "Neutrino"
    stray = [*neutrino.glob("config"), *neutrino.glob("*/config")]
    if stray:
        raise SystemExit(
            f"configuration under Program Files: {[str(p) for p in stray]}"
        )
    access = _answer(["icacls", str(HUB_WINDOWS_VAULT)])
    print(access)
    named = [account for account in WINDOWS_EVERY_PERSON if account in access]
    if named:
        raise SystemExit(f"the vault is open to {', '.join(named)}")


def check_hub_macos(pkg: Path) -> None:
    """Install the hub's .pkg, set it up, remove it, and install it by script.

    Args:
        pkg: The installer.

    Raises:
        SystemExit: When a step fails.
    """
    _require_host("darwin", "macOS")
    _sudo(["installer", "-pkg", str(pkg), "-target", "/"])
    print(f"nhub {_answer([HUB_MACOS_COMMAND, '--version'])}")
    if not HUB_MACOS_PLIST.is_file():
        raise SystemExit("the hub's service is not registered")
    if not _is_job_loaded(HUB_MACOS_JOB):
        raise SystemExit("the hub's service is not loaded after install")
    _check_hub_macos_entry()
    _wait_for_wizard()

    _set_up_hub(["sudo", HUB_MACOS_COMMAND])
    job = _answer(["sudo", "launchctl", "print", HUB_MACOS_JOB])
    if "state = running" not in job:
        raise SystemExit(f"{HUB_MACOS_JOB} is not running after setup")
    _wait_for_panel()
    _sudo([HUB_MACOS_COMMAND, "stop", "--yes"])

    for job_name in (HUB_MACOS_JOB, AGENT_MACOS_JOB):
        subprocess.run(["sudo", "launchctl", "bootout", job_name])
    subprocess.run(
        ["sudo", "launchctl", "bootout", "system/com.carriez.RustDesk_service"]
    )
    _sudo(["rm", "-rf", *HUB_MACOS_LEFTOVERS, *AGENT_MACOS_LEFTOVERS])
    for package_id in (HUB_MACOS_PACKAGE_ID, AGENT_MACOS_PACKAGE_ID):
        subprocess.run(["sudo", "pkgutil", "--forget", package_id])
    if not _wait_for_job_gone(HUB_MACOS_JOB):
        raise SystemExit("the hub's job outlived its removal")

    _run_install_script(pkg, ["sh", str(INSTALL_SCRIPTS_DIR / "install.sh"), "hub"])
    print(f"nhub by install.sh {_answer([HUB_MACOS_COMMAND, '--version'])}")


def _check_hub_macos_entry() -> None:
    """The app entry declares this machine's architecture first, so a
    script executable opens without Rosetta.

    Raises:
        SystemExit: When the key is missing or names another machine first.
    """
    information = plistlib.loads(HUB_MACOS_APP_INFO.read_bytes())
    declared = information.get("LSArchitecturePriority") or []
    wanted = HUB_MACOS_APP_ARCHITECTURE.get(platform.machine(), "")
    if not declared or declared[0] != wanted:
        raise SystemExit(
            f"Neutrino Hub.app declares {declared}, expected {wanted} first"
        )
    print(f"Neutrino Hub.app declares {declared}")


def check_client_android(apk: Path) -> None:
    """Install the apk on the attached emulator and launch it once.

    Args:
        apk: The x86_64 apk.

    Raises:
        SystemExit: When a step fails.
    """
    if shutil.which("adb") is None:
        raise SystemExit("adb is needed and is not on the path")
    _answer(["adb", "install", "-r", str(apk)])
    print(_answer(["adb", "shell", "am", "start", "-W", "-n", ANDROID_ACTIVITY]))
    time.sleep(ANDROID_SETTLE_S)
    print(f"pid {_answer(['adb', 'shell', 'pidof', ANDROID_PACKAGE])}")


def check_linux(package: Path) -> None:
    """Install a Linux package in a fresh container and run its command.

    Args:
        package: The .deb, .rpm or .pkg.tar.zst.

    Raises:
        SystemExit: When no container tool is installed, the file is not a
            package this project builds, or the install or the command
            fails.
    """
    engine = next((n for n in ("podman", "docker") if shutil.which(n)), None)
    if engine is None:
        raise SystemExit("podman or docker is needed and neither is on the path")
    suffix = next((s for s in LINUX_INSTALLS if package.name.endswith(s)), None)
    match = LINUX_PACKAGE_NAME.match(package.name)
    if suffix is None or match is None:
        raise SystemExit(f"{package.name} is not a Linux package this project builds")
    command = LINUX_COMMANDS[match.group(1)]
    machine = match.group(2)
    image, install = LINUX_INSTALLS[suffix]
    inside = f"/package/{package.name}"
    script = install.format(package=inside)
    if command == LINUX_COMMANDS["neutrino-hub"]:
        script += (
            f" && {{ ls -1 {HUB_AGENT_CACHE_DIR} 2>/dev/null || true; }}"
            f" | sed 's/^/{HUB_AGENT_CACHE_LINE}/'"
        )
    if command == LINUX_COMMANDS["neutrino-agent"]:
        script += f" && {AGENT_LINUX_RUSTDESK_CHECK}"
    script += f" && {command} --version"
    if command == LINUX_COMMANDS["neutrino-hub"]:
        script += f" && {command} open --print"
    print(f"installing {package.name} in {image}")
    result = subprocess.run(
        [
            engine,
            "run",
            "--rm",
            "--network=host",
            "--platform",
            LINUX_PLATFORMS[machine],
            "-v",
            f"{package}:{inside}:ro",
            image,
            "sh",
            "-c",
            script,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit(
            f"the install or {command} --version failed:\n"
            + (result.stderr or result.stdout).strip()[-3000:]
        )
    if command == LINUX_COMMANDS["neutrino-hub"]:
        address = result.stdout.strip().splitlines()[-1]
        print(f"{command} {result.stdout.strip().splitlines()[-2]}")
        if "/?token=" not in address:
            raise SystemExit(
                f"nhub open --print gave no setup wizard address: {address}"
            )
        # dnf prints a scriptlet's words on its standard error, pacman and apt
        # on standard output.
        if HUB_INSTALLED_SENTENCE not in result.stdout + result.stderr:
            raise SystemExit("the hub's install printed no setup wizard address")
        carried = [
            line[len(HUB_AGENT_CACHE_LINE) :]
            for line in result.stdout.splitlines()
            if line.startswith(HUB_AGENT_CACHE_LINE)
        ]
        expected = hub_agent_cache(package.name)
        if carried != expected:
            raise SystemExit(
                f"the hub's agent cache holds {carried or 'nothing'}, "
                f"not {expected or 'nothing'}"
            )
        print(f"agent cache: {', '.join(carried) or 'empty'}")
    else:
        print(f"{command} {result.stdout.strip().splitlines()[-1]}")


def hub_agent_cache(name: str) -> list:
    """The agent package a Linux hub package carries, by the hub file's name.

    Args:
        name: The hub package's file name.

    Returns:
        The one agent file of the same version, family and machine, or
        nothing for the Arch package.
    """
    if not name.endswith(HUB_AGENT_CARRYING_SUFFIXES):
        return []
    return [name.replace("neutrino-hub", "neutrino-agent", 1)]


def _set_up_hub(nhub: list) -> None:
    """Run ``nhub setup`` with the answers of a server hub.

    Args:
        nhub: The command that runs nhub, as root.

    Raises:
        SystemExit: When setup fails.
    """
    answers = {
        "password": secrets.token_urlsafe(18),
        "vault_passphrase": f"{secrets.token_urlsafe(18)}Aa1!",
        "network": {"mode": "server"},
    }
    with tempfile.TemporaryDirectory() as workdir:
        path = Path(workdir) / "answers.json"
        path.write_text(json.dumps(answers), encoding="utf-8")
        result = subprocess.run([*nhub, "setup", "--json", str(path)])
    if result.returncode != 0:
        raise SystemExit(f"nhub setup exited {result.returncode}")


def _wait_for_wizard() -> None:
    """Wait for the service to serve the setup wizard on the panel's port.

    Raises:
        SystemExit: When the page does not answer 200, or its API does not
            refuse a request with no token, in time.
    """
    deadline = time.monotonic() + HUB_PANEL_WAIT_S
    last = ""
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(HUB_WIZARD_PAGE_URL, timeout=5) as response:
                last = f"{HUB_WIZARD_PAGE_URL} answered {response.status}"
            urllib.request.urlopen(HUB_WIZARD_API_URL, timeout=5).close()
            last = f"{HUB_WIZARD_API_URL} answered without the token"
        except urllib.error.HTTPError as error:
            if error.code == HUB_WIZARD_REFUSAL:
                print(f"{HUB_WIZARD_PAGE_URL} serves the setup wizard")
                return
            last = f"{error.url} answered {error.code}"
        except OSError as error:
            last = str(error)
        time.sleep(HUB_PANEL_POLL_S)
    raise SystemExit(f"the setup wizard is not served: {last}")


def _wait_for_panel() -> None:
    """Wait for the panel to answer on its default port.

    Raises:
        SystemExit: When it does not answer 200 in time.
    """
    deadline = time.monotonic() + HUB_PANEL_WAIT_S
    last = ""
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(HUB_PANEL_URL, timeout=5) as response:
                if response.status == 200:
                    print(f"{HUB_PANEL_URL} answered 200")
                    return
                last = str(response.status)
        except (OSError, urllib.error.URLError) as error:
            last = str(error)
        time.sleep(HUB_PANEL_POLL_S)
    raise SystemExit(f"{HUB_PANEL_URL} did not answer 200: {last}")


def _run_install_script(package: Path, command: list) -> None:
    """Run an install script over a directory holding the package and its
    checksum, with no terminal, as a release serves it.

    Args:
        package: The built package.
        command: The script's command line.

    Raises:
        SystemExit: When the script fails.
    """
    with tempfile.TemporaryDirectory() as workdir:
        assets = Path(workdir)
        shutil.copyfile(package, assets / package.name)
        digest = hashlib.sha256(package.read_bytes()).hexdigest()
        (assets / "SHA256SUMS").write_text(f"{digest}  {package.name}\n")
        result = subprocess.run(
            command,
            env={**os.environ, "NEUTRINO_ASSET_DIR": str(assets)},
            stdin=subprocess.DEVNULL,
            start_new_session=sys.platform != "win32",
        )
    if result.returncode != 0:
        raise SystemExit(f"{Path(command[-2]).name} exited {result.returncode}")


def _is_job_loaded(job: str) -> bool:
    """Whether launchd has a job loaded."""
    result = subprocess.run(["sudo", "launchctl", "print", job], capture_output=True)
    return result.returncode == 0


def _remove_windows_product(name: str) -> None:
    """Remove every installed product of one display name, by its code."""
    import winreg

    codes = []
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, UNINSTALL_KEY) as key:
        for index in range(winreg.QueryInfoKey(key)[0]):
            code = winreg.EnumKey(key, index)
            with winreg.OpenKey(key, code) as product:
                try:
                    shown = winreg.QueryValueEx(product, "DisplayName")[0]
                except OSError:
                    continue
            if shown == name:
                codes.append(code)
    for code in codes:
        result = subprocess.run(["msiexec", "/x", code, *CHECK_MSIEXEC_QUIET])
        print(f"msiexec /x {name} exited {result.returncode}")


def _require_host(platform: str, name: str) -> None:
    """Refuse to run a check on a host it is not for.

    Args:
        platform: What ``sys.platform`` says on that host.
        name: The host, as a person names it.

    Raises:
        SystemExit: When this is not that host.
    """
    if sys.platform != platform:
        raise SystemExit(f"this check runs on {name}; this is {sys.platform}")


def _msiexec(
    action: str,
    msi: Path,
    log: Path,
    properties: tuple = (),
    *,
    is_restart_accepted: bool = False,
) -> int:
    """Run msiexec quietly with a verbose log, and return its exit code.

    Args:
        action: ``/i`` or ``/x``.
        msi: The installer.
        log: Where the verbose log goes.
        properties: Public properties for this run, such as a reinstall's.
        is_restart_accepted: Whether this run goes over a released earlier
            package, whose removal may leave a restart owed: exit 3010 is
            then returned, with one line saying why.

    Returns:
        msiexec's exit code.

    Raises:
        SystemExit: When it runs past ``CHECK_MSIEXEC_TIMEOUT_S``, after what
            the machine is doing and the log's last lines are printed; or
            when it finished wanting a restart, after the log's lines that
            name what held a file: no install, upgrade or removal of ours may
            need one, and an install over an earlier package only 3010.
    """
    named = " ".join((action, *properties))
    _say(f"msiexec {named} {msi.name}")
    try:
        code = subprocess.run(
            [
                "msiexec",
                action,
                str(msi),
                *properties,
                *CHECK_MSIEXEC_QUIET,
                "/l*v",
                str(log),
            ],
            timeout=CHECK_MSIEXEC_TIMEOUT_S,
        ).returncode
    except subprocess.TimeoutExpired:
        _snapshot()
        _print_log(log, ("",), 40)
        raise SystemExit(f"msiexec {named} ran past {CHECK_MSIEXEC_TIMEOUT_S} s")
    _say(f"msiexec {named} exited {code}")
    if code in CHECK_MSIEXEC_RESTART_CODES:
        _print_log(log, CHECK_MSIEXEC_HELD_PATTERNS, 40)
        if is_restart_accepted and code == CHECK_MSIEXEC_WANTED_RESTART:
            print(f"msiexec {named} wants a restart: {CHECK_EARLIER_RESTART_REASON}")
            return code
        raise SystemExit(f"msiexec {named} wants a restart (exit {code})")
    return code


def _take_upgrade_away(msi: Path, target: str, folder: Path) -> None:
    """Remove what an install over an earlier package left, and every file
    of ours it left for the next restart, so what follows starts clean.

    Args:
        msi: The installer.
        target: The check, naming the log.
        folder: The package's folder, which must be gone after.

    Raises:
        SystemExit: When the removal fails or the folder outlives it.
    """
    log = Path(tempfile.gettempdir()) / f"{target}_upgrade_remove.log"
    code = _msiexec("/x", msi, log, is_restart_accepted=True)
    if code not in (0, CHECK_MSIEXEC_WANTED_RESTART):
        raise SystemExit(f"the upgraded package did not uninstall (exit {code})")
    if folder.exists():
        raise SystemExit(f"{folder} outlived the uninstaller after the upgrade")
    dropped = _drop_pending_renames_of_ours()
    if dropped:
        print(
            f"dropped the restart's {len(dropped)} renames of ours: {', '.join(dropped)}"
        )


def without_ours(entries: list) -> tuple:
    """Split Windows' pending renames into what is kept and what is ours.

    Args:
        entries: The value's strings: a source, then its target or an
            empty string for a deletion, pair after pair.

    Returns:
        The strings kept, pair after pair, and the paths of ours dropped.
    """
    if len(entries) % 2 and entries[-1] == "":
        entries = entries[:-1]
    kept, dropped = [], []
    for source, target in zip(entries[0::2], entries[1::2]):
        if CHECK_PENDING_RENAMES_MARK in f"{source}|{target}".lower():
            dropped.append(target or source)
        else:
            kept += [source, target]
    return kept, dropped


def _drop_pending_renames_of_ours() -> list:
    """Take every file of ours out of what Windows does at the next restart.

    Returns:
        The paths dropped.
    """
    import winreg

    with winreg.OpenKey(
        winreg.HKEY_LOCAL_MACHINE,
        CHECK_PENDING_RENAMES_KEY,
        0,
        winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE,
    ) as key:
        try:
            value, _kind = winreg.QueryValueEx(key, CHECK_PENDING_RENAMES_VALUE)
        except OSError:
            return []
        kept, dropped = without_ours(list(value))
        if not dropped:
            return []
        if kept:
            winreg.SetValueEx(
                key, CHECK_PENDING_RENAMES_VALUE, 0, winreg.REG_MULTI_SZ, kept
            )
        else:
            winreg.DeleteValue(key, CHECK_PENDING_RENAMES_VALUE)
    return dropped


def _install_earlier(target: str) -> None:
    """Fetch a target's released earlier package, check its hash, and install it.

    Args:
        target: A key of ``PACKAGING_EARLIER_PACKAGES``.

    Raises:
        SystemExit: When the download's hash is not the pinned one, or the
            earlier package does not install.
    """
    earlier = fetch_earlier(target, Path(tempfile.gettempdir()))
    log = Path(tempfile.gettempdir()) / f"{target}_earlier.log"
    code = _msiexec("/i", earlier, log)
    if code != 0:
        _print_log(log, ("return value 3", "Error "), 25)
        raise SystemExit(f"the earlier {earlier.name} did not install (exit {code})")
    print(f"{earlier.name} installed")


def fetch_earlier(target: str, directory: Path) -> Path:
    """Download a target's released earlier package and check its hash.

    Args:
        target: A key of ``PACKAGING_EARLIER_PACKAGES``.
        directory: Where the file is written.

    Returns:
        The downloaded file.

    Raises:
        SystemExit: When its hash is not the pinned one.
    """
    asset, digest = PACKAGING_EARLIER_PACKAGES[target]
    url = PACKAGING_EARLIER_RELEASE_URL.format(
        version=PACKAGING_EARLIER_VERSION, asset=asset
    )
    path = directory / asset
    _say(f"fetching {url}")
    with urllib.request.urlopen(url, timeout=CHECK_COMMAND_TIMEOUT_S) as response:
        path.write_bytes(response.read())
    found = hashlib.sha256(path.read_bytes()).hexdigest()
    if found != digest:
        path.unlink()
        raise SystemExit(f"{asset} hashes {found}, not the pinned {digest}")
    return path


def _check_no_pending_rename() -> None:
    """No file of ours is left for Windows to replace at the next restart.

    Raises:
        SystemExit: When one is, naming each.
    """
    ours = [
        entry
        for entry in _pending_renames()
        if CHECK_PENDING_RENAMES_MARK in entry.lower()
    ]
    if ours:
        raise SystemExit(
            "files of ours wait for a restart to be replaced: " + ", ".join(ours)
        )


def _pending_renames() -> list:
    """What Windows is to rename or delete at the next restart; empty for none."""
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, CHECK_PENDING_RENAMES_KEY
        ) as key:
            value, _kind = winreg.QueryValueEx(key, CHECK_PENDING_RENAMES_VALUE)
    except OSError:
        return []
    return [entry for entry in value if entry]


def _say(text: str) -> None:
    """Print one progress line with the time the check has run, and keep it
    in the evidence on disk at once."""
    line = f"[{int(time.monotonic() - CHECK_STARTED):>5} s] {text}"
    print(line, flush=True)
    if CHECK_EVIDENCE is None:
        return
    try:
        with open(CHECK_EVIDENCE / CHECK_PROGRESS_NAME, "a", encoding="utf-8") as kept:
            kept.write(line + "\n")
            kept.flush()
            os.fsync(kept.fileno())
    except OSError:
        pass


def _snapshot() -> str:
    """Print what the machine is doing now, and return it. Never raises."""
    _say("what the machine is doing:")
    if sys.platform == "win32":
        command = ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command"]
        command.append(CHECK_WINDOWS_SNAPSHOT)
    else:
        command = ["ps", "-eo", "pid,pcpu,rss,comm", "--sort=-pcpu"]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=CHECK_SNAPSHOT_TIMEOUT_S
        )
    except (OSError, subprocess.SubprocessError) as error:
        print(f"no snapshot: {error}", flush=True)
        return f"no snapshot: {error}\n"
    text = (result.stdout or "")[-20000:] + "\n" + (result.stderr or "")[-2000:]
    print(text, flush=True)
    return text


def _watchdog() -> None:
    """Watch the check: what the machine does every few minutes, whether the
    network still reaches GitHub, and the time limit.

    The network is watched once a check has registered a rescue, since
    only then is there something of its own to take away. A network gone
    for ``CHECK_NETWORK_MISSES`` probes in a row, or a check past
    ``CHECK_LIMIT_S``, prints a snapshot, runs every rescue and ends the
    process.
    """
    misses = 0
    last_heartbeat = time.monotonic()
    while time.monotonic() - CHECK_STARTED < CHECK_LIMIT_S:
        time.sleep(min(CHECK_NETWORK_EVERY_S, CHECK_LIMIT_S))
        if CHECK_RESCUES:
            misses = 0 if _is_network_up() else misses + 1
        if misses:
            _say(f"GitHub did not answer ({misses} in a row)")
        if misses >= CHECK_NETWORK_MISSES:
            _give_up("the network is gone")
            return
        if time.monotonic() - last_heartbeat >= CHECK_HEARTBEAT_S:
            last_heartbeat = time.monotonic()
            _snapshot()
    _give_up(f"the check ran past {CHECK_LIMIT_S} s")


def _is_network_up() -> bool:
    """Whether a connection to GitHub opens within its timeout."""
    try:
        socket.create_connection(
            CHECK_NETWORK_PROBE, timeout=CHECK_NETWORK_TIMEOUT_S
        ).close()
    except OSError:
        return False
    return True


def _give_up(reason: str) -> None:
    """Print a snapshot, take away what the check installed, and end the process."""
    _say(reason)
    _snapshot()
    for rescue in list(CHECK_RESCUES):
        try:
            rescue()
        except Exception as error:  # noqa: BLE001 - every rescue is tried
            print(f"a rescue failed: {error}", flush=True)
    _say(f"network after the rescues: {'up' if _is_network_up() else 'down'}")
    _snapshot()
    os._exit(1)


def _remove_windows_package(msi: Path, services: tuple = ()) -> None:
    """Stop a package's services, then take it away by its installer, within limits.

    Args:
        msi: The installer.
        services: The services to stop first, which works while another
            msiexec still holds the installer.
    """
    for name in services:
        try:
            subprocess.run(
                ["sc.exe", "stop", name],
                capture_output=True,
                timeout=CHECK_COMMAND_TIMEOUT_S,
            )
        except subprocess.SubprocessError:
            pass
    _say(f"taking {msi.name} away")
    try:
        result = subprocess.run(
            ["msiexec", "/x", str(msi), *CHECK_MSIEXEC_QUIET],
            timeout=CHECK_MSIEXEC_TIMEOUT_S,
        )
    except subprocess.SubprocessError as error:
        _say(f"msiexec /x did not finish: {error}")
        return
    _say(f"msiexec /x exited {result.returncode}")


def _print_log(log: Path, patterns: tuple, count: int) -> None:
    """Print the last lines of an msiexec log that name one of the patterns."""
    if not log.is_file():
        return
    raw = log.read_bytes()
    text = raw.decode("utf-16" if raw[:2] == b"\xff\xfe" else "utf-8", "replace")
    lines = [line for line in text.splitlines() if any(p in line for p in patterns)]
    for line in lines[-count:]:
        print(line)


def _service_state(name: str) -> str:
    """The STATE line ``sc query`` prints for a service, or empty."""
    result = subprocess.run(["sc.exe", "query", name], capture_output=True, text=True)
    return next(
        (line.strip() for line in result.stdout.splitlines() if "STATE" in line), ""
    )


def _service_exists(name: str) -> bool:
    """Whether the service control manager knows a service."""
    result = subprocess.run(["sc.exe", "query", name], capture_output=True)
    return result.returncode != SERVICE_DOES_NOT_EXIST


def _wait_for_job_gone(job: str) -> bool:
    """Wait for a launchd job to leave the system domain after its bootout.

    Args:
        job: The job, such as ``system/com.neutrino.agent``.

    Returns:
        Whether it was gone in time.
    """
    deadline = time.monotonic() + SERVICE_WAIT_S
    while time.monotonic() < deadline:
        if not _is_job_loaded(job):
            return True
        time.sleep(SERVICE_POLL_S)
    return False


def _wait_for_service(name: str, *, is_running: bool) -> bool:
    """Wait for a service to run, or to be gone.

    Args:
        name: The service.
        is_running: True to wait for it to run, False for it to be gone.

    Returns:
        Whether it got there in time.
    """
    deadline = time.monotonic() + SERVICE_WAIT_S
    while time.monotonic() < deadline:
        if is_running and "RUNNING" in _service_state(name):
            return True
        if not is_running and not _service_exists(name):
            return True
        time.sleep(SERVICE_POLL_S)
    return False


def _machine_path() -> str:
    """The machine-wide PATH as the registry holds it."""
    import winreg

    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, MACHINE_ENVIRONMENT_KEY) as key:
        return winreg.QueryValueEx(key, "Path")[0]


def _powershell(script: str) -> str:
    """Run one PowerShell command line and return what it printed, stripped.

    Raises:
        SystemExit: When it fails.
    """
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=CHECK_COMMAND_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        _snapshot()
        raise SystemExit(f"powershell ran past {CHECK_COMMAND_TIMEOUT_S} s: {script}")
    if result.returncode != 0:
        raise SystemExit(f"powershell exited {result.returncode}: {result.stderr}")
    return result.stdout.strip()


def _sudo(command: list) -> None:
    """Run a command as root, failing the check when it fails.

    Raises:
        SystemExit: When it fails.
    """
    result = subprocess.run(["sudo", *command])
    if result.returncode != 0:
        raise SystemExit(f"sudo {command[0]} exited {result.returncode}")


def _answer(command: list) -> str:
    """Run a command and return what it printed.

    Raises:
        SystemExit: When it fails.
    """
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=CHECK_COMMAND_TIMEOUT_S
        )
    except subprocess.TimeoutExpired:
        _snapshot()
        raise SystemExit(
            f"{' '.join(command[:2])} ran past {CHECK_COMMAND_TIMEOUT_S} s"
        )
    if result.returncode != 0:
        raise SystemExit(
            f"{' '.join(command[:2])} exited {result.returncode}: "
            f"{(result.stderr or result.stdout).strip()}"
        )
    return result.stdout.strip()


CHECKS = {
    "agent_windows": check_agent_windows,
    "client_windows": check_client_windows,
    "agent_macos": check_agent_macos,
    "client_macos": check_client_macos,
    "hub_windows": check_hub_windows,
    "hub_macos": check_hub_macos,
    "client_android": check_client_android,
    "linux": check_linux,
}


if __name__ == "__main__":
    sys.exit(main())
