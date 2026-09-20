"""What the hub reads off its own releases, answered from recorded replies."""

import json
import urllib.error

import pytest

from neutrino_hub.modules.hub_update import release as release_module
from neutrino_hub.modules.hub_update.release import (
    HubReleaseChecker,
    asset_name,
    relation,
    version_of_asset,
)

ASSET = "neutrino-hub_{version}_amd64.deb"
LATEST_URL = "https://api.github.com/repos/iffiX/neutrino/releases/latest"
TAG_URL = "https://api.github.com/repos/iffiX/neutrino/releases/tags/{tag}"
DOWNLOAD = "https://github.com/iffiX/neutrino/releases/download/{tag}/{name}"
DIGEST = "a" * 64


def release_json(version: str, *, assets=None) -> bytes:
    """A release as GitHub describes it, carrying the named files."""
    tag = f"v{version}"
    names = assets if assets is not None else [ASSET.format(version=version)]
    return json.dumps(
        {
            "tag_name": tag,
            "published_at": "2026-10-01T12:00:00Z",
            "body": "## Changes\n\n- one thing\n",
            "html_url": f"https://github.com/iffiX/neutrino/releases/tag/{tag}",
            "assets": [
                {
                    "name": name,
                    "size": 1000 + index,
                    "browser_download_url": DOWNLOAD.format(tag=tag, name=name),
                }
                for index, name in enumerate([*names, "SHA256SUMS"])
            ],
        }
    ).encode("utf-8")


def answering(table: dict) -> callable:
    """A fetch answering from a table, or refusing like GitHub does."""

    def fetch(url: str) -> bytes:
        if url not in table:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        return table[url]

    return fetch


# --- names ---


def test_the_stamp_names_the_package_at_any_version():
    assert asset_name("0.3.1", asset=ASSET) == "neutrino-hub_0.3.1_amd64.deb"


def test_a_checkout_has_no_package_to_name():
    with pytest.raises(ValueError):
        asset_name("0.3.1", asset="")


def test_the_version_reads_back_off_a_file_name():
    assert version_of_asset("neutrino-hub_0.3.1_amd64.deb", asset=ASSET) == "0.3.1"
    assert (
        version_of_asset(
            "neutrino-hub-0.3.1-1.x86_64.rpm",
            asset="neutrino-hub-{version}-1.x86_64.rpm",
        )
        == "0.3.1"
    )


def test_another_machines_package_is_not_this_ones():
    with pytest.raises(ValueError):
        version_of_asset("neutrino-hub_0.3.1_arm64.deb", asset=ASSET)
    with pytest.raises(ValueError):
        version_of_asset("neutrino-agent_0.3.1_amd64.deb", asset=ASSET)


def test_the_stamp_and_the_name_are_each_others_inverse():
    version = "0.4.2"
    assert version_of_asset(asset_name(version, asset=ASSET), asset=ASSET) == version


# --- how a release stands to the version running ---


@pytest.mark.parametrize(
    ("current", "latest", "expected"),
    [
        ("0.3.0", "0.3.1", "newer"),
        ("0.3.0", "0.4.0", "newer"),
        ("0.3.0", "0.3.0", "current"),
        ("0.3.1", "0.3.0", "current"),
        ("0.3.0", "1.0.0", "major"),
        ("0.3.0+dev", "0.3.1", "newer"),
        ("not-a-version", "0.3.1", "current"),
        ("0.3.0", "", "current"),
    ],
)
def test_the_relation_orders_by_number_and_singles_out_a_new_major(
    current, latest, expected
):
    assert relation(current, latest) == expected


# --- reading GitHub ---


def test_the_latest_release_names_this_boxs_package():
    checker = HubReleaseChecker(
        asset=ASSET, fetch_bytes=answering({LATEST_URL: release_json("0.3.1")})
    )

    found = checker.latest()

    assert found.version == "0.3.1"
    assert found.tag == "v0.3.1"
    assert found.asset_name == "neutrino-hub_0.3.1_amd64.deb"
    assert found.asset_url == DOWNLOAD.format(
        tag="v0.3.1", name="neutrino-hub_0.3.1_amd64.deb"
    )
    assert found.asset_size == 1000
    assert found.checksums_url == DOWNLOAD.format(tag="v0.3.1", name="SHA256SUMS")
    assert found.published_at == "2026-10-01T12:00:00Z"
    assert found.notes.startswith("## Changes")
    assert found.page_url.endswith("/v0.3.1")


def test_nothing_published_reads_as_no_release():
    checker = HubReleaseChecker(asset=ASSET, fetch_bytes=answering({}))

    assert checker.latest() is None
    assert checker.for_version("0.3.0") is None


def test_a_release_without_this_boxs_package_is_refused():
    checker = HubReleaseChecker(
        asset=ASSET,
        fetch_bytes=answering(
            {LATEST_URL: release_json("0.3.1", assets=["neutrino-hub_0.3.1_arm64.deb"])}
        ),
    )

    with pytest.raises(ValueError):
        checker.latest()


def test_a_reply_that_is_not_a_release_is_refused():
    checker = HubReleaseChecker(
        asset=ASSET, fetch_bytes=answering({LATEST_URL: b"<html>"})
    )

    with pytest.raises(ValueError):
        checker.latest()


def test_an_unreachable_github_is_an_os_error():
    def down(url: str) -> bytes:
        raise urllib.error.URLError("no route")

    checker = HubReleaseChecker(asset=ASSET, fetch_bytes=down)

    with pytest.raises(OSError):
        checker.latest()


def test_the_release_of_one_version_is_read_by_its_tag():
    checker = HubReleaseChecker(
        asset=ASSET,
        fetch_bytes=answering({TAG_URL.format(tag="v0.3.0"): release_json("0.3.0")}),
    )

    found = checker.for_version("0.3.0")

    assert found.version == "0.3.0"
    assert found.asset_name == "neutrino-hub_0.3.0_amd64.deb"


def test_the_digest_is_the_line_of_the_checksums_that_names_the_package():
    checksums = (
        f"{'b' * 64}  neutrino-hub_0.3.1_arm64.deb\n"
        f"{DIGEST}  neutrino-hub_0.3.1_amd64.deb\n"
    ).encode("utf-8")
    checker = HubReleaseChecker(
        asset=ASSET,
        fetch_bytes=answering(
            {
                LATEST_URL: release_json("0.3.1"),
                DOWNLOAD.format(tag="v0.3.1", name="SHA256SUMS"): checksums,
            }
        ),
    )

    assert checker.digest_of(checker.latest()) == DIGEST


def test_a_checksums_file_without_the_package_is_refused():
    checker = HubReleaseChecker(
        asset=ASSET,
        fetch_bytes=answering(
            {
                LATEST_URL: release_json("0.3.1"),
                DOWNLOAD.format(tag="v0.3.1", name="SHA256SUMS"): b"nothing here\n",
            }
        ),
    )

    with pytest.raises(ValueError):
        checker.digest_of(checker.latest())


def test_a_line_that_is_not_a_digest_is_refused():
    checker = HubReleaseChecker(
        asset=ASSET,
        fetch_bytes=answering(
            {
                LATEST_URL: release_json("0.3.1"),
                DOWNLOAD.format(
                    tag="v0.3.1", name="SHA256SUMS"
                ): b"xyz  neutrino-hub_0.3.1_amd64.deb\n",
            }
        ),
    )

    with pytest.raises(ValueError):
        checker.digest_of(checker.latest())


def test_the_network_read_sends_a_user_agent(monkeypatch):
    """GitHub's API answers nothing to a request without one."""
    seen = {}

    class Reply:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self):
            return b"{}"

    def urlopen(request, timeout):
        seen["headers"] = dict(request.header_items())
        seen["timeout"] = timeout
        return Reply()

    monkeypatch.setattr(release_module.urllib.request, "urlopen", urlopen)

    release_module._read("https://example.invalid/x")

    assert seen["headers"]["User-agent"] == "neutrino-hub"
    assert seen["timeout"] == 600
