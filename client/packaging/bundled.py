"""The binaries the client packages carry, pinned and unpacked at build time.

Two of them: the cc-switch CLI, which points a person's AI tools at the hub's
gateway, and the RustDesk viewer, which opens a desktop the fleet shares. Both
are fetched from their own upstream releases and checked against a hash
recorded here, so a build either produces the binaries this project was
tested against or fails.

The Linux RustDesk build is unpacked out of upstream's own package; only its
host directory is carried, under the client's prefix. Its binary's RUNPATH is
:data:`RUSTDESK_EXPECTED_RUNPATH`, so it finds the libraries beside it with no
environment set for it; a build whose binary says otherwise is refused rather
than shipped broken. The macOS build is the app bundle out of upstream's
disk image, attached with ``hdiutil`` on the Mac the package is built on.

Not pure: downloads binaries, attaches disk images, writes package trees.
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "packaging"))
import payload  # noqa: E402
import rustdesk_assets  # noqa: E402

# The AI tool switcher, published as one static binary per machine. The musl
# builds are the ones that need nothing of the machine's own C library.
CC_SWITCH_VERSION = "5.10.4"
CC_SWITCH_URL = (
    "https://github.com/SaladDay/cc-switch-cli/releases/download/"
    "v{version}/cc-switch-cli-v{version}-{asset}"
)
CC_SWITCH_ASSETS = {
    ("linux", "x86_64"): (
        "linux-x64-musl.tar.gz",
        "a9a569d85cb0a61169082a558f86786e0e7ee9c2725900e7d6e876873eb416c3",  # scan: allow
    ),
    ("linux", "aarch64"): (
        "linux-arm64-musl.tar.gz",
        "37d9b2564f9d47215dbb45914158d71f746d92d829ad62ca1214de4eeb5bfc6f",  # scan: allow
    ),
    ("windows", "x86_64"): (
        "windows-x64.zip",
        "6bc4ceea645cdf3cebc662e859d6a8804e3a3c737d4968497f66ba6df481f1a7",  # scan: allow
    ),
    ("darwin", "aarch64"): (
        "darwin-arm64.tar.gz",
        "7ca345ac2c9c930e7929252584fcfe7e7507ae40c1350d4969a80bafbad769f5",  # scan: allow
    ),
}
CC_SWITCH_BINARY_NAME = "cc-switch"
CC_SWITCH_WINDOWS_BINARY_NAME = "cc-switch.exe"

# The RustDesk viewer, pinned in ``packaging/rustdesk_assets.py``. Linux
# takes it out of upstream's Flutter .deb, Windows takes the portable
# executable as it is, and macOS takes the app bundle out of the disk image.
# Where the upstream package keeps the whole viewer: the binary, the
# libraries it loads and the data it reads. What surrounds it there — the
# unit, the desktop file, the polkit and pam rules — is upstream's own
# session setup and is not carried.
RUSTDESK_UPSTREAM_DIR = "usr/share/rustdesk"
RUSTDESK_BINARY_NAME = "rustdesk"
# Checked at build time: the binary loads the libraries beside it by itself,
# so the client spawns the viewer with no library path set for it.
RUSTDESK_EXPECTED_RUNPATH = "$ORIGIN/lib"

# Where both land under the install prefix, matching what the runtime
# resolver in ``neutrino_client.bundled`` looks for.
CC_SWITCH_INSTALL_PATH = "bin/cc-switch"
RUSTDESK_INSTALL_DIR = "rustdesk"
# Where both land under the app bundle's Contents on macOS.
DARWIN_RESOURCES_DIR = "Resources"


def stage_linux_binaries(tree: Path, architecture: str) -> None:
    """Put both carried binaries into a Linux package tree.

    Args:
        tree: The staging directory standing in for the filesystem root.
        architecture: The architecture, named however the format names it.

    Raises:
        SystemExit: When an asset is not pinned for the machine, what
            arrived is not what was pinned, or the viewer is not the shape
            the client expects.
    """
    machine = payload.machine_name(architecture)
    prefix = tree / str(payload.INSTALL_PREFIX).lstrip("/")
    _stage_cc_switch(prefix / CC_SWITCH_INSTALL_PATH, "linux", machine)
    _stage_rustdesk_host(prefix / RUSTDESK_INSTALL_DIR, machine)


def stage_windows_binaries(installed: Path, architecture: str) -> None:
    """Put both carried binaries into the Windows payload directory.

    Args:
        installed: The directory the installer lays down whole.
        architecture: The architecture, named however the format names it.

    Raises:
        SystemExit: When an asset is not pinned for the machine, or what
            arrived is not what was pinned.
    """
    machine = payload.machine_name(architecture)
    _stage_cc_switch(
        installed / "bin" / CC_SWITCH_WINDOWS_BINARY_NAME, "windows", machine
    )
    rustdesk_assets.stage_windows_exe(installed / "bin", machine=machine)


def stage_darwin_binaries(app_contents: Path) -> None:
    """Put both carried binaries under an app bundle's Contents directory.

    Args:
        app_contents: The bundle's ``Contents`` directory.

    Raises:
        SystemExit: When what arrived is not what was pinned, the disk
            image carries no viewer, or hdiutil refuses.
    """
    resources = app_contents / DARWIN_RESOURCES_DIR
    _stage_cc_switch(resources / CC_SWITCH_INSTALL_PATH, "darwin", "aarch64")
    rustdesk_assets.stage_darwin_app(resources / RUSTDESK_INSTALL_DIR)


def _asset(assets: dict, os_name: str, machine: str, what: str) -> tuple:
    """One pinned asset, or the refusal naming the machines there are.

    Args:
        assets: The pin table.
        os_name: ``linux``, ``windows`` or ``darwin``.
        machine: The interpreter release's name for the machine.
        what: The component, for the message.

    Returns:
        The asset's suffix and its pinned SHA-256.

    Raises:
        SystemExit: When there is no pin for that machine.
    """
    asset = assets.get((os_name, machine))
    if asset is None:
        published = sorted(name for keyed_os, name in assets if keyed_os == os_name)
        raise SystemExit(
            f"no {what} pinned for {os_name} {machine}; there is one for: "
            f"{', '.join(published)}"
        )
    return asset


def _stage_cc_switch(target: Path, os_name: str, machine: str) -> None:
    """Unpack the pinned cc-switch binary to one path.

    Args:
        target: Where the binary belongs.
        os_name: ``linux``, ``windows`` or ``darwin``.
        machine: The interpreter release's name for the machine.

    Raises:
        SystemExit: When there is no pin, what arrived is not what was
            pinned, or the archive carries no binary.
    """
    asset, digest = _asset(CC_SWITCH_ASSETS, os_name, machine, "cc-switch")
    url = CC_SWITCH_URL.format(version=CC_SWITCH_VERSION, asset=asset)
    downloaded = payload.fetch(url, digest, "cc-switch")
    name = (
        CC_SWITCH_WINDOWS_BINARY_NAME if os_name == "windows" else CC_SWITCH_BINARY_NAME
    )
    with tempfile.TemporaryDirectory() as workdir:
        root = Path(workdir)
        archive = root / asset
        archive.write_bytes(downloaded)
        opened = root / "opened"
        opened.mkdir()
        shutil.unpack_archive(str(archive), str(opened))
        binary = opened / name
        if not binary.is_file():
            raise SystemExit(f"{url} carries no {name}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(binary, target)
    target.chmod(0o755)


def _stage_rustdesk_host(target: Path, machine: str) -> None:
    """Unpack the pinned RustDesk viewer out of its upstream package.

    Args:
        target: Where the viewer's own directory belongs.
        machine: The interpreter release's name for the machine.

    Raises:
        SystemExit: When there is no pin, what arrived is not what was
            pinned, the package carries no viewer, or the viewer would not
            find its own libraries once installed.
    """
    url = rustdesk_assets.asset_url("linux", machine)
    downloaded = rustdesk_assets.download("linux", machine)
    with tempfile.TemporaryDirectory() as workdir:
        root = Path(workdir)
        package = root / url.rsplit("/", 1)[-1]
        package.write_bytes(downloaded)
        opened = root / "opened"
        opened.mkdir()
        payload.run(["dpkg-deb", "-x", str(package), str(opened)])
        carried = opened / RUSTDESK_UPSTREAM_DIR
        binary = carried / RUSTDESK_BINARY_NAME
        if not binary.is_file():
            raise SystemExit(
                f"{url} carries no {RUSTDESK_UPSTREAM_DIR}/{RUSTDESK_BINARY_NAME}"
            )
        check_runpath(binary)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(carried, target)


def check_runpath(binary: Path) -> None:
    """Refuse a viewer that would not find the libraries carried beside it.

    Args:
        binary: The unpacked viewer binary.

    Raises:
        SystemExit: When its RUNPATH is not the expected one, or readelf is
            not in the build container.
    """
    try:
        result = subprocess.run(
            ["readelf", "-d", str(binary)], capture_output=True, text=True
        )
    except OSError as error:
        raise SystemExit(f"readelf is needed to check the viewer: {error}")
    if result.returncode != 0:
        raise SystemExit(f"readelf refused {binary}: {result.stderr.strip()}")
    if RUSTDESK_EXPECTED_RUNPATH not in result.stdout:
        raise SystemExit(
            f"{binary} carries no {RUSTDESK_EXPECTED_RUNPATH} runpath, so the "
            "libraries carried beside it would not be found"
        )
