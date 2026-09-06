"""The agent module cache: resolution, one fetch, and what it refuses.

Nothing here reaches the network — every fetch is replaced. What is pinned
is the judgment around it: which entry a platform resolves to, that two
askers share one fetch, that a manifest edit is never served the old file,
and that losing the directory costs a download and nothing else.
"""

import hashlib
import threading

import pytest

from neutrino_hub.modules.devices.agent_module_cache import (
    AgentModuleCache,
    AgentModuleFetchError,
    looks_like_package,
    platform_keys,
    resolve_platform_entry,
)

DEB = b"!<arch>debian-package-bytes"
SOURCE = b"\x1f\x8bcorresponding-source-bytes"
AMD64_KEY = "linux-debian-amd64"

MANIFEST = {
    "name": "fakedesk",
    "platforms": {
        "linux-debian-amd64": {
            "url": "https://vendor.example/fakedesk-amd64.deb",
            "package_kind": "deb",
        },
        "linux-debian-arm64": {
            "url": "https://vendor.example/fakedesk-arm64.deb",
            "package_kind": "deb",
        },
        "darwin": {"url": "https://vendor.example/fakedesk.dmg", "package_kind": "dmg"},
    },
}

AMD64 = {"os": "linux", "family": "debian", "arch": "amd64"}
ARM64 = {"os": "linux", "family": "debian", "arch": "arm64"}
DARWIN = {"os": "darwin", "family": "", "arch": "arm64"}
UNKNOWN = {"os": "windows", "family": "", "arch": "amd64"}


@pytest.fixture
def cache(tmp_path):
    """A cache rooted in a temporary directory."""
    return AgentModuleCache(root=tmp_path / "agent_modules")


def serving(content=DEB, fetches=None):
    """A fetch that hands back fixed bytes and counts the calls."""

    def fetch(entry):
        if fetches is not None:
            fetches.append(entry.get("url", ""))
        return content

    return fetch


def test_keys_run_most_specific_first_with_a_family():
    assert platform_keys(AMD64) == [
        "linux-debian-amd64",
        "linux-debian",
        "linux-amd64",
        "linux",
    ]


def test_keys_without_a_family_skip_the_family_pair():
    assert platform_keys(UNKNOWN) == ["windows-amd64", "windows"]


def test_a_machine_that_has_not_reported_matches_nothing():
    assert platform_keys({}) == []


@pytest.mark.parametrize(
    "platform, expected_key",
    [
        (AMD64, "linux-debian-amd64"),
        (ARM64, "linux-debian-arm64"),
        (DARWIN, "darwin"),
    ],
)
def test_each_platform_resolves_to_its_own_entry(platform, expected_key):
    key, entry = resolve_platform_entry(MANIFEST, platform)

    assert key == expected_key
    assert entry == MANIFEST["platforms"][expected_key]


def test_a_platform_the_manifest_offers_nothing_resolves_to_nothing():
    assert resolve_platform_entry(MANIFEST, UNKNOWN) == ("", None)


def test_an_unsupported_platform_is_refused_before_any_fetch(cache, monkeypatch):
    fetches: list = []
    monkeypatch.setattr(cache, "_fetch", serving(fetches=fetches))

    with pytest.raises(AgentModuleFetchError) as raised:
        cache.artifact(name="fakedesk", manifest=MANIFEST, platform=UNKNOWN)

    assert raised.value.code == "no_platform_build"
    assert fetches == []


def test_the_bytes_land_under_the_key_with_their_digest(cache, monkeypatch):
    monkeypatch.setattr(cache, "_fetch", serving())

    artifact = cache.artifact(name="fakedesk", manifest=MANIFEST, platform=AMD64)

    assert artifact.path.read_bytes() == DEB
    assert artifact.package_kind == "deb"
    assert artifact.key.startswith("fakedesk-linux-debian-amd64-")


def test_two_platforms_get_two_artifacts(cache, monkeypatch):
    monkeypatch.setattr(cache, "_fetch", serving())

    amd = cache.artifact(name="fakedesk", manifest=MANIFEST, platform=AMD64)
    arm = cache.artifact(name="fakedesk", manifest=MANIFEST, platform=ARM64)

    assert amd.key != arm.key


def test_a_second_asker_waits_on_the_first_fetch_rather_than_starting_one(cache):
    started = threading.Event()
    release = threading.Event()
    fetches: list = []

    def slow_fetch(entry):
        fetches.append(entry.get("url", ""))
        started.set()
        release.wait(timeout=5)
        return DEB

    cache._fetch = slow_fetch
    results: list = []

    def ask():
        results.append(
            cache.artifact(name="fakedesk", manifest=MANIFEST, platform=AMD64)
        )

    first = threading.Thread(target=ask)
    first.start()
    started.wait(timeout=5)
    second = threading.Thread(target=ask)
    second.start()
    release.set()
    first.join(timeout=5)
    second.join(timeout=5)

    # One fetch serves every device of that platform.
    assert len(fetches) == 1
    assert len(results) == 2
    assert results[0].key == results[1].key


def test_a_manifest_that_changes_its_url_is_not_served_the_old_file(cache, monkeypatch):
    monkeypatch.setattr(cache, "_fetch", serving(content=DEB))
    first = cache.artifact(name="fakedesk", manifest=MANIFEST, platform=AMD64)

    moved = {
        **MANIFEST,
        "platforms": {
            **MANIFEST["platforms"],
            "linux-debian-amd64": {
                "url": "https://vendor.example/fakedesk-amd64-v5.deb",
                "package_kind": "deb",
            },
        },
    }
    newer = b"!<arch>newer-bytes"
    monkeypatch.setattr(cache, "_fetch", serving(content=newer))
    second = cache.artifact(name="fakedesk", manifest=moved, platform=AMD64)

    # The key carries a digest of the entry itself, so the edit is a
    # different artifact rather than a stale file under the same name.
    assert second.key != first.key
    assert second.path.read_bytes() == newer
    assert first.path.read_bytes() == DEB


def test_a_held_artifact_is_not_fetched_again(cache, monkeypatch):
    fetches: list = []
    monkeypatch.setattr(cache, "_fetch", serving(fetches=fetches))

    cache.artifact(name="fakedesk", manifest=MANIFEST, platform=AMD64)
    cache.artifact(name="fakedesk", manifest=MANIFEST, platform=AMD64)

    assert len(fetches) == 1


def test_losing_the_directory_costs_only_a_re_download(cache, monkeypatch):
    import shutil

    fetches: list = []
    monkeypatch.setattr(cache, "_fetch", serving(fetches=fetches))
    first = cache.artifact(name="fakedesk", manifest=MANIFEST, platform=AMD64)

    shutil.rmtree(cache._root)
    again = cache.artifact_for_key(
        first.key, sources={"fakedesk": MANIFEST}, platform=AMD64
    )

    # The same key, fetched again — an order made before the directory went
    # still finds its bytes, which is what makes this a cache.
    assert again.key == first.key
    assert again.path.read_bytes() == DEB
    assert len(fetches) == 2


def test_a_github_release_entry_resolves_and_fetches_plain(cache, monkeypatch):
    # The hub tier's one fetch path: cc-switch names a GitHub release, the
    # asset resolves by suffix, and the download is a plain fetch.
    binary = b"\x1f\x8btar-binary-bytes"
    monkeypatch.setattr(
        AgentModuleCache,
        "_resolve_github_asset",
        staticmethod(lambda repo, pattern: f"https://github.example/{repo}/{pattern}"),
    )
    monkeypatch.setattr(
        AgentModuleCache, "_fetch_plain", staticmethod(lambda url: binary)
    )
    manifest = {
        "name": "cc_switch",
        "installer": "hub",
        "platforms": {
            "linux-amd64": {
                "github_repo": "example/cc-switch-cli",
                "asset_pattern": "linux-x64.tar.gz",
                "package_kind": "tar_binary",
            }
        },
    }

    artifact = cache.artifact(name="cc_switch", manifest=manifest, platform=AMD64)

    assert artifact.path.read_bytes() == binary
    assert artifact.package_kind == "tar_binary"


def test_a_key_no_manifest_resolves_to_is_refused(cache):
    with pytest.raises(AgentModuleFetchError) as raised:
        cache.artifact_for_key(
            "nothing-like-this", sources={"fakedesk": MANIFEST}, platform=AMD64
        )

    assert raised.value.code == "module_artifact_unknown"


@pytest.mark.parametrize("key", ["", "../escape", "a/b", ".hidden"])
def test_a_key_that_is_not_one_names_no_file(cache, key):
    assert cache.held(key) is None


# --- the pinned checksum, and the source a copyleft license obliges ---


def test_a_pinned_sha256_that_matches_is_fetched_and_kept(cache, monkeypatch):
    monkeypatch.setattr(AgentModuleCache, "_fetch_plain", staticmethod(_serve_deb))
    manifest = _pinned_manifest(hashlib.sha256(DEB).hexdigest())

    artifact = cache.artifact(name="rustdesk", manifest=manifest, platform=AMD64)

    assert artifact.path.read_bytes() == DEB
    assert artifact.digest == hashlib.sha256(DEB).hexdigest()


def test_a_download_that_misses_its_pin_is_refused_and_never_cached(cache, monkeypatch):
    monkeypatch.setattr(AgentModuleCache, "_fetch_plain", staticmethod(_serve_deb))
    manifest = _pinned_manifest("0" * 64)

    with pytest.raises(AgentModuleFetchError) as refusal:
        cache.artifact(name="rustdesk", manifest=manifest, platform=AMD64)

    assert refusal.value.code == "module_sha256_mismatch"
    assert refusal.value.params["expected"] == "0" * 64
    assert refusal.value.params["received"] == hashlib.sha256(DEB).hexdigest()
    # Nothing a pin refused is left behind for the next asker to be served.
    assert list(cache._root.glob("*")) == []


def test_the_corresponding_source_is_kept_beside_the_binary(cache, monkeypatch):
    served = {}

    def fetch(url):
        served[url] = served.get(url, 0) + 1
        return SOURCE if url.endswith(".tar.gz") else DEB

    monkeypatch.setattr(AgentModuleCache, "_fetch_plain", staticmethod(fetch))
    manifest = _pinned_manifest(hashlib.sha256(DEB).hexdigest())
    manifest["source_archive"] = "https://vendor.example/rustdesk-source.tar.gz"

    artifact = cache.artifact(name="rustdesk", manifest=manifest, platform=AMD64)

    assert artifact.source_path is not None
    assert artifact.source_path.read_bytes() == SOURCE
    assert artifact.source_path.parent == artifact.path.parent
    assert cache.source_path(artifact.key) == artifact.source_path

    # Asking again fetches neither the binary nor the source a second time.
    cache.artifact(name="rustdesk", manifest=manifest, platform=AMD64)
    assert sorted(served.values()) == [1, 1]


def test_a_module_naming_no_source_keeps_none(cache, monkeypatch):
    monkeypatch.setattr(AgentModuleCache, "_fetch_plain", staticmethod(_serve_deb))

    artifact = cache.artifact(
        name="rustdesk", manifest=_pinned_manifest(""), platform=AMD64
    )

    assert artifact.source_path is None
    assert cache.source_path(artifact.key) is None


def test_a_source_that_cannot_be_fetched_fails_the_module(cache, monkeypatch):
    def fetch(url):
        if url.endswith(".tar.gz"):
            raise AgentModuleFetchError("module_fetch_failed", detail="gone")
        return DEB

    monkeypatch.setattr(AgentModuleCache, "_fetch_plain", staticmethod(fetch))
    manifest = _pinned_manifest("")
    manifest["source_archive"] = "https://vendor.example/rustdesk-source.tar.gz"

    with pytest.raises(AgentModuleFetchError) as refusal:
        cache.artifact(name="rustdesk", manifest=manifest, platform=AMD64)

    assert refusal.value.code == "module_fetch_failed"


def test_a_real_disk_image_opens_like_one():
    # RustDesk's dmg assets are zlib at best compression; a magic table that
    # knows only one zlib level reads a genuine image as an error page.
    for opening in (b"\x78\x01", b"\x78\x9c", b"\x78\xda", b"koly", b"BZh"):
        assert looks_like_package(opening + b"rest-of-the-image", "dmg")


def _serve_deb(url):
    return DEB


def _pinned_manifest(digest):
    entry = {
        "url": "https://vendor.example/rustdesk-amd64.deb",
        "package_kind": "deb",
    }
    if digest:
        entry["sha256"] = digest
    return {"name": "rustdesk", "installer": "hub", "platforms": {AMD64_KEY: entry}}
