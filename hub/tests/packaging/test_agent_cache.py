"""What the hub's build stamps about the agent packages it seeds.

The build writes the files and the manifest that reads them back, so the two
are pinned together here: an entry the panel cannot resolve to the file beside
it is a cache that never hits.
"""

import hashlib
import json

import pytest

import venv_tree
from neutrino_hub.modules.devices.agent_package import (
    AgentPackageCache,
    package_key,
)

DEB_NAME = "neutrino-agent_0.1.0_amd64.deb"
RPM_NAME = "neutrino-agent-0.1.0-1.x86_64.rpm"
RELEASE_BASE = "https://example.invalid/releases/download/v0.1.0"


@pytest.fixture
def built(tmp_path):
    """The two files the agent's builds write, for one machine."""
    directory = tmp_path / "built"
    directory.mkdir()
    (directory / DEB_NAME).write_bytes(b"!<arch>deb bytes")
    (directory / RPM_NAME).write_bytes(b"\xed\xab\xee\xdbrpm bytes")
    return sorted(directory.iterdir())


def test_a_local_build_stamps_what_it_seeded_and_no_url(built):
    """Nothing published it, so nothing may be reached for: the entry carries
    the hash and the weight and an empty url."""
    entries = venv_tree.agent_cache_entries(built, "")

    assert sorted(entries) == ["deb-amd64", "rpm-amd64"]
    for entry in entries.values():
        assert sorted(entry) == ["sha256", "size", "url"]
        assert entry["url"] == ""
    assert (
        entries["deb-amd64"]["sha256"]
        == hashlib.sha256(b"!<arch>deb bytes").hexdigest()
    )
    assert entries["deb-amd64"]["size"] == len(b"!<arch>deb bytes")


def test_a_release_build_stamps_where_each_file_is_published(built):
    entries = venv_tree.agent_cache_entries(built, RELEASE_BASE)

    assert entries["deb-amd64"]["url"] == f"{RELEASE_BASE}/{DEB_NAME}"
    assert entries["rpm-amd64"]["url"] == f"{RELEASE_BASE}/{RPM_NAME}"


def test_a_trailing_slash_on_the_base_does_not_double(built):
    entries = venv_tree.agent_cache_entries(built, RELEASE_BASE + "/")

    assert entries["deb-amd64"]["url"] == f"{RELEASE_BASE}/{DEB_NAME}"


def test_a_build_that_names_no_machine_stops_the_package(tmp_path):
    """Seeded under a key nothing asks for, the file would be dead weight in
    every package built after it."""
    stray = tmp_path / "neutrino-agent_0.1.0_all.deb"
    stray.write_bytes(b"!<arch>")

    with pytest.raises(SystemExit) as refused:
        venv_tree.agent_cache_entries([stray], "")

    assert stray.name in str(refused.value)


def test_the_cache_resolves_every_entry_the_build_stamped(built, tmp_path):
    """The one thing the two sides must agree on: the name the build writes is
    the name the panel looks up."""
    entries = venv_tree.agent_cache_entries(built, "")
    root = tmp_path / "agent_cache"
    root.mkdir()
    for path in built:
        key = "deb-amd64" if path.name.endswith(".deb") else "rpm-amd64"
        name = package_key(key=key, digest=entries[key]["sha256"])
        (root / name).write_bytes(path.read_bytes())

    manifest = tmp_path / "agent_packages.json"
    manifest.write_text(json.dumps(entries), encoding="utf-8")
    cache = AgentPackageCache(
        root=root, manifest_path=manifest, pinned_dir=tmp_path / "none"
    )

    assert cache.package(family="deb", architecture="amd64").read_bytes() == (
        b"!<arch>deb bytes"
    )
    assert cache.package(family="rpm", architecture="amd64").read_bytes() == (
        b"\xed\xab\xee\xdbrpm bytes"
    )


def test_the_cache_directory_is_the_one_the_runtime_names():
    """Packaging follows the runtime here: a directory spelled twice is a
    package that seeds one place and a panel that reads another."""
    assert str(venv_tree.AGENT_PACKAGE_CACHE_DIR) == "/var/lib/neutrino/agent_cache"
