"""The module versions' feeds: each version's digest for the artifact the feed answers for.

What these pin, against a fake fetcher that serves a registry: an anonymous
token taken from the service the registry's bearer challenge names, with
``scope`` for the repository; the dotted tags newest first, at most ten
read for a digest; each tag's digest the SHA-256 of the index the registry
serves, a single-architecture manifest refused; the digest going to the
image whose sources name the feed's repository alone, every other image
keeping its own; and the recipe of a chosen version naming that digest.
Against a fake that serves documents: an ``npm`` feed's ``dist.integrity``
going to the npm artifact of its package alone, a ``vscode_update`` feed's
digest and address going to the entry's artifact, and every module's manifest
naming a digest of the chosen version for each artifact that changes with it.
Against a fake that refuses: a feed read once in one read however many entries
name it, and one warning with each source's reason. Through the real fetcher:
a release listing as large as Gitea's read whole.
"""

import hashlib
import json

import pytest

from neutrino_hub.exceptions import DownloadFailedError
from neutrino_hub.modules.devices import module_releases
from neutrino_hub.modules.devices.manifests import (
    entry_artifacts,
    load_module_manifests,
)
from neutrino_hub.modules.devices.module_releases import (
    ModuleReleaseReader,
    ModuleReleaseStore,
    bearer_token_address,
    oci_index_digest,
)
from neutrino_hub.utils.source_fetch import SourceFetcher

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


class RefusingFeed:
    """A publisher's API that refuses every read, as GitHub past its hourly limit."""

    def __init__(self):
        self.reads = 0

    def fetch_document(self, *, file, sources, parse, headers=None, limit=0):
        self.reads += 1
        failures = [{"source": sources[0], "reason": "http_403", "detail": "limit"}]
        raise DownloadFailedError(file, failures)


class ListingAnswer:
    """A publisher's answer, as the fetcher opens and reads it."""

    def __init__(self, body: bytes):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *_details):
        return False

    def read(self, size: int = -1) -> bytes:
        return self._body if size < 0 else self._body[:size]


def test_a_release_listing_as_large_as_gitea_s_is_read(tmp_path):
    """Gitea's newest 100 releases weighed 15 MB and Codeg's 6.7 MB on 2026-11-01."""
    feed = {
        "kind": "github",
        "sources": ["https://api.github.com"],
        "repository": REPOSITORY,
        "tag": "v{version}",
    }
    artifact = {
        "name": "app",
        "kind": "binary",
        "file": "app-{version}",
        "digest": TESTED_DIGEST,
        "sources": ["https://app.example/{file}"],
    }
    entry = {
        "runner": "app",
        "install": {
            "method": "hub",
            "params": {"version": "1.2.0", "releases": [feed], "artifacts": [artifact]},
        },
    }
    digest = "sha256:" + "c" * 64
    release = {
        "tag_name": "v1.3.0",
        "body": "x" * (15 * 1024 * 1024),
        "assets": [{"name": "app-1.3.0", "digest": digest}],
    }
    body = json.dumps([release]).encode()

    def opener(_request, _timeout):
        return ListingAnswer(body)

    read = ModuleReleaseReader(
        fetcher=SourceFetcher(opener=opener),
        store=ModuleReleaseStore(path=tmp_path / "module_releases.json"),
    )

    listed = read.read_entry({"name": "app", "platforms": {"linux": entry}}, entry)

    assert listed == [{"version": "1.3.0", "artifacts": {"app": {"digest": digest}}}]


def test_a_feed_that_failed_is_read_and_warned_of_once_in_one_read(
    tmp_path, monkeypatch, caplog
):
    feed = {
        "kind": "github",
        "sources": ["https://api.github.com"],
        "repository": REPOSITORY,
        "tag": "v{version}",
    }
    entry = {
        "runner": "app",
        "install": {
            "method": "hub",
            "params": {"version": "1.2.0", "releases": [feed], "artifacts": []},
        },
    }
    manifest = {
        "name": "app",
        "platforms": {"linux": entry, "darwin": entry, "windows": entry},
    }
    monkeypatch.setattr(
        module_releases, "load_module_manifests", lambda: {"app": manifest}
    )
    fetcher = RefusingFeed()
    store = ModuleReleaseStore(path=tmp_path / "module_releases.json")

    ModuleReleaseReader(fetcher=fetcher, store=store).read()

    warnings = [record.getMessage() for record in caplog.records]
    assert fetcher.reads == 1
    assert warnings == [
        "module versions of app not read: "
        "no source served acme/app releases: http_403 limit"
    ]


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


NPM_FEED = {
    "kind": "npm",
    "sources": ["https://registry.example"],
    "package": "@acme/app",
}
NODE_DIGEST = "sha256:" + "c" * 64
TESTED_INTEGRITY = "sha512-tested"
NPM_ENTRY = {
    "runner": "cloudcli",
    "install": {
        "method": "hub",
        "params": {
            "version": "1.2.0",
            "releases": [NPM_FEED],
            "artifacts": [
                {
                    "name": "node",
                    "kind": "tar_gz",
                    "directory": "node",
                    "file": "node.tar.gz",
                    "digest": NODE_DIGEST,
                    "sources": ["https://nodejs.example/{file}"],
                },
                {
                    "name": "app",
                    "kind": "npm",
                    "package": "@acme/app",
                    "digest": TESTED_INTEGRITY,
                    "source_set": "npm",
                },
            ],
        },
    },
}
NPM_MANIFEST = {"name": "app", "platforms": {"linux": NPM_ENTRY}}
VSCODE_FEED = {
    "kind": "vscode_update",
    "sources": ["https://update.example"],
    "platform": "cli-alpine-x64",
}
VSCODE_ENTRY = {
    "runner": "vscode",
    "install": {
        "method": "hub",
        "params": {
            "version": "1.2.0",
            "releases": [VSCODE_FEED],
            "artifacts": [
                {
                    "name": "cli",
                    "kind": "tar_gz",
                    "directory": "cli",
                    "file": "cli.tar.gz",
                    "digest": TESTED_DIGEST,
                    "sources": ["https://download.example/stable/abc/{file}"],
                }
            ],
        },
    },
}
VSCODE_MANIFEST = {"name": "vs", "platforms": {"linux": VSCODE_ENTRY}}
# The artifacts that keep their own digest for every version of their module.
PINNED_ARTIFACTS = ("node", "wsl", "mongo", "redis")


class FakeDocuments:
    """The fetcher's document call, answered from a table of addresses."""

    def __init__(self, documents):
        self.documents = dict(documents)

    def fetch_document(self, *, file, sources, parse, headers=None, limit=0):
        (url,) = sources
        return parse(json.dumps(self.documents[url]).encode()), url


def npm_document():
    return {
        "versions": {
            "1.3.0": {"dist": {"integrity": "sha512-newer"}},
            "1.2.0": {"dist": {"integrity": TESTED_INTEGRITY}},
            "1.1.0": {"dist": {"integrity": "sha512-older"}},
        }
    }


def test_an_npm_feed_gives_each_version_its_own_integrity(tmp_path, monkeypatch):
    """CloudCLI: a chosen version with the tested version's digest fails
    ``digest_mismatch`` on every registry."""
    monkeypatch.setattr(
        module_releases, "load_module_manifests", lambda: {"app": NPM_MANIFEST}
    )
    fetcher = FakeDocuments(
        {
            "https://registry.example"
            + module_releases.NPM_PACKAGE_PATH.format(package="@acme/app"): (
                npm_document()
            )
        }
    )
    store = ModuleReleaseStore(path=tmp_path / "module_releases.json")
    read = ModuleReleaseReader(fetcher=fetcher, store=store)

    listed = read.read_entry(NPM_MANIFEST, NPM_ENTRY)
    read.read()
    recipe = store.recipe("app", {"os": "linux"}, "1.1.0")

    assert listed[2] == {
        "version": "1.1.0",
        "artifacts": {"app": {"digest": "sha512-older"}},
    }
    node, app = recipe["params"]["artifacts"]
    assert (node["digest"], app["digest"]) == (NODE_DIGEST, "sha512-older")
    assert recipe["params"]["version"] == "1.1.0"


def test_a_vscode_feed_gives_each_version_its_digest_and_address(tmp_path, monkeypatch):
    monkeypatch.setattr(
        module_releases, "load_module_manifests", lambda: {"vs": VSCODE_MANIFEST}
    )
    version_path = module_releases.VSCODE_VERSION_PATH.format(
        version="1.1.0", platform="cli-alpine-x64"
    )
    fetcher = FakeDocuments(
        {
            "https://update.example" + module_releases.VSCODE_RELEASES_PATH: ["1.1.0"],
            "https://update.example"
            + version_path: {"sha256hash": "d" * 64, "url": "https://ms.example/1.1.0"},
        }
    )
    store = ModuleReleaseStore(path=tmp_path / "module_releases.json")
    read = ModuleReleaseReader(fetcher=fetcher, store=store)

    read.read()
    recipe = store.recipe("vs", {"os": "linux"}, "1.1.0")

    digest = "sha256:" + "d" * 64
    assert recipe["params"]["artifacts"][0]["digest"] == digest
    assert store.artifact_sources("vs", {"os": "linux"}, "cli", digest) == [
        "https://ms.example/1.1.0"
    ]


def test_each_artifact_of_a_module_with_feeds_follows_the_version_or_stays_pinned():
    """An artifact left out of a listing keeps the tested version's digest
    beside another version's number."""
    for name, manifest in load_module_manifests().items():
        for key, entry in (manifest.get("platforms") or {}).items():
            feeds = (entry.get("install") or {}).get("params", {}).get("releases") or []
            if not feeds:
                continue
            for artifact in entry_artifacts(manifest, entry):
                follows = module_releases._is_versioned(
                    artifact, feeds
                ) or module_releases._feed_repository(artifact, feeds)
                is_pinned = artifact["name"] in PINNED_ARTIFACTS
                assert bool(follows) != is_pinned, (name, key, artifact["name"])
