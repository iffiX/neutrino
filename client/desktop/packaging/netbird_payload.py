"""NetBird's part of the client packages: its pinned binary and its daemon.

The packages carry NetBird's own binary and register its daemon as a system
service on every system: a systemd unit on Linux, a service on Windows, a
LaunchDaemon on macOS. The payload takes this part when the tree holds it,
through :func:`payload.parts`; the mainland tree does not. The part gives
the versions and licences the package carries for it, what the Linux
maintainer scripts run before the package goes, the package it conflicts
with, and its staging and daemon for each system.

Not pure: downloads, writes package trees.
"""

import shlex
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from neutrino_client.constants import CLIENT_INSTALL_PREFIX_LINUX  # noqa: E402
from neutrino_client.netbird.constants import (  # noqa: E402
    CLIENT_NETBIRD_CONFIG_PATH_DARWIN,
    CLIENT_NETBIRD_LAUNCHD_LABEL,
    CLIENT_NETBIRD_SERVICE_WINDOWS,
    NETBIRD_BUNDLED_PATHS,
)

# NetBird's release: one tarball per machine holding the one binary. The
# Linux pins are the hub's own.
NETBIRD_VERSION = "0.78.1"
NETBIRD_URL = (
    "https://github.com/netbirdio/netbird/releases/download/"
    "v{version}/netbird_{version}_{asset}.tar.gz"
)
NETBIRD_ASSETS = {
    ("linux", "x86_64"): (
        "linux_amd64",
        "9239c9e37c2acc0612563ef5ce0c3326397460d0eb811b5a59a8e373f1a4ebde",  # scan: allow
    ),
    ("linux", "aarch64"): (
        "linux_arm64",
        "d686745aa64bb4c597602ce95e76558f5f848d0672c88d63f96397d2507005b2",  # scan: allow
    ),
    ("windows", "x86_64"): (
        "windows_amd64",
        "c9ad0e7aa778b9ba28b3e2338354d705df7ead94cdf6edbde137bdae79d30eab",  # scan: allow
    ),
    ("darwin", "aarch64"): (
        "darwin_arm64",
        "8d613dc78aa0e5b9f01b07ec9d02417c27638bf68b829a72399293f76da0fa03",  # scan: allow
    ),
    ("darwin", "x86_64"): (
        "darwin_amd64",
        "1441be19db0394497866fc19a519d7d0483fbad0fcd4d1adaeb0ed1bded739be",  # scan: allow
    ),
}
NETBIRD_BINARY_NAME = "netbird"
NETBIRD_WINDOWS_BINARY_NAME = "netbird.exe"
# Where the binary lands under the Linux prefix and under the app bundle's
# Resources, matching what the runtime resolver looks for.
NETBIRD_INSTALL_PATH = "netbird/netbird"

# What the part adds to every package: the version the About card shows, the
# licence the package carries, and the distribution package holding the same
# state and socket, which the Linux packages conflict with.
CARRIED_VERSIONS = {"netbird": NETBIRD_VERSION}
CARRIED_LICENSES = ("netbird.txt",)
CONFLICTS = ("netbird",)

# What the Linux maintainer scripts run before the package goes: NetBird
# taken off its network.
LINUX_UNITS_STOP = (
    f"{CLIENT_INSTALL_PREFIX_LINUX}/{NETBIRD_BUNDLED_PATHS['linux']['netbird']} down"
    " >/dev/null 2>&1 || true\n"
)

# How NetBird's Windows service runs, its state and its log under the
# client's directories in ProgramData.
NETBIRD_SERVICE_ARGUMENTS = (
    "service run --config "
    '"[CommonAppDataFolder]Neutrino\\client\\state\\netbird\\config.json"'
    ' --log-file "[CommonAppDataFolder]Neutrino\\client\\log\\netbird.log"'
)
# The services the Windows package registers for it.
WINDOWS_SERVICES = (CLIENT_NETBIRD_SERVICE_WINDOWS,)
# The folder of its state under the client's state folder, as WiX names it.
NETBIRD_DATA_FOLDER_ID = "NETBIRDDATAFOLDER"

# The socket every NetBird daemon on a Mac listens on; one already there
# belongs to NetBird's own install, which the client then uses as it is.
NETBIRD_SOCKET_PATH = "/var/run/netbird.sock"
NETBIRD_LOG_NAME = "netbird.log"


def stage_linux(prefix: Path, machine: str) -> None:
    """Put NetBird's binary under a Linux package's prefix.

    Args:
        prefix: The install prefix inside the package tree.
        machine: The interpreter release's name for the machine.

    Raises:
        SystemExit: When there is no pin, what arrived is not what was
            pinned, or the tarball carries no binary.
    """
    stage(prefix / NETBIRD_INSTALL_PATH, "linux", machine)


def stage_windows(installed: Path, machine: str) -> None:
    """Put NetBird's binary into the Windows payload's ``bin``.

    Args:
        installed: The directory the installer lays down whole.
        machine: The interpreter release's name for the machine.

    Raises:
        SystemExit: As :func:`stage_linux`.
    """
    stage(installed / "bin" / NETBIRD_WINDOWS_BINARY_NAME, "windows", machine)


def stage_darwin(resources: Path, machine: str) -> None:
    """Put NetBird's binary under an app bundle's Resources.

    Args:
        resources: The bundle's ``Contents/Resources`` directory.
        machine: The interpreter release's name for the machine.

    Raises:
        SystemExit: As :func:`stage_linux`.
    """
    stage(resources / NETBIRD_INSTALL_PATH, "darwin", machine)


def stage(target: Path, os_name: str, machine: str) -> None:
    """Unpack the pinned NetBird binary to one path.

    Args:
        target: Where the binary belongs.
        os_name: ``linux``, ``windows`` or ``darwin``.
        machine: The interpreter release's name for the machine.

    Raises:
        SystemExit: When there is no pin, what arrived is not what was
            pinned, or the tarball carries no binary.
    """
    import bundled  # bundled reaches this part through payload
    import payload

    asset, digest = bundled._asset(NETBIRD_ASSETS, os_name, machine, "NetBird")
    url = NETBIRD_URL.format(version=NETBIRD_VERSION, asset=asset)
    downloaded = payload.fetch(url, digest, "NetBird")
    name = NETBIRD_WINDOWS_BINARY_NAME if os_name == "windows" else NETBIRD_BINARY_NAME
    with tempfile.TemporaryDirectory() as workdir:
        opened = bundled._unpacked(Path(workdir), url, downloaded)
        binary = opened / name
        if not binary.is_file():
            raise SystemExit(f"{url} carries no {name}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(binary, target)
    target.chmod(0o755)


def windows_excluded(payload_dir: Path) -> tuple:
    """The payload's files the Windows service components carry themselves.

    Args:
        payload_dir: The staged payload.

    Returns:
        NetBird's binary, which the glob of the payload leaves out.
    """
    return (payload_dir / "bin" / NETBIRD_WINDOWS_BINARY_NAME,)


def windows_state_folders(wix_build) -> tuple:
    """The folders of NetBird's state under the client's state folder.

    Args:
        wix_build: The shared WiX module.

    Returns:
        Its ``Directory`` elements.
    """
    return (wix_build.directory(NETBIRD_DATA_FOLDER_ID, "netbird"),)


def windows_components(wix_build, payload_dir: Path) -> tuple:
    """NetBird's service and the folder its state is in.

    Args:
        wix_build: The shared WiX module.
        payload_dir: The staged payload: ``bin`` holds NetBird.

    Returns:
        The two ``Component`` elements.
    """
    service = wix_build.element(
        "Component",
        {"Id": "NetbirdService", "Guid": "*", "Subdirectory": "bin"},
        (
            wix_build.element(
                "File",
                {
                    "Id": "NetbirdServiceFile",
                    "Source": str(payload_dir / "bin" / NETBIRD_WINDOWS_BINARY_NAME),
                    "KeyPath": "yes",
                },
            ),
            wix_build.element(
                "ServiceInstall",
                {
                    "Id": "NetbirdServiceInstall",
                    "Name": CLIENT_NETBIRD_SERVICE_WINDOWS,
                    "DisplayName": "Neutrino Client NetBird",
                    "Description": "The NetBird daemon the Neutrino client joins with",
                    "Type": "ownProcess",
                    "Start": "auto",
                    "ErrorControl": "normal",
                    "Account": "LocalSystem",
                    "Arguments": NETBIRD_SERVICE_ARGUMENTS,
                },
            ),
            # The stop is waited for, so netbird.exe is free before the
            # files are written and no upgrade owes a restart. The start is
            # not: a NetBird daemon already on the machine holds what this
            # one needs, its service then cannot start, and that must not
            # fail the install.
            wix_build.element(
                "ServiceControl",
                {
                    "Id": "NetbirdServiceStop",
                    "Name": CLIENT_NETBIRD_SERVICE_WINDOWS,
                    "Stop": "both",
                    "Remove": "uninstall",
                    "Wait": "yes",
                },
            ),
            wix_build.element(
                "ServiceControl",
                {
                    "Id": "NetbirdServiceStart",
                    "Name": CLIENT_NETBIRD_SERVICE_WINDOWS,
                    "Start": "install",
                    "Wait": "no",
                },
            ),
        ),
    )
    folder = wix_build.element(
        "Component",
        {"Id": "NetbirdDataFolder", "Guid": "*", "Directory": NETBIRD_DATA_FOLDER_ID},
        (
            wix_build.element("CreateFolder", {}),
            wix_build.element(
                "RegistryValue",
                {
                    "Root": "HKLM",
                    "Key": "Software\\Neutrino\\Client",
                    "Name": "NetbirdDataFolder",
                    "Type": "integer",
                    "Value": "1",
                    "KeyPath": "yes",
                },
            ),
        ),
    )
    return (service, folder)


def darwin_daemons(installed_contents: Path, log_dir: str) -> tuple:
    """NetBird's LaunchDaemon, as the macOS package writes and loads it.

    Args:
        installed_contents: The installed bundle's ``Contents`` directory.
        log_dir: The client's log directory.

    Returns:
        One ``{label, program_arguments, log_path, extra, state_dir}``: the
        daemon runs NetBird unless another daemon holds its socket, and is
        kept running unless it exits cleanly.
    """
    netbird = shlex.quote(
        str(installed_contents / NETBIRD_BUNDLED_PATHS["darwin"]["netbird"])
    )
    config = shlex.quote(CLIENT_NETBIRD_CONFIG_PATH_DARWIN)
    command = (
        f"[ -S {NETBIRD_SOCKET_PATH} ] && exit 0; "
        f"exec {netbird} service run --config {config} --log-file console"
    )
    return (
        {
            "label": CLIENT_NETBIRD_LAUNCHD_LABEL,
            "program_arguments": ["/bin/sh", "-c", command],
            "log_path": log_dir + "/" + NETBIRD_LOG_NAME,
            "extra": {"KeepAlive": {"SuccessfulExit": False}},
            "state_dir": str(Path(CLIENT_NETBIRD_CONFIG_PATH_DARWIN).parent),
        },
    )
