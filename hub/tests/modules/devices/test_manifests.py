"""The shipped manifests: one source of module truth under data/manifests.

What the panel offers, what the catalog resolves and what an agent installs
all read these files, so the modules the design names are pinned here as
shipped: the four a device hosts from the hub's desired state, three by the
machine's own packages and Gitea as a pinned release binary, and the two
remote desktops as user-tier detection with nothing to download. Every
manifest names its installer tier and where its software comes from.
"""

import json

import pytest

from neutrino_hub.modules.devices import manifests as manifests_module
from neutrino_hub.modules.devices.agent_module_cache import (
    looks_like_package,
    resolve_platform_entry,
)
from neutrino_hub.modules.devices.catalog import resolve_module
from neutrino_hub.modules.devices.manifests import load_module_manifests

# The fields that mean the hub downloads something. A user-tier manifest
# carrying any of them is one the hub would fetch for after all.
DOWNLOAD_FIELDS = ("url", "github_repo", "asset_pattern", "download")

GITEA_VERSION = "1.27.3"
# The checksums dl.gitea.com publishes beside each release binary, in its
# own .sha256 files. Each is a published checksum of a public download.
GITEA_DIGESTS = {
    "linux-amd64": "4da93c2c10b6980c359bcb86d5573ebfd7770e2e151756534edee24c8c12d971",  # scan: allow
    "linux-arm64": "04c086d36dba793546e331484a9da34571763efdfa77dc526cc98e0f10917e7b",  # scan: allow
}

DEBIAN = {"os": "linux", "family": "debian", "arch": "amd64"}
RHEL = {"os": "linux", "family": "rhel", "arch": "amd64"}


def write_manifest(directory, name: str, manifest: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{name}.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_every_shipped_manifest_names_its_installer_tier():
    tiers = {
        name: manifest["installer"]
        for name, manifest in load_module_manifests().items()
    }

    assert tiers == {
        "podman": "platform",
        "samba": "platform",
        "zfs": "platform",
        "gitea": "hub",
        "anydesk": "user",
        "teamviewer": "user",
    }


def test_every_shipped_manifest_says_where_its_software_comes_from():
    sources = {
        name: manifest["source"] for name, manifest in load_module_manifests().items()
    }

    assert sources == {
        "podman": "system",
        "samba": "system",
        "zfs": "system",
        "gitea": "go-gitea/gitea",
        "anydesk": "AnyDesk Software GmbH",
        "teamviewer": "TeamViewer Germany GmbH",
    }


def test_the_manifests_come_back_in_the_order_both_surfaces_draw():
    """What the machine carries, then what this hub fetches, then what a
    person installs themselves, and by title inside each tier."""
    assert list(load_module_manifests()) == [
        "podman",
        "samba",
        "zfs",
        "gitea",
        "anydesk",
        "teamviewer",
    ]


@pytest.mark.parametrize("name", ["ssh_server", "samba_mount", "cc_switch", "rustdesk"])
def test_the_modules_that_left_are_not_shipped_any_more(name):
    assert name not in load_module_manifests()


@pytest.mark.parametrize(
    "name, debian, rhel",
    [
        ("samba", ["samba"], ["samba", "samba-client"]),
        ("podman", ["podman", "podman-docker"], ["podman", "podman-docker"]),
        (
            "zfs",
            ["zfsutils-linux", "zfs-zed", "smartmontools"],
            ["zfs", "smartmontools"],
        ),
    ],
)
def test_a_system_package_module_names_its_packages_per_family(name, debian, rhel):
    manifest = load_module_manifests()[name]

    assert manifest["kind"] == "system_package"
    assert resolve_module(manifest, DEBIAN)["entry"]["packages"] == debian
    assert resolve_module(manifest, RHEL)["entry"]["packages"] == rhel


def test_zfs_adds_the_repository_each_family_keeps_it_in_before_its_packages():
    manifest = load_module_manifests()["zfs"]

    debian_steps = resolve_module(manifest, DEBIAN)["entry"]["pre_install"]
    rhel_steps = resolve_module(manifest, RHEL)["entry"]["pre_install"]
    assert any("contrib" in step for step in debian_steps)
    assert any("apt-get update" in step for step in debian_steps)
    assert any("zfs-dkms" in step for step in debian_steps)
    assert any("zfsonlinux.org" in step for step in rhel_steps)
    assert manifest["platforms"]["linux-arch"]["pre_install"]


def test_gitea_pins_the_release_binary_and_its_published_digest_per_machine():
    manifest = load_module_manifests()["gitea"]

    assert manifest["kind"] == "gitea"
    assert manifest["version"] == GITEA_VERSION
    assert manifest["license"] == "MIT"
    assert manifest["corresponding_source"] == (
        f"https://github.com/go-gitea/gitea/tree/v{GITEA_VERSION}"
    )
    for key, digest in GITEA_DIGESTS.items():
        entry = manifest["platforms"][key]
        assert entry["url"] == (
            f"https://dl.gitea.com/gitea/{GITEA_VERSION}/gitea-{GITEA_VERSION}-{key}"
        )
        assert entry["sha256"] == digest
        assert entry["package_kind"] == "binary"
        assert entry["packages"] == ["git"]


def test_gitea_resolves_by_machine_and_refuses_the_rest():
    manifest = load_module_manifests()["gitea"]

    assert resolve_platform_entry(manifest, DEBIAN)[0] == "linux-amd64"
    assert resolve_platform_entry(manifest, {**RHEL, "arch": "arm64"})[0] == (
        "linux-arm64"
    )
    assert resolve_platform_entry(manifest, {**DEBIAN, "arch": "armhf"}) == ("", None)


def test_a_binary_package_is_recognised_by_its_elf_magic():
    assert looks_like_package(b"\x7fELF\x02\x01\x01", "binary")
    assert not looks_like_package(b"<!doctype html>", "binary")


@pytest.mark.parametrize("tier", ["platform", "hub", "user"])
def test_the_loader_accepts_each_tier(tier, tmp_path, monkeypatch):
    monkeypatch.setattr(manifests_module, "MANIFESTS_DIR", tmp_path)
    write_manifest(
        tmp_path, "sample", {"name": "sample", "installer": tier, "source": "s"}
    )

    assert load_module_manifests()["sample"]["installer"] == tier


@pytest.mark.parametrize(
    "manifest",
    [
        {"name": "sample", "source": "s"},
        {"name": "sample", "installer": "vendor", "source": "s"},
    ],
)
def test_the_loader_refuses_a_manifest_without_a_real_tier(
    manifest, tmp_path, monkeypatch
):
    monkeypatch.setattr(manifests_module, "MANIFESTS_DIR", tmp_path)
    write_manifest(tmp_path, "sample", manifest)

    with pytest.raises(ValueError) as refusal:
        load_module_manifests()

    assert "sample.json" in str(refusal.value)
    assert "installer" in str(refusal.value)


def test_user_tier_manifests_carry_nothing_to_download():
    for name, manifest in load_module_manifests().items():
        if manifest["installer"] != "user":
            continue
        assert not any(field in manifest for field in DOWNLOAD_FIELDS), name
        for entry in manifest["platforms"].values():
            assert not any(field in entry for field in DOWNLOAD_FIELDS), name


def test_windows_verify_commands_fail_when_the_software_is_absent():
    # PowerShell Test-Path prints False but exits 0, so a bare Test-Path
    # reads absent software as installed.
    verified = []
    for name, manifest in load_module_manifests().items():
        command = manifest.get("platforms", {}).get("windows", {}).get("verify", "")
        if "Test-Path" not in command:
            continue
        assert "exit 1" in command, f"{name} reads absent software as installed"
        verified.append(name)
    assert set(verified) == {"anydesk", "teamviewer"}


def test_a_user_tier_module_resolves_to_its_verify_on_each_platform():
    manifest = load_module_manifests()["teamviewer"]

    for os_name in ("linux", "windows", "darwin"):
        resolved = resolve_module(
            manifest, {"os": os_name, "family": "", "arch": "amd64"}
        )
        assert resolved["installer"] == "user"
        assert resolved["verify"]
        assert resolved["entry"] not in (None, {})


def test_the_resolved_module_carries_the_installer_tier():
    resolved = resolve_module(load_module_manifests()["gitea"], DEBIAN)

    assert resolved["installer"] == "hub"


def test_every_module_the_hub_conveys_names_its_license_and_source():
    """Hub-tier means this hub fetches the bytes and hands them on, which is
    what obliges the license and the directions to the source."""
    for name, manifest in load_module_manifests().items():
        if manifest["installer"] != "hub":
            assert "license" not in manifest, name
            assert "corresponding_source" not in manifest, name
            continue
        assert manifest["license"], name
        assert manifest["corresponding_source"].startswith("https://github.com/"), name


def test_the_loader_refuses_a_manifest_that_names_no_source(tmp_path, monkeypatch):
    monkeypatch.setattr(manifests_module, "MANIFESTS_DIR", tmp_path)
    write_manifest(tmp_path, "sample", {"name": "sample", "installer": "hub"})

    with pytest.raises(ValueError) as refusal:
        load_module_manifests()

    assert "sample.json" in str(refusal.value)
    assert "source" in str(refusal.value)
