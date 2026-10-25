"""The mainland source tree, and the check that a tree is the edition it says.

The mainland tree is a checkout's tree with every path of
``PACKAGING_CN_LEFT_OUT_PATHS`` deleted, the root ``EDITION`` file naming
``cn``, both install scripts stamped ``cn`` with the release sites, and the
CNB README as its only README. A ``cn`` build refuses a tree that holds a
left-out path, and an ``intl`` build one that lacks it.

Not pure: deletes and writes files under the tree it is given.
"""

import shutil
from pathlib import Path

from shared import install_script_stamp
from shared.constants import (
    PACKAGING_CN_LEFT_OUT_PATHS,
    PACKAGING_EDITION_FILE,
    PACKAGING_EDITIONS,
    PACKAGING_INSTALL_EDITION_LINES,
    PACKAGING_RELEASE_SITES,
)

# The mainland tree's README is the CNB one, under the name CNB shows.
EDITION_README = "README.md"
EDITION_CN_README_SOURCE = "README.zh-CN-CNB.md"
EDITION_CN_DROPPED_READMES = ("README.zh-CN.md", EDITION_CN_README_SOURCE)


def make_cn_tree(root: Path) -> None:
    """Turn a checkout's tree into the mainland tree, in place.

    Args:
        root: The tree's root, holding ``hub/``, ``packaging/`` and the rest.

    Raises:
        SystemExit: When an install script holds no committed line to stamp,
            the tree holds no CNB README, or the result still holds a
            left-out path.
    """
    for relative in PACKAGING_CN_LEFT_OUT_PATHS:
        path = root / relative
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
    (root / PACKAGING_EDITION_FILE).write_text("cn\n", encoding="utf-8")
    install_script_stamp.stamp_tree(root, edition="cn", sites=PACKAGING_RELEASE_SITES)
    source = root / EDITION_CN_README_SOURCE
    if not source.is_file():
        raise SystemExit(f"the tree holds no {EDITION_CN_README_SOURCE}")
    (root / EDITION_README).write_text(
        source.read_text(encoding="utf-8"), encoding="utf-8"
    )
    for name in EDITION_CN_DROPPED_READMES:
        (root / name).unlink(missing_ok=True)
    check_tree(root, "cn")


def check_tree(root: Path, edition: str) -> None:
    """Refuse a tree that is not the edition a build makes of it.

    Args:
        root: The tree's root.
        edition: ``intl`` or ``cn``.

    Raises:
        SystemExit: One sentence naming the first path a ``cn`` tree holds
            or an ``intl`` tree lacks, the CNB README a ``cn`` tree holds or
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
    is_cnb_readme_present = (root / EDITION_CN_README_SOURCE).exists()
    if edition == "cn" and is_cnb_readme_present:
        raise SystemExit(f"a cn tree holds {EDITION_CN_README_SOURCE}")
    if edition == "intl" and not is_cnb_readme_present:
        raise SystemExit(f"an intl tree lacks {EDITION_CN_README_SOURCE}")
    for relative, line in PACKAGING_INSTALL_EDITION_LINES.items():
        path = root / relative
        if line.format(edition=edition) not in path.read_text(encoding="utf-8"):
            raise SystemExit(f"{relative} is not stamped {edition}")
