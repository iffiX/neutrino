"""The mainland source tree: the left-out paths gone, everything stamped cn.

A cn tree holding a path of ``PACKAGING_CN_LEFT_OUT_PATHS`` is refused by
name, and so is an intl tree lacking one; the repository itself is the
intl tree, so every listed path is one it holds.
"""

from pathlib import Path

import pytest

import build_sources
from shared.constants import (
    PACKAGING_CN_LEFT_OUT_PATHS,
    PACKAGING_INSTALL_EDITION_LINES,
)
from shared.edition_tree import check_tree, make_cn_tree

REPO_ROOT = Path(__file__).resolve().parents[3]


def intl_tree(root: Path) -> Path:
    """A tree holding every left-out path, the edition file and both scripts."""
    for relative in PACKAGING_CN_LEFT_OUT_PATHS:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix:
            path.write_text("left out\n", encoding="utf-8")
        else:
            path.mkdir()
            (path / "__init__.py").write_text("", encoding="utf-8")
    for relative, line in PACKAGING_INSTALL_EDITION_LINES.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# a script\n{line.format(edition='intl')}\n", "utf-8")
    (root / "EDITION").write_text("intl\n", encoding="utf-8")
    (root / "README.md").write_text("# the full README\n", encoding="utf-8")
    (root / "README.zh-CN.md").write_text("# 完整的中文 README\n", encoding="utf-8")
    (root / "README.zh-CN-Gitee.md").write_text("# Gitee 的 README\n", "utf-8")
    (root / "hub" / "neutrino_hub" / "kept.py").write_text("", encoding="utf-8")
    return root


def test_the_repository_is_the_edition_its_root_file_names():
    """The GitHub repository holds every listed path; the mainland tree
    none of them."""
    edition = (REPO_ROOT / "EDITION").read_text(encoding="utf-8").strip()

    check_tree(REPO_ROOT, edition)


def test_the_mainland_tree_holds_none_of_the_listed_paths(tmp_path):
    root = intl_tree(tmp_path)

    make_cn_tree(root)

    assert [p for p in PACKAGING_CN_LEFT_OUT_PATHS if (root / p).exists()] == []
    assert (root / "hub" / "neutrino_hub" / "kept.py").is_file()
    assert (root / "EDITION").read_text(encoding="utf-8") == "cn\n"
    check_tree(root, "cn")


def test_both_install_scripts_are_stamped_cn(tmp_path):
    root = intl_tree(tmp_path)

    make_cn_tree(root)

    for relative, line in PACKAGING_INSTALL_EDITION_LINES.items():
        text = (root / relative).read_text(encoding="utf-8")
        assert line.format(edition="cn") in text.splitlines()
        assert line.format(edition="intl") not in text


def test_the_mainland_readme_is_the_gitee_one_and_the_only_one(tmp_path):
    root = intl_tree(tmp_path)

    make_cn_tree(root)

    assert (root / "README.md").read_text(encoding="utf-8") == "# Gitee 的 README\n"
    assert not (root / "README.zh-CN.md").exists()
    assert not (root / "README.zh-CN-Gitee.md").exists()


def test_a_tree_without_the_gitee_readme_stops_the_mainland_tree(tmp_path):
    root = intl_tree(tmp_path)
    (root / "README.zh-CN-Gitee.md").unlink()

    with pytest.raises(SystemExit, match="holds no README.zh-CN-Gitee.md"):
        make_cn_tree(root)


def test_the_gitee_readme_tells_a_mainland_tree_from_a_full_one(tmp_path):
    root = intl_tree(tmp_path)
    make_cn_tree(root)
    (root / "README.zh-CN-Gitee.md").write_text("# back\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="a cn tree holds README.zh-CN-Gitee.md"):
        check_tree(root, "cn")


def test_an_intl_tree_lacking_the_gitee_readme_is_refused(tmp_path):
    root = intl_tree(tmp_path)
    (root / "README.zh-CN-Gitee.md").unlink()

    with pytest.raises(SystemExit, match="an intl tree lacks README.zh-CN-Gitee.md"):
        check_tree(root, "intl")


def test_a_cn_tree_holding_a_left_out_path_is_refused_by_name(tmp_path):
    root = intl_tree(tmp_path)
    make_cn_tree(root)
    (root / "hub/neutrino_hub/modules/xray").mkdir()

    with pytest.raises(SystemExit, match="hub/neutrino_hub/modules/xray"):
        check_tree(root, "cn")


def test_an_intl_tree_lacking_a_left_out_path_is_refused_by_name(tmp_path):
    root = intl_tree(tmp_path)
    (root / "hub/neutrino_hub/web/routers/hub/overlay_netbird.py").unlink()

    with pytest.raises(SystemExit, match="overlay_netbird.py"):
        check_tree(root, "intl")


def test_a_tree_whose_edition_file_says_otherwise_is_refused(tmp_path):
    root = intl_tree(tmp_path)

    with pytest.raises(SystemExit, match="EDITION names intl, not cn"):
        check_tree(root, "cn")


def test_a_script_with_no_line_to_stamp_stops_the_tree(tmp_path):
    root = intl_tree(tmp_path)
    (root / "packaging/install/install.sh").write_text("# no edition\n", "utf-8")

    with pytest.raises(SystemExit, match="install.sh holds no line"):
        make_cn_tree(root)


def test_the_cn_archive_carries_no_upstream_source_of_a_left_out_feature():
    kept = [
        name
        for name, _, _ in build_sources.SOURCE_ARCHIVES
        if not name.startswith(build_sources.CN_LEFT_OUT_SOURCES)
    ]

    assert not any("netbird" in name or "xray" in name for name in kept)
    assert any(name.startswith("easytier-") for name in kept)
    assert any(name.startswith("rustdesk-") for name in kept)


def test_both_archives_carry_the_source_of_the_pinned_cc_switch():
    """The client and every agent package carry cc-switch in both editions."""
    from shared.constants import PACKAGING_CC_SWITCH_VERSION

    name = f"cc-switch-cli-{PACKAGING_CC_SWITCH_VERSION}-source.tar.gz"
    (url,) = [url for found, url, _ in build_sources.SOURCE_ARCHIVES if found == name]

    assert not name.startswith(build_sources.CN_LEFT_OUT_SOURCES)
    assert url.endswith(f"/v{PACKAGING_CC_SWITCH_VERSION}.tar.gz")


def test_the_removal_scripts_stop_only_units_this_tree_carries():
    """The removal scripts' list comes from the code, so in the mainland
    tree it names no unit of the proxy or NetBird."""
    import re

    import venv_tree
    from neutrino_hub.utils.constants import UTILS_DATA_DIR

    lines = venv_tree.stop_hub_lines()
    named = re.search(r"for unit in ([^;]+); do", lines).group(1).split()
    templates = {path.name for path in (UTILS_DATA_DIR / "services").iterdir()}

    assert named and all(f"{unit}.service" in templates for unit in named), named
