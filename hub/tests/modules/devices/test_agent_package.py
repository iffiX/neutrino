"""Which agent package the hub hands a device, and where it comes from.

The hub's own package seeds the cache with the one package of its own
platform, so for that platform the answer is a file already on disk, under
the name the release publishes it as. Every other platform is fetched once
from the release sites the build stamped, at the release the hub came from,
checked against the manifest's hash, and kept under that same name. A
platform the manifest does not name, an entry with no hash and a build with
no release sites are refused by name.
"""

import hashlib
import json
import os

import pytest

from neutrino_hub.exceptions import AgentArtifactFetchError
from neutrino_hub.modules.devices.agent_package import (
    AgentPackageCache,
    package_architecture,
    package_family,
    package_name,
    platform_family,
    platform_key,
)
from tests.conftest import FakeSourceFetcher
from tests.utils.test_source_fetch import Behaviour, Source
from tests.utils.test_source_fetch import fetcher as loopback_fetcher

DEB_BYTES = b"!<arch>an agent deb"
DEB_DIGEST = hashlib.sha256(DEB_BYTES).hexdigest()
DEB_NAME = "neutrino-agent_0.1.0_amd64.deb"
DEB_ARM_NAME = "neutrino-agent_0.1.0_arm64.deb"
RPM_NAME = "neutrino-agent-0.1.0-1.x86_64.rpm"
HUB_VERSION = "0.1.0"
# The two release sites the build stamped, each ``{files, latest}``.
SITES = (
    {
        "files": "https://one.invalid/download/{tag}/",
        "latest": "https://one.invalid/latest.json",
    },
    {
        "files": "https://two.invalid/releases/{tag}/",
        "latest": "https://two.invalid/latest.json",
    },
)
FIRST_SITE = "https://one.invalid/download/v0.1.0"
SECOND_SITE = "https://two.invalid/releases/v0.1.0"


class RefusingFetcher:
    """A fetcher that fails the test the moment anything is fetched."""

    def fetch_file(self, **kwargs):
        raise AssertionError("nothing should have been fetched")


def make_cache(tmp_path, *, fetcher=None, sites=SITES) -> AgentPackageCache:
    """A cache over three directories under ``tmp_path``."""
    (tmp_path / "pinned").mkdir(exist_ok=True)
    return AgentPackageCache(
        root=tmp_path / "agent_cache",
        manifest_path=tmp_path / "agent_packages.json",
        pinned_dir=tmp_path / "pinned",
        fetcher=fetcher if fetcher is not None else RefusingFetcher(),
        sites=sites,
        hub_version=HUB_VERSION,
    )


@pytest.fixture
def cache(tmp_path):
    """A cache over three empty directories, with nothing fetched."""
    return make_cache(tmp_path)


def write_manifest(path, entries: dict) -> None:
    """Stamp a manifest the way a build would."""
    path.write_text(json.dumps(entries), encoding="utf-8")


def entry(name: str, *, content: bytes = DEB_BYTES) -> dict:
    """One manifest entry, stamped over the bytes it is for."""
    return {
        "name": name,
        "sha256": hashlib.sha256(content).hexdigest(),
        "size": len(content),
    }


def seed(root, name: str, content: bytes) -> None:
    """Put a package in the cache the way the hub's package does."""
    root.mkdir(parents=True, exist_ok=True)
    (root / name).write_bytes(content)


def fetched_files(fetcher: FakeSourceFetcher) -> list:
    """Each file the fake fetcher was asked for, with its sources."""
    return [(file, sources) for kind, file, sources in fetcher.asked if kind == "file"]


@pytest.mark.parametrize(
    "name, architecture",
    [
        ("neutrino-agent_0.1.0_amd64.deb", "amd64"),
        ("neutrino-agent_0.1.0_arm64.deb", "arm64"),
        ("neutrino-agent-0.1.0-1.x86_64.rpm", "amd64"),
        ("neutrino-agent-0.1.0-1.aarch64.rpm", "arm64"),
        ("neutrino-agent-0.1.0-1-x86_64.pkg.tar.zst", "amd64"),
        ("neutrino-agent_0.1.0_all.deb", ""),
        ("neutrino-agent-0.1.0-1.noarch.rpm", ""),
    ],
)
def test_every_name_either_family_writes_says_its_machine(name, architecture):
    """The two families punctuate the same machine differently, and the older
    machine-independent names say no machine at all."""
    assert package_architecture(name) == architecture


@pytest.mark.parametrize(
    "name, family",
    [
        ("neutrino-agent_0.1.0_amd64.deb", "deb"),
        ("neutrino-agent-0.1.0-1.x86_64.rpm", "rpm"),
        ("neutrino-agent-0.1.0-1-x86_64.pkg.tar.zst", "arch"),
        ("neutrino-agent-0.1.0-1-x86_64-cn.pkg.tar.zst", "arch"),
        ("neutrino-agent-0.4.0-windows-amd64.msi", "msi"),
        ("neutrino-agent-0.4.0-macos-arm64.pkg", "pkg"),
        ("neutrino-agent-0.4.0.tar.gz", ""),
        ("SHA256SUMS", ""),
    ],
)
def test_the_family_is_read_from_the_suffix(name, family):
    assert package_family(name) == family


@pytest.mark.parametrize(
    "name, key",
    [
        ("neutrino-agent-0.4.0-windows-amd64.msi", "msi-amd64"),
        ("neutrino-agent-0.4.0-macos-arm64.pkg", "pkg-arm64"),
    ],
)
def test_the_windows_and_macos_installers_are_keyed_by_family_and_machine(name, key):
    assert platform_key(package_family(name), package_architecture(name)) == key


@pytest.mark.parametrize(
    "platform, family",
    [
        ({"os": "windows", "family": "", "arch": "amd64"}, "msi"),
        ({"os": "darwin", "family": "", "arch": "arm64"}, "pkg"),
        ({"os": "linux", "family": "debian", "arch": "amd64"}, "deb"),
        ({"os": "linux", "family": "rhel", "arch": "arm64"}, "rpm"),
        ({"os": "linux", "family": "arch", "arch": "amd64"}, "arch"),
        ({"os": "linux", "family": "", "arch": "amd64"}, ""),
        ({"os": "freebsd13", "family": "", "arch": "amd64"}, ""),
    ],
)
def test_a_machine_installs_the_family_its_os_or_distribution_names(platform, family):
    assert platform_family(platform) == family


def test_an_entry_names_its_file_the_way_the_release_publishes_it():
    """One name addresses the package here, in the manifest and in the
    release, which is also a name apt and dnf can be handed: both read a local
    file's format from its suffix and refuse one that says none."""
    assert package_name(entry(DEB_NAME)) == DEB_NAME
    assert package_family(package_name(entry(RPM_NAME))) == "rpm"


@pytest.mark.parametrize("name", ["", "../elsewhere.deb", "sub/dir.deb", ".."])
def test_a_name_that_would_leave_the_cache_directory_names_nothing(name):
    assert package_name({"name": name}) == ""


def test_a_platform_key_needs_both_halves():
    assert platform_key("deb", "") == ""
    assert platform_key("", "amd64") == ""


def test_a_seeded_package_is_served_without_reaching_for_anything(cache, tmp_path):
    """What the hub's own package laid down is the whole answer: a Linux
    install and a Linux self-update need no network."""
    write_manifest(tmp_path / "agent_packages.json", {"deb-amd64": entry(DEB_NAME)})
    seed(tmp_path / "agent_cache", DEB_NAME, DEB_BYTES)

    path = cache.package(family="deb", architecture="amd64")

    assert path.read_bytes() == DEB_BYTES
    assert path.name == DEB_NAME
    assert cache.serves(family="deb", architecture="amd64")


def test_a_held_file_that_is_another_build_is_fetched_again(tmp_path):
    """The name is the release's and says nothing about what is inside it, so
    the pinned hash is what decides whether a held file is still the answer."""
    write_manifest(tmp_path / "agent_packages.json", {"deb-amd64": entry(DEB_NAME)})
    seed(tmp_path / "agent_cache", DEB_NAME, b"!<arch>an older agent deb")
    fetcher = FakeSourceFetcher({f"{FIRST_SITE}/{DEB_NAME}": DEB_BYTES})

    path = make_cache(tmp_path, fetcher=fetcher).package(
        family="deb", architecture="amd64"
    )

    assert path.name == DEB_NAME
    assert path.read_bytes() == DEB_BYTES
    assert len(fetched_files(fetcher)) == 1


def test_a_platform_the_release_publishes_is_fetched_once_from_the_sites_and_kept(
    tmp_path,
):
    """Every release site is a source of the file, at the release the hub came
    from, in the order the build stamped them."""
    write_manifest(tmp_path / "agent_packages.json", {"deb-arm64": entry(DEB_ARM_NAME)})
    fetcher = FakeSourceFetcher({f"{SECOND_SITE}/{DEB_ARM_NAME}": DEB_BYTES})
    cache = make_cache(tmp_path, fetcher=fetcher)

    path = cache.package(family="deb", architecture="arm64")

    assert fetched_files(fetcher) == [
        (
            DEB_ARM_NAME,
            [f"{FIRST_SITE}/{DEB_ARM_NAME}", f"{SECOND_SITE}/{DEB_ARM_NAME}"],
        )
    ]
    assert path.read_bytes() == DEB_BYTES
    assert path.name == DEB_ARM_NAME
    assert cache.package(family="deb", architecture="arm64") == path
    assert len(fetched_files(fetcher)) == 1


def test_a_site_serving_something_else_is_dropped_and_its_file_cached_nowhere(
    tmp_path,
):
    write_manifest(tmp_path / "agent_packages.json", {"deb-arm64": entry(DEB_ARM_NAME)})
    fetcher = FakeSourceFetcher(
        {
            f"{FIRST_SITE}/{DEB_ARM_NAME}": b"!<arch>another build",
            f"{SECOND_SITE}/{DEB_ARM_NAME}": b"!<arch>a third build",
        }
    )

    with pytest.raises(AgentArtifactFetchError) as refused:
        make_cache(tmp_path, fetcher=fetcher).package(
            family="deb", architecture="arm64"
        )

    assert refused.value.code == "download_failed"
    assert refused.value.params["file"] == DEB_ARM_NAME
    assert [item["reason"] for item in refused.value.params["sources"]] == [
        "digest_mismatch",
        "digest_mismatch",
    ]
    assert list(tmp_path.glob("agent_cache/*")) == []


def test_a_build_with_no_release_sites_refuses_the_rest_by_name(tmp_path):
    """A checkout, or a local build, names no site: what it did not seed is
    refused by name rather than handing over another machine's build."""
    write_manifest(
        tmp_path / "agent_packages.json",
        {"rpm-arm64": entry("neutrino-agent-0.1.0-1.aarch64.rpm")},
    )
    cache = make_cache(tmp_path, sites=())

    with pytest.raises(AgentArtifactFetchError) as refused:
        cache.package(family="rpm", architecture="arm64")

    assert refused.value.code == "agent_package_missing"
    assert refused.value.params == {"platform": "rpm-arm64"}
    assert not cache.serves(family="rpm", architecture="arm64")


def test_a_platform_the_manifest_never_names_is_refused_by_name(cache, tmp_path):
    write_manifest(tmp_path / "agent_packages.json", {"deb-amd64": entry(DEB_NAME)})

    with pytest.raises(AgentArtifactFetchError) as refused:
        cache.package(family="msi", architecture="amd64")

    assert refused.value.code == "agent_package_missing"
    assert refused.value.params == {"platform": "msi-amd64"}


def test_a_pinned_build_wins_over_the_manifest(cache, tmp_path):
    """A build dropped in by hand is a decision, and it beats both the seeded
    file and anything the release publishes."""
    write_manifest(tmp_path / "agent_packages.json", {"deb-amd64": entry(DEB_NAME)})
    seed(tmp_path / "agent_cache", DEB_NAME, DEB_BYTES)
    (tmp_path / "pinned" / "neutrino-agent_0.2.0_amd64.deb").write_bytes(b"pinned")

    path = cache.package(family="deb", architecture="amd64")

    assert path.read_bytes() == b"pinned"


def test_a_pinned_build_of_one_family_leaves_the_other_alone(cache, tmp_path):
    write_manifest(tmp_path / "agent_packages.json", {"rpm-amd64": entry(RPM_NAME)})
    seed(tmp_path / "agent_cache", RPM_NAME, DEB_BYTES)
    (tmp_path / "pinned" / "neutrino-agent_0.2.0_amd64.deb").write_bytes(b"pinned")

    assert cache.package(family="deb", architecture="amd64").read_bytes() == b"pinned"
    assert cache.package(family="rpm", architecture="amd64").read_bytes() == DEB_BYTES


def test_a_hub_carrying_nothing_says_so_before_a_device_is_reached(cache):
    """No manifest and nothing pinned is a checkout, refused before the panel
    starts a task against a machine."""
    assert not cache.has_packages()


def test_a_stamped_manifest_alone_is_a_hub_that_carries_something(cache, tmp_path):
    write_manifest(tmp_path / "agent_packages.json", {"deb-amd64": entry(DEB_NAME)})

    assert cache.has_packages()
    assert cache.serves(family="deb", architecture="amd64")


def test_a_pinned_build_alone_is_a_hub_that_carries_something(cache, tmp_path):
    (tmp_path / "pinned" / "neutrino-agent_0.2.0_amd64.deb").write_bytes(b"pinned")

    assert cache.has_packages()


def test_an_unreadable_manifest_is_a_hub_that_knows_no_platform(cache, tmp_path):
    (tmp_path / "agent_packages.json").write_text("not json", encoding="utf-8")

    assert cache.manifest() == {}
    assert not cache.has_packages()


# --- another platform's package comes from the release sites ---------------

MSI_NAME = "neutrino-agent-0.1.0-windows-amd64.msi"
MSI_BYTES = b"MZ an agent installer"


def test_a_deb_hub_fetches_the_windows_installer_and_checks_it(tmp_path):
    """The hub carries its own platform's package alone; a Windows agent
    updating itself is served the release's file once it hashes right."""
    write_manifest(
        tmp_path / "agent_packages.json",
        {
            "deb-amd64": entry(DEB_NAME),
            "msi-amd64": entry(MSI_NAME, content=MSI_BYTES),
        },
    )
    seed(tmp_path / "agent_cache", DEB_NAME, DEB_BYTES)
    fetcher = FakeSourceFetcher({f"{FIRST_SITE}/{MSI_NAME}": MSI_BYTES})
    cache = make_cache(tmp_path, fetcher=fetcher)

    assert cache.package(family="deb", architecture="amd64").name == DEB_NAME
    path = cache.package(family="msi", architecture="amd64")

    assert [file for file, _ in fetched_files(fetcher)] == [MSI_NAME]
    assert path == tmp_path / "agent_cache" / MSI_NAME
    assert path.read_bytes() == MSI_BYTES


def test_an_entry_that_pins_no_hash_is_never_fetched(cache, tmp_path):
    """A fetch is kept only once it matches; with nothing to match it against
    the platform is refused by name and nothing is downloaded."""
    unpinned = entry(MSI_NAME, content=MSI_BYTES)
    unpinned["sha256"] = ""
    write_manifest(tmp_path / "agent_packages.json", {"msi-amd64": unpinned})

    with pytest.raises(AgentArtifactFetchError) as refused:
        cache.package(family="msi", architecture="amd64")

    assert refused.value.code == "agent_package_missing"
    assert not cache.serves(family="msi", architecture="amd64")


def test_no_site_serving_the_file_names_each_site_and_why(tmp_path):
    write_manifest(
        tmp_path / "agent_packages.json",
        {"msi-amd64": entry(MSI_NAME, content=MSI_BYTES)},
    )

    with pytest.raises(AgentArtifactFetchError) as refused:
        make_cache(tmp_path, fetcher=FakeSourceFetcher()).package(
            family="msi", architecture="amd64"
        )

    assert refused.value.code == "download_failed"
    assert refused.value.params["sources"] == [
        {"source": f"{FIRST_SITE}/{MSI_NAME}", "reason": "http_404", "detail": ""},
        {"source": f"{SECOND_SITE}/{MSI_NAME}", "reason": "http_404", "detail": ""},
    ]
    assert list(tmp_path.glob("agent_cache/*")) == []


def test_a_held_file_that_no_longer_hashes_right_is_fetched_again(tmp_path):
    write_manifest(
        tmp_path / "agent_packages.json",
        {"msi-amd64": entry(MSI_NAME, content=MSI_BYTES)},
    )
    seed(tmp_path / "agent_cache", MSI_NAME, b"MZ a truncated download")
    fetcher = FakeSourceFetcher({f"{FIRST_SITE}/{MSI_NAME}": MSI_BYTES})

    path = make_cache(tmp_path, fetcher=fetcher).package(
        family="msi", architecture="amd64"
    )

    assert len(fetched_files(fetcher)) == 1
    assert path.read_bytes() == MSI_BYTES


def test_the_real_fetcher_takes_the_package_from_a_site_on_loopback(tmp_path):
    """One end-to-end fetch: the stamped site, the tag, the file's name and the
    digest, through the fetcher every download uses."""
    body = b"!<arch>" + os.urandom(3 * 1024 * 1024)
    write_manifest(
        tmp_path / "agent_packages.json",
        {"deb-arm64": entry(DEB_ARM_NAME, content=body)},
    )
    site = Source(Behaviour(body=body))
    try:
        base = f"http://127.0.0.1:{site.server.server_port}"
        cache = make_cache(
            tmp_path,
            fetcher=loopback_fetcher(),
            sites=({"files": base + "/{tag}/", "latest": base + "/latest.json"},),
        )

        path = cache.package(family="deb", architecture="arm64")
    finally:
        site.close()

    assert path.read_bytes() == body
    assert os.listdir(tmp_path / "agent_cache") == [DEB_ARM_NAME]
    assert site.behaviour.ranges[0].startswith("bytes=0-")
