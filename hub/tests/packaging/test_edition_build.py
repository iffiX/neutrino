"""The edition every build is asked for, and the check on the tree it runs in.

A build stops on a tree that is not its edition's, by
``shared.edition_tree.check_tree``; the edition reaches the step that writes
``_version.py`` through ``NEUTRINO_EDITION``.
"""

import argparse
import subprocess
import sys
from pathlib import Path

import pytest

from shared import edition_build
from shared.constants import PACKAGING_EDITION_ENV, PACKAGING_INSTALL_EDITION_LINES
import venv_tree

# The phone core scripts take no edition: a core is the same in both, and
# each script's own bytes name its cache.
BUILD_SCRIPTS = sorted(
    path
    for path in (Path(__file__).resolve().parents[3] / "packaging" / "build").glob(
        "build_*.py"
    )
    if not path.name.startswith("build_core_")
)


REPO_ROOT = Path(__file__).resolve().parents[3]
# The edition this tree is, and the one it is not.
OWN_EDITION = (REPO_ROOT / "EDITION").read_text().strip()
OTHER_EDITION = "cn" if OWN_EDITION == "intl" else "intl"


@pytest.fixture
def cn_tree(tmp_path, monkeypatch):
    """A tree the mainland edition would build: its root file and both
    install scripts say cn, and it holds no left-out path."""
    monkeypatch.setenv(PACKAGING_EDITION_ENV, "")
    (tmp_path / "EDITION").write_text("cn\n")
    for relative, line in PACKAGING_INSTALL_EDITION_LINES.items():
        (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / relative).write_text(line.format(edition="cn") + "\n")
    return tmp_path


def test_a_build_of_the_other_edition_stops_on_this_tree(monkeypatch):
    monkeypatch.setenv(PACKAGING_EDITION_ENV, "")

    with pytest.raises(SystemExit) as refused:
        edition_build.require_edition_tree(OTHER_EDITION, REPO_ROOT)

    assert str(refused.value) == f"EDITION names {OWN_EDITION}, not {OTHER_EDITION}"


def test_an_intl_build_stops_on_the_mainland_tree(cn_tree):
    with pytest.raises(SystemExit) as refused:
        edition_build.require_edition_tree("intl", cn_tree)

    assert str(refused.value) == "EDITION names cn, not intl"


def test_a_tree_of_its_edition_names_the_edition_for_the_build(cn_tree):
    edition_build.require_edition_tree("cn", cn_tree)

    assert edition_build.build_edition() == "cn"


def test_a_build_script_asked_for_the_other_edition_exits_with_one_sentence(
    tmp_path,
):
    script = REPO_ROOT / "packaging" / "build" / "build_checksums.py"

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--edition",
            OTHER_EDITION,
            "--output-dir",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert result.stderr.strip() == (
        f"EDITION names {OWN_EDITION}, not {OTHER_EDITION}"
    )


def test_a_build_with_no_edition_named_is_intl(monkeypatch):
    monkeypatch.setenv(PACKAGING_EDITION_ENV, "")

    assert edition_build.build_edition() == "intl"


def test_an_edition_that_is_none_stops_the_build(monkeypatch):
    monkeypatch.setenv(PACKAGING_EDITION_ENV, "eu")

    with pytest.raises(SystemExit) as refused:
        edition_build.build_edition()

    assert "NEUTRINO_EDITION is eu" in str(refused.value)


def test_the_option_takes_the_two_editions_and_defaults_to_intl():
    parser = argparse.ArgumentParser()
    edition_build.add_edition_argument(parser)

    assert parser.parse_args([]).edition == "intl"
    assert parser.parse_args(["--edition", "cn"]).edition == "cn"
    with pytest.raises(SystemExit):
        parser.parse_args(["--edition", "eu"])


@pytest.mark.parametrize("script", BUILD_SCRIPTS, ids=lambda path: path.name)
def test_every_build_script_takes_the_edition(script):
    result = subprocess.run(
        [sys.executable, str(script), "--help"], capture_output=True, text=True
    )

    assert result.returncode == 0, result.stderr
    assert "--edition {intl,cn}" in result.stdout


@pytest.mark.parametrize("edition", ["intl", "cn"])
def test_the_hub_stamp_carries_the_edition(monkeypatch, edition):
    monkeypatch.setenv(PACKAGING_EDITION_ENV, edition)
    namespace = {}

    exec(venv_tree.version_stamp("9.9.9", "x"), namespace)  # noqa: S102

    assert namespace["EDITION"] == edition


@pytest.mark.parametrize(
    ("kind", "architecture", "intl", "cn"),
    [
        ("deb", "amd64", "x_1.0_amd64.deb", "x_1.0_amd64-cn.deb"),
        ("rpm", "x86_64", "x-1.0-1.x86_64.rpm", "x-1.0-1.x86_64-cn.rpm"),
        (
            "pkg",
            "x86_64",
            "x-1.0-1-x86_64.pkg.tar.zst",
            "x-1.0-1-x86_64-cn.pkg.tar.zst",
        ),
        ("msi", "amd64", "x-1.0-windows-amd64.msi", "x-1.0-windows-amd64-cn.msi"),
        ("macos_pkg", "arm64", "x-1.0-macos-arm64.pkg", "x-1.0-macos-arm64-cn.pkg"),
        ("apk", "", "x-1.0-android.apk", "x-1.0-android-cn.apk"),
        ("ipa", "", "x-1.0-ios.ipa", "x-1.0-ios-cn.ipa"),
    ],
)
def test_a_cn_file_name_holds_cn_before_its_extension(
    monkeypatch, kind, architecture, intl, cn
):
    for edition, expected in (("intl", intl), ("cn", cn)):
        monkeypatch.setenv(PACKAGING_EDITION_ENV, edition)

        found = edition_build.asset_name(
            kind, name="x", version="1.0", architecture=architecture
        )

        assert found == expected
        assert edition_build.is_edition_file(found, edition)
        assert not edition_build.is_edition_file(found, OTHER_OF[edition])
    if kind in ("rpm", "pkg"):
        assert (
            edition_build.built_name(
                kind, name="x", version="1.0", architecture=architecture
            )
            == intl
        )


OTHER_OF = {"intl": "cn", "cn": "intl"}
