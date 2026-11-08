"""Write latest.json and SHA256SUMS over the files of one edition's release
site.

    python3 packaging/build/build_checksums.py --output-dir dist/
    python3 packaging/build/build_checksums.py --release-files collected/ --output-dir dist/
    python3 packaging/build/build_checksums.py --edition cn \\
        --release-files collected/ --output-dir dist_cn/

Runs on: any machine with Python 3.11 or newer. An edition's site holds its
edition's files, the cc-switch files and its own two of these.
``--release-files`` names a directory of every file the release's jobs
made, both editions' and the cc-switch files, and the site's files are
linked from it, by name, into the output directory first. The output
directory then holds the site's files alone, or the run stops naming the
first that is not. ``latest.json`` names the release as ``{tag, version}``,
the tag being ``v`` and the version the packages declare, and
``SHA256SUMS`` lists every file of the directory, ``latest.json`` among
them.

Not pure: links or copies the site's files, writes latest.json and
SHA256SUMS.
"""

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "packaging"))
from build_sources import version  # noqa: E402
from shared import edition_build, release_sites  # noqa: E402
from shared.constants import (  # noqa: E402
    PACKAGING_CHECKSUMS_FILE,
    PACKAGING_LATEST_FILE,
)


def main() -> int:
    """Write the two files.

    Returns:
        The process exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    edition_build.add_edition_argument(parser)
    parser.add_argument(
        "--output-dir", default="dist", help="the directory of the site's files"
    )
    parser.add_argument(
        "--release-files",
        default="",
        help="a directory of both editions' files to take the site's files from",
    )
    arguments = parser.parse_args()
    edition_build.require_edition_tree(arguments.edition)
    output_dir = (REPO_ROOT / arguments.output_dir).resolve()
    if arguments.release_files:
        take_site_files(
            (REPO_ROOT / arguments.release_files).resolve(),
            output_dir,
            arguments.edition,
        )
    if not output_dir.is_dir():
        raise SystemExit(f"{output_dir} is not a directory of release files")
    check_site_files(output_dir, arguments.edition)
    write_latest(output_dir, version())
    write_checksums(output_dir)
    return 0


def take_site_files(release_files: Path, output_dir: Path, edition: str) -> list:
    """Link the files of an edition's site into the site's directory.

    Args:
        release_files: A directory of every file the release's jobs made.
        output_dir: The site's directory, made when missing.
        edition: ``intl`` or ``cn``.

    Returns:
        The files placed, sorted, ``latest.json`` and ``SHA256SUMS`` left
        out.

    Raises:
        SystemExit: When ``release_files`` is no directory.
    """
    if not release_files.is_dir():
        raise SystemExit(f"{release_files} is not a directory of release files")
    output_dir.mkdir(parents=True, exist_ok=True)
    placed = []
    for path in sorted(release_files.iterdir()):
        if not path.is_file() or path.name in (
            PACKAGING_LATEST_FILE,
            PACKAGING_CHECKSUMS_FILE,
        ):
            continue
        if not release_sites.is_site_file(path.name, edition):
            continue
        target = output_dir / path.name
        target.unlink(missing_ok=True)
        try:
            os.link(path, target)
        except OSError:
            shutil.copyfile(path, target)
        placed.append(target)
    return placed


def check_site_files(output_dir: Path, edition: str) -> None:
    """Refuse a directory holding a file the edition's site does not hold.

    Args:
        output_dir: The site's directory.
        edition: ``intl`` or ``cn``.

    Raises:
        SystemExit: Naming the first file of the other edition.
    """
    for path in sorted(output_dir.iterdir()):
        if path.is_file() and not release_sites.is_site_file(path.name, edition):
            raise SystemExit(
                f"{path.name} in {output_dir} is no file of the {edition} site"
            )


def write_latest(output_dir: Path, package_version: str) -> Path:
    """Write ``latest.json``, which names the release.

    Args:
        output_dir: The directory holding the release files.
        package_version: The version the packages declare.

    Returns:
        The file written.
    """
    target = output_dir / PACKAGING_LATEST_FILE
    target.write_text(
        json.dumps({"tag": f"v{package_version}", "version": package_version}) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {target}")
    return target


def write_checksums(output_dir: Path) -> None:
    """Write SHA256SUMS beside the release files.

    The hub verifies this before installing an agent on a device, so a
    truncated download fails loudly instead of half-installing.

    Args:
        output_dir: The directory holding the release files.
    """
    lines = []
    for path in sorted(output_dir.iterdir()):
        if path.name == PACKAGING_CHECKSUMS_FILE or not path.is_file():
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.name}")
        print(f"  {path.name}  {path.stat().st_size // 1024} KiB")
    (output_dir / PACKAGING_CHECKSUMS_FILE).write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    print(f"wrote {output_dir / PACKAGING_CHECKSUMS_FILE}")


if __name__ == "__main__":
    sys.exit(main())
