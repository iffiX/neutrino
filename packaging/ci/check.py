"""Install a built package where it runs, check it works, and take it away.

    python3 packaging/ci/check.py <target> <artifact>

Runs on: the host the target is for, as an administrator or with
passwordless sudo, since every check installs what it checks. The release
workflow runs it after each build; on a workstation it changes the machine
it runs on, so run it on a throwaway one.

The targets:

- ``agent_windows``: the .msi installs, the ``neutrino_agent`` and
  ``RustDesk`` services run, ``nagent --version`` answers, ``bin\\cc-switch.exe``
  prints the pinned version, belongs to the administrators and is the users'
  to run and no one else's to change, and removing it takes both services
  and cc-switch away, with a scheduled task and a firewall rule named
  as a module names them, and leaves a rule named as the hub names its
  own. Windows.
- ``client_windows``: the .msi installs, ``nclient --version`` answers,
  ``nclient status`` exits 1 unbound, the folder is on PATH, ``packet.dll``
  lies beside EasyTier's core, the EasyTier daemon runs, answers on its
  pipe and makes its state under ``Neutrino\\client\\state``, and removing
  it takes the folder and the daemon away. Windows.
- ``agent_macos``: the .pkg installs, its LaunchDaemon runs, ``nagent
  --version`` answers, ``app/bin/cc-switch`` prints the pinned version, is
  root's and is mode 755, its ``config`` is root's alone and its ``state`` open
  to every account, and ``nagent service uninstall --yes`` leaves no job,
  no ``nagent``, no cc-switch, no receipt and no LaunchDaemon named as a
  module names
  them, and keeps one named as the hub names its own. macOS.
- ``client_macos``: the .pkg installs, ``nclient --version`` answers and
  ``nclient status`` exits 1 unbound. macOS.
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
  none for Arch; the agent's ``/opt/neutrino/agent/bin/cc-switch`` prints
  the pinned version, is root's and is mode 755. Linux with podman or docker; another architecture needs QEMU registered with
  binfmt_misc.

Not pure: installs and removes packages.
"""

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALL_SCRIPTS_DIR = REPO_ROOT / "packaging" / "install"
sys.path.insert(0, str(REPO_ROOT / "packaging"))
from shared.constants import PACKAGING_CC_SWITCH_VERSION  # noqa: E402

# --- The cc-switch every agent package carries ---
# Where each system's agent package puts it.
AGENT_LINUX_CC_SWITCH = "/opt/neutrino/agent/bin/cc-switch"
AGENT_MACOS_CC_SWITCH = "/Library/Application Support/Neutrino/agent/app/bin/cc-switch"
# What its --version prints.
CC_SWITCH_VERSION_LINE = f"cc-switch {PACKAGING_CC_SWITCH_VERSION}"
# The prefix of the lines the Linux check prints about it inside the
# container.
CC_SWITCH_LINE = "cc-switch: "
# The well-known SIDs of the accounts every user is in, and of the owners an
# installed program may have.
WINDOWS_EVERY_ACCOUNT_SIDS = ("S-1-1-0", "S-1-5-11", "S-1-5-32-545")
WINDOWS_ADMIN_SIDS = ("S-1-5-18", "S-1-5-32-544")
# Prints the owner's SID, then whether any account of every user may change
# the file, then whether the users may run it: one line, three words.
WINDOWS_CC_SWITCH_ACL_SCRIPT = (
    "$acl = Get-Acl -LiteralPath '{path}'; "
    "$sid = [System.Security.Principal.SecurityIdentifier]; "
    "$rules = $acl.GetAccessRules($true, $true, $sid) | "
    "Where-Object {{ $_.AccessControlType -eq 'Allow' -and "
    "@({everyone}) -contains $_.IdentityReference.Value }}; "
    "$write = [int][System.Security.AccessControl.FileSystemRights]"
    "'WriteData, AppendData, Delete, ChangePermissions, TakeOwnership'; "
    "$run = [int][System.Security.AccessControl.FileSystemRights]'ExecuteFile'; "
    "$writable = [bool]($rules | Where-Object {{ "
    "([int]$_.FileSystemRights -band $write) -ne 0 }}); "
    "$runnable = [bool]($rules | Where-Object {{ "
    "$_.IdentityReference.Value -eq 'S-1-5-32-545' -and "
    "([int]$_.FileSystemRights -band $run) -ne 0 }}); "
    "Write-Output (@($acl.GetOwner($sid).Value, $writable, $runnable) -join ' ')"
)

# --- Windows ---
PROGRAM_FILES = Path(os.environ.get("ProgramFiles", "C:/Program Files"))
AGENT_WINDOWS_FOLDER = PROGRAM_FILES / "Neutrino" / "agent"
AGENT_WINDOWS_CC_SWITCH = AGENT_WINDOWS_FOLDER / "bin" / "cc-switch.exe"
AGENT_WINDOWS_SERVICES = ("neutrino_agent", "RustDesk")
RUSTDESK_WINDOWS_FOLDER = PROGRAM_FILES / "RustDesk"
CLIENT_WINDOWS_FOLDER = PROGRAM_FILES / "Neutrino" / "client"
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
CLIENT_WINDOWS_EASYTIER_SERVICE = "NeutrinoClientEasytier"
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
    arguments = parser.parse_args()
    artifact = Path(arguments.artifact).resolve()
    if not artifact.is_file():
        raise SystemExit(f"{artifact} is not a file")
    CHECKS[arguments.target](artifact)
    print(f"{arguments.target}: {artifact.name} passed")
    return 0


def check_agent_windows(msi: Path) -> None:
    """Install the agent's .msi, check both services, and remove it.

    Args:
        msi: The installer.

    Raises:
        SystemExit: When a step fails.
    """
    _require_host("win32", "Windows")
    log = Path(tempfile.gettempdir()) / "agent_install.log"
    print(f"msiexec /i exited {_msiexec('/i', msi, log)}")
    _print_log(log, ("RustDesk", "return value 3"), 40)
    for folder in (AGENT_WINDOWS_FOLDER, RUSTDESK_WINDOWS_FOLDER):
        if folder.is_dir():
            print(f"{folder}: {', '.join(sorted(p.name for p in folder.iterdir()))}")
    if not _wait_for_service("RustDesk", is_running=True):
        print("RustDesk is not running; running its installer by hand for comparison")
        installers = sorted(AGENT_WINDOWS_FOLDER.glob("rustdesk*.exe"))
        if installers:
            result = subprocess.run([str(installers[0]), "--silent-install"])
            print(f"rustdesk --silent-install by hand exited {result.returncode}")
            time.sleep(20)
            print(f"RustDesk by hand: {_service_state('RustDesk')}")
    for service in AGENT_WINDOWS_SERVICES:
        state = _service_state(service)
        print(f"{service} {state}")
        if "RUNNING" not in state:
            raise SystemExit(f"{service} is not running")
    print(f"nagent {_answer([str(AGENT_WINDOWS_FOLDER / 'nagent.exe'), '--version'])}")
    _check_cc_switch_windows()
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
    _print_log(log, ("UninstallRustDesk", "UninstallAdded", "return value 3"), 12)
    for service in AGENT_WINDOWS_SERVICES:
        if not _wait_for_service(service, is_running=False):
            raise SystemExit(f"{service} outlived the uninstaller")
        print(f"{service} is gone")
    if AGENT_WINDOWS_CC_SWITCH.exists():
        raise SystemExit(f"{AGENT_WINDOWS_CC_SWITCH} outlived the uninstaller")
    found = _powershell(AGENT_WINDOWS_FOUND_SCRIPT.format(**names))
    _powershell(f"Remove-NetFirewallRule -Name {AGENT_WINDOWS_FOREIGN_RULE}")
    if found != "False False True":
        raise SystemExit(
            f"after the removal the task, the rule and the hub's rule read {found}; "
            "expected False False True"
        )
    print("the module's task and rule are gone, the hub's rule stays")


def check_client_windows(msi: Path) -> None:
    """Install the client's .msi, use it, and remove it.

    Args:
        msi: The installer.

    Raises:
        SystemExit: When a step fails.
    """
    _require_host("win32", "Windows")
    _plant_client_windows_leftovers()
    log = Path(tempfile.gettempdir()) / "client_install.log"
    code = _msiexec("/i", msi, log)
    print(f"msiexec /i exited {code}")
    nclient = CLIENT_WINDOWS_FOLDER / "nclient.exe"
    if code != 0 or not nclient.is_file():
        _print_log(
            log, ("return value 3", "Error 19", CLIENT_WINDOWS_EASYTIER_SERVICE), 25
        )
        raise SystemExit("the client did not install")
    print(f"nclient {_answer([str(nclient), '--version'])}")
    status = subprocess.run([str(nclient), "status"]).returncode
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
    _check_client_windows_data()
    _check_client_windows_relaunch(msi)

    log = Path(tempfile.gettempdir()) / "client_remove.log"
    print(f"msiexec /x exited {_msiexec('/x', msi, log)}")
    if CLIENT_WINDOWS_FOLDER.exists():
        raise SystemExit("the folder outlived the uninstaller")
    if _service_exists(CLIENT_WINDOWS_EASYTIER_SERVICE):
        raise SystemExit("the EasyTier daemon outlived the uninstaller")
    if _relaunch_tasks():
        raise SystemExit(
            f"relaunch tasks outlived the uninstaller: {_relaunch_tasks()}"
        )


def _check_client_windows_relaunch(msi: Path) -> None:
    """An install over no running client starts nothing; a repair starts the relaunch tasks.

    Args:
        msi: The installer, run again as a repair.

    Raises:
        SystemExit: When the install left a relaunch task or a running
            window, or the repair did not start the planted task.
    """
    if _relaunch_tasks():
        raise SystemExit(f"the install left relaunch tasks: {_relaunch_tasks()}")
    windows = _answer(["tasklist", "/fi", "imagename eq nclientw.exe", "/fo", "csv"])
    if "nclientw.exe" in windows.lower():
        raise SystemExit("an install over no running client started one")
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
    log = Path(tempfile.gettempdir()) / "client_repair.log"
    print(f"msiexec /fa exited {_msiexec('/fa', msi, log)}")
    deadline = time.monotonic() + CLIENT_WINDOWS_RELAUNCH_WAIT_S
    while not CLIENT_WINDOWS_RELAUNCH_MARKER.is_file():
        if time.monotonic() >= deadline:
            _print_log(log, ("RelaunchClients", "WixQuietExec"), 10)
            raise SystemExit("the repair did not start the relaunch task")
        time.sleep(SERVICE_POLL_S)
    CLIENT_WINDOWS_RELAUNCH_MARKER.unlink(missing_ok=True)
    print("the repair started the relaunch task")


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
    problem = _darwin_cc_switch_problem(AGENT_MACOS_CC_SWITCH)
    if problem:
        raise SystemExit(problem)
    print(f"{AGENT_MACOS_CC_SWITCH}: {CC_SWITCH_VERSION_LINE}")
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
    if Path(AGENT_MACOS_CC_SWITCH).exists():
        raise SystemExit(f"{AGENT_MACOS_CC_SWITCH} outlived nagent service uninstall")
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
    _answer([str(nhub), "stop"])

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
    _wait_for_wizard()

    _set_up_hub(["sudo", HUB_MACOS_COMMAND])
    job = _answer(["sudo", "launchctl", "print", HUB_MACOS_JOB])
    if "state = running" not in job:
        raise SystemExit(f"{HUB_MACOS_JOB} is not running after setup")
    _wait_for_panel()
    _sudo([HUB_MACOS_COMMAND, "stop"])

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
        script += (
            f" && stat -c '{CC_SWITCH_LINE}%u %a' {AGENT_LINUX_CC_SWITCH}"
            f" && {AGENT_LINUX_CC_SWITCH} --version | sed 's/^/{CC_SWITCH_LINE}/'"
        )
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
    if command == LINUX_COMMANDS["neutrino-agent"]:
        problem = linux_cc_switch_problem(result.stdout)
        if problem:
            raise SystemExit(problem)
        print(f"{AGENT_LINUX_CC_SWITCH}: {CC_SWITCH_VERSION_LINE}")


def linux_cc_switch_problem(output: str) -> str:
    """What is wrong with the cc-switch a Linux agent package installed.

    Args:
        output: What the install in the container printed: a line with the
            binary's owner and mode, then its ``--version``, each after
            :data:`CC_SWITCH_LINE`.

    Returns:
        The one sentence naming the first fault, or an empty string.
    """
    lines = [
        line[len(CC_SWITCH_LINE) :]
        for line in output.splitlines()
        if line.startswith(CC_SWITCH_LINE)
    ]
    if len(lines) < 2:
        return f"{AGENT_LINUX_CC_SWITCH} printed no owner, mode and version"
    owner, mode = lines[0].split()
    bits = int(mode, 8)
    return cc_switch_problem(
        is_admin_owned=owner == "0",
        is_writable_by_others=bool(bits & 0o022),
        is_runnable_by_all=bits & 0o111 == 0o111,
        version_output="\n".join(lines[1:]),
    )


def cc_switch_problem(
    *,
    is_admin_owned: bool,
    is_writable_by_others: bool,
    is_runnable_by_all: bool,
    version_output: str,
) -> str:
    """What is wrong with an installed cc-switch.

    Args:
        is_admin_owned: Whether root, or on Windows an administrator or the
            system, owns it.
        is_writable_by_others: Whether an account other than its owner may
            change it.
        is_runnable_by_all: Whether every account may run it.
        version_output: What ``cc-switch --version`` printed.

    Returns:
        The one sentence naming the first fault, or an empty string.
    """
    if not is_admin_owned:
        return "cc-switch is not owned by root or the administrators"
    if is_writable_by_others:
        return "cc-switch can be changed by accounts other than its owner"
    if not is_runnable_by_all:
        return "cc-switch cannot be run by every account"
    if CC_SWITCH_VERSION_LINE not in version_output:
        return (
            f"cc-switch --version printed {version_output.strip()!r}, "
            f"not {CC_SWITCH_VERSION_LINE!r}"
        )
    return ""


def _darwin_cc_switch_problem(path: str) -> str:
    """What is wrong with the cc-switch the agent's .pkg installed.

    Args:
        path: Where the package puts it.

    Returns:
        The one sentence naming the first fault, or an empty string.
    """
    if not Path(path).is_file():
        return f"the agent's .pkg installed no {path}"
    found = os.stat(path)
    return cc_switch_problem(
        is_admin_owned=found.st_uid == 0,
        is_writable_by_others=bool(found.st_mode & 0o022),
        is_runnable_by_all=found.st_mode & 0o111 == 0o111,
        version_output=_answer([path, "--version"]),
    )


def windows_cc_switch_problem(acl_answer: str, version_output: str) -> str:
    """What is wrong with the cc-switch the agent's .msi installed.

    Args:
        acl_answer: What :data:`WINDOWS_CC_SWITCH_ACL_SCRIPT` printed: the
            owner's SID, whether every account may change the file, and
            whether the users may run it.
        version_output: What ``cc-switch.exe --version`` printed.

    Returns:
        The one sentence naming the first fault, or an empty string.
    """
    owner, writable, runnable = acl_answer.split()
    return cc_switch_problem(
        is_admin_owned=owner in WINDOWS_ADMIN_SIDS,
        is_writable_by_others=writable == "True",
        is_runnable_by_all=runnable == "True",
        version_output=version_output,
    )


def _check_cc_switch_windows() -> None:
    """Check the cc-switch the agent's .msi installed.

    Raises:
        SystemExit: When it is missing, open to change by every account, not
            runnable by the users, or not the pinned version.
    """
    if not AGENT_WINDOWS_CC_SWITCH.is_file():
        raise SystemExit(f"the agent's .msi installed no {AGENT_WINDOWS_CC_SWITCH}")
    everyone = ", ".join(f"'{sid}'" for sid in WINDOWS_EVERY_ACCOUNT_SIDS)
    problem = windows_cc_switch_problem(
        _powershell(
            WINDOWS_CC_SWITCH_ACL_SCRIPT.format(
                path=AGENT_WINDOWS_CC_SWITCH, everyone=everyone
            )
        ),
        _answer([str(AGENT_WINDOWS_CC_SWITCH), "--version"]),
    )
    if problem:
        raise SystemExit(problem)
    print(f"{AGENT_WINDOWS_CC_SWITCH}: {CC_SWITCH_VERSION_LINE}")


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
        result = subprocess.run(["msiexec", "/x", code, "/quiet", "/norestart"])
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


def _msiexec(action: str, msi: Path, log: Path) -> int:
    """Run msiexec quietly with a verbose log, and return its exit code."""
    return subprocess.run(
        ["msiexec", action, str(msi), "/quiet", "/norestart", "/l*v", str(log)]
    ).returncode


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
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
    )
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
    result = subprocess.run(command, capture_output=True, text=True)
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
