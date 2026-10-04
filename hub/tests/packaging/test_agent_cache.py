"""What the hub's build stamps about the agent packages it seeds.

The build writes the one file and the manifest that reads it back, so the two
are pinned together here: an entry the panel cannot resolve to the file beside
it is a cache that never hits.
"""

import hashlib
import json
from pathlib import Path

import pytest

import venv_tree
from neutrino_hub.modules.devices.agent_package import (
    AgentPackageCache,
    package_name,
)

DEB_NAME = "neutrino-agent_0.1.0_amd64.deb"
RPM_NAME = "neutrino-agent-0.1.0-1.x86_64.rpm"
RELEASE_BASE = "https://example.invalid/releases/download/v0.1.0"
RELEASE_AGENTS = (
    DEB_NAME,
    RPM_NAME,
    "neutrino-agent_0.1.0_arm64.deb",
    "neutrino-agent-0.1.0-1.aarch64.rpm",
    "neutrino-agent-0.1.0-windows-amd64.msi",
    "neutrino-agent-0.1.0-macos-arm64.pkg",
    "neutrino-agent-0.1.0-macos-amd64.pkg",
)


@pytest.fixture
def built(tmp_path):
    """The two files the agent's builds write, for one machine."""
    directory = tmp_path / "built"
    directory.mkdir()
    (directory / DEB_NAME).write_bytes(b"!<arch>deb bytes")
    (directory / RPM_NAME).write_bytes(b"\xed\xab\xee\xdbrpm bytes")
    return sorted(directory.iterdir())


def _staging(tmp_path, monkeypatch, *, prebuilt: bool, url_base: str):
    """A tree to stage into, with or without a release's agent packages."""
    if prebuilt:
        directory = tmp_path / "prebuilt"
        directory.mkdir()
        for name in RELEASE_AGENTS + ("SHA256SUMS",):
            (directory / name).write_bytes(name.encode())
        monkeypatch.setenv(venv_tree.AGENT_PACKAGES_DIR_ENV, str(directory))
    else:
        monkeypatch.delenv(venv_tree.AGENT_PACKAGES_DIR_ENV, raising=False)
    if url_base:
        monkeypatch.setenv(venv_tree.AGENT_PACKAGE_URL_BASE_ENV, url_base)
    else:
        monkeypatch.delenv(venv_tree.AGENT_PACKAGE_URL_BASE_ENV, raising=False)
    monkeypatch.setattr(
        venv_tree, "run", lambda *a, **k: pytest.fail("the agent was built")
    )
    tree = tmp_path / "tree"
    staged_python = tree / "opt/neutrino/hub/python"
    data = staged_python / "lib/python3.13/site-packages/neutrino_hub/data"
    data.mkdir(parents=True)
    return tree, staged_python, data


def _cached(tree) -> list:
    cache = tree / str(venv_tree.AGENT_PACKAGE_CACHE_DIR).lstrip("/")
    return sorted(path.name for path in cache.iterdir())


def _manifest(data) -> dict:
    return json.loads((data / venv_tree.AGENT_PACKAGE_MANIFEST_NAME).read_text())


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
    the name the panel looks up, and it is the release's own asset name."""
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
    assert str(venv_tree.AGENT_PACKAGE_CACHE_DIR) == "/var/lib/neutrino/hub/agent_cache"


# --- one agent package per hub package -------------------------------------


@pytest.mark.parametrize(
    ("kind", "machine", "carried"),
    [
        ("deb", "amd64", DEB_NAME),
        ("deb", "arm64", "neutrino-agent_0.1.0_arm64.deb"),
        ("rpm", "x86_64", RPM_NAME),
        ("rpm", "aarch64", "neutrino-agent-0.1.0-1.aarch64.rpm"),
        ("pkg", "x86_64", None),
    ],
)
def test_a_hub_package_carries_the_agent_package_of_its_own_platform_alone(
    tmp_path, monkeypatch, kind, machine, carried
):
    """The Arch package carries none, because no agent package is published
    for Arch."""
    tree, staged_python, _ = _staging(
        tmp_path, monkeypatch, prebuilt=True, url_base=RELEASE_BASE
    )

    venv_tree.stage_agent_cache(
        tree,
        staged_python,
        machine,
        family=venv_tree.AGENT_FAMILY_OF_HUB_KIND[kind],
    )

    assert _cached(tree) == ([carried] if carried else [])


def test_a_release_names_every_agent_package_with_its_url_and_hash(
    tmp_path, monkeypatch
):
    """The hub fetches what it does not carry from the release, checked
    against the hash the build read from the very file the release publishes."""
    tree, staged_python, data = _staging(
        tmp_path, monkeypatch, prebuilt=True, url_base=RELEASE_BASE
    )

    venv_tree.stage_agent_cache(tree, staged_python, "amd64", family="deb")

    manifest = _manifest(data)
    assert sorted(manifest) == [
        "deb-amd64",
        "deb-arm64",
        "msi-amd64",
        "pkg-amd64",
        "pkg-arm64",
        "rpm-amd64",
        "rpm-arm64",
    ]
    msi = "neutrino-agent-0.1.0-windows-amd64.msi"
    assert manifest["msi-amd64"]["url"] == f"{RELEASE_BASE}/{msi}"
    assert manifest["msi-amd64"]["sha256"] == hashlib.sha256(msi.encode()).hexdigest()
    assert _cached(tree) == [DEB_NAME]


def test_a_build_with_no_url_base_names_the_carried_package_alone(
    tmp_path, monkeypatch
):
    """Nothing published the others, so the manifest does not name them and
    the hub refuses them by name."""
    tree, staged_python, data = _staging(
        tmp_path, monkeypatch, prebuilt=True, url_base=""
    )

    venv_tree.stage_agent_cache(tree, staged_python, "amd64", family="deb")

    assert sorted(_manifest(data)) == ["deb-amd64"]
    cache = AgentPackageCache(
        root=tree / str(venv_tree.AGENT_PACKAGE_CACHE_DIR).lstrip("/"),
        manifest_path=data / venv_tree.AGENT_PACKAGE_MANIFEST_NAME,
        pinned_dir=tmp_path / "none",
    )
    assert cache.package(family="deb", architecture="amd64").name == DEB_NAME
    assert not cache.serves(family="msi", architecture="amd64")


def test_a_release_missing_this_platform_stops_the_build(tmp_path, monkeypatch):
    tree, staged_python, _ = _staging(tmp_path, monkeypatch, prebuilt=True, url_base="")
    (tmp_path / "prebuilt" / RPM_NAME).unlink()

    with pytest.raises(SystemExit) as refused:
        venv_tree.stage_agent_cache(tree, staged_python, "x86_64", family="rpm")

    assert "no agent rpm for x86_64" in str(refused.value)


def test_a_build_with_no_release_makes_its_own_family_alone(tmp_path, monkeypatch):
    """The container of one family never runs the other family's build."""
    tree, staged_python, data = _staging(
        tmp_path, monkeypatch, prebuilt=False, url_base=""
    )
    scripts = []

    def build(command, **_):
        scripts.append(Path(command[1]).name)
        output = Path(command[command.index("--output-dir") + 1])
        (output / DEB_NAME).write_bytes(b"!<arch>deb bytes")

    monkeypatch.setattr(venv_tree, "run", build)

    venv_tree.stage_agent_cache(tree, staged_python, "amd64", family="deb")

    assert scripts == ["build_deb.py"]
    assert _cached(tree) == [DEB_NAME]
    assert sorted(_manifest(data)) == ["deb-amd64"]


def test_the_arch_build_with_no_release_builds_no_agent(tmp_path, monkeypatch):
    tree, staged_python, data = _staging(
        tmp_path, monkeypatch, prebuilt=False, url_base=""
    )

    venv_tree.stage_agent_cache(tree, staged_python, "x86_64", family="")

    assert _cached(tree) == []
    assert _manifest(data) == {}


def test_a_directory_with_no_agent_package_stops_the_build(tmp_path, monkeypatch):
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / "SHA256SUMS").write_text("")
    monkeypatch.setenv(venv_tree.AGENT_PACKAGES_DIR_ENV, str(empty))

    with pytest.raises(SystemExit) as refused:
        venv_tree.stage_agent_cache(
            tmp_path / "tree", tmp_path / "python", "amd64", family="deb"
        )

    assert "no agent package" in str(refused.value)
