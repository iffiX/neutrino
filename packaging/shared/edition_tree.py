"""The mainland source tree, and the check that a tree is the edition it says.

The mainland tree is a checkout's tree with every path of
``PACKAGING_CN_LEFT_OUT_PATHS`` deleted, the root ``EDITION`` file naming
``cn``, both install scripts stamped ``cn`` and the READMEs pointing at
Gitee. A ``cn`` build refuses a tree that holds a left-out path, and an
``intl`` build one that lacks it.

Not pure: deletes and writes files under the tree it is given.
"""

import shutil
from pathlib import Path

from shared.constants import (
    PACKAGING_CN_LEFT_OUT_PATHS,
    PACKAGING_EDITION_FILE,
    PACKAGING_EDITIONS,
    PACKAGING_INSTALL_EDITION_LINES,
)

# The READMEs of the mainland tree name the mainland release.
EDITION_CN_README_NAMES = ("README.md", "README.zh-CN.md")
EDITION_CN_README_ADDRESSES = (
    (
        "https://github.com/iffiX/neutrino/releases",
        "https://gitee.com/iffiX/neutrino/releases",
    ),
)


def make_cn_tree(root: Path) -> None:
    """Turn a checkout's tree into the mainland tree, in place.

    Args:
        root: The tree's root, holding ``hub/``, ``packaging/`` and the rest.

    Raises:
        SystemExit: When an install script holds no ``intl`` edition line to
            stamp, or the result still holds a left-out path.
    """
    for relative in PACKAGING_CN_LEFT_OUT_PATHS:
        path = root / relative
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
    (root / PACKAGING_EDITION_FILE).write_text("cn\n", encoding="utf-8")
    for relative, line in PACKAGING_INSTALL_EDITION_LINES.items():
        stamp_install_script(root / relative, line)
    for name in EDITION_CN_README_NAMES:
        path = root / name
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for international, mainland in EDITION_CN_README_ADDRESSES:
            text = text.replace(international, mainland)
        path.write_text(text, encoding="utf-8")
    check_tree(root, "cn")


def stamp_install_script(path: Path, line: str) -> None:
    """Stamp one install script ``cn``.

    Args:
        path: The script.
        line: Its edition line, with ``{edition}`` open.

    Raises:
        SystemExit: When the script holds no ``intl`` line to stamp.
    """
    text = path.read_text(encoding="utf-8")
    international = line.format(edition="intl")
    if international not in text.splitlines():
        raise SystemExit(f"{path.name} holds no line {international!r} to stamp cn")
    path.write_text(
        text.replace(international, line.format(edition="cn"), 1), encoding="utf-8"
    )


def check_tree(root: Path, edition: str) -> None:
    """Refuse a tree that is not the edition a build makes of it.

    Args:
        root: The tree's root.
        edition: ``intl`` or ``cn``.

    Raises:
        SystemExit: One sentence naming the first path a ``cn`` tree holds
            or an ``intl`` tree lacks, or an install script not stamped with
            the edition.
        ValueError: When ``edition`` is neither.
    """
    if edition not in PACKAGING_EDITIONS:
        raise ValueError(f"no edition named {edition!r}")
    edition_file = root / PACKAGING_EDITION_FILE
    named = (
        edition_file.read_text(encoding="utf-8").strip()
        if edition_file.is_file()
        else ""
    )
    if named != edition:
        raise SystemExit(
            f"{PACKAGING_EDITION_FILE} names {named or 'nothing'}, not {edition}"
        )
    for relative in PACKAGING_CN_LEFT_OUT_PATHS:
        is_present = (root / relative).exists()
        if edition == "cn" and is_present:
            raise SystemExit(f"a cn tree holds {relative}, which cn leaves out")
        if edition == "intl" and not is_present:
            raise SystemExit(f"an intl tree lacks {relative}")
    for relative, line in PACKAGING_INSTALL_EDITION_LINES.items():
        path = root / relative
        if line.format(edition=edition) not in path.read_text(encoding="utf-8"):
            raise SystemExit(f"{relative} is not stamped {edition}")
