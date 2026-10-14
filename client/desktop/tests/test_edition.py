"""The edition the client was built as, and the client leaving nothing out.

The stamp a build writes outranks the root ``EDITION`` file of a checkout,
which reads as ``intl`` when it is missing or names neither edition. The
mainland tree deletes no file of the client.
"""

import importlib
import sys
from pathlib import Path

from neutrino_client import edition

CLIENT_ROOT = Path(edition.__file__).resolve().parents[1]
REPO_ROOT = CLIENT_ROOT.parents[1]


def test_the_mainland_tree_leaves_out_no_file_of_the_client():
    sys.path.insert(0, str(REPO_ROOT / "packaging"))
    try:
        from shared.constants import PACKAGING_CN_LEFT_OUT_PATHS
    finally:
        sys.path.remove(str(REPO_ROOT / "packaging"))

    assert [
        path
        for path in PACKAGING_CN_LEFT_OUT_PATHS
        if path.startswith("client/desktop/")
    ] == []


def test_a_checkout_reads_its_edition_from_the_root_file():
    named = (REPO_ROOT / edition.EDITION_FILE_NAME).read_text(encoding="utf-8")

    assert named.strip() in edition.EDITIONS
    assert edition._checkout_edition() == named.strip()


def test_a_missing_or_unknown_root_file_reads_as_intl(monkeypatch, tmp_path):
    fake = tmp_path / "client" / "desktop" / "neutrino_client" / "edition.py"
    fake.parent.mkdir(parents=True)
    monkeypatch.setattr(edition, "__file__", str(fake))

    assert edition._checkout_edition() == "intl"
    (tmp_path / "EDITION").write_text("elsewhere\n", encoding="utf-8")
    assert edition._checkout_edition() == "intl"
    (tmp_path / "EDITION").write_text("cn\n", encoding="utf-8")
    assert edition._checkout_edition() == "cn"


def test_a_built_package_reads_the_stamp(monkeypatch):
    """The stamp a build writes outranks the root file."""
    import types

    stamp = types.ModuleType("neutrino_client._version")
    stamp.EDITION = "cn"
    monkeypatch.setitem(sys.modules, "neutrino_client._version", stamp)
    try:
        assert importlib.reload(edition).EDITION == "cn"
    finally:
        monkeypatch.delitem(sys.modules, "neutrino_client._version")
        importlib.reload(edition)
