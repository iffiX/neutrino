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
    package_name,
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
        assert sorted(entry) == ["name", "sha256", "size", "url"]
        assert entry["url"] == ""
    assert entries["deb-amd64"]["name"] == DEB_NAME
    assert entries["rpm-amd64"]["name"] == RPM_NAME
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
    the name the panel looks up — and it is the release's own asset name."""
    entries = venv_tree.agent_cache_entries(built, RELEASE_BASE)
    root = tmp_path / "agent_cache"
    root.mkdir()
    for path in built:
        key = "deb-amd64" if path.name.endswith(".deb") else "rpm-amd64"
        assert package_name(entries[key]) == path.name
        assert entries[key]["url"].endswith("/" + path.name)
        (root / path.name).write_bytes(path.read_bytes())

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


# --- seeding from packages a release already built ------------------------


def test_a_release_seeds_every_machine_it_built_and_builds_nothing(
    tmp_path, monkeypatch
):
    """The hub's own build makes the agent for one machine; a release hands
    it both, so a hub of either architecture can enroll a device of either."""
    prebuilt = tmp_path / "prebuilt"
    prebuilt.mkdir()
    for name in (
        DEB_NAME,
        RPM_NAME,
        "neutrino-agent_0.1.0_arm64.deb",
        "neutrino-agent-0.1.0-1.aarch64.rpm",
        "SHA256SUMS",
    ):
        (prebuilt / name).write_bytes(name.encode())
    monkeypatch.setenv(venv_tree.AGENT_PACKAGES_DIR_ENV, str(prebuilt))
    monkeypatch.setattr(
        venv_tree, "run", lambda *a, **k: pytest.fail("the agent was built")
    )
    tree = tmp_path / "tree"
    staged_python = tree / "opt/neutrino/python"
    (staged_python / "lib/python3.13/site-packages/neutrino_hub/data").mkdir(
        parents=True
    )

    venv_tree.stage_agent_cache(tree, staged_python, "amd64")

    cache = tree / str(venv_tree.AGENT_PACKAGE_CACHE_DIR).lstrip("/")
    assert sorted(path.name for path in cache.iterdir()) == sorted(
        [
            DEB_NAME,
            RPM_NAME,
            "neutrino-agent_0.1.0_arm64.deb",
            "neutrino-agent-0.1.0-1.aarch64.rpm",
        ]
    )
    manifest = json.loads(
        (
            staged_python
            / "lib/python3.13/site-packages/neutrino_hub/data"
            / venv_tree.AGENT_PACKAGE_MANIFEST_NAME
        ).read_text()
    )
    assert sorted(manifest) == ["deb-amd64", "deb-arm64", "rpm-amd64", "rpm-arm64"]


def test_a_directory_with_no_agent_package_stops_the_build(tmp_path, monkeypatch):
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / "SHA256SUMS").write_text("")
    monkeypatch.setenv(venv_tree.AGENT_PACKAGES_DIR_ENV, str(empty))

    with pytest.raises(SystemExit) as refused:
        venv_tree.stage_agent_cache(tmp_path / "tree", tmp_path / "python", "amd64")

    assert "no agent package" in str(refused.value)
