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

# The fields that mean the module's installer fetches something. A
# user-tier manifest carrying any of them is one fetched for after all.
DOWNLOAD_FIELDS = ("url", "github_repo", "asset_pattern", "download")

GITEA_VERSION = "1.27.3"
# The checksums dl.gitea.com publishes beside each release binary, in its
# own .sha256 files. Each is a published checksum of a public download.
# Each platform key to the asset's name after the version, and its digest.
GITEA_DIGESTS = {
    "linux-amd64": (
        "linux-amd64",
        "4da93c2c10b6980c359bcb86d5573ebfd7770e2e151756534edee24c8c12d971",  # scan: allow
    ),
    "linux-arm64": (
        "linux-arm64",
        "04c086d36dba793546e331484a9da34571763efdfa77dc526cc98e0f10917e7b",  # scan: allow
    ),
    "darwin-amd64": (
        "darwin-10.12-amd64",
        "23964155add4490ed73733fa90ea63154b724ab6fe389b7a979db4ef3d7ed8ce",  # scan: allow
    ),
    "darwin-arm64": (
        "darwin-10.12-arm64",
        "fd83383e05a4185e8f852563a7599f5d8f3e18ede00d412c0f9f044771aef162",  # scan: allow
    ),
    "windows-amd64": (
        "windows-4.0-amd64.exe",
        "d9ed1fc48ec33a8cb97d7fed3882b4e159efc3fcae3a77d0d240e250d5bf6e21",  # scan: allow
    ),
}

VSCODE_VERSION = "1.140.0"
VSCODE_COMMIT = "07f806f999227108933c2e30515b26eecc1fda74"  # scan: allow
# What update.code.visualstudio.com answered for each CLI build of that
# commit: the platform key, Microsoft's build name, the archive, its sha256.
VSCODE_DIGEST_ALPINE_X64 = (
    "938b4f5b4690102e0b5b805af6df42fe7f91e043608ceefd5786ed01e4a6fcd1"  # scan: allow
)
VSCODE_DIGEST_ALPINE_ARM64 = (
    "6205d8b4787ea0a4e7f7e7f152b456db2fef5fcfd0bff3f130150ebf2886bc86"  # scan: allow
)
VSCODE_DIGEST_WIN32_X64 = (
    "ae2eb828dc2874a43e2ee840d036d2b415cebed29d22417042da145c4bdc6efe"  # scan: allow
)
VSCODE_DIGEST_DARWIN_ARM64 = (
    "352754c307ff1edb03ea01f55388e17b7e4e5bb1485aa62bcd2663b42ce5420c"  # scan: allow
)
VSCODE_DIGEST_DARWIN_X64 = (
    "ef91848ae48438f6589ad013a2ef795e5bd61568f1026042a4bdab934e6bedd4"  # scan: allow
)
VSCODE_BUILDS = {
    "linux-amd64": ("cli_alpine_x64", "tar.gz", VSCODE_DIGEST_ALPINE_X64),
    "linux-arm64": ("cli_alpine_arm64", "tar.gz", VSCODE_DIGEST_ALPINE_ARM64),
    "windows-amd64": ("cli_win32_x64", "zip", VSCODE_DIGEST_WIN32_X64),
    "darwin-arm64": ("cli_darwin_arm64", "zip", VSCODE_DIGEST_DARWIN_ARM64),
    "darwin-amd64": ("cli_darwin_x64", "zip", VSCODE_DIGEST_DARWIN_X64),
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
        "vscode": "hub",
        "code_server": "hub",
        "cloudcli": "hub",
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
        "vscode": "Microsoft",
        "code_server": "Coder",
        "cloudcli": "nodejs.org",
        "anydesk": "AnyDesk Software GmbH",
        "teamviewer": "TeamViewer Germany GmbH",
    }


def test_the_manifests_come_back_in_the_order_both_surfaces_draw():
    """What the machine carries, then what the module's installer fetches,
    then what a person installs themselves, and by title inside each tier."""
    assert list(load_module_manifests()) == [
        "podman",
        "samba",
        "zfs",
        "cloudcli",
        "code_server",
        "gitea",
        "vscode",
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
    assert set(manifest["platforms"]) == set(GITEA_DIGESTS)
    for key, (asset, digest) in GITEA_DIGESTS.items():
        entry = manifest["platforms"][key]
        assert entry["url"] == (
            f"https://dl.gitea.com/gitea/{GITEA_VERSION}/gitea-{GITEA_VERSION}-{asset}"
        )
        assert entry["sha256"] == digest
        assert entry["package_kind"] == "binary"
        assert "cn_url" not in entry
        assert entry["packages"] == (["git"] if key.startswith("linux") else [])
    assert "gitea\\gitea.exe" in manifest["platforms"]["windows-amd64"]["verify"]
    assert manifest["platforms"]["darwin-arm64"]["verify"] == (
        '"/Library/Application Support/Neutrino/agent/state/gitea/gitea" --version'
    )


def test_gitea_resolves_by_machine_and_refuses_the_rest():
    manifest = load_module_manifests()["gitea"]

    assert resolve_platform_entry(manifest, DEBIAN)[0] == "linux-amd64"
    assert resolve_platform_entry(manifest, {**RHEL, "arch": "arm64"})[0] == (
        "linux-arm64"
    )
    assert resolve_platform_entry(manifest, {**DEBIAN, "arch": "armhf"}) == ("", None)
    windows = {"os": "windows", "family": "", "arch": "amd64", "version": "17763"}
    assert resolve_platform_entry(manifest, windows)[0] == "windows-amd64"
    assert resolve_platform_entry(manifest, {**windows, "arch": "arm64"}) == ("", None)
    for arch in ("arm64", "amd64"):
        mac = {"os": "darwin", "family": "", "arch": arch, "version": "12.3"}
        assert resolve_platform_entry(manifest, mac)[0] == f"darwin-{arch}"


def test_a_binary_package_is_recognised_by_its_elf_mach_o_or_pe_magic():
    assert looks_like_package(b"\x7fELF\x02\x01\x01", "binary")
    assert looks_like_package(b"\xcf\xfa\xed\xfe\x0c\x00\x00\x01", "binary")
    assert looks_like_package(b"MZ\x90\x00", "binary")
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


def test_every_branch_the_hub_installs_from_says_how_to_verify_and_uninstall():
    """What the agent is sent for a module: the command whose exit says the
    software is there, and the block an uninstall runs by; a builtin branch
    installs nothing and the agent's runner checks for it itself."""
    for name, manifest in load_module_manifests().items():
        for key, entry in manifest["platforms"].items():
            if entry == {} or entry.get("installer") == "builtin":
                continue
            assert entry["verify"], (name, key)
            if manifest["installer"] == "user":
                continue
            removal = entry["uninstall"]
            assert isinstance(removal["packages"], list), (name, key)
            assert isinstance(removal["post_uninstall"], list), (name, key)
            assert isinstance(removal["is_data_kept"], bool), (name, key)


def test_a_windows_verify_that_runs_a_file_tests_the_path_first():
    """PowerShell's ``&`` on a missing file is a non-terminating error that
    leaves ``$LASTEXITCODE`` unset, so ``exit $LASTEXITCODE`` says installed;
    the path has to be tested before the program is run."""
    for name, manifest in load_module_manifests().items():
        for key, entry in manifest.get("platforms", {}).items():
            verify = str(entry.get("verify", "") or "")
            if key.startswith("windows") and "& " in verify:
                assert "Test-Path" in verify, (name, key)


def test_the_loader_refuses_a_branch_without_a_verify_command(tmp_path, monkeypatch):
    monkeypatch.setattr(manifests_module, "MANIFESTS_DIR", tmp_path)
    write_manifest(
        tmp_path,
        "sample",
        {
            "name": "sample",
            "installer": "platform",
            "source": "system",
            "platforms": {"linux-debian": {"packages": ["sample"]}},
        },
    )

    with pytest.raises(ValueError) as refusal:
        load_module_manifests()

    assert "verify" in str(refusal.value)


def test_the_loader_refuses_a_hub_installed_branch_without_an_uninstall_block(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(manifests_module, "MANIFESTS_DIR", tmp_path)
    write_manifest(
        tmp_path,
        "sample",
        {
            "name": "sample",
            "installer": "platform",
            "source": "system",
            "platforms": {
                "linux-debian": {
                    "packages": ["sample"],
                    "verify": "sample --version",
                    "uninstall": {"packages": ["sample"]},
                }
            },
        },
    )

    with pytest.raises(ValueError) as refusal:
        load_module_manifests()

    assert "uninstall" in str(refusal.value)


def test_a_user_tier_branch_needs_only_its_verify(tmp_path, monkeypatch):
    """Nobody but the person installs or removes these; the hub only looks."""
    monkeypatch.setattr(manifests_module, "MANIFESTS_DIR", tmp_path)
    write_manifest(
        tmp_path,
        "sample",
        {
            "name": "sample",
            "installer": "user",
            "source": "vendor",
            "platforms": {"linux": {"verify": "which sample"}, "windows": {}},
        },
    )

    assert "sample" in load_module_manifests()


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


def test_every_hub_tier_module_names_its_license_and_source():
    """A hub-tier module's installer fetches its bytes from a public release,
    and its manifest names their license and where their source is."""
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


@pytest.mark.parametrize("floor", ["2.28", "17763", "12.3.1"])
def test_the_loader_accepts_a_dotted_floor(floor, tmp_path, monkeypatch):
    monkeypatch.setattr(manifests_module, "MANIFESTS_DIR", tmp_path)
    write_manifest(
        tmp_path,
        "sample",
        {
            "name": "sample",
            "installer": "user",
            "source": "vendor",
            "platforms": {"linux": {"verify": "which s", "min_version": floor}},
        },
    )

    assert "sample" in load_module_manifests()


@pytest.mark.parametrize("floor", ["", "2.x", "v2.28", 2.28])
def test_the_loader_refuses_a_floor_that_is_not_a_dotted_number(
    floor, tmp_path, monkeypatch
):
    monkeypatch.setattr(manifests_module, "MANIFESTS_DIR", tmp_path)
    write_manifest(
        tmp_path,
        "sample",
        {
            "name": "sample",
            "installer": "user",
            "source": "vendor",
            "platforms": {"linux": {"verify": "which s", "min_version": floor}},
        },
    )

    with pytest.raises(ValueError) as refusal:
        load_module_manifests()

    assert "min_version" in str(refusal.value)


@pytest.mark.parametrize(
    "platform",
    [
        {"os": "windows", "family": "", "arch": "amd64", "version": "19045"},
        {"os": "darwin", "family": "", "arch": "arm64", "version": "15.3.1"},
    ],
)
def test_samba_is_the_system_s_own_server_on_windows_and_macos(platform):
    key, entry = resolve_platform_entry(load_module_manifests()["samba"], platform)

    assert key == platform["os"]
    assert entry == {"installer": "builtin"}


def test_a_builtin_branch_needs_no_verify_and_no_uninstall(tmp_path, monkeypatch):
    monkeypatch.setattr(manifests_module, "MANIFESTS_DIR", tmp_path)
    write_manifest(
        tmp_path,
        "sample",
        {
            "name": "sample",
            "installer": "platform",
            "source": "system",
            "platforms": {"windows": {"installer": "builtin"}},
        },
    )

    assert "sample" in load_module_manifests()


@pytest.mark.parametrize(
    "branch",
    [
        {"installer": "builtin", "url": "https://vendor.example/s.msi"},
        {"installer": "builtin", "packages": ["samba"]},
        {"installer": "vendor", "verify": "where s"},
    ],
)
def test_the_loader_refuses_a_branch_installer_that_is_not_a_bare_builtin(
    branch, tmp_path, monkeypatch
):
    monkeypatch.setattr(manifests_module, "MANIFESTS_DIR", tmp_path)
    write_manifest(
        tmp_path,
        "sample",
        {
            "name": "sample",
            "installer": "platform",
            "source": "system",
            "platforms": {"windows": branch},
        },
    )

    with pytest.raises(ValueError) as refusal:
        load_module_manifests()

    assert "installer" in str(refusal.value) or "builtin" in str(refusal.value)


NODE_VERSION = "22.23.3"
NODE_BUILDS = {
    "linux-amd64": (
        "linux-x64.tar.gz",
        "1084aa36196bba4c3a5e69a1ee388a6e4ff729dad09445fbcd434b28fe3c24af",  # scan: allow
    ),
    "linux-arm64": (
        "linux-arm64.tar.gz",
        "5ced2d48d1d7198739b7f86804de0171aefb6823b684b12341d3321afc3cb0b2",  # scan: allow
    ),
    "windows-amd64": (
        "win-x64.zip",
        "2b0ff57b049cda1bbcea2240eec20467018713c1efe1f7360c2681859b90ed71",  # scan: allow
    ),
    "windows-arm64": (
        "win-arm64.zip",
        "33dad22e4cef5ee8f9fbb1b0d037fdacd0e56d12a4580f0d63f68b894deab535",  # scan: allow
    ),
    "darwin-amd64": (
        "darwin-x64.tar.gz",
        "8a677b0219178efd6eb0e475457c4afb452b521a92f6e67845a73bd85727f2a8",  # scan: allow
    ),
    "darwin-arm64": (
        "darwin-arm64.tar.gz",
        "23b25245dcfb9af7262f8ff142e9e2e0af025368117329e7a7458a51e5922f53",  # scan: allow
    ),
}


def test_cloudcli_pins_one_node_release_per_platform():
    manifest = load_module_manifests()["cloudcli"]

    assert manifest["version"] == "1.37.3"
    assert manifest["license"] == "AGPL-3.0"
    assert manifest["corresponding_source"] == (
        "https://github.com/siteboon/claudecodeui/tree/v1.37.3"
    )
    assert set(manifest["platforms"]) == set(NODE_BUILDS)
    for key, (build, digest) in NODE_BUILDS.items():
        entry = manifest["platforms"][key]
        assert entry["url"] == (
            f"https://nodejs.org/dist/v{NODE_VERSION}/node-v{NODE_VERSION}-{build}"
        )
        assert entry["sha256"] == digest
        assert entry["package_kind"] == ("zip" if build.endswith(".zip") else "tar")
        assert f"node-v{NODE_VERSION}-{build.split('.')[0]}" in entry["verify"]
        assert entry.get("min_version", "") == (
            "2.28" if key.startswith("linux") else ""
        )


def test_vscode_pins_microsofts_cli_per_platform_at_one_build():
    manifest = load_module_manifests()["vscode"]

    assert manifest["version"] == VSCODE_VERSION
    assert manifest["corresponding_source"].endswith(f"/{VSCODE_COMMIT}/cli")
    assert set(manifest["platforms"]) == set(VSCODE_BUILDS)
    for key, (build, archive, digest) in VSCODE_BUILDS.items():
        entry = manifest["platforms"][key]
        assert entry["url"] == (
            "https://vscode.download.prss.microsoft.com/dbazure/download/stable/"
            f"{VSCODE_COMMIT}/vscode_{build}_cli.{archive}"
        )
        assert entry["sha256"] == digest
        assert entry["package_kind"] == ("tar" if archive == "tar.gz" else "zip")


def test_vscode_needs_glibc_2_28_on_linux_and_nothing_elsewhere():
    manifest = load_module_manifests()["vscode"]
    old = {**DEBIAN, "version": "2.27"}
    new = {**RHEL, "arch": "arm64", "version": "2.28"}
    windows = {"os": "windows", "family": "", "arch": "amd64", "version": "17763"}

    assert resolve_platform_entry(manifest, old) == ("", None)
    assert resolve_platform_entry(manifest, new)[0] == "linux-arm64"
    assert resolve_platform_entry(manifest, windows)[0] == "windows-amd64"


@pytest.mark.parametrize(
    "key, path",
    [
        ("linux-amd64", "/var/lib/neutrino/agent/vscode/code"),
        ("windows-amd64", "Neutrino\\agent\\state\\vscode\\code.exe"),
        (
            "darwin-arm64",
            "/Library/Application Support/Neutrino/agent/state/vscode/code",
        ),
    ],
)
def test_vscode_verifies_the_cli_where_the_agent_unpacks_it(key, path):
    verify = load_module_manifests()["vscode"]["platforms"][key]["verify"]

    assert path in verify
    assert "--version" in verify


CODE_SERVER_VERSION = "4.140.0"
# The sha256 of each of the publisher's release archives, computed here from
# the files the release serves, since the publisher ships no checksum file.
CODE_SERVER_BUILDS = {
    "linux-amd64": (
        "linux-amd64",
        "864c5d01c808ade57e4d12c708717be7a187219fded60428f263b9e2da9f6b48",  # scan: allow
    ),
    "linux-arm64": (
        "linux-arm64",
        "ae4b07153f2037b06d24749bc8004221fcbf3ffe317038401be0452f541bf200",  # scan: allow
    ),
    "darwin-amd64": (
        "macos-amd64",
        "a5393b6eed4aa68b084e724c3c565f805abd996c609356043119f0323e40cf52",  # scan: allow
    ),
    "darwin-arm64": (
        "macos-arm64",
        "82c7144406ac31c373acfa786b6705c7c5463d895f728fde2cb94402b945b301",  # scan: allow
    ),
}
CODE_SERVER_RELEASES = "https://github.com/coder/code-server/releases/download/"
CODE_SERVER_MIRROR = "https://mirrors.ustc.edu.cn/github-release/coder/code-server/"


def test_code_server_pins_coders_release_per_platform_with_its_mirror():
    manifest = load_module_manifests()["code_server"]

    assert manifest["version"] == CODE_SERVER_VERSION
    assert manifest["license"] == "MIT"
    assert manifest["kind"] == "code_server"
    assert set(manifest["platforms"]) == set(CODE_SERVER_BUILDS)
    for key, (build, digest) in CODE_SERVER_BUILDS.items():
        entry = manifest["platforms"][key]
        name = f"code-server-{CODE_SERVER_VERSION}-{build}.tar.gz"
        assert entry["url"] == f"{CODE_SERVER_RELEASES}v{CODE_SERVER_VERSION}/{name}"
        assert entry["cn_url"] == f"{CODE_SERVER_MIRROR}v{CODE_SERVER_VERSION}/{name}"
        assert entry["cn_latest_url"] == f"{CODE_SERVER_MIRROR}LatestRelease/"
        assert entry["sha256"] == digest
        assert entry["package_kind"] == "tar"
        assert "code_server/release/lib/node" in entry["verify"]
        assert entry.get("min_version", "") == (
            "2.28" if key.startswith("linux") else ""
        )


NODE_MIRROR = "https://registry.npmmirror.com/-/binary/node/"


def test_cloudclis_node_names_the_same_file_on_npmmirror():
    """A mainland hub fetches Node.js from npmmirror, which keeps every
    release, so one pin checks both addresses."""
    manifest = load_module_manifests()["cloudcli"]

    for key, entry in manifest["platforms"].items():
        path = entry["url"].split("/dist/", 1)[1]
        assert entry["cn_url"] == f"{NODE_MIRROR}{path}", key
        assert "cn_latest_url" not in entry


def test_code_server_has_no_windows_branch_and_needs_glibc_2_28():
    manifest = load_module_manifests()["code_server"]
    windows = {"os": "windows", "family": "", "arch": "amd64", "version": "17763"}
    old = {**DEBIAN, "version": "2.27"}

    assert resolve_platform_entry(manifest, windows) == ("", None)
    assert resolve_platform_entry(manifest, old) == ("", None)
    assert resolve_platform_entry(manifest, {**DEBIAN, "version": "2.36"})[0] == (
        "linux-amd64"
    )


def test_an_archive_package_is_recognised_by_its_compressor():
    assert looks_like_package(b"\x1f\x8b\x08", "tar")
    assert looks_like_package(b"PK\x03\x04", "zip")
    assert not looks_like_package(b"<!doctype html>", "zip")


@pytest.mark.parametrize(
    ("edition", "registry"),
    [("intl", "https://registry.npmjs.org"), ("cn", "https://registry.npmmirror.com")],
)
def test_cloudclis_state_names_the_npm_registry_of_the_hubs_edition(edition, registry):
    from neutrino_hub.modules.devices.desired_state import cloudcli_agent_config

    sent = cloudcli_agent_config({}, {}, edition=edition)

    assert sent["npm_registry"] == registry


@pytest.mark.parametrize(
    ("edition", "environment"),
    [
        ("intl", {}),
        (
            "cn",
            {
                "npm_config_better_sqlite3_binary_host": (
                    "https://registry.npmmirror.com/-/binary/better-sqlite3"
                )
            },
        ),
    ],
)
def test_cloudclis_state_carries_the_npm_environment_the_manifest_names(
    edition, environment
):
    from neutrino_hub.modules.devices.desired_state import cloudcli_agent_config

    sent = cloudcli_agent_config({}, {}, edition=edition)

    assert sent["npm_environment"] == environment
    assert all(name.startswith("npm_config_") for name in environment)


def packaging_constants():
    """The packaging pins, read from their file as the build reads them."""
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[4] / "packaging/shared/constants.py"
    spec = importlib.util.spec_from_file_location("packaging_pins", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# The packaging pin's systems and machines, as the manifest's platform keys.
CC_SWITCH_KEYS = {
    ("linux", "x86_64"): "linux-amd64",
    ("linux", "aarch64"): "linux-arm64",
    ("darwin", "x86_64"): "darwin-amd64",
    ("darwin", "aarch64"): "darwin-arm64",
    ("windows", "x86_64"): "windows-amd64",
}


def test_cc_switch_is_pinned_where_the_client_s_packages_are():
    pins = packaging_constants()
    manifest = manifests_module.load_tool_manifests()["cc_switch"]

    assert manifest["version"] == pins.PACKAGING_CC_SWITCH_VERSION
    assert set(manifest["platforms"]) == {
        CC_SWITCH_KEYS[key] for key in pins.PACKAGING_CC_SWITCH_ASSETS
    }
    for key, (asset, digest) in pins.PACKAGING_CC_SWITCH_ASSETS.items():
        entry = manifest["platforms"][CC_SWITCH_KEYS[key]]
        assert entry["url"] == pins.PACKAGING_CC_SWITCH_URL.format(
            version=pins.PACKAGING_CC_SWITCH_VERSION, asset=asset
        )
        assert entry["sha256"] == digest
        assert entry["package_kind"] == ("zip" if asset.endswith(".zip") else "tar")
        assert entry["cn_url"] == "{release}/" + entry["url"].rsplit("/", 1)[-1]


def test_cc_switch_is_no_module():
    assert "cc_switch" not in load_module_manifests()
    assert list(manifests_module.load_tool_manifests()) == ["cc_switch"]


def test_the_loader_refuses_a_program_branch_that_lacks_a_field(tmp_path, monkeypatch):
    monkeypatch.setattr(manifests_module, "MANIFESTS_DIR", tmp_path)
    (tmp_path / "tool.json").write_text(
        json.dumps(
            {
                "name": "tool",
                "is_module": False,
                "source": "x",
                "version": "1",
                "platforms": {
                    "linux-amd64": {"url": "u", "sha256": "s", "package_kind": "tar"}
                },
            }
        )
    )

    with pytest.raises(ValueError, match="linux-amd64 must name cn_url"):
        manifests_module.load_tool_manifests()
    assert load_module_manifests() == {}
