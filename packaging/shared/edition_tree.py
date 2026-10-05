"""The mainland source tree, and the check that a tree is the edition it says.

The mainland tree is a checkout's tree with every path of
``PACKAGING_CN_LEFT_OUT_PATHS`` deleted, the root ``EDITION`` file naming
``cn``, both install scripts stamped ``cn`` and the Gitee README as its
only README. A ``cn`` build refuses a tree that holds a left-out path, and an
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

# The mainland tree's README is the Gitee one, under the name Gitee shows.
EDITION_README = "README.md"
EDITION_CN_README_SOURCE = "README.zh-CN-Gitee.md"
EDITION_CN_DROPPED_READMES = ("README.zh-CN.md", EDITION_CN_README_SOURCE)


def make_cn_tree(root: Path) -> None:
    """Turn a checkout's tree into the mainland tree, in place.

    Args:
        root: The tree's root, holding ``hub/``, ``packaging/`` and the rest.

    Raises:
        SystemExit: When an install script holds no ``intl`` edition line to
            stamp, the tree holds no Gitee README, or the result still holds
            a left-out path.
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
    source = root / EDITION_CN_README_SOURCE
    if not source.is_file():
        raise SystemExit(f"the tree holds no {EDITION_CN_README_SOURCE}")
    (root / EDITION_README).write_text(
        source.read_text(encoding="utf-8"), encoding="utf-8"
    )
    for name in EDITION_CN_DROPPED_READMES:
        (root / name).unlink(missing_ok=True)
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
            or an ``intl`` tree lacks, the Gitee README a ``cn`` tree holds or
            an ``intl`` tree lacks, or an install script not stamped with the
            edition.
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
    is_gitee_readme_present = (root / EDITION_CN_README_SOURCE).exists()
    if edition == "cn" and is_gitee_readme_present:
        raise SystemExit(f"a cn tree holds {EDITION_CN_README_SOURCE}")
    if edition == "intl" and not is_gitee_readme_present:
        raise SystemExit(f"an intl tree lacks {EDITION_CN_README_SOURCE}")
    for relative, line in PACKAGING_INSTALL_EDITION_LINES.items():
        path = root / relative
        if line.format(edition=edition) not in path.read_text(encoding="utf-8"):
            raise SystemExit(f"{relative} is not stamped {edition}")
