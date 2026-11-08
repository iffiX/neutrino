"""The release sites of each edition, whether a build stamps them, and which
files each site holds: a release build is asked with ``--release-sites``,
and the steps of the build read it from ``NEUTRINO_HAS_RELEASE_SITES`` and
stamp the sites of the edition ``NEUTRINO_EDITION`` names alone."""

import argparse

import pytest

from shared import cc_switch_assets, release_sites
from shared.constants import (
    PACKAGING_EDITION_ENV,
    PACKAGING_RELEASE_SITES,
    PACKAGING_RELEASE_SITES_ENV,
)

GITHUB = {
    "files": "https://github.com/iffiX/neutrino/releases/download/{tag}/",
    "latest": "https://github.com/iffiX/neutrino/releases/latest/download/latest.json",
}
CNB = {
    "files": "https://cnb.cool/iffi-X/neutrino/-/releases/download/{tag}/",
    "latest": "https://cnb.cool/iffi-X/neutrino/-/git/raw/main/latest.json",
}


@pytest.fixture(autouse=True)
def no_release(monkeypatch):
    monkeypatch.setenv(PACKAGING_RELEASE_SITES_ENV, "")


def test_the_option_is_off_unless_given():
    parser = argparse.ArgumentParser()
    release_sites.add_release_sites_argument(parser)

    assert parser.parse_args([]).has_release_sites is False
    assert parser.parse_args(["--release-sites"]).has_release_sites is True


@pytest.mark.parametrize(("edition", "site"), [("intl", GITHUB), ("cn", CNB)])
def test_a_release_build_stamps_its_own_edition_s_site_alone(
    monkeypatch, edition, site
):
    monkeypatch.setenv(PACKAGING_EDITION_ENV, edition)
    release_sites.name_release_sites(True)

    assert release_sites.stamped_sites() == (site,)


@pytest.mark.parametrize("edition", ["intl", "cn"])
def test_any_other_build_stamps_none(monkeypatch, edition):
    monkeypatch.setenv(PACKAGING_EDITION_ENV, edition)
    release_sites.name_release_sites(False)

    assert release_sites.stamped_sites() == ()


def test_github_is_the_intl_site_and_cnb_the_cn_site():
    assert PACKAGING_RELEASE_SITES == {"intl": (GITHUB,), "cn": (CNB,)}


@pytest.mark.parametrize(
    ("name", "edition"),
    [
        ("neutrino-hub_0.6.0_amd64.deb", "intl"),
        ("neutrino-hub_0.6.0_amd64-cn.deb", "cn"),
        ("neutrino-agent-0.6.0-1.aarch64-cn.rpm", "cn"),
        ("neutrino-agent-0.6.0-1-x86_64-cn.pkg.tar.zst", "cn"),
        ("neutrino-client-0.6.0-windows-amd64.msi", "intl"),
        ("neutrino-hub-0.6.0-macos-arm64-cn.pkg", "cn"),
        ("neutrino-client-0.6.0-android-cn.apk", "cn"),
        ("neutrino-client-0.6.0-ios.ipa", "intl"),
        ("install.sh", "intl"),
        ("install-cn.ps1", "cn"),
        ("neutrino-0.6.0-source.tar.xz", "intl"),
        ("neutrino-0.6.0-cn-source.tar.xz", "cn"),
    ],
)
def test_each_site_holds_its_own_edition_s_files_alone(name, edition):
    other = {"intl": "cn", "cn": "intl"}[edition]

    assert release_sites.is_site_file(name, edition)
    assert not release_sites.is_site_file(name, other)


def test_both_sites_hold_the_cc_switch_files_and_their_own_two():
    shared = [
        *cc_switch_assets.release_files(),
        cc_switch_assets.license_name(),
        "latest.json",
        "SHA256SUMS",
    ]

    for name in shared:
        assert release_sites.is_site_file(name, "intl"), name
        assert release_sites.is_site_file(name, "cn"), name
