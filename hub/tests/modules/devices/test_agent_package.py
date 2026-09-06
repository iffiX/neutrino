"""Which agent package the hub hands a device, and where it comes from.

The hub's own package seeds the cache with the builds it was made from, so
the ordinary answer is a file already on disk. A platform it seeded none for
is fetched once from the release the manifest names and kept under the same
key. A platform with neither is refused by name.
"""

import hashlib
import io
import json

import pytest

from neutrino_hub.modules.devices import agent_package
from neutrino_hub.modules.devices.agent_package import (
    AgentPackageCache,
    AgentPackageFetchError,
    package_architecture,
    package_family,
    package_key,
    platform_key,
)

DEB_BYTES = b"!<arch>an agent deb"
DEB_DIGEST = hashlib.sha256(DEB_BYTES).hexdigest()
RELEASE_URL = "https://example.invalid/neutrino-agent_0.1.0_amd64.deb"


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


def seed(root, key: str, content: bytes) -> None:
    """Put a package in the cache the way the hub's package does."""
    root.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(content).hexdigest()
    (root / package_key(key=key, digest=digest)).write_bytes(content)


def answers(monkeypatch, content: bytes):
    """Make the one release URL answer with these bytes."""
    served = []

    def urlopen(url, timeout=None):
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
        ("neutrino-agent-0.1.0.msi", ""),
        ("SHA256SUMS", ""),
    ],
)
def test_the_family_is_read_from_the_suffix(name, family):
    assert package_family(name) == family


def test_a_key_names_the_package_the_platform_and_what_is_inside_it():
    """The digest is the file's own, so a build that changed cannot be served
    under the name the old one had."""
    key = package_key(key=platform_key("deb", "amd64"), digest=DEB_DIGEST)

    assert key == f"neutrino_agent-deb-amd64-{DEB_DIGEST[:16]}"


def test_a_platform_key_needs_both_halves():
    assert platform_key("deb", "") == ""
    assert platform_key("", "amd64") == ""


def test_a_seeded_package_is_served_without_reaching_for_anything(cache, tmp_path):
    """What the hub's own package laid down is the whole answer: a Linux
    install and a Linux self-update need no network."""
    write_manifest(
        tmp_path / "agent_packages.json",
        {"deb-amd64": {"url": "", "sha256": DEB_DIGEST, "size": len(DEB_BYTES)}},
    )
    seed(tmp_path / "agent_cache", "deb-amd64", DEB_BYTES)

    path = cache.package(family="deb", architecture="amd64")

    assert path.read_bytes() == DEB_BYTES
    assert path.name == f"neutrino_agent-deb-amd64-{DEB_DIGEST[:16]}"
    assert cache.serves(family="deb", architecture="amd64")


def test_a_platform_the_release_publishes_is_fetched_once_and_kept(
    cache, tmp_path, monkeypatch
):
    write_manifest(
        tmp_path / "agent_packages.json",
        {
            "deb-arm64": {
                "url": RELEASE_URL,
                "sha256": DEB_DIGEST,
                "size": len(DEB_BYTES),
            }
        },
    )
    served = answers(monkeypatch, DEB_BYTES)

    path = cache.package(family="deb", architecture="arm64")

    assert served == [RELEASE_URL]
    assert path.read_bytes() == DEB_BYTES
    assert path.name == f"neutrino_agent-deb-arm64-{DEB_DIGEST[:16]}"

    def refuse(*args, **kwargs):
        raise AssertionError("the second ask should have been a cache hit")

    monkeypatch.setattr(agent_package.urllib.request, "urlopen", refuse)
    assert cache.package(family="deb", architecture="arm64") == path


def test_a_release_that_serves_something_else_is_refused_and_kept_nowhere(
    cache, tmp_path, monkeypatch
):
    write_manifest(
        tmp_path / "agent_packages.json",
        {"deb-arm64": {"url": RELEASE_URL, "sha256": "0" * 64, "size": 9}},
    )
    answers(monkeypatch, DEB_BYTES)

    with pytest.raises(AgentPackageFetchError) as refused:
        cache.package(family="deb", architecture="arm64")

    assert refused.value.code == "agent_package_sha256_mismatch"
    assert refused.value.params["received"] == DEB_DIGEST
    assert list((tmp_path / "agent_cache").glob("*")) == []


def test_a_platform_with_no_url_and_nothing_held_is_refused_by_name(cache, tmp_path):
    """A local build seeds what it made and stamps no URL for the rest; the
    refusal says which platform rather than handing over another machine's."""
    write_manifest(
        tmp_path / "agent_packages.json",
        {"rpm-arm64": {"url": "", "sha256": DEB_DIGEST, "size": len(DEB_BYTES)}},
    )

    with pytest.raises(AgentPackageFetchError) as refused:
        cache.package(family="rpm", architecture="arm64")

    assert refused.value.code == "agent_package_missing"
    assert refused.value.params == {"platform": "rpm-arm64"}
    assert not cache.serves(family="rpm", architecture="arm64")


def test_a_platform_the_manifest_never_names_is_refused_by_name(cache, tmp_path):
    write_manifest(tmp_path / "agent_packages.json", {"deb-amd64": {"url": ""}})

    with pytest.raises(AgentPackageFetchError) as refused:
        cache.package(family="msi", architecture="amd64")

    assert refused.value.params == {"platform": "msi-amd64"}


def test_a_pinned_build_wins_over_the_manifest(cache, tmp_path):
    """A build dropped in by hand is a decision, and it beats both the seeded
    file and anything the release publishes."""
    write_manifest(
        tmp_path / "agent_packages.json",
        {"deb-amd64": {"url": RELEASE_URL, "sha256": DEB_DIGEST, "size": 9}},
    )
    seed(tmp_path / "agent_cache", "deb-amd64", DEB_BYTES)
    (tmp_path / "pinned" / "neutrino-agent_0.2.0_amd64.deb").write_bytes(b"pinned")

    path = cache.package(family="deb", architecture="amd64")

    assert path.read_bytes() == b"pinned"


def test_a_pinned_build_of_one_family_leaves_the_other_alone(cache, tmp_path):
    write_manifest(
        tmp_path / "agent_packages.json",
        {"rpm-amd64": {"url": "", "sha256": DEB_DIGEST, "size": len(DEB_BYTES)}},
    )
    seed(tmp_path / "agent_cache", "rpm-amd64", DEB_BYTES)
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
        {"deb-amd64": {"url": RELEASE_URL, "sha256": DEB_DIGEST, "size": 9}},
    )

    assert cache.has_packages()
    assert cache.serves(family="deb", architecture="amd64")


def test_a_pinned_build_alone_is_a_hub_that_carries_something(cache, tmp_path):
    (tmp_path / "pinned" / "neutrino-agent_0.2.0_amd64.deb").write_bytes(b"pinned")

    assert cache.has_packages()


def test_an_unreadable_manifest_is_a_hub_that_knows_no_platform(cache, tmp_path):
    (tmp_path / "agent_packages.json").write_text("not json", encoding="utf-8")

    assert cache.manifest() == {}
    assert not cache.has_packages()
