"""The mainland source tree ``build_sources.py --edition cn`` writes.

The tree is staged from the real install scripts into ``tmp_path``: what is
asserted is that it holds none of the left-out paths and that its root
``EDITION`` file and both install scripts say ``cn``.
"""

import shutil
from pathlib import Path

import pytest

import build_sources

REPO_ROOT = Path(__file__).resolve().parents[3]
LEFT_OUT = ("hub/neutrino_hub/modules/xray", "packaging/build/build_core_netbird.py")


@pytest.fixture
def tree(tmp_path, monkeypatch):
    monkeypatch.setattr(build_sources, "PACKAGING_CN_LEFT_OUT_PATHS", LEFT_OUT)
    root = tmp_path / "neutrino-9.9.9"
    (root / "hub" / "neutrino_hub" / "modules" / "xray").mkdir(parents=True)
    (root / "hub" / "neutrino_hub" / "modules" / "xray" / "constants.py").write_text("")
    (root / "packaging" / "build").mkdir(parents=True)
    (root / "packaging" / "build" / "build_core_netbird.py").write_text("")
    shutil.copytree(REPO_ROOT / "packaging" / "install", root / "packaging" / "install")
    (root / "EDITION").write_text("intl\n")
    return root


def test_the_mainland_tree_holds_no_left_out_path(tree):
    build_sources.stamp_mainland_tree(tree)

    for path in LEFT_OUT:
        assert not (tree / path).exists()
    assert (tree / "hub" / "neutrino_hub" / "modules").is_dir()


def test_the_mainland_tree_and_both_install_scripts_say_cn(tree):
    build_sources.stamp_mainland_tree(tree)

    assert (tree / "EDITION").read_text() == "cn\n"
    install_sh = (tree / "packaging" / "install" / "install.sh").read_text()
    install_ps1 = (tree / "packaging" / "install" / "install.ps1").read_text()
    assert '\nEDITION="cn"\n' in install_sh
    assert 'EDITION="intl"' not in install_sh
    assert "\n$EDITION = 'cn'\n" in install_ps1
    assert "$EDITION = 'intl'" not in install_ps1


def test_the_committed_scripts_and_root_say_intl():
    assert (REPO_ROOT / "EDITION").read_text() == "intl\n"
    for name, stamp in build_sources.INSTALL_SCRIPT_STAMPS.items():
        text = (REPO_ROOT / "packaging" / "install" / name).read_text()
        assert f"\n{stamp['intl']}\n" in text
