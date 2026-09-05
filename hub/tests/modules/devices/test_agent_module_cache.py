"""The agent module cache: resolution, one fetch, and what it refuses.

Nothing here reaches the network — every fetch is replaced. What is pinned
is the judgment around it: which entry a platform resolves to, that two
askers share one fetch, that a page served in a package's place is refused,
that a manifest edit is never served the old file, and that losing the
directory costs a download and nothing else.
"""

import threading

import pytest

from neutrino_hub.modules.devices.agent_module_cache import (
    AgentModuleCache,
    AgentModuleFetchError,
    looks_like_package,
    platform_keys,
    resolve_platform_entry,
)

DEB = b"!<arch>" + b"x" * 200_000
CHALLENGE_PAGE = b"<!DOCTYPE html><html><body>are you a robot</body></html>"

MANIFEST = {
    "name": "todesk",
    "download": {"impersonate": True},
    "platforms": {
        "linux-debian-amd64": {
            "url": "https://vendor.example/todesk-amd64.deb",
            "package_kind": "deb",
        },
        "linux-debian-arm64": {
            "url": "https://vendor.example/todesk-arm64.deb",
            "package_kind": "deb",
        },
        "darwin": {"url": "https://vendor.example/todesk.dmg", "package_kind": "dmg"},
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

    def fetch(entry, *, manifest, package_kind):
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
        cache.artifact(name="todesk", manifest=MANIFEST, platform=UNKNOWN)

    assert raised.value.code == "no_platform_build"
    assert fetches == []


def test_the_bytes_land_under_the_key_with_their_digest(cache, monkeypatch):
    monkeypatch.setattr(cache, "_fetch", serving())

    artifact = cache.artifact(name="todesk", manifest=MANIFEST, platform=AMD64)

    assert artifact.path.read_bytes() == DEB
    assert artifact.package_kind == "deb"
    assert artifact.key.startswith("todesk-linux-debian-amd64-")


def test_two_platforms_get_two_artifacts(cache, monkeypatch):
    monkeypatch.setattr(cache, "_fetch", serving())

    amd = cache.artifact(name="todesk", manifest=MANIFEST, platform=AMD64)
    arm = cache.artifact(name="todesk", manifest=MANIFEST, platform=ARM64)

    assert amd.key != arm.key


def test_a_second_asker_waits_on_the_first_fetch_rather_than_starting_one(cache):
    started = threading.Event()
    release = threading.Event()
    fetches: list = []

    def slow_fetch(entry, *, manifest, package_kind):
        fetches.append(entry.get("url", ""))
        started.set()
        release.wait(timeout=5)
        return DEB

    cache._fetch = slow_fetch
    results: list = []

    def ask():
        results.append(cache.artifact(name="todesk", manifest=MANIFEST, platform=AMD64))

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


def test_a_challenge_page_is_refused_and_never_cached(cache, monkeypatch):
    # A CDN refusing a fetcher answers 200 with HTML, so the bytes are what
    # is judged rather than the status line.
    monkeypatch.setattr(
        AgentModuleCache,
        "_fetch_impersonated",
        staticmethod(lambda url: CHALLENGE_PAGE),
    )

    with pytest.raises(AgentModuleFetchError) as raised:
        cache.artifact(name="todesk", manifest=MANIFEST, platform=AMD64)

    assert raised.value.code == "vendor_served_a_page"
    assert list((cache._root).glob("*")) == []


def test_a_truncated_package_reads_as_a_page(cache, monkeypatch):
    monkeypatch.setattr(
        AgentModuleCache,
        "_fetch_impersonated",
        staticmethod(lambda url: b"!<arch>tiny"),
    )

    with pytest.raises(AgentModuleFetchError) as raised:
        cache.artifact(name="todesk", manifest=MANIFEST, platform=AMD64)

    assert raised.value.code == "vendor_served_a_page"


def test_a_manifest_that_changes_its_url_is_not_served_the_old_file(cache, monkeypatch):
    monkeypatch.setattr(cache, "_fetch", serving(content=DEB))
    first = cache.artifact(name="todesk", manifest=MANIFEST, platform=AMD64)

    moved = {
        **MANIFEST,
        "platforms": {
            **MANIFEST["platforms"],
            "linux-debian-amd64": {
                "url": "https://vendor.example/todesk-amd64-v5.deb",
                "package_kind": "deb",
            },
        },
    }
    newer = b"!<arch>" + b"y" * 200_000
    monkeypatch.setattr(cache, "_fetch", serving(content=newer))
    second = cache.artifact(name="todesk", manifest=moved, platform=AMD64)

    # The key carries a digest of the entry itself, so the edit is a
    # different artifact rather than a stale file under the same name.
    assert second.key != first.key
    assert second.path.read_bytes() == newer
    assert first.path.read_bytes() == DEB


def test_a_held_artifact_is_not_fetched_again(cache, monkeypatch):
    fetches: list = []
    monkeypatch.setattr(cache, "_fetch", serving(fetches=fetches))

    cache.artifact(name="todesk", manifest=MANIFEST, platform=AMD64)
    cache.artifact(name="todesk", manifest=MANIFEST, platform=AMD64)

    assert len(fetches) == 1


def test_losing_the_directory_costs_only_a_re_download(cache, monkeypatch):
    import shutil

    fetches: list = []
    monkeypatch.setattr(cache, "_fetch", serving(fetches=fetches))
    first = cache.artifact(name="todesk", manifest=MANIFEST, platform=AMD64)

    shutil.rmtree(cache._root)
    again = cache.artifact_for_key(
        first.key, sources={"todesk": MANIFEST}, platform=AMD64
    )

    # The same key, fetched again — an order made before the directory went
    # still finds its bytes, which is what makes this a cache.
    assert again.key == first.key
    assert again.path.read_bytes() == DEB
    assert len(fetches) == 2


def test_a_key_no_manifest_resolves_to_is_refused(cache):
    with pytest.raises(AgentModuleFetchError) as raised:
        cache.artifact_for_key(
            "nothing-like-this", sources={"todesk": MANIFEST}, platform=AMD64
        )

    assert raised.value.code == "module_artifact_unknown"


@pytest.mark.parametrize("key", ["", "../escape", "a/b", ".hidden"])
def test_a_key_that_is_not_one_names_no_file(cache, key):
    assert cache.held(key) is None


def test_each_kind_knows_its_own_opening():
    assert looks_like_package(b"!<arch>rest", "deb")
    assert looks_like_package(b"\xed\xab\xee\xdbrest", "rpm")
    assert looks_like_package(b"MZrest", "exe")
    assert looks_like_package(b"PK\x03\x04rest", "zip_binary")
    assert looks_like_package(b"\x1f\x8b\x08rest", "tar_binary")


def test_a_challenge_page_is_not_a_package():
    for kind in ("deb", "rpm", "exe"):
        assert looks_like_package(CHALLENGE_PAGE, kind) is False


def test_an_unknown_kind_is_not_evidence_of_a_page():
    assert looks_like_package(b"anything at all", "flatpak") is True
