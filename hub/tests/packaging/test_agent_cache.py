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
from shared.constants import PACKAGING_EDITION_ENV, PACKAGING_RELEASE_SITES_ENV

DEB_NAME = "neutrino-agent_0.1.0_amd64.deb"
RPM_NAME = "neutrino-agent-0.1.0-1.x86_64.rpm"
RELEASE_AGENTS = (
    DEB_NAME,
    RPM_NAME,
    "neutrino-agent_0.1.0_arm64.deb",
    "neutrino-agent-0.1.0-1.aarch64.rpm",
    "neutrino-agent-0.1.0-1-x86_64.pkg.tar.zst",
    "neutrino-agent-0.1.0-windows-amd64.msi",
    "neutrino-agent-0.1.0-macos-arm64.pkg",
    "neutrino-agent-0.1.0-macos-amd64.pkg",
)
# The same release's cn agent packages, which one directory holds beside
# the intl ones.
CN_RELEASE_AGENTS = (
    "neutrino-agent_0.1.0_amd64-cn.deb",
    "neutrino-agent-0.1.0-1.x86_64-cn.rpm",
    "neutrino-agent-0.1.0-1-x86_64-cn.pkg.tar.zst",
    "neutrino-agent-0.1.0-windows-amd64-cn.msi",
)


@pytest.fixture(autouse=True)
def intl_build(monkeypatch):
    """Every build here is intl unless a test names cn."""
    monkeypatch.setenv(PACKAGING_EDITION_ENV, "intl")


@pytest.fixture
def built(tmp_path):
    """The two files the agent's builds write, for one machine."""
    directory = tmp_path / "built"
    directory.mkdir()
    (directory / DEB_NAME).write_bytes(b"!<arch>deb bytes")
    (directory / RPM_NAME).write_bytes(b"\xed\xab\xee\xdbrpm bytes")
    return sorted(directory.iterdir())


def _staging(tmp_path, monkeypatch, *, prebuilt: bool, has_release_sites: bool):
    """A tree to stage into, with or without a release's agent packages."""
    if prebuilt:
        directory = tmp_path / "prebuilt"
        directory.mkdir()
        for name in RELEASE_AGENTS + CN_RELEASE_AGENTS + ("SHA256SUMS",):
            (directory / name).write_bytes(name.encode())
        monkeypatch.setenv(venv_tree.AGENT_PACKAGES_DIR_ENV, str(directory))
    else:
        monkeypatch.delenv(venv_tree.AGENT_PACKAGES_DIR_ENV, raising=False)
    monkeypatch.setenv(PACKAGING_RELEASE_SITES_ENV, "1" if has_release_sites else "")
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


def test_an_entry_names_the_file_its_hash_and_its_weight(built):
    entries = venv_tree.agent_cache_entries(built)

    assert sorted(entries) == ["deb-amd64", "rpm-amd64"]
    for entry in entries.values():
        assert sorted(entry) == ["name", "sha256", "size"]
    assert entries["deb-amd64"]["name"] == DEB_NAME
    assert entries["rpm-amd64"]["name"] == RPM_NAME
    assert (
        entries["deb-amd64"]["sha256"]
        == hashlib.sha256(b"!<arch>deb bytes").hexdigest()
    )
    assert entries["deb-amd64"]["size"] == len(b"!<arch>deb bytes")


def test_a_build_that_names_no_machine_stops_the_package(tmp_path):
    """Seeded under a key nothing asks for, the file would be dead weight in
    every package built after it."""
    stray = tmp_path / "neutrino-agent_0.1.0_all.deb"
    stray.write_bytes(b"!<arch>")

    with pytest.raises(SystemExit) as refused:
        venv_tree.agent_cache_entries([stray])

    assert stray.name in str(refused.value)


def test_the_cache_resolves_every_entry_the_build_stamped(built, tmp_path):
    """The one thing the two sides must agree on: the name the build writes is
    the name the panel looks up, and it is the release's own asset name."""
    entries = venv_tree.agent_cache_entries(built)
    root = tmp_path / "agent_cache"
    root.mkdir()
    for path in built:
        key = "deb-amd64" if path.name.endswith(".deb") else "rpm-amd64"
        assert package_name(entries[key]) == path.name
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


def test_the_cache_resolves_a_cn_file_by_its_family_and_machine(tmp_path):
    """The edition's suffix sits before the extension, where neither the
    family nor the machine is read."""
    names = [
        "neutrino-agent_0.1.0_arm64-cn.deb",
        "neutrino-agent-0.1.0-1.aarch64-cn.rpm",
        "neutrino-agent-0.1.0-windows-amd64-cn.msi",
        "neutrino-agent-0.1.0-macos-arm64-cn.pkg",
    ]
    paths = []
    for name in names:
        (tmp_path / name).write_bytes(name.encode())
        paths.append(tmp_path / name)

    entries = venv_tree.agent_cache_entries(paths)

    assert {key: entry["name"] for key, entry in entries.items()} == {
        "deb-arm64": names[0],
        "rpm-arm64": names[1],
        "msi-amd64": names[2],
        "pkg-arm64": names[3],
    }


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
        ("pkg", "x86_64", "neutrino-agent-0.1.0-1-x86_64.pkg.tar.zst"),
    ],
)
def test_a_hub_package_carries_the_agent_package_of_its_own_platform_alone(
    tmp_path, monkeypatch, kind, machine, carried
):
    tree, staged_python, _ = _staging(
        tmp_path, monkeypatch, prebuilt=True, has_release_sites=True
    )

    venv_tree.stage_agent_cache(
        tree,
        staged_python,
        machine,
        family=venv_tree.AGENT_FAMILY_OF_HUB_KIND[kind],
    )

    assert _cached(tree) == [carried]


def test_a_release_names_every_agent_package_of_its_edition_with_its_hash(
    tmp_path, monkeypatch
):
    """The hub fetches what it does not carry from the release sites, checked
    against the hash the build read from the very file the release holds."""
    tree, staged_python, data = _staging(
        tmp_path, monkeypatch, prebuilt=True, has_release_sites=True
    )

    venv_tree.stage_agent_cache(tree, staged_python, "amd64", family="deb")

    manifest = _manifest(data)
    assert sorted(manifest) == [
        "arch-amd64",
        "deb-amd64",
        "deb-arm64",
        "msi-amd64",
        "pkg-amd64",
        "pkg-arm64",
        "rpm-amd64",
        "rpm-arm64",
    ]
    msi = "neutrino-agent-0.1.0-windows-amd64.msi"
    assert manifest["msi-amd64"] == {
        "name": msi,
        "sha256": hashlib.sha256(msi.encode()).hexdigest(),
        "size": len(msi.encode()),
    }
    assert _cached(tree) == [DEB_NAME]


def test_a_cn_release_names_and_carries_the_cn_agent_packages_alone(
    tmp_path, monkeypatch
):
    tree, staged_python, data = _staging(
        tmp_path, monkeypatch, prebuilt=True, has_release_sites=True
    )
    monkeypatch.setenv(PACKAGING_EDITION_ENV, "cn")

    venv_tree.stage_agent_cache(tree, staged_python, "amd64", family="deb")

    assert {key: entry["name"] for key, entry in _manifest(data).items()} == {
        "deb-amd64": "neutrino-agent_0.1.0_amd64-cn.deb",
        "rpm-amd64": "neutrino-agent-0.1.0-1.x86_64-cn.rpm",
        "arch-amd64": "neutrino-agent-0.1.0-1-x86_64-cn.pkg.tar.zst",
        "msi-amd64": "neutrino-agent-0.1.0-windows-amd64-cn.msi",
    }
    assert _cached(tree) == ["neutrino-agent_0.1.0_amd64-cn.deb"]


def test_a_debian_hub_names_the_arch_agent_and_carries_its_own(tmp_path, monkeypatch):
    """A hub of any family serves an Arch machine from the release sites."""
    tree, staged_python, data = _staging(
        tmp_path, monkeypatch, prebuilt=True, has_release_sites=True
    )

    venv_tree.stage_agent_cache(tree, staged_python, "amd64", family="deb")

    assert (
        _manifest(data)["arch-amd64"]["name"]
        == "neutrino-agent-0.1.0-1-x86_64.pkg.tar.zst"
    )
    assert _cached(tree) == [DEB_NAME]


def test_a_build_with_no_release_sites_names_the_carried_package_alone(
    tmp_path, monkeypatch
):
    """Nothing published the others, so the manifest does not name them and
    the hub refuses them by name."""
    tree, staged_python, data = _staging(
        tmp_path, monkeypatch, prebuilt=True, has_release_sites=False
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
    tree, staged_python, _ = _staging(
        tmp_path, monkeypatch, prebuilt=True, has_release_sites=False
    )
    (tmp_path / "prebuilt" / RPM_NAME).unlink()

    with pytest.raises(SystemExit) as refused:
        venv_tree.stage_agent_cache(tree, staged_python, "x86_64", family="rpm")

    assert "no agent rpm for x86_64" in str(refused.value)


def test_a_build_with_no_release_makes_its_own_family_alone(tmp_path, monkeypatch):
    """The container of one family never runs the other family's build."""
    tree, staged_python, data = _staging(
        tmp_path, monkeypatch, prebuilt=False, has_release_sites=False
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
        tmp_path, monkeypatch, prebuilt=False, has_release_sites=False
    )

    venv_tree.stage_agent_cache(tree, staged_python, "x86_64", family="")

    assert _cached(tree) == []
    assert _manifest(data) == {}


@pytest.mark.parametrize(
    ("edition", "held"),
    [("intl", ("SHA256SUMS",)), ("cn", ("SHA256SUMS", DEB_NAME))],
)
def test_a_directory_with_no_agent_package_of_the_edition_stops_the_build(
    tmp_path, monkeypatch, edition, held
):
    directory = tmp_path / "agents"
    directory.mkdir()
    for name in held:
        (directory / name).write_text("")
    monkeypatch.setenv(venv_tree.AGENT_PACKAGES_DIR_ENV, str(directory))
    monkeypatch.setenv(PACKAGING_EDITION_ENV, edition)

    with pytest.raises(SystemExit) as refused:
        venv_tree.stage_agent_cache(
            tmp_path / "tree", tmp_path / "python", "amd64", family="deb"
        )

    assert str(refused.value) == f"no {edition} agent package under {directory}"
