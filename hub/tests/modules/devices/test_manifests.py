"""The shipped manifests: one source of module truth under data/manifests.

What the panel offers, what the catalog resolves and what an agent installs
all read these files, so the modules the design names are pinned here as
shipped — cc-switch as a real module, the mount tooling as a distro package,
the SSH server under its plain title, and the remote desktops as user-tier
detection with nothing to download. Every manifest names its installer tier;
the loader refuses one that does not, so a wrong file fails here instead of
shipping, and every one names where its software comes from, which is the
line each surface draws under the title.
"""

import json

import pytest

from neutrino_hub.modules.cliproxyapi.constants import CLIPROXYAPI_SWITCHER_NAME
from neutrino_hub.modules.devices.catalog import resolve_module
from neutrino_hub.modules.devices import manifests as manifests_module
from neutrino_hub.modules.devices.manifests import load_module_manifests

# The fields that mean the hub downloads something. A user-tier manifest
# carrying any of them is one the hub would fetch for after all.
DOWNLOAD_FIELDS = ("url", "github_repo", "asset_pattern", "download")


def write_manifest(directory, name: str, manifest: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{name}.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_cc_switch_is_a_shipped_module_not_an_injection():
    manifests = load_module_manifests()

    manifest = manifests[CLIPROXYAPI_SWITCHER_NAME]
    assert manifest["title"] == "cc-switch"
    assert manifest["kind"] == "switcher"
    for key in ("linux-amd64", "linux-arm64", "darwin", "windows-amd64"):
        assert manifest["platforms"][key]["github_repo"]


def test_samba_mount_resolves_per_platform():
    manifest = load_module_manifests()["samba_mount"]
    assert manifest["title"] == "Samba mount"
    assert manifest["kind"] == "system_package"

    debian = resolve_module(
        manifest, {"os": "linux", "family": "debian", "arch": "amd64"}
    )
    assert debian["entry"] == {"packages": ["cifs-utils"]}
    rhel = resolve_module(manifest, {"os": "linux", "family": "rhel", "arch": "amd64"})
    assert rhel["entry"] == {"packages": ["cifs-utils"]}
    # Windows and macOS speak SMB natively: an empty entry, nothing to do.
    for os_name in ("windows", "darwin"):
        native = resolve_module(
            manifest, {"os": os_name, "family": "", "arch": "arm64"}
        )
        assert native["entry"] == {}


def test_the_ssh_server_wears_its_plain_title():
    assert load_module_manifests()["ssh_server"]["title"] == "SSH server"


def test_every_shipped_manifest_names_its_installer_tier():
    tiers = {
        name: manifest["installer"]
        for name, manifest in load_module_manifests().items()
    }

    assert tiers == {
        "ssh_server": "platform",
        "samba_mount": "platform",
        "cc_switch": "hub",
        "rustdesk": "hub",
        "anydesk": "user",
        "teamviewer": "user",
    }


def test_todesk_is_not_shipped_any_more():
    assert "todesk" not in load_module_manifests()


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
    # reads absent software as installed. A windows verify built on it must
    # turn the result into a nonzero exit.
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
        # A non-empty entry: supported, and never worded built in.
        assert resolved["entry"] not in (None, {})


def test_the_resolved_module_carries_the_installer_tier():
    manifest = load_module_manifests()["cc_switch"]

    resolved = resolve_module(
        manifest, {"os": "linux", "family": "debian", "arch": "amd64"}
    )

    assert resolved["installer"] == "hub"


def test_every_shipped_manifest_says_where_its_software_comes_from():
    """The line under a row's title: a repository for what the hub fetches, a
    company for what a person installs, and the machine's own packages for
    what the platform carries."""
    sources = {
        name: manifest["source"] for name, manifest in load_module_manifests().items()
    }

    assert sources == {
        "ssh_server": "system",
        "samba_mount": "system",
        "cc_switch": "SaladDay/cc-switch-cli",
        "rustdesk": "rustdesk/rustdesk",
        "anydesk": "AnyDesk Software GmbH",
        "teamviewer": "TeamViewer Germany GmbH",
    }


def test_every_module_the_hub_conveys_names_its_license_and_source():
    """Hub-tier means this hub fetches the bytes and hands them on, which is
    what obliges the license and the directions to the source. A tier that
    downloads nothing owes neither."""
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


def test_the_manifests_come_back_in_the_order_both_surfaces_draw():
    """One order, decided here, so the panel and the agent's page cannot
    disagree: what the machine carries, then what this hub fetches, then what
    a person installs themselves — and by title inside each tier."""
    assert list(load_module_manifests()) == [
        "samba_mount",
        "ssh_server",
        "cc_switch",
        "rustdesk",
        "anydesk",
        "teamviewer",
    ]
