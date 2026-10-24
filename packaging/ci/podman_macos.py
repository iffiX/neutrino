"""Install the pinned Podman on a macOS runner and make a machine with the agent's own code.

    python3 packaging/ci/podman_macos.py key <platform>
    python3 packaging/ci/podman_macos.py fetch <platform> <directory>
    sudo python3 -I packaging/ci/podman_macos.py check <platform> <directory> \\
        <account> <account's TMPDIR>

Runs on: a GitHub macOS runner, ``darwin-arm64`` on ``macos-15`` and
``darwin-amd64`` on ``macos-15-intel``. ``key`` prints the cache key of the
branch's pinned files; ``fetch`` downloads each one missing from the
directory and checks its sha256; ``check``, as root, drives the agent's
``PodmanDarwinApplier``, ``installers.install_pkg`` and ``PodmanMachine`` as
the account: the install, ``podman --version``, ``podman machine init
--image``, inspect, a grown disk and a refused smaller one, the machine's
removal and the uninstall. No machine starts: the runners have no nested
virtualisation. It changes the machine it runs on, so run it on a
throwaway one.

Not pure: installs and removes Podman.
"""

import argparse
import hashlib
import json
import os
import platform
import pwd
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

# --- config ---
REPOSITORY = Path(__file__).resolve().parents[2]
MANIFEST = REPOSITORY / "hub/neutrino_hub/data/manifests/podman.json"
PLATFORMS = ("darwin-arm64", "darwin-amd64")
# The names the agent keeps each component under, by its package kind.
KEPT_NAMES = {"pkg": "installer.pkg", "raw_zst": "image.raw.zst"}
CHUNK_BYTES = 1024 * 1024
GIB = 1024**3
# The machine the check makes: small, so the runner's disk holds it.
INIT_MEMORY_GIB = 2
INIT_DISK_GIB = 20
GROWN_DISK_GIB = 24
SMALLER_DISK_GIB = 16
SET_MEMORY_GIB = 3
COMMAND_TIMEOUT_S = 600
# What the pkg's postinstall makes for a person a sudo names.
HELPER_PLIST_PREFIX = "com.github.containers.podman.helper-"
HELPER_DIR = "/usr/local/podman/helper"
SUDO_VARIABLES = ("SUDO_USER", "SUDO_UID", "SUDO_GID", "SUDO_COMMAND")
LAUNCH_DAEMONS = "/Library/LaunchDaemons"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    verbs = parser.add_subparsers(dest="verb", required=True)
    key = verbs.add_parser("key", help="print the cache key of the pinned files")
    key.add_argument("platform", choices=PLATFORMS)
    fetched = verbs.add_parser("fetch", help="download and check the pinned files")
    fetched.add_argument("platform", choices=PLATFORMS)
    fetched.add_argument("directory", type=Path)
    checked = verbs.add_parser("check", help="install, make a machine, uninstall")
    checked.add_argument("platform", choices=PLATFORMS)
    checked.add_argument("directory", type=Path)
    checked.add_argument("account")
    checked.add_argument("session_tmpdir", help="the account's own TMPDIR")
    args = parser.parse_args()
    if args.verb == "key":
        print(cache_key(args.platform))
    elif args.verb == "fetch":
        fetch(args.platform, args.directory)
    else:
        check(args.platform, args.directory, args.account, args.session_tmpdir)
    return 0


def cache_key(platform_name: str) -> str:
    """The cache key of one platform's pinned files: their digests."""
    components = _components(_branch(platform_name))
    digests = "_".join(components[name]["sha256"] for name in ("installer", "image"))
    return f"podman_{platform_name}_{digests}"


def fetch(platform_name: str, directory: Path) -> None:
    """Download each pinned file that is missing, and check every digest.

    Raises:
        SystemExit: When a file's digest is not its pin.
    """
    directory.mkdir(parents=True, exist_ok=True)
    for component in _branch(platform_name)["components"]:
        path = directory / KEPT_NAMES[component["package_kind"]]
        if path.is_file() and _sha256(path) == component["sha256"]:
            print(f"cached: {path.name}")
            continue
        partial = path.with_name(path.name + ".part")
        started = time.monotonic()
        with urllib.request.urlopen(component["url"]) as answer:
            with open(partial, "wb") as stream:
                shutil.copyfileobj(answer, stream, CHUNK_BYTES)
        found = _sha256(partial)
        if found != component["sha256"]:
            partial.unlink()
            raise SystemExit(
                f"{component['url']}: sha256 {found}, pinned {component['sha256']}"
            )
        partial.replace(path)
        mib = path.stat().st_size / 1024**2
        print(
            f"fetched: {path.name}, {mib:.0f} MiB in {time.monotonic() - started:.0f} s"
        )


def check(platform_name: str, directory: Path, account: str, session_tmpdir: str):
    """Install Podman, make, size and remove a machine, and uninstall Podman.

    Raises:
        SystemExit: Naming every expectation that failed.
    """
    sys.path.insert(0, str(REPOSITORY / "agent"))
    from neutrino_agent.exceptions import ModuleApplyError
    from neutrino_agent.modules.podman.applier import podman_version
    from neutrino_agent.modules.podman.constants import (
        PODMAN_DARWIN_INSTALLED_PATHS,
        PODMAN_DARWIN_PKG_ID,
        PODMAN_MACHINE_NAME,
    )
    from neutrino_agent.modules.podman.machine import PodmanMachine
    from neutrino_agent.modules.podman.machine_runner import (
        podman_system_applier_for,
    )
    from neutrino_agent.platforms.darwin import DarwinPlatform

    # The agent's LaunchDaemon runs the installer with no SUDO_USER, and the
    # pkg's postinstall then makes no podman-mac-helper; the check does too.
    for name in SUDO_VARIABLES:
        os.environ.pop(name, None)
    log = CheckLog()
    branch = _branch(platform_name)
    components = _components(branch)
    computer = DarwinPlatform()
    system = podman_system_applier_for(computer)
    log.show(
        "the runner",
        {
            "macos": platform.mac_ver()[0],
            "machine": platform.machine(),
            "python": sys.version.split()[0],
            "account": account,
            "applier": type(system).__name__,
        },
    )
    log.expect(os.geteuid() == 0, "the check runs as root")
    log.expect(not os.path.exists(system.binary), f"no {system.binary} before")

    cpus, memory_gib = system.host_facts()
    log.show("host_facts", {"cpus": cpus, "memory_gib": memory_gib})
    log.expect(cpus == os.cpu_count(), "host_facts' CPUs are the logical CPUs")
    log.expect(memory_gib > 0, "host_facts reads the memory")

    environment = system.machine_environment(account)
    log.show("machine_environment", environment)
    temp_dir = environment.get("TMPDIR", "")
    log.expect(
        temp_dir.rstrip("/") == session_tmpdir.rstrip("/"),
        f"TMPDIR as the account is the session's {session_tmpdir}",
    )

    started = time.monotonic()
    system.install_component(
        dict(components["installer"]), str(directory / KEPT_NAMES["pkg"])
    )
    log.show("install seconds", f"{time.monotonic() - started:.0f}")
    log.expect(os.path.isfile(system.binary), f"{system.binary} is installed")
    receipts = _output(["pkgutil", "--pkgs"]).split()
    log.show("receipts naming podman", [name for name in receipts if "podman" in name])
    log.expect(PODMAN_DARWIN_PKG_ID in receipts, f"the receipt {PODMAN_DARWIN_PKG_ID}")
    log.show("its receipt", _output(["pkgutil", "--pkg-info", PODMAN_DARWIN_PKG_ID]))
    for path in PODMAN_DARWIN_INSTALLED_PATHS:
        log.expect(os.path.exists(path), f"the pkg made {path}")
    helpers = [
        name
        for name in os.listdir(LAUNCH_DAEMONS)
        if name.startswith(HELPER_PLIST_PREFIX)
    ]
    log.expect(not helpers, f"no podman-mac-helper LaunchDaemon {helpers}")
    log.expect(not os.path.exists(HELPER_DIR), f"no {HELPER_DIR}")
    version = podman_version(podman=(system.binary,))
    log.expect(version == branch["version"], f"podman --version is {version}")

    machine = PodmanMachine(
        platform=computer,
        account=account,
        password="",
        binary=system.binary,
        provider=system.provider,
        environment=environment,
    )
    log.expect(not machine.is_present(), "the account has no machine before")
    init_cpus = max(1, cpus // 2)
    started = time.monotonic()
    machine.init(
        str(directory / KEPT_NAMES["raw_zst"]),
        cpus=init_cpus,
        memory_gib=INIT_MEMORY_GIB,
        disk_gib=INIT_DISK_GIB,
    )
    log.show("init seconds", f"{time.monotonic() - started:.0f}")
    log.expect(machine.is_present(), f"the settings file is {machine.settings_path()}")

    inspected = _inspect(machine)
    log.show("podman machine inspect", inspected)
    settings = _settings(machine)
    log.show("the settings file", settings)
    config_dir = Path(computer.account_home(account)) / ".config/containers"
    connections = config_dir / "podman-connections.json"
    if connections.is_file():
        log.show("podman-connections.json", connections.read_text())
    log.show(
        "the account's ~/.config/containers",
        sorted(str(path.relative_to(config_dir)) for path in config_dir.rglob("*")),
    )
    log.show("what the ignition puts in the machine", _ignition(machine))
    state = machine.inspect()
    log.expect(state.state == "stopped", f"a new machine is {state.state}")
    log.expect(state.is_rootful, "the machine is rootful")
    ssh_config = inspected.get("SSHConfig") or {}
    port = machine.ssh_port()
    log.expect(
        port == int(ssh_config.get("Port") or 0),
        f"the settings file's SSH.Port {port} is inspect's",
    )
    identity = machine.identity_path()
    log.expect(identity == ssh_config.get("IdentityPath"), f"the key is {identity}")
    log.expect(
        os.path.isfile(identity) and os.access(identity, os.R_OK),
        "root reads the key in place",
    )
    socket = ((inspected.get("ConnectionInfo") or {}).get("PodmanSocket") or {}).get(
        "Path", ""
    )
    log.expect(
        bool(temp_dir) and str(socket).startswith(os.path.join(temp_dir, "podman")),
        f"the API socket {socket} is under the account's TMPDIR",
    )
    command = machine.read_command()
    log.show("the read's command", list(command))
    log.expect(
        command[2] == f"ssh://root@127.0.0.1:{port}/run/podman/podman.sock",
        "the read is root's socket through the ssh port",
    )
    log.expect(
        os.stat(machine.settings_path()).st_uid == pwd.getpwnam(account).pw_uid,
        "the account owns the settings file",
    )
    resources = inspected.get("Resources") or {}
    log.expect(
        (resources.get("CPUs"), resources.get("Memory"), resources.get("DiskSize"))
        == (init_cpus, INIT_MEMORY_GIB * 1024, INIT_DISK_GIB),
        f"init's size is inspect's {resources}",
    )
    log.expect(system.disk_gib(machine) == INIT_DISK_GIB, "disk_gib reads init's disk")
    log.expect(_image_gib(settings) == INIT_DISK_GIB, "the disk image is that size")

    system.halt(machine)
    log.expect(True, "halt takes a stopped machine")
    system.write_resources(machine, cpus=cpus, memory_gib=SET_MEMORY_GIB)
    resources = _inspect(machine).get("Resources") or {}
    log.expect(
        (resources.get("CPUs"), resources.get("Memory"))
        == (cpus, SET_MEMORY_GIB * 1024),
        f"write_resources sets the CPUs and the memory {resources}",
    )
    system.resize_disk(machine, disk_gib=GROWN_DISK_GIB)
    log.expect(system.disk_gib(machine) == GROWN_DISK_GIB, "resize_disk grows it")
    log.expect(
        _image_gib(_settings(machine)) == GROWN_DISK_GIB, "the disk image grew too"
    )
    for size in (SMALLER_DISK_GIB, GROWN_DISK_GIB):
        try:
            system.resize_disk(machine, disk_gib=size)
        except ModuleApplyError as error:
            log.show(f"resize_disk to {size}", {"code": error.code, **error.params})
            log.expect(error.code == "machine_set_failed", f"{size} GiB is refused")
        else:
            log.expect(False, f"{size} GiB is refused")
    log.expect(system.disk_gib(machine) == GROWN_DISK_GIB, "a refusal keeps the disk")

    done = machine.run_as_account(
        [system.binary, "machine", "rm", "-f", PODMAN_MACHINE_NAME],
        timeout_s=COMMAND_TIMEOUT_S,
    )
    log.expect(done.returncode == 0, f"machine rm {done.stdout}{done.stderr}".strip())
    log.expect(not machine.is_present(), "the machine's settings file is gone")

    system.uninstall()
    for path in PODMAN_DARWIN_INSTALLED_PATHS:
        log.expect(not os.path.lexists(path), f"the uninstall deleted {path}")
    receipt = subprocess.run(
        ["pkgutil", "--pkg-info", PODMAN_DARWIN_PKG_ID], capture_output=True
    )
    log.expect(receipt.returncode != 0, "the receipt is forgotten")
    if log.failures:
        raise SystemExit("failed: " + "; ".join(log.failures))
    print("every expectation held")


def _branch(platform_name: str) -> dict:
    """One platform's branch of the Podman manifest."""
    with open(MANIFEST, "r", encoding="utf-8") as stream:
        return json.load(stream)["platforms"][platform_name]


def _components(branch: dict) -> dict:
    """A branch's components by name."""
    return {component["name"]: component for component in branch["components"]}


def _sha256(path: Path) -> str:
    """One file's sha256, as hex."""
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        chunk = stream.read(CHUNK_BYTES)
        while chunk:
            digest.update(chunk)
            chunk = stream.read(CHUNK_BYTES)
    return digest.hexdigest()


def _output(command: list) -> str:
    """One command's standard output, empty when it fails."""
    done = subprocess.run(command, capture_output=True, text=True)
    return done.stdout if done.returncode == 0 else ""


def _inspect(machine) -> dict:
    """``podman machine inspect`` of the account's default machine, parsed."""
    done = machine.run_as_account(
        [machine.binary, "machine", "inspect", "podman-machine-default"],
        timeout_s=COMMAND_TIMEOUT_S,
    )
    if done.returncode != 0:
        raise SystemExit(f"podman machine inspect: {done.stderr}")
    found = json.loads(done.stdout)
    return found[0] if found else {}


def _settings(machine) -> dict:
    """The machine's settings file, parsed."""
    with open(machine.settings_path(), "r", encoding="utf-8") as stream:
        return json.load(stream)


def _ignition(machine) -> dict:
    """The units, files and links the machine's ignition file names, without their contents."""
    path = Path(machine.settings_path()).with_suffix(".ign")
    if not path.is_file():
        return {"missing": str(path)}
    with open(path, "r", encoding="utf-8") as stream:
        ignition = json.load(stream)
    storage = ignition.get("storage") or {}
    return {
        "units": [
            unit.get("name")
            for unit in (ignition.get("systemd") or {}).get("units") or []
        ],
        "files": [item.get("path") for item in storage.get("files") or []],
        "links": [item.get("path") for item in storage.get("links") or []],
        "directories": [item.get("path") for item in storage.get("directories") or []],
    }


def _image_gib(settings: dict) -> int:
    """The apparent size of the disk image the settings file names, in GiB."""
    path = (settings.get("ImagePath") or {}).get("Path") or ""
    return os.path.getsize(path) // GIB if path and os.path.isfile(path) else 0


class CheckLog:
    """Each expectation printed with its outcome, and the ones that failed."""

    def __init__(self):
        self.failures: list = []

    def expect(self, is_met: bool, what: str) -> None:
        """Print one expectation's outcome and keep a failure."""
        print(f"{'pass' if is_met else 'FAIL'}: {what}", flush=True)
        if not is_met:
            self.failures.append(what)

    def show(self, title: str, value) -> None:
        """Print one finding the standard is checked against."""
        text = value if isinstance(value, str) else json.dumps(value, indent=2)
        print(f"--- {title}\n{text}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
