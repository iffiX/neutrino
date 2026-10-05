"""The agent module cache: resolution, one fetch, and what it refuses.

Nothing here reaches the network — every fetch is replaced. What is pinned
is the judgment around it: which entry a platform resolves to, that two
askers share one fetch, that a manifest edit is never served the old file,
and that losing the directory costs a download and nothing else.
"""

import hashlib
import os
import threading
import urllib.error

import pytest

from neutrino_hub.exceptions import AgentArtifactFetchError
from neutrino_hub.modules.devices.agent_module_cache import (
    AgentModuleCache,
    AgentModuleFetchProgress,
    is_version_below,
    latest_release_url,
    looks_like_package,
    platform_keys,
    resolve_platform_entry,
)

DEB = b"!<arch>debian-package-bytes"
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
LINUX_AMD = {"os": "linux", "family": "debian", "arch": "amd64", "version": "2.36"}


@pytest.fixture
def cache(tmp_path):
    """A cache rooted in a temporary directory."""
    return AgentModuleCache(root=tmp_path / "agent_module_cache")


def serving(content=DEB, fetches=None):
    """An open that answers fixed bytes and counts the calls."""

    def open_(request):
        if fetches is not None:
            fetches.append(request.full_url)
        return ChunkedResponse(content)

    return open_


def left_on_disk(cache) -> list:
    """Every file the cache directory holds, a hidden partial one included."""
    if not cache._root.is_dir():
        return []
    return sorted(os.listdir(cache._root))


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
    monkeypatch.setattr(cache, "_open", serving(fetches=fetches))

    with pytest.raises(AgentArtifactFetchError) as raised:
        cache.artifact(name="fakedesk", manifest=MANIFEST, platform=UNKNOWN)

    assert raised.value.code == "no_platform_build"
    assert fetches == []


def test_the_bytes_land_under_the_key_with_their_digest(cache, monkeypatch):
    monkeypatch.setattr(cache, "_open", serving())

    artifact = cache.artifact(name="fakedesk", manifest=MANIFEST, platform=AMD64)

    assert artifact.path.read_bytes() == DEB
    assert artifact.package_kind == "deb"
    assert artifact.key.startswith("fakedesk-linux-debian-amd64-")


def test_two_platforms_get_two_artifacts(cache, monkeypatch):
    monkeypatch.setattr(cache, "_open", serving())

    amd = cache.artifact(name="fakedesk", manifest=MANIFEST, platform=AMD64)
    arm = cache.artifact(name="fakedesk", manifest=MANIFEST, platform=ARM64)

    assert amd.key != arm.key


def test_a_second_asker_waits_on_the_first_fetch_rather_than_starting_one(cache):
    started = threading.Event()
    release = threading.Event()
    fetches: list = []

    def slow_open(request):
        fetches.append(request.full_url)
        started.set()
        release.wait(timeout=5)
        return ChunkedResponse(DEB)

    cache._open = slow_open
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
    monkeypatch.setattr(cache, "_open", serving(content=DEB))
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
    monkeypatch.setattr(cache, "_open", serving(content=newer))
    second = cache.artifact(name="fakedesk", manifest=moved, platform=AMD64)

    # The key carries a digest of the entry itself, so the edit is a
    # different artifact rather than a stale file under the same name.
    assert second.key != first.key
    assert second.path.read_bytes() == newer
    assert first.path.read_bytes() == DEB


def test_a_held_artifact_is_not_fetched_again(cache, monkeypatch):
    fetches: list = []
    monkeypatch.setattr(cache, "_open", serving(fetches=fetches))

    cache.artifact(name="fakedesk", manifest=MANIFEST, platform=AMD64)
    cache.artifact(name="fakedesk", manifest=MANIFEST, platform=AMD64)

    assert len(fetches) == 1


def test_losing_the_directory_costs_only_a_re_download(cache, monkeypatch):
    import shutil

    fetches: list = []
    monkeypatch.setattr(cache, "_open", serving(fetches=fetches))
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
    monkeypatch.setattr(cache, "_open", serving(content=binary))
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
    with pytest.raises(AgentArtifactFetchError) as raised:
        cache.artifact_for_key(
            "nothing-like-this", sources={"fakedesk": MANIFEST}, platform=AMD64
        )

    assert raised.value.code == "module_artifact_unknown"


@pytest.mark.parametrize("key", ["", "../escape", "a/b", ".hidden"])
def test_a_key_that_is_not_one_names_no_file(cache, key):
    assert cache.held(key) is None


# --- the pinned checksum, and the source a copyleft license obliges ---


def test_a_pinned_sha256_that_matches_is_fetched_and_kept(cache, monkeypatch):
    monkeypatch.setattr(AgentModuleCache, "_open", staticmethod(_serve_deb))
    manifest = _pinned_manifest(hashlib.sha256(DEB).hexdigest())

    artifact = cache.artifact(name="rustdesk", manifest=manifest, platform=AMD64)

    assert artifact.path.read_bytes() == DEB
    assert artifact.digest == hashlib.sha256(DEB).hexdigest()


def test_a_download_that_misses_its_pin_is_refused_and_never_cached(cache, monkeypatch):
    monkeypatch.setattr(AgentModuleCache, "_open", staticmethod(_serve_deb))
    manifest = _pinned_manifest("0" * 64)

    with pytest.raises(AgentArtifactFetchError) as refusal:
        cache.artifact(name="rustdesk", manifest=manifest, platform=AMD64)

    assert refusal.value.code == "module_sha256_mismatch"
    assert refusal.value.params["expected"] == "0" * 64
    assert refusal.value.params["received"] == hashlib.sha256(DEB).hexdigest()
    # Nothing a pin refused is left behind for the next asker to be served.
    assert left_on_disk(cache) == []


def test_a_real_disk_image_opens_like_one():
    # RustDesk's dmg assets are zlib at best compression; a magic table that
    # knows only one zlib level reads a genuine image as an error page.
    for opening in (b"\x78\x01", b"\x78\x9c", b"\x78\xda", b"koly", b"BZh"):
        assert looks_like_package(opening + b"rest-of-the-image", "dmg")


def _serve_deb(request):
    return ChunkedResponse(DEB)


def _pinned_manifest(digest):
    entry = {
        "url": "https://vendor.example/rustdesk-amd64.deb",
        "package_kind": "deb",
    }
    if digest:
        entry["sha256"] = digest
    return {"name": "rustdesk", "installer": "hub", "platforms": {AMD64_KEY: entry}}


FLOORED = {
    "name": "floored",
    "platforms": {
        "linux-amd64": {"url": "https://vendor.example/f", "min_version": "2.28"},
        "windows": {"verify": "where f", "min_version": "17763"},
    },
}


@pytest.mark.parametrize(
    "platform, expected_key",
    [
        ({**AMD64, "version": "2.36"}, "linux-amd64"),
        ({**AMD64, "version": "2.28"}, "linux-amd64"),
        ({**AMD64, "version": "2.27"}, ""),
        ({**AMD64, "version": "2.3"}, ""),
        ({**UNKNOWN, "version": "26100"}, "windows"),
        ({**UNKNOWN, "version": "17134"}, ""),
    ],
)
def test_a_platform_below_the_entry_floor_resolves_to_nothing(platform, expected_key):
    key, entry = resolve_platform_entry(FLOORED, platform)

    assert key == expected_key
    assert (entry is None) == (expected_key == "")


def test_a_platform_that_reports_no_version_is_not_ruled_out():
    assert resolve_platform_entry(FLOORED, AMD64)[0] == "linux-amd64"


@pytest.mark.parametrize(
    "version, floor, is_below",
    [
        ("15.3.1", "12.3", False),
        ("12.2", "12.3", True),
        ("12.3", "12.3", False),
        ("2.28", "2.28.1", True),
        ("26100", "17763", False),
        ("", "2.28", False),
        ("2.17", "", False),
    ],
)
def test_versions_compare_part_by_part(version, floor, is_below):
    assert is_version_below(version, floor) is is_below


# --- progress lines while the artifact is fetched ---

MEGABYTE = 1024 * 1024


class ChunkedResponse:
    """A response that hands out its body in the sizes asked for."""

    def __init__(self, body: bytes, *, is_sized: bool = True, broken_at=None):
        self._body = body
        self._offset = 0
        self._broken_at = broken_at
        self.headers = {"Content-Length": str(len(body))} if is_sized else {}
        self.reads: list = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, size):
        self.reads.append(size)
        if self._broken_at is not None and self._offset >= self._broken_at:
            raise ConnectionResetError("the peer went away")
        chunk = self._body[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk


class StoppedClock:
    """A clock that moves only when told."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_a_large_download_is_streamed_to_disk_in_64_kb_pieces(cache, monkeypatch):
    body = b"!<arch>" + os.urandom(5 * MEGABYTE)
    response = ChunkedResponse(body)
    monkeypatch.setattr(cache, "_open", lambda request: response)

    artifact = cache.artifact(name="fakedesk", manifest=MANIFEST, platform=AMD64)

    assert artifact.path.read_bytes() == body
    assert artifact.digest == hashlib.sha256(body).hexdigest()
    assert len(response.reads) > 80
    assert max(response.reads) == 64 * 1024
    assert left_on_disk(cache) == [artifact.key]


def test_a_read_that_breaks_off_leaves_nothing_behind(cache, monkeypatch):
    response = ChunkedResponse(b"!<arch>" + b"x" * MEGABYTE, broken_at=512 * 1024)
    monkeypatch.setattr(cache, "_open", lambda request: response)

    with pytest.raises(AgentArtifactFetchError) as refusal:
        cache.artifact(name="fakedesk", manifest=MANIFEST, platform=AMD64)

    assert refusal.value.code == "module_fetch_failed"
    assert left_on_disk(cache) == []


def test_a_download_of_the_wrong_kind_leaves_nothing_behind(cache, monkeypatch):
    monkeypatch.setattr(cache, "_open", serving(content=b"<!doctype html>"))

    with pytest.raises(AgentArtifactFetchError) as refusal:
        cache.artifact(name="fakedesk", manifest=MANIFEST, platform=AMD64)

    assert refusal.value.code == "module_fetch_failed"
    assert left_on_disk(cache) == []


def test_progress_is_written_every_five_percent_and_at_the_end(cache, monkeypatch):
    lines: list = []
    monkeypatch.setattr(
        cache,
        "_open",
        lambda request: ChunkedResponse(b"!<arch>" + b"x" * (20 * MEGABYTE - 7)),
    )
    manifest = {
        **MANIFEST,
        "title": "VS Code",
        "version": "1.140.0",
        "source": "Microsoft",
    }

    cache.artifact(
        name="fakedesk", manifest=manifest, platform=AMD64, on_progress=lines.append
    )

    assert (
        lines[0]
        == "hub: downloading VS Code 1.140.0 from vendor.example, 0.1 / 20.0 MB"
    )
    assert (
        lines[-1]
        == "hub: downloading VS Code 1.140.0 from vendor.example, 20.0 / 20.0 MB"
    )
    # The first chunk, one line per 5 percent after it, and the last again.
    assert len(lines) == 22


def test_progress_is_written_every_two_seconds_when_the_size_is_unknown():
    lines: list = []
    clock = StoppedClock()
    progress = AgentModuleFetchProgress(
        title="Gitea 1.27.3", on_line=lines.append, clock=clock
    )

    progress.note(MEGABYTE, 0)
    clock.now = 1.0
    progress.note(2 * MEGABYTE, 0)
    clock.now = 2.5
    progress.note(3 * MEGABYTE, 0)

    assert lines == [
        "hub: downloading Gitea 1.27.3, 1.0 MB",
        "hub: downloading Gitea 1.27.3, 3.0 MB",
    ]


def test_a_fetch_tells_its_progress_and_a_held_artifact_says_it_is_cached(
    cache, monkeypatch
):
    lines: list = []
    monkeypatch.setattr(AgentModuleCache, "_open", staticmethod(_serve_deb))
    manifest = {**MANIFEST, "title": "FakeDesk", "version": "2.0", "source": "Vendor"}

    cache.artifact(
        name="fakedesk", manifest=manifest, platform=AMD64, on_progress=lines.append
    )
    cache.artifact(
        name="fakedesk", manifest=manifest, platform=AMD64, on_progress=lines.append
    )

    assert set(lines[:-1]) == {
        "hub: downloading FakeDesk 2.0 from vendor.example, 0.0 / 0.0 MB"
    }
    assert lines[-1] == "hub: FakeDesk 2.0 is in the cache"


# --- the edition's own source: cn_url, and a mirror that kept only its latest ---

TARBALL = b"\x1f\x8bcode-server-release-bytes"
MIRROR = "https://mirror.example/code-server/"
PINNED_NAME = "code-server-4.140.0-linux-amd64.tar.gz"
MIRRORED_MANIFEST = {
    "name": "code_server",
    "title": "code-server",
    "version": "4.140.0",
    "platforms": {
        "linux-amd64": {
            "url": f"https://publisher.example/v4.140.0/{PINNED_NAME}",
            "cn_url": f"{MIRROR}v4.140.0/{PINNED_NAME}",
            "cn_latest_url": f"{MIRROR}LatestRelease/",
            "sha256": hashlib.sha256(TARBALL).hexdigest(),
            "package_kind": "tar",
        }
    },
}
LISTING = (
    '<a href="..">..</a>'
    '<a href="/code-server/LatestRelease/code-server-4.141.0-amd64.rpm">x</a>'
    '<a href="/code-server/LatestRelease/code-server-4.141.0-linux-arm64.tar.gz">x</a>'
    '<a href="/code-server/LatestRelease/code-server-4.141.0-linux-amd64.tar.gz">x</a>'
)


class MirrorFetches:
    """``_open`` and ``_fetch_listing`` stood in for, every url recorded."""

    def __init__(self, *, missing=(), served=TARBALL, listing=LISTING):
        self.urls: list = []
        self._missing = set(missing)
        self._served = served
        self._listing = listing

    def open(self, request):
        url = request.full_url
        self.urls.append(url)
        if url in self._missing:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        return ChunkedResponse(self._served)

    def listing(self, url):
        self.urls.append(url)
        return self._listing


def mirrored(monkeypatch, tmp_path, edition, fetches):
    monkeypatch.setattr(AgentModuleCache, "_open", staticmethod(fetches.open))
    monkeypatch.setattr(
        AgentModuleCache, "_fetch_listing", staticmethod(fetches.listing)
    )
    return AgentModuleCache(root=tmp_path / "cache", edition=edition)


def test_an_intl_hub_fetches_the_publishers_url(monkeypatch, tmp_path):
    fetches = MirrorFetches()
    cache = mirrored(monkeypatch, tmp_path, "intl", fetches)

    cache.artifact(name="code_server", manifest=MIRRORED_MANIFEST, platform=LINUX_AMD)

    assert fetches.urls == [MIRRORED_MANIFEST["platforms"]["linux-amd64"]["url"]]


def test_a_cn_hub_fetches_the_pinned_file_from_the_mirror_and_checks_it(
    monkeypatch, tmp_path
):
    fetches = MirrorFetches(served=b"\x1f\x8bsomething else")
    cache = mirrored(monkeypatch, tmp_path, "cn", fetches)

    with pytest.raises(AgentArtifactFetchError) as refusal:
        cache.artifact(
            name="code_server", manifest=MIRRORED_MANIFEST, platform=LINUX_AMD
        )

    assert fetches.urls == [f"{MIRROR}v4.140.0/{PINNED_NAME}"]
    assert refusal.value.code == "module_sha256_mismatch"
    assert left_on_disk(cache) == []


def test_a_cn_hub_takes_the_mirrors_current_release_when_the_pin_is_gone(
    monkeypatch, tmp_path
):
    lines: list = []
    fetches = MirrorFetches(
        missing={f"{MIRROR}v4.140.0/{PINNED_NAME}"}, served=b"\x1f\x8bnewer release"
    )
    cache = mirrored(monkeypatch, tmp_path, "cn", fetches)

    artifact = cache.artifact(
        name="code_server",
        manifest=MIRRORED_MANIFEST,
        platform=LINUX_AMD,
        on_progress=lines.append,
    )

    assert fetches.urls == [
        f"{MIRROR}v4.140.0/{PINNED_NAME}",
        f"{MIRROR}LatestRelease/",
        "https://mirror.example/code-server/LatestRelease/"
        "code-server-4.141.0-linux-amd64.tar.gz",
    ]
    assert artifact.path.read_bytes() == b"\x1f\x8bnewer release"
    assert any("4.141.0" in line and "HTTPS alone" in line for line in lines)


def test_a_mirror_whose_latest_holds_no_such_file_names_no_download(
    monkeypatch, tmp_path
):
    fetches = MirrorFetches(
        missing={f"{MIRROR}v4.140.0/{PINNED_NAME}"}, listing='<a href="x.deb">x</a>'
    )
    cache = mirrored(monkeypatch, tmp_path, "cn", fetches)

    with pytest.raises(AgentArtifactFetchError) as refusal:
        cache.artifact(
            name="code_server", manifest=MIRRORED_MANIFEST, platform=LINUX_AMD
        )

    assert refusal.value.code == "no_download_named"


def test_a_mirror_that_fails_otherwise_is_not_read_for_its_latest(
    monkeypatch, tmp_path
):
    def broken(request):
        raise urllib.error.HTTPError(request.full_url, 503, "Unavailable", {}, None)

    fetches = MirrorFetches()
    cache = mirrored(monkeypatch, tmp_path, "cn", fetches)
    monkeypatch.setattr(AgentModuleCache, "_open", staticmethod(broken))

    with pytest.raises(AgentArtifactFetchError) as refusal:
        cache.artifact(
            name="code_server", manifest=MIRRORED_MANIFEST, platform=LINUX_AMD
        )

    assert refusal.value.params["status"] == 503
    assert fetches.urls == []


def test_the_latest_file_is_the_pinned_name_with_its_version_left_open():
    url, version = latest_release_url(
        f"{MIRROR}LatestRelease/", f"{MIRROR}v4.140.0/{PINNED_NAME}", LISTING
    )

    assert version == "4.141.0"
    assert url.endswith("/LatestRelease/code-server-4.141.0-linux-amd64.tar.gz")


def test_a_line_names_the_host_it_fetched_from_not_the_publisher(monkeypatch, tmp_path):
    lines: list = []
    fetches = MirrorFetches(served=TARBALL)
    cache = mirrored(monkeypatch, tmp_path, "cn", fetches)

    cache.artifact(
        name="code_server",
        manifest={**MIRRORED_MANIFEST, "source": "Coder"},
        platform=LINUX_AMD,
        on_progress=lines.append,
    )

    assert lines[0].startswith(
        "hub: downloading code-server 4.140.0 from mirror.example,"
    )
    assert not any("Coder" in line for line in lines)
