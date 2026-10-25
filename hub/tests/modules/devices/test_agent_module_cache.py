"""The module cache: one artifact by its digest, fetched once, and what it refuses.

Nothing here reaches the network. The manifests are the test's own, every
fetch goes through a fake fetcher or a source served on loopback, and the
cache's root is a temporary directory. What is pinned is the judgment
around the fetch: which entry and which artifact a ``package {module,
artifact, digest}`` names, the file named by its digest, the head check, the
2 GiB limit, two askers sharing one fetch, and the files a new one leaves.
"""

import hashlib
import threading

import pytest

from neutrino_hub.exceptions import DownloadTooLargeError
from neutrino_hub.exceptions import AgentArtifactFetchError
from neutrino_hub.modules.devices import agent_module_cache
from neutrino_hub.modules.devices.agent_module_cache import (
    AgentModuleCache,
    AgentModuleSendProgress,
    clear_module_cache,
    looks_like_kind,
)
from neutrino_hub.modules.devices.constants import AGENT_MODULE_FETCH_LIMIT_BYTES
from tests.conftest import FakeSourceFetcher
from tests.utils.test_source_fetch import Behaviour, Source
from tests.utils.test_source_fetch import fetcher as loopback_fetcher

GZIP = b"\x1f\x8b"
ZSTD = b"\x28\xb5\x2f\xfd"
MACHO = b"\xcf\xfa\xed\xfe"
MSI = b"\xd0\xcf\x11\xe0"
APP = GZIP + b"the app's archive"
IMAGE = ZSTD + b"the machine image"
BINARY = MACHO + b"a release binary"
INSTALLER = MSI + b"a windows installer"
OTHER = GZIP + b"another module's archive"
SWITCH = GZIP + b"cc-switch's archive"
OLD = GZIP + b"an artifact no manifest pins any more"
MEGABYTE = 1024 * 1024

LINUX = {"os": "linux", "family": "debian", "arch": "amd64"}
DARWIN = {"os": "darwin", "family": "", "arch": "arm64", "version": "15.1"}
WINDOWS = {"os": "windows", "family": "", "arch": "amd64", "version": "26100"}
OLD_WINDOWS = {"os": "windows", "family": "", "arch": "amd64", "version": "17763"}
FREEBSD = {"os": "freebsd", "family": "", "arch": "amd64"}


def digest(body: bytes) -> str:
    return "sha256:" + hashlib.sha256(body).hexdigest()


def hexed(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def hub_entry(version: str, artifacts: list, **extra) -> dict:
    """One platform entry of the hub method."""
    return {
        "runner": "fakedesk",
        **extra,
        "install": {
            "method": "hub",
            "params": {
                "version": version,
                "releases": [],
                "artifacts": artifacts,
                "verify": "true",
                "uninstall": {"post_uninstall": [], "is_data_kept": True},
            },
        },
    }


def desk_manifest(sources: "list | None" = None) -> dict:
    return {
        "name": "fakedesk",
        "title": "Fake desk",
        "platforms": {
            "linux-amd64": hub_entry(
                "2.0",
                [
                    {
                        "name": "app",
                        "kind": "tar_gz",
                        "directory": "app",
                        "file": "desk-{version}-amd64.tar.gz",
                        "digest": digest(APP),
                        "sources": sources
                        or [
                            "https://vendor.example/{version}/{file}",
                            "https://mirror.example/{file}",
                        ],
                    },
                    {
                        "name": "image",
                        "kind": "tar_zst",
                        "directory": "image",
                        "file": "image.tar.zst",
                        "digest": digest(IMAGE),
                        "sources": ["https://vendor.example/{file}"],
                    },
                    {
                        "name": "agentpkg",
                        "kind": "npm",
                        "package": "@fake/desk",
                        "digest": "sha512-AAAA",
                        "sources": ["https://registry.example"],
                    },
                ],
            ),
            "darwin-arm64": hub_entry(
                "2.0",
                [
                    {
                        "name": "desk",
                        "kind": "binary",
                        "file": "desk-{version}-darwin",
                        "digest": digest(BINARY),
                        "sources": ["https://vendor.example/{file}"],
                    }
                ],
            ),
            "windows-amd64": hub_entry(
                "2.0",
                [
                    {
                        "name": "installer",
                        "kind": "msi",
                        "directory": "installer",
                        "file": "desk.msi",
                        "digest": digest(INSTALLER),
                        "sources": ["https://vendor.example/{file}"],
                    }
                ],
                min_version="19041",
            ),
        },
    }


OTHER_MANIFEST = {
    "name": "otherdesk",
    "title": "Other desk",
    "platforms": {
        "linux-amd64": hub_entry(
            "1.0",
            [
                {
                    "name": "app",
                    "kind": "tar_gz",
                    "directory": "app",
                    "file": "other.tar.gz",
                    "digest": digest(OTHER),
                    "sources": ["https://other.example/{file}"],
                }
            ],
        )
    },
}
SWITCH_MANIFEST = {
    "name": "cc_switch",
    "title": "cc-switch",
    "is_module": False,
    "version": "5.0",
    "platforms": {
        "linux-amd64": {
            "artifacts": [
                {
                    "name": "cc_switch",
                    "kind": "tar_gz",
                    "file": "cc-switch-{version}.tar.gz",
                    "digest": digest(SWITCH),
                    "sources": ["https://switch.example/{file}", "{release}/{file}"],
                }
            ]
        }
    },
}


@pytest.fixture
def manifests(monkeypatch):
    """The test's own manifests in place of the shipped ones."""
    held = {"fakedesk": desk_manifest(), "otherdesk": OTHER_MANIFEST}
    monkeypatch.setattr(agent_module_cache, "load_module_manifests", lambda: held)
    monkeypatch.setattr(
        agent_module_cache,
        "load_tool_manifests",
        lambda: {"cc_switch": SWITCH_MANIFEST},
    )
    return held


@pytest.fixture
def root(tmp_path):
    return tmp_path / "agent_module_cache"


def make_cache(root, fetcher, named=None) -> AgentModuleCache:
    return AgentModuleCache(
        root=root,
        fetcher=fetcher,
        named_modules=(lambda: set(named)) if named is not None else None,
    )


def serving_app() -> FakeSourceFetcher:
    """A fetcher whose mirror alone serves the app's archive."""
    return FakeSourceFetcher({"https://mirror.example/desk-2.0-amd64.tar.gz": APP})


def ask(cache, module="fakedesk", artifact="app", body=APP, platform=LINUX, **kw):
    return cache.artifact(
        module=module,
        artifact=artifact,
        digest=digest(body),
        platform=platform,
        **kw,
    )


def test_an_artifact_is_fetched_from_its_sources_and_kept_under_its_digest(
    manifests, root
):
    fetcher = serving_app()
    lines: list = []

    held = ask(make_cache(root, fetcher), on_progress=lines.append)

    assert fetcher.asked == [
        (
            "file",
            "desk-2.0-amd64.tar.gz",
            [
                "https://vendor.example/2.0/desk-2.0-amd64.tar.gz",
                "https://mirror.example/desk-2.0-amd64.tar.gz",
            ],
        )
    ]
    assert held.path == root / hexed(APP)
    assert held.path.read_bytes() == APP
    assert held.digest == digest(APP)
    assert held.file == "desk-2.0-amd64.tar.gz"
    assert held.title == "Fake desk 2.0 (app)"
    assert lines == ["hub: fetching desk-2.0-amd64.tar.gz from mirror.example"]


def test_a_held_file_is_served_with_no_fetch_and_says_it_is_in_the_cache(
    manifests, root
):
    root.mkdir()
    (root / hexed(APP)).write_bytes(APP)
    lines: list = []

    held = ask(make_cache(root, FakeSourceFetcher()), on_progress=lines.append)

    assert held.path.read_bytes() == APP
    assert lines == ["hub: Fake desk 2.0 (app) is in the cache"]


def test_a_held_file_that_no_longer_hashes_to_its_name_is_fetched_again(
    manifests, root
):
    root.mkdir()
    (root / hexed(APP)).write_bytes(b"a cut download")
    fetcher = serving_app()

    held = ask(make_cache(root, fetcher))

    assert held.path.read_bytes() == APP
    assert len(fetcher.asked) == 1


def test_a_one_artifact_entry_is_titled_by_its_module_and_version(manifests, root):
    fetcher = FakeSourceFetcher({"https://vendor.example/desk-2.0-darwin": BINARY})

    held = ask(make_cache(root, fetcher), artifact="desk", body=BINARY, platform=DARWIN)

    assert held.title == "Fake desk 2.0"
    assert held.path.read_bytes() == BINARY


def test_a_name_no_manifest_names_is_refused(manifests, root):
    with pytest.raises(AgentArtifactFetchError) as refused:
        ask(make_cache(root, FakeSourceFetcher()), module="nosuch")

    assert refused.value.code == "module_unknown"
    assert refused.value.params == {"name": "nosuch"}


@pytest.mark.parametrize("platform", [FREEBSD, OLD_WINDOWS])
def test_a_platform_the_manifest_names_no_entry_for_is_refused(
    manifests, root, platform
):
    """A system the manifest leaves out, and one below an entry's floor, have
    no entry; nothing is fetched for either."""
    fetcher = FakeSourceFetcher()

    with pytest.raises(AgentArtifactFetchError) as refused:
        ask(make_cache(root, fetcher), platform=platform)

    assert refused.value.code == "no_platform_build"
    assert refused.value.params == {"module": "fakedesk"}
    assert fetcher.asked == []


@pytest.mark.parametrize(
    "artifact, body",
    [
        ("nosuch", APP),
        ("app", IMAGE),
        ("installer", INSTALLER),
        ("agentpkg", APP),
    ],
)
def test_an_artifact_the_entry_does_not_name_with_that_digest_is_refused(
    manifests, root, artifact, body
):
    """A name the entry lacks, another artifact's digest, another platform's
    artifact and an npm artifact the machine fetches itself are all unknown
    to the cache."""
    fetcher = FakeSourceFetcher()

    with pytest.raises(AgentArtifactFetchError) as refused:
        ask(make_cache(root, fetcher), artifact=artifact, body=body)

    assert refused.value.code == "module_artifact_unknown"
    assert refused.value.params == {
        "module": "fakedesk",
        "artifact": artifact,
        "digest": digest(body),
    }
    assert fetcher.asked == []


def test_no_source_serving_it_names_each_source_and_leaves_nothing(manifests, root):
    fetcher = FakeSourceFetcher(
        {"https://vendor.example/2.0/desk-2.0-amd64.tar.gz": GZIP + b"other bytes"}
    )

    with pytest.raises(AgentArtifactFetchError) as refused:
        ask(make_cache(root, fetcher))

    assert refused.value.code == "download_failed"
    assert refused.value.params == {
        "file": "desk-2.0-amd64.tar.gz",
        "sources": [
            {
                "source": "https://vendor.example/2.0/desk-2.0-amd64.tar.gz",
                "reason": "digest_mismatch",
                "detail": "",
            },
            {
                "source": "https://mirror.example/desk-2.0-amd64.tar.gz",
                "reason": "http_404",
                "detail": "",
            },
        ],
    }
    assert list(root.glob("*")) == []


def test_a_source_serving_other_bytes_is_dropped_for_the_next_on_loopback(
    manifests, root, tmp_path
):
    """The real fetcher: a source whose file hashes otherwise is dropped and
    the file comes from the next one; when every source does it, nothing is
    kept and each source is named."""
    wrong = Source(Behaviour(body=GZIP + b"x" * len(APP)))
    right = Source(Behaviour(body=APP, chunk_delay_s=0.01))
    try:
        manifests["fakedesk"] = desk_manifest([wrong.url, right.url])
        held = ask(make_cache(root, loopback_fetcher()))
        assert held.path.read_bytes() == APP

        manifests["fakedesk"] = desk_manifest([wrong.url])
        (root / hexed(APP)).unlink()
        with pytest.raises(AgentArtifactFetchError) as refused:
            ask(make_cache(root, loopback_fetcher()))
    finally:
        wrong.close()
        right.close()

    assert refused.value.code == "download_failed"
    assert [item["reason"] for item in refused.value.params["sources"]] == [
        "digest_mismatch"
    ]
    assert list(root.glob("*")) == []


class LimitFetcher:
    """A fetcher that records the limit it was given and refuses as too large."""

    def __init__(self):
        self.limits: list = []

    def fetch_file(self, *, limit, **kwargs):
        self.limits.append(limit)
        raise DownloadTooLargeError(limit)


def test_the_limit_is_two_gib_and_a_file_past_it_is_refused(manifests, root):
    fetcher = LimitFetcher()

    with pytest.raises(AgentArtifactFetchError) as refused:
        ask(make_cache(root, fetcher))

    assert AGENT_MODULE_FETCH_LIMIT_BYTES == 2 * 1024 * 1024 * 1024
    assert fetcher.limits == [AGENT_MODULE_FETCH_LIMIT_BYTES]
    assert refused.value.code == "module_fetch_too_large"
    assert refused.value.params == {"limit_mb": 2048}


class BrokenDiskFetcher:
    def fetch_file(self, **kwargs):
        raise OSError("No space left on device")


def test_a_cache_that_cannot_be_written_says_so(manifests, root):
    with pytest.raises(AgentArtifactFetchError) as refused:
        ask(make_cache(root, BrokenDiskFetcher()))

    assert refused.value.code == "module_cache_unwritable"
    assert "No space left" in refused.value.params["detail"]


@pytest.mark.parametrize(
    "kind, head",
    [
        ("tar_zst", ZSTD),
        ("raw_zst", ZSTD),
        ("binary", b"\x7fELF"),
        ("binary", MACHO),
        ("binary", b"MZ"),
        ("msi", MSI),
        ("pkg", b"xar!"),
        ("tar_gz", GZIP),
        ("zip", b"PK\x03\x04"),
    ],
)
def test_each_kind_is_recognised_by_its_head(kind, head):
    assert looks_like_kind(head + b"the rest", kind)
    assert not looks_like_kind(b"<html>an error page</html>", kind)


def test_a_file_whose_head_is_not_its_kind_is_refused_and_kept_nowhere(manifests, root):
    """The digest matched, so the manifest names the wrong kind; the cache
    still keeps nothing that does not open like its kind."""
    page = b"<html>an error page served as the archive</html>"
    manifests["fakedesk"]["platforms"]["linux-amd64"]["install"]["params"]["artifacts"][
        0
    ]["digest"] = digest(page)
    fetcher = FakeSourceFetcher({"https://mirror.example/desk-2.0-amd64.tar.gz": page})

    with pytest.raises(AgentArtifactFetchError) as refused:
        ask(make_cache(root, fetcher), body=page)

    assert refused.value.code == "download_failed"
    assert refused.value.params["sources"] == [
        {
            "source": "https://mirror.example/desk-2.0-amd64.tar.gz",
            "reason": "digest_mismatch",
            "detail": "the file does not open like a tar_gz",
        }
    ]
    assert list(root.glob("*")) == []


def test_a_new_file_deletes_the_files_no_named_version_holds(manifests, root):
    """After a new file is placed, a file of a version no manifest pins and a
    module no machine names go; every file of a named module's version, on
    every platform, cc-switch's pinned files and a file not named by a
    digest stay."""
    root.mkdir()
    for body in (OLD, BINARY, INSTALLER, IMAGE, OTHER, SWITCH):
        (root / hexed(body)).write_bytes(body)
    (root / "notes.txt").write_text("kept")

    ask(make_cache(root, serving_app(), named={"fakedesk"}))

    assert sorted(path.name for path in root.iterdir()) == sorted(
        [hexed(APP), hexed(BINARY), hexed(INSTALLER), hexed(IMAGE), hexed(SWITCH)]
        + ["notes.txt"]
    )


def test_a_new_file_deletes_every_file_of_a_0_5_hubs_naming(manifests, root):
    """An upgrade from 0.5 left ``<module>-<platform>-<digest16>`` files, 1.5 GB
    on the lab hub, which no hub serves."""
    root.mkdir()
    for name in (
        "vscode-linux-amd64-82a1956cf354a293",
        "codeg-node-darwin-amd64-4505455b62ce2619",
        "cc_switch-linux-amd64-d501e05187c45205",
    ):
        (root / name).write_bytes(b"old")
    (root / "podman-image-windows-amd64-51f8fbca7a7ec68a").mkdir()
    (root / "podman-image-windows-amd64-51f8fbca7a7ec68a" / "part").write_text("x")
    (root / "notes-2026-0123456789abcdef.txt").write_text("kept")

    ask(make_cache(root, serving_app(), named={"fakedesk"}))

    assert sorted(path.name for path in root.iterdir()) == sorted(
        [hexed(APP), "notes-2026-0123456789abcdef.txt"]
    )


def test_with_no_named_modules_given_every_module_keeps_its_files(manifests, root):
    root.mkdir()
    for body in (OLD, OTHER):
        (root / hexed(body)).write_bytes(body)

    ask(make_cache(root, serving_app()))

    assert sorted(path.name for path in root.iterdir()) == sorted(
        [hexed(APP), hexed(OTHER)]
    )


def test_cc_switch_is_served_from_the_cache_and_a_checkout_names_no_release_site(
    manifests, root
):
    fetcher = FakeSourceFetcher({"https://switch.example/cc-switch-5.0.tar.gz": SWITCH})

    held = ask(
        make_cache(root, fetcher, named=set()),
        module="cc_switch",
        artifact="cc_switch",
        body=SWITCH,
    )

    assert fetcher.asked == [
        (
            "file",
            "cc-switch-5.0.tar.gz",
            ["https://switch.example/cc-switch-5.0.tar.gz"],
        )
    ]
    assert held.title == "cc-switch 5.0"
    assert held.path.read_bytes() == SWITCH


class SlowFetcher(FakeSourceFetcher):
    """A fake fetcher that holds its first fetch until it is let go."""

    def __init__(self, bodies):
        super().__init__(bodies)
        self.started = threading.Event()
        self.release = threading.Event()

    def fetch_file(self, **kwargs):
        self.started.set()
        self.release.wait(timeout=5)
        return super().fetch_file(**kwargs)


def test_a_second_asker_of_one_digest_waits_on_the_first_fetch(manifests, root):
    fetcher = SlowFetcher({"https://mirror.example/desk-2.0-amd64.tar.gz": APP})
    cache = make_cache(root, fetcher)
    results: list = []

    def asking():
        results.append(ask(cache))

    first = threading.Thread(target=asking)
    first.start()
    fetcher.started.wait(timeout=5)
    second = threading.Thread(target=asking)
    second.start()
    fetcher.release.set()
    first.join(timeout=5)
    second.join(timeout=5)

    assert len(fetcher.asked) == 1
    assert [held.path for held in results] == [root / hexed(APP)] * 2


class StoppedClock:
    """A monotonic clock that moves only when told."""

    def __init__(self):
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def test_a_send_is_counted_in_sending_lines_naming_the_machine():
    lines: list = []
    clock = StoppedClock()
    progress = AgentModuleSendProgress(
        title="Containers 6.1.4 (image)",
        recipient="nmxwin",
        on_line=lines.append,
        clock=clock,
    )

    progress.note(MEGABYTE, 40 * MEGABYTE)
    progress.note(MEGABYTE + 1, 40 * MEGABYTE)
    progress.note(3 * MEGABYTE, 40 * MEGABYTE)
    clock.now += 2.0
    progress.note(4 * MEGABYTE, 40 * MEGABYTE)
    progress.note(40 * MEGABYTE, 40 * MEGABYTE, is_done=True)

    assert lines == [
        "hub: sending Containers 6.1.4 (image), 1.0 / 40.0 MB to nmxwin",
        "hub: sending Containers 6.1.4 (image), 3.0 / 40.0 MB to nmxwin",
        "hub: sending Containers 6.1.4 (image), 4.0 / 40.0 MB to nmxwin",
        "hub: sending Containers 6.1.4 (image), 40.0 / 40.0 MB to nmxwin",
    ]


def test_clearing_the_cache_drops_every_file(manifests, root):
    ask(make_cache(root, serving_app()))

    clear_module_cache(root)

    assert not root.exists()
