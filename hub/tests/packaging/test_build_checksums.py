"""The two files each release site writes over its others: latest.json,
which names the release, and SHA256SUMS, which lists every file of the
site; and the files of each edition's site, taken from the files every job
of the release made."""

import hashlib
import json

import pytest

import build_checksums
import build_sources
from shared import cc_switch_assets

# One release's files as the release workflow collects them: both editions'
# packages, scripts and source archives, and the cc-switch files.
INTL_FILES = (
    "neutrino-hub_9.9.9_amd64.deb",
    "neutrino-agent-9.9.9-1-x86_64.pkg.tar.zst",
    "neutrino-client-9.9.9-android.apk",
    "install.sh",
    "install.ps1",
    "neutrino-9.9.9-source.tar.xz",
)
CN_FILES = (
    "neutrino-hub_9.9.9_amd64-cn.deb",
    "neutrino-agent-9.9.9-1-x86_64-cn.pkg.tar.zst",
    "neutrino-client-9.9.9-android-cn.apk",
    "install-cn.sh",
    "install-cn.ps1",
    "neutrino-9.9.9-cn-source.tar.xz",
)
CC_SWITCH_FILES = (*cc_switch_assets.release_files(), cc_switch_assets.license_name())


@pytest.fixture
def collected(tmp_path):
    """A directory of every file the release's jobs made."""
    directory = tmp_path / "collected"
    directory.mkdir()
    for name in INTL_FILES + CN_FILES + CC_SWITCH_FILES:
        (directory / name).write_bytes(name.encode())
    return directory


def _site(collected, tmp_path, edition):
    """One edition's site as the release workflow writes it."""
    output = tmp_path / f"site_{edition}"
    build_checksums.take_site_files(collected, output, edition)
    build_checksums.check_site_files(output, edition)
    build_checksums.write_latest(output, "9.9.9")
    build_checksums.write_checksums(output)
    return output


def _listed(site):
    """The names a site's SHA256SUMS lists, with their digests."""
    return dict(
        reversed(line.split("  ", 1))
        for line in (site / "SHA256SUMS").read_text().splitlines()
    )


def test_latest_json_names_the_release_by_its_tag_and_version(tmp_path):
    build_checksums.write_latest(tmp_path, "9.9.9")

    assert json.loads((tmp_path / "latest.json").read_text()) == {
        "tag": "v9.9.9",
        "version": "9.9.9",
    }


def test_sha256sums_lists_every_file_and_latest_json_among_them(tmp_path):
    for name in ("neutrino-hub_9.9.9_amd64.deb", "install.sh"):
        (tmp_path / name).write_bytes(name.encode())
    build_checksums.write_latest(tmp_path, "9.9.9")

    build_checksums.write_checksums(tmp_path)

    listed = _listed(tmp_path)
    assert sorted(listed) == [
        "install.sh",
        "latest.json",
        "neutrino-hub_9.9.9_amd64.deb",
    ]
    for name, digest in listed.items():
        assert digest == hashlib.sha256((tmp_path / name).read_bytes()).hexdigest()


def test_the_github_site_takes_no_cn_file(collected, tmp_path):
    site = _site(collected, tmp_path, "intl")

    names = sorted(path.name for path in site.iterdir())
    assert [name for name in names if "-cn" in name] == []
    assert names == sorted(INTL_FILES + CC_SWITCH_FILES + ("SHA256SUMS", "latest.json"))


def test_the_cnb_site_takes_the_cn_files_and_the_cc_switch_files_alone(
    collected, tmp_path
):
    site = _site(collected, tmp_path, "cn")

    names = sorted(path.name for path in site.iterdir())
    assert names == sorted(CN_FILES + CC_SWITCH_FILES + ("SHA256SUMS", "latest.json"))
    assert [name for name in names if name in INTL_FILES] == []


@pytest.mark.parametrize("edition", ["intl", "cn"])
def test_each_site_s_sha256sums_lists_exactly_the_files_it_holds(
    collected, tmp_path, edition
):
    site = _site(collected, tmp_path, edition)

    listed = _listed(site)
    assert sorted(listed) == sorted(
        path.name for path in site.iterdir() if path.name != "SHA256SUMS"
    )
    for name, digest in listed.items():
        assert digest == hashlib.sha256((site / name).read_bytes()).hexdigest()


def test_a_collection_s_own_two_files_are_written_again_not_taken(collected, tmp_path):
    (collected / "SHA256SUMS").write_text("0" * 64 + "  elsewhere.deb\n")
    (collected / "latest.json").write_text('{"tag": "v0.0.1"}\n')

    site = _site(collected, tmp_path, "cn")

    assert "elsewhere.deb" not in _listed(site)
    assert json.loads((site / "latest.json").read_text())["tag"] == "v9.9.9"


@pytest.mark.parametrize(
    ("edition", "stray"),
    [
        ("intl", "neutrino-hub_9.9.9_amd64-cn.deb"),
        ("cn", "neutrino-hub_9.9.9_amd64.deb"),
    ],
)
def test_a_site_holding_a_file_of_the_other_edition_is_refused(
    tmp_path, edition, stray
):
    (tmp_path / stray).write_bytes(b"package")

    with pytest.raises(SystemExit) as refused:
        build_checksums.check_site_files(tmp_path, edition)

    assert (
        str(refused.value) == f"{stray} in {tmp_path} is no file of the {edition} site"
    )


def test_the_version_is_the_one_the_packages_declare():
    assert build_checksums.version is build_sources.version
