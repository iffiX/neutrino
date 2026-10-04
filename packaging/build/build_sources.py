"""Write the release's one source archive.

    python3 packaging/build/build_sources.py --output-dir dist/

Runs on: any machine with git and Python 3.11 or newer.

``neutrino-<version>-source.tar.gz`` is this tree at the current commit, with
the source of everything the packages carry beside it under
``third_party/``, so a release attaches a single file. ``--edition cn``
writes ``neutrino-<version>-cn-source.tar.gz``, the mainland source tree:
the same tree without the paths of ``PACKAGING_CN_LEFT_OUT_PATHS``, its root
``EDITION`` file and both install scripts stamped ``cn``. Both are written
from the full checkout.

Not pure: runs git, downloads, writes the archive.
"""

import argparse
import hashlib
import io
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "packaging"))
from shared import edition_build  # noqa: E402
from shared.constants import (  # noqa: E402
    PACKAGING_CN_LEFT_OUT_PATHS,
    PACKAGING_EDITIONS,
)

# The source of everything the packages carry, pinned to the archive at the
# tag the binaries were built from: RustDesk (AGPL-3.0) in the agent and the
# client, EasyTier (LGPL-3.0), NetBird (BSD-3), xray (MPL-2.0) and
# CLIProxyAPI (MIT) in the hub, cc-switch (MIT) in the client. Each goes into
# the release's source archive unmodified.
SOURCE_ARCHIVES = (
    (
        "rustdesk-1.4.9-source.tar.gz",
        "https://github.com/rustdesk/rustdesk/archive/refs/tags/1.4.9.tar.gz",
        "1769fcc51751aab91bc0cfa691723722f51d3693ce3ddea3d92cfb1c319100e0",  # scan: allow
    ),
    (
        "easytier-2.6.4-source.tar.gz",
        "https://github.com/EasyTier/EasyTier/archive/refs/tags/v2.6.4.tar.gz",
        "352c0866da709415a837405a6ce4f51b8dfae27e5d5c1da1fb4d8f7338e46795",  # scan: allow
    ),
    (
        "netbird-0.78.1-source.tar.gz",
        "https://github.com/netbirdio/netbird/archive/refs/tags/v0.78.1.tar.gz",
        "2adde8bbd77ea595b5f50174be10574466f1c07fc9fbf827024245aec2f4dabc",  # scan: allow
    ),
    (
        "xray-core-26.3.27-source.tar.gz",
        "https://github.com/XTLS/Xray-core/archive/refs/tags/v26.3.27.tar.gz",
        "992a4997e6bb846d11469435d687f99ef812fcde1e0a009bb8e95189ea20331d",  # scan: allow
    ),
    (
        "cliproxyapi-7.2.146-source.tar.gz",
        "https://github.com/router-for-me/CLIProxyAPI/archive/refs/tags/v7.2.146.tar.gz",
        "10078716be34cc7ecf488c3b50b17d5675261a36eb78cbdfd768331b989f9fca",  # scan: allow
    ),
    (
        "cc-switch-cli-5.10.4-source.tar.gz",
        "https://github.com/SaladDay/cc-switch-cli/archive/refs/tags/v5.10.4.tar.gz",
        "cb10c2742b5552bb4de4cf58663afdf8d79e96e05ea68b5533489a6ba0583dcb",  # scan: allow
    ),
)

# The line near the top of each install script that names its edition.
INSTALL_SCRIPT_STAMPS = {
    "install.sh": {"intl": 'EDITION="intl"', "cn": 'EDITION="cn"'},
    "install.ps1": {"intl": "$EDITION = 'intl'", "cn": "$EDITION = 'cn'"},
}


def main() -> int:
    """Write the archive.

    Returns:
        The process exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    edition_build.add_edition_argument(parser)
    parser.add_argument("--output-dir", default="dist", help="where to write it")
    arguments = parser.parse_args()
    edition_build.require_edition_tree(PACKAGING_EDITIONS[0])
    if shutil.which("git") is None:
        raise SystemExit("git is needed and is not on the path")
    output_dir = (REPO_ROOT / arguments.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    write_source_archive(output_dir, arguments.edition)
    return 0


def write_source_archive(output_dir: Path, edition: str = "intl") -> None:
    """Write the release's one source archive of an edition.

    ``neutrino-<version>/`` holds this tree as git carries it at the current
    commit, and ``neutrino-<version>/third_party/`` the pinned upstream
    archives as they were fetched. The ``cn`` tree lacks every left-out
    path and is stamped ``cn``.

    Args:
        output_dir: The directory holding the packages.
        edition: ``intl`` or ``cn``.

    Raises:
        SystemExit: When an upstream archive is not the one pinned, or the
            tree is not a git checkout.
    """
    package_version = version()
    root = f"neutrino-{package_version}"
    infix = "-cn" if edition == "cn" else ""
    target = output_dir / f"{root}{infix}-source.tar.gz"
    with tempfile.TemporaryDirectory() as workdir:
        tree = Path(workdir) / root
        tree.mkdir()
        archived = subprocess.run(
            ["git", "archive", "--format=tar", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
        )
        if archived.returncode != 0:
            raise SystemExit(archived.stderr.decode(errors="replace").strip())
        with tarfile.open(fileobj=io.BytesIO(archived.stdout)) as bundle:
            bundle.extractall(tree, filter="data")
        if edition == "cn":
            stamp_mainland_tree(tree)

        third_party = tree / "third_party"
        third_party.mkdir()
        for name, url, digest in SOURCE_ARCHIVES:
            print(f"  fetching {name}")
            with urllib.request.urlopen(url, timeout=600) as response:
                data = response.read()
            found = hashlib.sha256(data).hexdigest()
            if found != digest:
                raise SystemExit(f"{name}: expected sha256 {digest}, got {found}")
            (third_party / name).write_bytes(data)

        with tarfile.open(target, "w:gz") as archive:
            archive.add(tree, arcname=root)
    print(f"wrote {target} ({target.stat().st_size // 1024 // 1024} MiB)")


def stamp_mainland_tree(tree: Path) -> None:
    """Take the left-out paths out of a tree and stamp it ``cn``.

    Args:
        tree: The unpacked tree.

    Raises:
        SystemExit: When an install script holds no edition line.
    """
    for path in PACKAGING_CN_LEFT_OUT_PATHS:
        target = tree / path
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()
    (tree / "EDITION").write_text("cn\n", encoding="utf-8")
    for name, stamp in INSTALL_SCRIPT_STAMPS.items():
        script = tree / "packaging" / "install" / name
        text = script.read_text(encoding="utf-8")
        if stamp["intl"] not in text:
            raise SystemExit(f"{name} holds no line {stamp['intl']}")
        script.write_text(text.replace(stamp["intl"], stamp["cn"], 1), "utf-8")


def version() -> str:
    """The version the packages declare, read off the hub's pyproject.

    Raises:
        SystemExit: When the pyproject declares none.
    """
    text = (REPO_ROOT / "hub" / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if match is None:
        raise SystemExit("hub/pyproject.toml declares no version")
    return match.group(1)


if __name__ == "__main__":
    sys.exit(main())
