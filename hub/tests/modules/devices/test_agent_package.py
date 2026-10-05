"""Which agent package the hub hands a device, and where it comes from.

The hub's own package seeds the cache with the one package of its own
platform, so for that platform the answer is a file already on disk, under
the name the release publishes it as. Every other platform is fetched once
from the release the manifest names, checked against the manifest's hash,
and kept under that same name. A platform with
neither is refused by name.
"""

import hashlib
import io
import json
import os

import pytest

from neutrino_hub.modules.devices import agent_package
from neutrino_hub.exceptions import AgentArtifactFetchError
from neutrino_hub.modules.devices.agent_package import (
    AgentPackageCache,
    package_architecture,
    package_family,
    package_name,
    platform_family,
    platform_key,
)

DEB_BYTES = b"!<arch>an agent deb"
DEB_DIGEST = hashlib.sha256(DEB_BYTES).hexdigest()
DEB_NAME = "neutrino-agent_0.1.0_amd64.deb"
DEB_ARM_NAME = "neutrino-agent_0.1.0_arm64.deb"
RPM_NAME = "neutrino-agent-0.1.0-1.x86_64.rpm"
RELEASE_URL = f"https://example.invalid/{DEB_NAME}"


@pytest.fixture
def cache(tmp_path, monkeypatch):
    """A cache over three empty directories, with nothing fetchable."""

    def refuse(*args, **kwargs):
        raise AssertionError("nothing should have been fetched")

    monkeypatch.setattr(agent_package.urllib.request, "urlopen", refuse)
    (tmp_path / "pinned").mkdir()
    return AgentPackageCache(
        root=tmp_path / "agent_cache",
        manifest_path=tmp_path / "agent_packages.json",
        pinned_dir=tmp_path / "pinned",
    )


def write_manifest(path, entries: dict) -> None:
    """Stamp a manifest the way a build would."""
    path.write_text(json.dumps(entries), encoding="utf-8")


def entry(name: str, *, url: str = "", content: bytes = DEB_BYTES) -> dict:
    """One manifest entry, stamped over the bytes it is for."""
    return {
        "name": name,
        "url": url,
        "sha256": hashlib.sha256(content).hexdigest(),
        "size": len(content),
    }


def seed(root, name: str, content: bytes) -> None:
    """Put a package in the cache the way the hub's package does."""
    root.mkdir(parents=True, exist_ok=True)
    (root / name).write_bytes(content)


def answers(monkeypatch, content: bytes):
    """Make the one release URL answer with these bytes."""
    served = []

    def urlopen(url, timeout=None, context=None):
        served.append(url)
        return io.BytesIO(content)

    monkeypatch.setattr(agent_package.urllib.request, "urlopen", urlopen)
    return served


@pytest.mark.parametrize(
    "name, architecture",
    [
        ("neutrino-agent_0.1.0_amd64.deb", "amd64"),
        ("neutrino-agent_0.1.0_arm64.deb", "arm64"),
        ("neutrino-agent-0.1.0-1.x86_64.rpm", "amd64"),
        ("neutrino-agent-0.1.0-1.aarch64.rpm", "arm64"),
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
        ("neutrino-agent-0.4.0-windows-amd64.msi", "msi"),
        ("neutrino-agent-0.4.0-macos-arm64.pkg", "pkg"),
        ("neutrino-hub-0.4.0-1-x86_64.pkg.tar.zst", ""),
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


def test_a_held_file_that_is_another_build_is_fetched_again(
    cache, tmp_path, monkeypatch
):
    """The name is the release's and says nothing about what is inside it, so
    the pinned hash is what decides whether a held file is still the answer."""
    write_manifest(
        tmp_path / "agent_packages.json",
        {"deb-amd64": entry(DEB_NAME, url=RELEASE_URL)},
    )
    seed(tmp_path / "agent_cache", DEB_NAME, b"!<arch>an older agent deb")
    served = answers(monkeypatch, DEB_BYTES)

    path = cache.package(family="deb", architecture="amd64")

    assert served == [RELEASE_URL]
    assert path.name == DEB_NAME
    assert path.read_bytes() == DEB_BYTES


def test_a_platform_the_release_publishes_is_fetched_once_and_kept(
    cache, tmp_path, monkeypatch
):
    write_manifest(
        tmp_path / "agent_packages.json",
        {"deb-arm64": entry(DEB_ARM_NAME, url=RELEASE_URL)},
    )
    served = answers(monkeypatch, DEB_BYTES)

    path = cache.package(family="deb", architecture="arm64")

    assert served == [RELEASE_URL]
    assert path.read_bytes() == DEB_BYTES
    assert path.name == DEB_ARM_NAME

    def refuse(*args, **kwargs):
        raise AssertionError("the second ask should have been a cache hit")

    monkeypatch.setattr(agent_package.urllib.request, "urlopen", refuse)
    assert cache.package(family="deb", architecture="arm64") == path


def test_a_release_that_serves_something_else_is_refused_and_kept_nowhere(
    cache, tmp_path, monkeypatch
):
    write_manifest(
        tmp_path / "agent_packages.json",
        {
            "deb-arm64": {
                "name": DEB_ARM_NAME,
                "url": RELEASE_URL,
                "sha256": "0" * 64,
                "size": 9,
            }
        },
    )
    answers(monkeypatch, DEB_BYTES)

    with pytest.raises(AgentArtifactFetchError) as refused:
        cache.package(family="deb", architecture="arm64")

    assert refused.value.code == "agent_package_sha256_mismatch"
    assert refused.value.params["received"] == DEB_DIGEST
    assert os.listdir(tmp_path / "agent_cache") == []


def test_a_platform_with_no_url_and_nothing_held_is_refused_by_name(cache, tmp_path):
    """A local build seeds what it made and stamps no URL for the rest; the
    refusal says which platform rather than handing over another machine's."""
    write_manifest(
        tmp_path / "agent_packages.json",
        {"rpm-arm64": entry("neutrino-agent-0.1.0-1.aarch64.rpm")},
    )

    with pytest.raises(AgentArtifactFetchError) as refused:
        cache.package(family="rpm", architecture="arm64")

    assert refused.value.code == "agent_package_missing"
    assert refused.value.params == {"platform": "rpm-arm64"}
    assert not cache.serves(family="rpm", architecture="arm64")


def test_a_platform_the_manifest_never_names_is_refused_by_name(cache, tmp_path):
    write_manifest(tmp_path / "agent_packages.json", {"deb-amd64": {"url": ""}})

    with pytest.raises(AgentArtifactFetchError) as refused:
        cache.package(family="msi", architecture="amd64")

    assert refused.value.params == {"platform": "msi-amd64"}


def test_a_pinned_build_wins_over_the_manifest(cache, tmp_path):
    """A build dropped in by hand is a decision, and it beats both the seeded
    file and anything the release publishes."""
    write_manifest(
        tmp_path / "agent_packages.json",
        {"deb-amd64": entry(DEB_NAME, url=RELEASE_URL)},
    )
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
    write_manifest(
        tmp_path / "agent_packages.json",
        {"deb-amd64": entry(DEB_NAME, url=RELEASE_URL)},
    )

    assert cache.has_packages()
    assert cache.serves(family="deb", architecture="amd64")


def test_the_release_url_is_where_the_build_stamped_the_packages(cache, tmp_path):
    write_manifest(
        tmp_path / "agent_packages.json",
        {"deb-amd64": entry(DEB_NAME, url=RELEASE_URL)},
    )

    assert cache.release_url() == "https://example.invalid"


def test_a_build_that_stamped_no_url_names_no_release(cache, tmp_path):
    write_manifest(tmp_path / "agent_packages.json", {"deb-amd64": entry(DEB_NAME)})

    assert cache.release_url() == ""


def test_a_pinned_build_alone_is_a_hub_that_carries_something(cache, tmp_path):
    (tmp_path / "pinned" / "neutrino-agent_0.2.0_amd64.deb").write_bytes(b"pinned")

    assert cache.has_packages()


def test_an_unreadable_manifest_is_a_hub_that_knows_no_platform(cache, tmp_path):
    (tmp_path / "agent_packages.json").write_text("not json", encoding="utf-8")

    assert cache.manifest() == {}
    assert not cache.has_packages()


# --- another platform's package comes from the release ---------------------

MSI_NAME = "neutrino-agent-0.1.0-windows-amd64.msi"
MSI_BYTES = b"MZ an agent installer"
MSI_URL = f"https://example.invalid/{MSI_NAME}"


def test_a_deb_hub_fetches_the_windows_installer_and_checks_it(
    cache, tmp_path, monkeypatch
):
    """The hub carries its own platform's package alone; a Windows agent
    updating itself is served the release's file once it hashes right."""
    write_manifest(
        tmp_path / "agent_packages.json",
        {
            "deb-amd64": entry(DEB_NAME, url=RELEASE_URL),
            "msi-amd64": entry(MSI_NAME, url=MSI_URL, content=MSI_BYTES),
        },
    )
    seed(tmp_path / "agent_cache", DEB_NAME, DEB_BYTES)
    served = answers(monkeypatch, MSI_BYTES)

    assert cache.package(family="deb", architecture="amd64").name == DEB_NAME
    path = cache.package(family="msi", architecture="amd64")

    assert served == [MSI_URL]
    assert path == tmp_path / "agent_cache" / MSI_NAME
    assert path.read_bytes() == MSI_BYTES


def test_an_entry_that_pins_no_hash_is_never_fetched(cache, tmp_path):
    """A fetch is kept only once it matches; with nothing to match it against
    the platform is refused by name and nothing is downloaded."""
    unpinned = entry(MSI_NAME, url=MSI_URL, content=MSI_BYTES)
    unpinned["sha256"] = ""
    write_manifest(tmp_path / "agent_packages.json", {"msi-amd64": unpinned})

    with pytest.raises(AgentArtifactFetchError) as refused:
        cache.package(family="msi", architecture="amd64")

    assert refused.value.code == "agent_package_missing"
    assert not cache.serves(family="msi", architecture="amd64")


def test_an_unreachable_release_is_refused_with_its_own_code(
    cache, tmp_path, monkeypatch
):
    write_manifest(
        tmp_path / "agent_packages.json",
        {"msi-amd64": entry(MSI_NAME, url=MSI_URL, content=MSI_BYTES)},
    )

    def unreachable(*args, **kwargs):
        raise OSError("Name or service not known")

    monkeypatch.setattr(agent_package.urllib.request, "urlopen", unreachable)

    with pytest.raises(AgentArtifactFetchError) as refused:
        cache.package(family="msi", architecture="amd64")

    assert refused.value.code == "agent_package_fetch_failed"
    assert list((tmp_path / "agent_cache").glob("*")) == []


def test_a_held_file_that_no_longer_hashes_right_is_fetched_again(
    cache, tmp_path, monkeypatch
):
    write_manifest(
        tmp_path / "agent_packages.json",
        {"msi-amd64": entry(MSI_NAME, url=MSI_URL, content=MSI_BYTES)},
    )
    seed(tmp_path / "agent_cache", MSI_NAME, b"MZ a truncated download")
    served = answers(monkeypatch, MSI_BYTES)

    path = cache.package(family="msi", architecture="amd64")

    assert served == [MSI_URL]
    assert path.read_bytes() == MSI_BYTES


class BrokenResponse(io.BytesIO):
    """A body that breaks off after its first chunk."""

    def read(self, size=-1):
        if self.tell() > 0:
            raise ConnectionResetError("the peer went away")
        return super().read(size)


def test_a_release_that_breaks_off_is_refused_and_leaves_nothing_behind(
    cache, tmp_path, monkeypatch
):
    body = b"!<arch>" + b"x" * (1024 * 1024)
    write_manifest(
        tmp_path / "agent_packages.json",
        {"deb-arm64": entry(DEB_ARM_NAME, url=RELEASE_URL, content=body)},
    )
    monkeypatch.setattr(
        agent_package.urllib.request,
        "urlopen",
        lambda url, timeout=None, context=None: BrokenResponse(body),
    )

    with pytest.raises(AgentArtifactFetchError) as refused:
        cache.package(family="deb", architecture="arm64")

    assert refused.value.code == "agent_package_fetch_failed"
    assert os.listdir(tmp_path / "agent_cache") == []


def test_a_large_release_lands_whole_under_its_name(cache, tmp_path, monkeypatch):
    body = b"!<arch>" + os.urandom(3 * 1024 * 1024)
    write_manifest(
        tmp_path / "agent_packages.json",
        {"deb-arm64": entry(DEB_ARM_NAME, url=RELEASE_URL, content=body)},
    )
    answers(monkeypatch, body)

    path = cache.package(family="deb", architecture="arm64")

    assert path.read_bytes() == body
    assert os.listdir(tmp_path / "agent_cache") == [DEB_ARM_NAME]
