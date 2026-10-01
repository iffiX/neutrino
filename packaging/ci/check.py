"""Install a built package where it runs, check it works, and take it away.

    python3 packaging/ci/check.py <target> <artifact>

Runs on: the host the target is for, as an administrator or with
passwordless sudo, since every check installs what it checks. The release
workflow runs it after each build; on a workstation it changes the machine
it runs on, so run it on a throwaway one.

The targets:

- ``agent_windows``: the .msi installs, the ``neutrino_agent`` and
  ``RustDesk`` services run, ``nagent --version`` answers, and removing it
  takes both services away. Windows.
- ``client_windows``: the .msi installs, ``nclient --version`` answers,
  ``nclient status`` exits 1 unbound, the folder is on PATH, ``packet.dll``
  lies beside EasyTier's core, the EasyTier daemon runs and answers on its
  pipe, and removing it takes the folder and the daemon away. Windows.
- ``agent_macos``: the .pkg installs, its LaunchDaemon runs, ``nagent
  --version`` answers, and removing it leaves no job. macOS.
- ``client_macos``: the .pkg installs, ``nclient --version`` answers and
  ``nclient status`` exits 1 unbound. macOS.
- ``client_android``: the apk installs on the running emulator, its main
  activity starts and its process is alive ten seconds later. Any host with
  ``adb`` and one emulator attached.
- ``linux``: a hub, agent or client .deb, .rpm or Arch package installs in a
  fresh container of its family and its command answers ``--version``. Linux
  with podman or docker; another architecture needs QEMU registered with
  binfmt_misc.

Not pure: installs and removes packages.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# --- Windows ---
AGENT_WINDOWS_FOLDER = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / (
    "Neutrino Agent"
)
AGENT_WINDOWS_SERVICES = ("neutrino_agent", "RustDesk")
RUSTDESK_WINDOWS_FOLDER = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / (
    "RustDesk"
)
CLIENT_WINDOWS_FOLDER = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / (
    "Neutrino Client"
)
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

# --- macOS ---
AGENT_MACOS_JOB = "system/com.neutrino.agent"
AGENT_MACOS_LEFTOVERS = (
    "/Library/Application Support/Neutrino/agent",
    "/Applications/RustDesk.app",
    "/usr/local/bin/nagent",
    "/Library/LaunchDaemons/com.neutrino.agent.plist",
    "/Library/LaunchDaemons/com.carriez.RustDesk_service.plist",
    "/Library/LaunchAgents/com.carriez.RustDesk_server.plist",
)
AGENT_MACOS_PACKAGE_ID = "com.neutrino.agent"

# --- Android ---
ANDROID_ACTIVITY = "io.github.iffix.neutrino/.MainActivity"
ANDROID_PACKAGE = "io.github.iffix.neutrino"
ANDROID_SETTLE_S = 10

# --- Linux ---
# The container each format installs in, and how it installs a local file.
LINUX_INSTALLS = {
    ".deb": (
        "debian:12",
        "apt-get -qq update && apt-get -qq install -y {package}",
    ),
    ".rpm": ("fedora:41", "dnf -q -y install {package}"),
    ".pkg.tar.zst": (
        "archlinux:latest",
        "pacman -Sy --noconfirm >/dev/null && pacman -U --noconfirm {package}",
    ),
}
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

    log = Path(tempfile.gettempdir()) / "agent_remove.log"
    print(f"msiexec /x exited {_msiexec('/x', msi, log)}")
    _print_log(log, ("UninstallRustDesk", "return value 3"), 12)
    for service in AGENT_WINDOWS_SERVICES:
        if not _wait_for_service(service, is_running=False):
            raise SystemExit(f"{service} outlived the uninstaller")
        print(f"{service} is gone")


def check_client_windows(msi: Path) -> None:
    """Install the client's .msi, use it, and remove it.

    Args:
        msi: The installer.

    Raises:
        SystemExit: When a step fails.
    """
    _require_host("win32", "Windows")
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
    if "Neutrino Client" not in _machine_path():
        raise SystemExit("the install is not on PATH")
    if not (CLIENT_WINDOWS_FOLDER / "bin" / "packet.dll").is_file():
        raise SystemExit("no packet.dll beside easytier-core.exe")
    if not _wait_for_service(CLIENT_WINDOWS_EASYTIER_SERVICE, is_running=True):
        raise SystemExit("the EasyTier daemon is not running")
    if CLIENT_WINDOWS_EASYTIER_PIPE not in os.listdir("\\\\.\\pipe\\"):
        raise SystemExit("the EasyTier daemon has no pipe")

    log = Path(tempfile.gettempdir()) / "client_remove.log"
    print(f"msiexec /x exited {_msiexec('/x', msi, log)}")
    if CLIENT_WINDOWS_FOLDER.exists():
        raise SystemExit("the folder outlived the uninstaller")
    if _service_exists(CLIENT_WINDOWS_EASYTIER_SERVICE):
        raise SystemExit("the EasyTier daemon outlived the uninstaller")


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
    _sudo(["launchctl", "bootout", AGENT_MACOS_JOB])
    subprocess.run(
        ["sudo", "launchctl", "bootout", "system/com.carriez.RustDesk_service"]
    )
    _sudo(["rm", "-rf", *AGENT_MACOS_LEFTOVERS])
    _sudo(["pkgutil", "--forget", AGENT_MACOS_PACKAGE_ID])
    if subprocess.run(["sudo", "launchctl", "print", AGENT_MACOS_JOB]).returncode == 0:
        raise SystemExit("the agent's job outlived its removal")


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
    script = f"{install.format(package=inside)} && {command} --version"
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
    print(f"{command} {result.stdout.strip().splitlines()[-1]}")


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
    "client_android": check_client_android,
    "linux": check_linux,
}


if __name__ == "__main__":
    sys.exit(main())
