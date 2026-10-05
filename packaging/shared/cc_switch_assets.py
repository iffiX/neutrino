"""The cc-switch CLI a package carries, pinned by hash and unpacked.

The client's packages take the build for a system and a machine at the pin
in ``shared.constants``. The binary lands at the path the
package names, executable by every account and writable by none but its
owner.

Not pure: downloads, writes files.
"""

import hashlib
import shutil
import tempfile
import urllib.request
from pathlib import Path

from shared.constants import (
    PACKAGING_CC_SWITCH_ASSETS,
    PACKAGING_CC_SWITCH_BINARY_NAME,
    PACKAGING_CC_SWITCH_URL,
    PACKAGING_CC_SWITCH_VERSION,
    PACKAGING_CC_SWITCH_WINDOWS_BINARY_NAME,
)

CC_SWITCH_FETCH_TIMEOUT_S = 600
# What the staged binary's mode is: the owner's to write, every account's to
# run.
CC_SWITCH_MODE = 0o755


def binary_name(os_name: str) -> str:
    """The binary's file name on one system.

    Args:
        os_name: ``linux``, ``windows`` or ``darwin``.

    Returns:
        ``cc-switch.exe`` on Windows, ``cc-switch`` elsewhere.
    """
    if os_name == "windows":
        return PACKAGING_CC_SWITCH_WINDOWS_BINARY_NAME
    return PACKAGING_CC_SWITCH_BINARY_NAME


def asset_url(os_name: str, machine: str) -> tuple:
    """Where the pinned build for one system and machine is, and its hash.

    Args:
        os_name: ``linux``, ``windows`` or ``darwin``.
        machine: ``x86_64`` or ``aarch64``.

    Returns:
        ``(url, sha256)``.

    Raises:
        SystemExit: When nothing is pinned for that system and machine.
    """
    pinned = PACKAGING_CC_SWITCH_ASSETS.get((os_name, machine))
    if pinned is None:
        published = ", ".join(f"{s} {m}" for s, m in sorted(PACKAGING_CC_SWITCH_ASSETS))
        raise SystemExit(
            f"no cc-switch pinned for {os_name} {machine}; there is one for: "
            f"{published}"
        )
    asset, digest = pinned
    return (
        PACKAGING_CC_SWITCH_URL.format(
            version=PACKAGING_CC_SWITCH_VERSION, asset=asset
        ),
        digest,
    )


def stage(target: Path, os_name: str, machine: str) -> Path:
    """Unpack the pinned cc-switch binary to one path.

    Args:
        target: Where the binary belongs, its name included.
        os_name: ``linux``, ``windows`` or ``darwin``.
        machine: ``x86_64`` or ``aarch64``.

    Returns:
        The staged binary.

    Raises:
        SystemExit: When there is no pin, what arrived is not what was
            pinned, or the archive carries no binary.
    """
    url, digest = asset_url(os_name, machine)
    downloaded = _fetch(url, digest)
    name = binary_name(os_name)
    with tempfile.TemporaryDirectory() as workdir:
        root = Path(workdir)
        archive = root / url.rsplit("/", 1)[-1]
        archive.write_bytes(downloaded)
        opened = root / "opened"
        opened.mkdir()
        shutil.unpack_archive(str(archive), str(opened))
        binary = opened / name
        if not binary.is_file():
            raise SystemExit(f"{url} carries no {name}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(binary, target)
    target.chmod(CC_SWITCH_MODE)
    return target


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
    with urllib.request.urlopen(url, timeout=CC_SWITCH_FETCH_TIMEOUT_S) as response:
        downloaded = response.read()
    arrived = hashlib.sha256(downloaded).hexdigest()
    if arrived != digest:
        raise SystemExit(
            f"cc-switch at {url} hashes to {arrived}, not the pinned {digest}"
        )
    return downloaded
