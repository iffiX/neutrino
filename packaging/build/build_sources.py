"""Write a release's source archive, of either edition.

    python3 packaging/build/build_sources.py --output-dir dist/
    python3 packaging/build/build_sources.py --edition cn --output-dir dist/
    python3 packaging/build/build_sources.py --edition cn --tree build/cn

Runs on: any machine with git and Python 3.11 or newer.

``neutrino-<version>-source.tar.gz`` is this tree at the current commit, with
the source of everything the packages carry beside it under
``third_party/``, so a release attaches a single file.
``neutrino-<version>-cn-source.tar.gz`` is the mainland tree: the same
commit without the paths ``PACKAGING_CN_LEFT_OUT_PATHS`` lists, ``EDITION``
naming ``cn`` and both install scripts stamped ``cn``, with the source of
what the ``cn`` packages carry. ``--tree`` writes the mainland tree
unpacked, without ``third_party/``, for a build or a test run from it.

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
from shared.constants import PACKAGING_EDITIONS  # noqa: E402
from shared.edition_tree import make_cn_tree  # noqa: E402

# The upstream source the mainland packages do not carry, left out of its
# archive's third_party/.
CN_LEFT_OUT_SOURCES = ("netbird-", "xray-core-")

# The source of everything the packages carry, pinned to the archive at the
# tag the binaries were built from: RustDesk (AGPL-3.0) in the agent and the
# client, EasyTier (LGPL-3.0), NetBird (BSD-3), xray (MPL-2.0) and
# CLIProxyAPI (MIT) in the hub, cc-switch (MIT) in the client,
# at the version of its pin in shared.constants. Each goes into
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


def main() -> int:
    """Write the archive.

    Returns:
        The process exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", default="dist", help="where to write it")
    parser.add_argument(
        "--edition",
        choices=PACKAGING_EDITIONS,
        default="intl",
        help="which edition's source archive (default: intl)",
    )
    parser.add_argument(
        "--tree",
        default="",
        help="write the cn tree unpacked into this new directory, and no archive",
    )
    arguments = parser.parse_args()
    if shutil.which("git") is None:
        raise SystemExit("git is needed and is not on the path")
    if arguments.tree:
        if arguments.edition != "cn":
            raise SystemExit("--tree writes the mainland tree; pass --edition cn")
        write_cn_tree((REPO_ROOT / arguments.tree).resolve())
        return 0
    output_dir = (REPO_ROOT / arguments.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    write_source_archive(output_dir, edition=arguments.edition)
    return 0


def write_source_archive(output_dir: Path, *, edition: str = "intl") -> None:
    """Write one edition's source archive.

    ``neutrino-<version>/`` holds this tree as git carries it at the current
    commit, the mainland tree for ``cn``, and ``neutrino-<version>/third_party/``
    the pinned upstream archives of what that edition's packages carry, as
    they were fetched.

    Args:
        output_dir: The directory holding the packages.
        edition: ``intl`` or ``cn``.

    Raises:
        SystemExit: When an upstream archive is not the one pinned, the tree
            is not a git checkout, or the mainland tree cannot be made.
    """
    package_version = version()
    root = f"neutrino-{package_version}"
    suffix = "-cn-source.tar.gz" if edition == "cn" else "-source.tar.gz"
    target = output_dir / f"{root}{suffix}"
    with tempfile.TemporaryDirectory() as workdir:
        tree = Path(workdir) / root
        unpack_head(tree)
        if edition == "cn":
            make_cn_tree(tree)

        third_party = tree / "third_party"
        third_party.mkdir()
        for name, url, digest in SOURCE_ARCHIVES:
            if edition == "cn" and name.startswith(CN_LEFT_OUT_SOURCES):
                continue
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


def write_cn_tree(target: Path) -> None:
    """Write the mainland tree, unpacked and without third_party/.

    Args:
        target: A directory that does not exist yet.

    Raises:
        SystemExit: When the directory exists, the tree is not a git
            checkout, or the mainland tree cannot be made.
    """
    if target.exists():
        raise SystemExit(f"{target} exists; the mainland tree goes into a new one")
    unpack_head(target)
    make_cn_tree(target)
    print(f"wrote the mainland tree at {target}")


def unpack_head(tree: Path) -> None:
    """Unpack this tree as git carries it at the current commit.

    Args:
        tree: The directory to unpack into, made here.

    Raises:
        SystemExit: When the tree is not a git checkout.
    """
    tree.mkdir(parents=True)
    archived = subprocess.run(
        ["git", "archive", "--format=tar", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
    )
    if archived.returncode != 0:
        raise SystemExit(archived.stderr.decode(errors="replace").strip())
    with tarfile.open(fileobj=io.BytesIO(archived.stdout)) as bundle:
        bundle.extractall(tree, filter="data")


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
