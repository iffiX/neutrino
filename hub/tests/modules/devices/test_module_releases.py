"""The ``oci`` feed of the module versions: a registry's tags, each with its index digest.

What these pin, against a fake fetcher that serves a registry: an anonymous
token taken from the service the registry's bearer challenge names, with
``scope`` for the repository; the dotted tags newest first, at most ten
read for a digest; each tag's digest the SHA-256 of the index the registry
serves, a single-architecture manifest refused; the digest going to the
image whose sources name the feed's repository alone, every other image
keeping its own; and the recipe of a chosen version naming that digest.
"""

import hashlib
import json

import pytest

from neutrino_hub.exceptions import DownloadFailedError
from neutrino_hub.modules.devices import module_releases
from neutrino_hub.modules.devices.module_releases import (
    ModuleReleaseReader,
    ModuleReleaseStore,
    bearer_token_address,
    oci_index_digest,
)

REPOSITORY = "acme/app"
FEED = {
    "kind": "oci",
    "sources": ["https://registry.example"],
    "repository": REPOSITORY,
    "tag": "{version}",
}
SIDE_DIGEST = "sha256:" + "b" * 64
TESTED_DIGEST = "sha256:" + "a" * 64
ENTRY = {
    "runner": "container",
    "install": {
        "method": "container",
        "params": {
            "version": "1.2.0",
            "releases": [FEED],
            "artifacts": [
                {
                    "name": "app",
                    "kind": "image",
                    "digest": TESTED_DIGEST,
                    "sources": ["registry.example/acme/app", "mirror.example/acme/app"],
                },
                {
                    "name": "db",
                    "kind": "image",
                    "digest": SIDE_DIGEST,
                    "sources": ["docker.io/library/db"],
                },
            ],
        },
    },
}
MANIFEST = {"name": "app", "platforms": {"linux": ENTRY}}
CHALLENGE = (
    'Bearer realm="https://registry.example/token",'
    'service="registry.example",scope="repository:user/image:pull"'
)


def index(version: str) -> bytes:
    return json.dumps(
        {
            "mediaType": "application/vnd.oci.image.index.v1+json",
            "manifests": [{"digest": "sha256:" + version.replace(".", "") * 10}],
        }
    ).encode()


class FakeRegistry:
    """The fetcher's two calls, answered as a registry that wants a token."""

    def __init__(self, tags):
        self.tags = list(tags)
        self.asked: list = []
        self.broken: set = set()

    def bearer_challenge(self, url):
        self.asked.append(("challenge", url, None))
        return CHALLENGE

    def fetch_document(self, *, file, sources, parse, headers=None, limit=0):
        (url,) = sources
        self.asked.append(("document", url, dict(headers or {})))
        if url.startswith("https://registry.example/token?"):
            return parse(json.dumps({"token": "anonymous"}).encode()), url
        assert (headers or {}).get("Authorization") == "Bearer anonymous"
        if url.endswith("/tags/list"):
            body = json.dumps({"name": REPOSITORY, "tags": self.tags}).encode()
            return parse(body), url
        tag = url.rsplit("/", 1)[1]
        if tag in self.broken:
            raise DownloadFailedError(file, [])
        return parse(index(tag)), url


@pytest.fixture
def reader(tmp_path, monkeypatch):
    registry = FakeRegistry(
        ["1.0.0", "1.2.0", "1.1.0", "latest", "1.2.0-amd64", "1.3.0"]
    )
    monkeypatch.setattr(
        module_releases, "load_module_manifests", lambda: {"app": MANIFEST}
    )
    store = ModuleReleaseStore(path=tmp_path / "module_releases.json")
    return ModuleReleaseReader(fetcher=registry, store=store), registry, store


def digest_of(version: str) -> str:
    return "sha256:" + hashlib.sha256(index(version)).hexdigest()


def test_each_dotted_tag_takes_the_digest_of_the_index_it_names(reader):
    read, registry, _ = reader

    listed = read.read_entry(MANIFEST, ENTRY)

    assert [item["version"] for item in listed] == ["1.3.0", "1.2.0", "1.1.0", "1.0.0"]
    assert listed[0]["artifacts"] == {"app": {"digest": digest_of("1.3.0")}}
    token = registry.asked[1]
    assert token[1] == (
        "https://registry.example/token?service=registry.example"
        "&scope=repository%3Aacme%2Fapp%3Apull"
    )
    assert "application/vnd.oci.image.index.v1+json" in (registry.asked[2][2]["Accept"])


def test_a_chosen_version_s_recipe_names_its_digest_and_keeps_the_side_image(reader):
    read, _, store = reader
    read.read()

    recipe = store.recipe("app", {"os": "linux"}, "1.3.0")
    tested = store.recipe("app", {"os": "linux"}, "1.2.0")

    app, db = recipe["params"]["artifacts"]
    assert (app["digest"], db["digest"]) == (digest_of("1.3.0"), SIDE_DIGEST)
    assert recipe["params"]["version"] == "1.3.0"
    assert tested["params"]["artifacts"][0]["digest"] == TESTED_DIGEST


def test_a_tag_whose_manifest_cannot_be_read_is_left_out(reader):
    read, registry, _ = reader
    registry.broken.add("1.1.0")

    listed = read.read_entry(MANIFEST, ENTRY)

    assert [item["version"] for item in listed] == ["1.3.0", "1.2.0", "1.0.0"]


def test_at_most_ten_tags_are_read_for_a_digest(reader):
    read, registry, _ = reader
    registry.tags = [f"1.{minor}.0" for minor in range(15)]

    listed = read.read_entry(MANIFEST, ENTRY)

    assert len(listed) == 10
    assert listed[0]["version"] == "1.14.0"


def test_a_feed_is_read_once_for_every_entry_of_one_read(reader, monkeypatch):
    read, registry, _ = reader
    manifest = {"name": "app", "platforms": {"linux": ENTRY, "windows-amd64": ENTRY}}
    monkeypatch.setattr(
        module_releases, "load_module_manifests", lambda: {"app": manifest}
    )

    read.read()

    assert [kind for kind, _, _ in registry.asked].count("challenge") == 1


def test_an_index_digest_is_the_sha256_of_the_bytes_served():
    body = index("2.0.0")

    assert oci_index_digest(body) == "sha256:" + hashlib.sha256(body).hexdigest()
    single = json.dumps(
        {"mediaType": "application/vnd.oci.image.manifest.v1+json"}
    ).encode()
    with pytest.raises(ValueError):
        oci_index_digest(single)
    with pytest.raises(ValueError):
        oci_index_digest(b"not json")


def test_the_token_address_names_the_realm_the_service_and_the_scope():
    assert bearer_token_address(CHALLENGE, "acme/app") == (
        "https://registry.example/token?service=registry.example"
        "&scope=repository%3Aacme%2Fapp%3Apull"
    )
    assert bearer_token_address('Basic realm="x"', "acme/app") == ""
    assert bearer_token_address('Bearer realm="http://x/token"', "acme/app") == ""
