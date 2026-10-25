"""What the hub reads off its own releases, from release sites answered from a table."""

import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from neutrino_hub.exceptions import DownloadFailedError
from neutrino_hub.modules.hub_update.release import (
    HubReleaseChecker,
    asset_name,
    digest_listing,
    latest_version,
    relation,
    version_of_asset,
)
from neutrino_hub.utils.source_fetch import SourceFetcher, failure_entry
from tests.conftest import FakeSourceFetcher

ASSET = "neutrino-hub_{version}_amd64.deb"
SITES = (
    {
        "files": "https://github.example/releases/download/{tag}/",
        "latest": "https://github.example/releases/latest/download/latest.json",
    },
    {
        "files": "https://cnb.example/-/releases/download/{tag}/",
        "latest": "https://cnb.example/-/git/raw/main/latest.json",
    },
)
GITHUB = "https://github.example/releases/download/v{version}/{name}"
CNB = "https://cnb.example/-/releases/download/v{version}/{name}"
LATEST = [site["latest"] for site in SITES]


def latest_json(version: str) -> bytes:
    return json.dumps({"tag": f"v{version}", "version": version}).encode()


def sums(*names: str, payload: bytes = b"package") -> bytes:
    digest = hashlib.sha256(payload).hexdigest()
    return "".join(f"{digest}  {name}\n" for name in names).encode()


def published(version: str, *, package: bytes = b"package", names=None) -> dict:
    """One release at both sites: its digest list and this box's package."""
    name = ASSET.format(version=version)
    listed = names if names is not None else [name, "install.sh"]
    table = {}
    for address in (GITHUB, CNB):
        table[address.format(version=version, name="SHA256SUMS")] = sums(
            *listed, payload=package
        )
        if name in listed:
            table[address.format(version=version, name=name)] = package
    return table


def checker_over(table: dict, **keywords) -> tuple:
    fetcher = FakeSourceFetcher(table)
    return (
        HubReleaseChecker(asset=ASSET, sites=SITES, fetcher=fetcher, **keywords),
        fetcher,
    )


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


# --- the files a release site holds ---


def test_latest_json_names_the_version_of_its_tag():
    assert latest_version(latest_json("0.6.1")) == "0.6.1"
    assert latest_version(b'{"tag": "v0.6.1"}') == "0.6.1"


@pytest.mark.parametrize(
    "body",
    [b"<html>", b"{}", b'{"tag": "0.6.1"}', b'{"tag": "v0.6.1", "version": "0.6.0"}'],
)
def test_a_latest_json_of_another_shape_is_refused(body):
    with pytest.raises(ValueError):
        latest_version(body)


def test_the_digest_list_is_read_by_file_name():
    digest = "a" * 64
    listing = digest_listing(f"{digest}  one.deb\n{digest} *two.msi\n\n".encode())

    assert listing == {"one.deb": digest, "two.msi": digest}


def test_a_digest_list_with_a_line_that_is_no_digest_is_refused():
    with pytest.raises(ValueError):
        digest_listing(b"not-a-digest  one.deb\n")


# --- reading the release sites ---


def test_the_latest_release_names_this_boxs_package_at_every_site():
    table = {LATEST[0]: latest_json("0.3.1"), **published("0.3.1")}
    checker, fetcher = checker_over(table)

    found = checker.latest()

    name = "neutrino-hub_0.3.1_amd64.deb"
    assert found.version == "0.3.1"
    assert found.tag == "v0.3.1"
    assert found.asset_name == name
    assert found.has_package is True
    assert found.sources == (
        GITHUB.format(version="0.3.1", name=name),
        CNB.format(version="0.3.1", name=name),
    )
    assert found.digest == "sha256:" + hashlib.sha256(b"package").hexdigest()
    assert found.asset_size == len(b"package")
    assert fetcher.asked[0] == ("document", "latest.json", LATEST)
    assert fetcher.asked[1] == (
        "document",
        "SHA256SUMS",
        [
            GITHUB.format(version="0.3.1", name="SHA256SUMS"),
            CNB.format(version="0.3.1", name="SHA256SUMS"),
        ],
    )


def test_one_site_answering_is_enough():
    table = {LATEST[1]: latest_json("0.3.1")}
    for key, value in published("0.3.1").items():
        if key.startswith("https://cnb.example/"):
            table[key] = value
    checker, _ = checker_over(table)

    found = checker.latest()

    assert found.version == "0.3.1"
    assert found.asset_size == len(b"package")


def test_nothing_published_reads_as_no_release():
    checker, _ = checker_over({})

    assert checker.latest() is None


def test_a_release_without_this_boxs_package_is_a_release_with_none():
    table = {
        LATEST[0]: latest_json("0.3.1"),
        **published("0.3.1", names=["neutrino-hub_0.3.1_arm64.deb"]),
    }
    checker, _ = checker_over(table)

    found = checker.latest()

    assert found.version == "0.3.1"
    assert found.has_package is False
    assert found.sources == ()
    assert found.digest == ""


class UnreachableFetcher(FakeSourceFetcher):
    """Every site refuses the connection."""

    def fetch_document(self, *, file, sources, parse, limit=0) -> tuple:
        raise DownloadFailedError(
            file,
            [failure_entry(source, "unreachable", "refused") for source in sources],
        )


def test_sites_that_do_not_answer_fail_the_check_naming_each():
    checker = HubReleaseChecker(asset=ASSET, sites=SITES, fetcher=UnreachableFetcher())

    with pytest.raises(DownloadFailedError) as raised:
        checker.latest()

    assert raised.value.params["file"] == "latest.json"
    assert [item["source"] for item in raised.value.params["sources"]] == LATEST


def test_a_checkout_names_no_site_and_reads_nothing():
    checker = HubReleaseChecker(asset=ASSET, sites=(), fetcher=FakeSourceFetcher())

    with pytest.raises(DownloadFailedError) as raised:
        checker.latest()

    assert raised.value.params == {"file": "latest.json", "sources": []}


def test_the_release_of_one_version_is_read_by_its_tag():
    checker, _ = checker_over(published("0.3.0"))

    found = checker.for_version("0.3.0")

    assert found.version == "0.3.0"
    assert found.has_package is True


def test_a_version_no_site_holds_is_no_release():
    checker, _ = checker_over(published("0.3.0"))

    assert checker.for_version("0.3.0+ci") is None


# --- what a checker remembers ---


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def documents_asked(fetcher: FakeSourceFetcher) -> list:
    return [file for kind, file, _ in fetcher.asked if kind == "document"]


def test_a_release_read_moments_ago_is_reused_when_asked_to():
    clock = Clock()
    table = {
        LATEST[0]: latest_json("0.3.1"),
        **published("0.3.1"),
        **published("0.3.0"),
    }
    checker, fetcher = checker_over(table, clock=clock)
    checker.latest()
    checker.for_version("0.3.0")
    clock.now += 599

    assert checker.latest(max_age_s=600).version == "0.3.1"
    assert checker.for_version("0.3.0", max_age_s=600).version == "0.3.0"
    assert documents_asked(fetcher) == ["latest.json", "SHA256SUMS", "SHA256SUMS"]


def test_a_check_always_asks_and_an_old_read_is_asked_again():
    clock = Clock()
    table = {LATEST[0]: latest_json("0.3.1"), **published("0.3.1")}
    checker, fetcher = checker_over(table, clock=clock)
    checker.latest()
    checker.latest()
    clock.now += 601
    checker.latest(max_age_s=600)

    assert documents_asked(fetcher).count("latest.json") == 3


def test_a_release_that_is_not_there_is_remembered_too():
    checker, fetcher = checker_over({}, clock=Clock())

    assert checker.for_version("0.3.0+ci") is None
    assert checker.for_version("0.3.0+ci", max_age_s=600) is None
    assert documents_asked(fetcher) == ["SHA256SUMS"]


# --- against sites served on loopback ---


class _Site(BaseHTTPRequestHandler):
    files: dict = {}

    def log_message(self, *args):
        pass

    def do_GET(self):
        body = self.files.get(self.path)
        if body is None:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        asked = self.headers.get("Range", "")
        if asked:
            first, _, last = asked.removeprefix("bytes=").partition("-")
            start = int(first)
            end = min(int(last), len(body) - 1) if last else len(body) - 1
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(body)}")
            body = body[start : end + 1]
        else:
            self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def test_the_real_fetcher_reads_a_site_and_sizes_the_package():
    package = b"p" * 4096
    name = ASSET.format(version="0.7.0")
    files = {
        "/latest.json": latest_json("0.7.0"),
        "/v0.7.0/SHA256SUMS": sums(name, payload=package),
        f"/v0.7.0/{name}": package,
    }
    handler = type("Handler", (_Site,), {"files": files})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        checker = HubReleaseChecker(
            asset=ASSET,
            sites=({"files": base + "/{tag}/", "latest": base + "/latest.json"},),
            fetcher=SourceFetcher(probe_bytes=1, probe_timeout_s=2.0),
        )
        found = checker.latest()
    finally:
        server.shutdown()
        server.server_close()

    assert found.version == "0.7.0"
    assert found.sources == (f"{base}/v0.7.0/{name}",)
    assert found.asset_size == len(package)
    assert found.digest == "sha256:" + hashlib.sha256(package).hexdigest()
