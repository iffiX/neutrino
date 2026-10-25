"""Whether a build stamps the release sites: a release build is asked with
``--release-sites``, and the steps of the build read it from
``NEUTRINO_HAS_RELEASE_SITES``."""

import argparse

import pytest

from shared import release_sites
from shared.constants import PACKAGING_RELEASE_SITES, PACKAGING_RELEASE_SITES_ENV


@pytest.fixture(autouse=True)
def no_release(monkeypatch):
    monkeypatch.setenv(PACKAGING_RELEASE_SITES_ENV, "")


def test_the_option_is_off_unless_given():
    parser = argparse.ArgumentParser()
    release_sites.add_release_sites_argument(parser)

    assert parser.parse_args([]).has_release_sites is False
    assert parser.parse_args(["--release-sites"]).has_release_sites is True


def test_a_release_build_stamps_every_site():
    release_sites.name_release_sites(True)

    assert release_sites.stamped_sites() == PACKAGING_RELEASE_SITES


def test_any_other_build_stamps_none():
    release_sites.name_release_sites(False)

    assert release_sites.stamped_sites() == ()


def test_the_sites_are_github_first_and_cnb_second():
    assert [site["files"] for site in PACKAGING_RELEASE_SITES] == [
        "https://github.com/iffiX/neutrino/releases/download/{tag}/",
        "https://cnb.cool/iffi-X/neutrino/-/releases/download/{tag}/",
    ]
    assert [site["latest"] for site in PACKAGING_RELEASE_SITES] == [
        "https://github.com/iffiX/neutrino/releases/latest/download/latest.json",
        "https://cnb.cool/iffi-X/neutrino/-/git/raw/main/latest.json",
    ]
