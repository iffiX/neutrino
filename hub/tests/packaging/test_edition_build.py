"""The edition every build is asked for, and the check on the tree it runs in.

A ``cn`` build stops on a tree that holds a path the mainland edition leaves
out, and an ``intl`` build on one that lacks it; the edition reaches the
step that writes ``_version.py`` through ``NEUTRINO_EDITION``.
"""

import argparse
import subprocess
import sys
from pathlib import Path

import pytest

from shared import edition_build
from shared.constants import PACKAGING_EDITION_ENV
import venv_tree

BUILD_SCRIPTS = sorted(
    (Path(__file__).resolve().parents[3] / "packaging" / "build").glob("build_*.py")
)


@pytest.fixture
def left_out(tmp_path, monkeypatch):
    """A tree and the one path its mainland edition leaves out."""
    monkeypatch.setattr(
        edition_build, "PACKAGING_CN_LEFT_OUT_PATHS", ("hub/neutrino_hub/modules/xray",)
    )
    monkeypatch.setenv(PACKAGING_EDITION_ENV, "")
    return tmp_path


def test_a_cn_build_stops_on_a_tree_that_holds_a_left_out_path(left_out):
    (left_out / "hub" / "neutrino_hub" / "modules" / "xray").mkdir(parents=True)

    with pytest.raises(SystemExit) as refused:
        edition_build.require_edition_tree("cn", left_out)

    assert str(refused.value) == (
        "a cn build cannot hold hub/neutrino_hub/modules/xray; build it from "
        "the mainland source tree"
    )


def test_an_intl_build_stops_on_a_tree_that_lacks_a_left_out_path(left_out):
    with pytest.raises(SystemExit) as refused:
        edition_build.require_edition_tree("intl", left_out)

    assert str(refused.value) == (
        "an intl build needs hub/neutrino_hub/modules/xray, which this tree "
        "does not hold"
    )


def test_a_tree_of_its_edition_names_the_edition_for_the_build(left_out):
    edition_build.require_edition_tree("cn", left_out)

    assert edition_build.build_edition() == "cn"


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
