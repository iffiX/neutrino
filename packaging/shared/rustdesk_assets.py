"""The RustDesk release a package carries, pinned by hash and unpacked.

Every asset comes from upstream's own release and is checked against the
SHA-256 recorded here, so a build either carries the RustDesk this project
was tested against or fails. Windows takes the executable as it is; macOS
takes the app bundle out of the disk image, attached with ``hdiutil`` on the
Mac the package is built on. The Linux ``.deb`` assets are pinned here too
and unpacked by the package that carries them.

Not pure: downloads, attaches disk images, writes files.
"""

import hashlib
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path

# The Flutter builds of one release. The same release publishes `-sciter`
# assets of the old frontend, which are carried nowhere.
RUSTDESK_VERSION = "1.4.9"
RUSTDESK_URL = (
    "https://github.com/rustdesk/rustdesk/releases/download/"
    "{version}/rustdesk-{version}{suffix}"
)
RUSTDESK_ASSETS = {
    ("linux", "x86_64"): (
        "-x86_64.deb",
        "7244ba47c40e804172044bfbe659467c54ce46554c98e78c8c0406f1d612fda3",  # scan: allow
    ),
    ("linux", "aarch64"): (
        "-aarch64.deb",
        "ce62c996f14d33f3bbe3a330e953644a44bace7f05885a7953f7395d69fb49c0",  # scan: allow
    ),
    ("windows", "x86_64"): (
        "-x86_64.exe",
        "eaedeb0088e687bf46f7c46a9c6ea5493ce51f3134dfd6acbedb47b5b9136274",  # scan: allow
    ),
    ("darwin", "aarch64"): (
        "-aarch64.dmg",
        "f7935597b247d42c8f2a2ed71176a9f5868018cd9e1a33b8096418a668c8caf0",  # scan: allow
    ),
}
RUSTDESK_WINDOWS_BINARY_NAME = "rustdesk.exe"
# The app bundle the disk image carries, and its binary inside.
RUSTDESK_APP_NAME = "RustDesk.app"
RUSTDESK_APP_BINARY = "Contents/MacOS/RustDesk"


def asset_url(os_name: str, machine: str) -> str:
    """Where upstream publishes the asset for one platform.

    Args:
        os_name: ``linux``, ``windows`` or ``darwin``.
        machine: ``x86_64`` or ``aarch64``.

    Returns:
        The asset's URL.

    Raises:
        SystemExit: When there is no pin for that machine.
    """
    suffix, _digest = _asset(os_name, machine)
    return RUSTDESK_URL.format(version=RUSTDESK_VERSION, suffix=suffix)


def download(os_name: str, machine: str) -> bytes:
    """Download the asset for one platform and check it against its pin.

    Args:
        os_name: ``linux``, ``windows`` or ``darwin``.
        machine: ``x86_64`` or ``aarch64``.

    Returns:
        The asset's bytes.

    Raises:
        SystemExit: When there is no pin for that machine, or what arrived
            is not what was pinned.
    """
    _suffix, digest = _asset(os_name, machine)
    return _fetch(asset_url(os_name, machine), digest)


def stage_windows_exe(
    dest_dir: Path, *, name: str = RUSTDESK_WINDOWS_BINARY_NAME, machine: str = "x86_64"
) -> Path:
    """Put the pinned Windows executable into a directory.

    Args:
        dest_dir: The directory it belongs in.
        name: What the file is called there.
        machine: ``x86_64`` or ``aarch64``.

    Returns:
        The executable written.

    Raises:
        SystemExit: When there is no pin for that machine, or what arrived
            is not what was pinned.
    """
    content = download("windows", machine)
    target = dest_dir / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return target


def stage_darwin_app(dest_dir: Path, *, machine: str = "aarch64") -> Path:
    """Copy the pinned app bundle out of upstream's disk image.

    Args:
        dest_dir: The directory the app bundle belongs in.
        machine: ``aarch64``.

    Returns:
        The app bundle written.

    Raises:
        SystemExit: When there is no pin, what arrived is not what was
            pinned, hdiutil refuses, or the image carries no app.
    """
    suffix, _digest = _asset("darwin", machine)
    url = asset_url("darwin", machine)
    content = download("darwin", machine)
    with tempfile.TemporaryDirectory() as workdir:
        root = Path(workdir)
        image = root / f"rustdesk{suffix}"
        image.write_bytes(content)
        mountpoint = root / "opened"
        mountpoint.mkdir()
        _run(
            [
                "hdiutil",
                "attach",
                "-nobrowse",
                "-readonly",
                "-mountpoint",
                str(mountpoint),
                str(image),
            ]
        )
        try:
            carried = mountpoint / RUSTDESK_APP_NAME
            if not (carried / RUSTDESK_APP_BINARY).is_file():
                raise SystemExit(
                    f"{url} carries no {RUSTDESK_APP_NAME}/{RUSTDESK_APP_BINARY}"
                )
            dest_dir.mkdir(parents=True, exist_ok=True)
            target = dest_dir / RUSTDESK_APP_NAME
            shutil.copytree(carried, target, symlinks=True)
        finally:
            _run(["hdiutil", "detach", str(mountpoint)])
    return target


def _asset(os_name: str, machine: str) -> tuple:
    """One pinned asset, or the refusal naming the machines there are.

    Args:
        os_name: ``linux``, ``windows`` or ``darwin``.
        machine: ``x86_64`` or ``aarch64``.

    Returns:
        The asset's suffix and its pinned SHA-256.

    Raises:
        SystemExit: When there is no pin for that machine.
    """
    asset = RUSTDESK_ASSETS.get((os_name, machine))
    if asset is None:
        published = sorted(name for keyed, name in RUSTDESK_ASSETS if keyed == os_name)
        raise SystemExit(
            f"no RustDesk pinned for {os_name} {machine}; there is one for: "
            f"{', '.join(published)}"
        )
    return asset


def _fetch(url: str, digest: str) -> bytes:
    """Download one pinned file and check it against its hash.

    Args:
        url: Where it lives.
        digest: The pinned SHA-256.

    Returns:
        The file's bytes.

    Raises:
        SystemExit: When what arrived is not what was pinned.
    """
    print(f"  fetching {url.rsplit('/', 1)[-1]}")
    with urllib.request.urlopen(url, timeout=600) as response:
        downloaded = response.read()
    arrived = hashlib.sha256(downloaded).hexdigest()
    if arrived != digest:
        raise SystemExit(
            f"RustDesk at {url} hashes to {arrived}, not the pinned {digest}"
        )
    return downloaded


def _run(command: list) -> None:
    """Run one step, failing loudly.

    Args:
        command: The argument vector.

    Raises:
        SystemExit: If the command fails.
    """
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(
            f"{' '.join(command[:3])} failed:\n"
            f"{(result.stderr or result.stdout).strip()}"
        )
