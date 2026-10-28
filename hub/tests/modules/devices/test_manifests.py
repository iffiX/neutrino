"""The shipped manifests and the loader that refuses any other shape.

What the panel offers, what the catalog resolves, what the cache fetches and
what an agent installs all read these files, so the modules the design names
are pinned here as shipped: the two the agent's own package carries, the
three the system holds or installs, Gitea as a pinned release binary, the
programs run as an account from their pinned archives, and cc-switch beside
them as no module. Every platform entry names a runner and one of the five
install methods with the params its method fixes, and every artifact a kind
and a digest of its kind's form, or the loader refuses the manifest.
"""

import copy
import importlib.util
import json
from pathlib import Path

import pytest

from neutrino_hub.exceptions import AgentArtifactFetchError
from neutrino_hub.modules.devices import manifests as manifests_module
from neutrino_hub.modules.devices.agent_module_cache import AgentModuleCache
from neutrino_hub.modules.devices.catalog import resolve_module
from neutrino_hub.modules.devices.manifests import (
    artifact_file,
    artifact_sources,
    entry_artifacts,
    entry_params,
    entry_version,
    load_module_manifests,
    load_tool_manifests,
    manifest_methods,
    module_recipe,
    platform_keys,
    resolve_platform_entry,
)

GITEA_VERSION = "1.27.3"
# The checksums dl.gitea.com publishes beside each release binary, in its
# own .sha256 files. Each platform key to the file's name after the version,
# and its digest.
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
# commit: the platform key, Microsoft's platform name, the archive's kind,
# its file and its sha256.
VSCODE_BUILDS = {
    "linux-amd64": (
        "cli-alpine-x64",
        "tar_gz",
        "vscode_cli_alpine_x64_cli.tar.gz",
        "938b4f5b4690102e0b5b805af6df42fe7f91e043608ceefd5786ed01e4a6fcd1",  # scan: allow
    ),
    "linux-arm64": (
        "cli-alpine-arm64",
        "tar_gz",
        "vscode_cli_alpine_arm64_cli.tar.gz",
        "6205d8b4787ea0a4e7f7e7f152b456db2fef5fcfd0bff3f130150ebf2886bc86",  # scan: allow
    ),
    "windows-amd64": (
        "cli-win32-x64",
        "zip",
        "vscode_cli_win32_x64_cli.zip",
        "ae2eb828dc2874a43e2ee840d036d2b415cebed29d22417042da145c4bdc6efe",  # scan: allow
    ),
    "darwin-arm64": (
        "cli-darwin-arm64",
        "zip",
        "vscode_cli_darwin_arm64_cli.zip",
        "352754c307ff1edb03ea01f55388e17b7e4e5bb1485aa62bcd2663b42ce5420c",  # scan: allow
    ),
    "darwin-amd64": (
        "cli-darwin-x64",
        "zip",
        "vscode_cli_darwin_x64_cli.zip",
        "ef91848ae48438f6589ad013a2ef795e5bd61568f1026042a4bdab934e6bedd4",  # scan: allow
    ),
}

CODE_SERVER_VERSION = "4.140.0"
# The sha256 of each of the publisher's release archives.
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

NODE_VERSION = "22.23.3"
# What nodejs.org/dist/v22.23.3/SHASUMS256.txt names for each build.
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
NODE_SOURCES = [
    f"https://nodejs.org/dist/v{NODE_VERSION}/{{file}}",
    f"https://registry.npmmirror.com/-/binary/node/v{NODE_VERSION}/{{file}}",
]
CLOUDCLI_VERSION = "1.37.3"
# The integrity registry.npmjs.org gives @cloudcli-ai/cloudcli 1.37.3.
CLOUDCLI_INTEGRITY = "sha512-z9ewBL8imlK2IgfuribkbE2N/7XCV6z6cSevQFxaIAP3UdA3gzSI41MLMb+2RBEyiYgCAU6hPRPN7O1ZyK8RNw=="  # scan: allow

CODEG_VERSION = "0.35.1"
# The sha256 of each server bundle, from the publisher's own .sha256 sidecar.
CODEG_SERVER_BUILDS = {
    "linux-amd64": (
        "linux-x64.tar.gz",
        "40e9d854967f34834ceeb64d4a5b89295e76877e9dbdc81e8b466619fcd84f5f",  # scan: allow
    ),
    "linux-arm64": (
        "linux-arm64.tar.gz",
        "2a97353b919c13ec76212970f50b2184123492ca7b2ce983fe9db0eece7b1ff6",  # scan: allow
    ),
    "darwin-amd64": (
        "darwin-x64.tar.gz",
        "5e1fd9ee3587e6046381da6de70428608987b6a747949996ecb658e755763730",  # scan: allow
    ),
    "darwin-arm64": (
        "darwin-arm64.tar.gz",
        "3d53baa54d4f834be101b6c5216e15001c71263a52efd2cabd4c9bf47ee2dc7c",  # scan: allow
    ),
    "windows-amd64": (
        "windows-x64.zip",
        "6e610a4a8d214bc15951e082dd05765ac51d02fdb5d657de5aa9162b35446262",  # scan: allow
    ),
}

PODMAN_RELEASES = "https://github.com/podman-container-tools/podman/releases/download/"
PODMAN_IMAGES = (
    "https://github.com/podman-container-tools/podman-machine-os/releases/download/"
)
# Each digest is the one the GitHub release API gives the asset; the msi and
# pkg ones are also in the Podman release's own shasums file. Per platform:
# the version, the floor, the verify, and each artifact's name, kind, file,
# digest and its first source filled in.
PODMAN_PINS = {
    "windows-amd64": (
        "6.1.4",
        "19041",
        '"C:\\Program Files\\Podman\\podman.exe" --version',
        [
            (
                "wsl",
                "msi",
                "wsl.3.0.3.0.x64.msi",
                "ae977286974255bd26bf925f00f40f5692c6b2084155cbc0563c09aea091f211",  # scan: allow
                "https://github.com/microsoft/WSL/releases/download/3.0.3/"
                "wsl.3.0.3.0.x64.msi",
            ),
            (
                "podman",
                "msi",
                "podman-installer-windows-amd64.msi",
                "4a05240054cb990629cbe098db090c5c7848c44162c11910cabb45ca75a40d53",  # scan: allow
                f"{PODMAN_RELEASES}v6.1.4/podman-installer-windows-amd64.msi",
            ),
            (
                "image",
                "tar_zst",
                "podman-machine.x86_64.wsl.tar.zst",
                "84c99d407af99d36e18d32327c86f57128d0e76f70c357fc4bc27f307be98738",  # scan: allow
                f"{PODMAN_IMAGES}v6.1.4/podman-machine.x86_64.wsl.tar.zst",
            ),
        ],
    ),
    "darwin-arm64": (
        "6.1.4",
        "13",
        "/opt/podman/bin/podman --version",
        [
            (
                "podman",
                "pkg",
                "podman-installer-macos-arm64.pkg",
                "48f675622f66233ca2116e67fdab41ed9dbcc25b48b78a8e6ef0be6549031d22",  # scan: allow
                f"{PODMAN_RELEASES}v6.1.4/podman-installer-macos-arm64.pkg",
            ),
            (
                "image",
                "raw_zst",
                "podman-machine.aarch64.applehv.raw.zst",
                "d92af11c2980615ad1645fd36999f5abb53e4118a7a19fc981fbaccf57de1737",  # scan: allow
                f"{PODMAN_IMAGES}v6.1.4/podman-machine.aarch64.applehv.raw.zst",
            ),
        ],
    ),
    "darwin-amd64": (
        "5.8.9",
        "13",
        "/opt/podman/bin/podman --version",
        [
            (
                "podman",
                "pkg",
                "podman-installer-macos-amd64.pkg",
                "3d600c6a1efd41445b56ed9864b9daba0765cfeae9d62604e87cf6c01b613403",  # scan: allow
                f"{PODMAN_RELEASES}v5.8.9/podman-installer-macos-amd64.pkg",
            ),
            (
                "image",
                "raw_zst",
                "podman-machine.x86_64.applehv.raw.zst",
                "eac6f4ca8e3b6c1abd6bd6f331f05eecf0779b4d601d13ed9815be521c4715af",  # scan: allow
                f"{PODMAN_IMAGES}v5.8.9/podman-machine.x86_64.applehv.raw.zst",
            ),
        ],
    ),
}

DEBIAN = {"os": "linux", "family": "debian", "arch": "amd64"}
RHEL = {"os": "linux", "family": "rhel", "arch": "amd64"}
WINDOWS = {"os": "windows", "family": "", "arch": "amd64", "version": "26100"}
MAC = {"os": "darwin", "family": "", "arch": "arm64", "version": "15.3.1"}
# Two release sites as a build stamps them.
SITES = (
    {
        "files": "https://releases.example/a/download/{tag}/",
        "latest": "https://releases.example/a/latest.json",
    },
    {
        "files": "https://releases.example/b/download/{tag}/",
        "latest": "https://releases.example/b/latest.json",
    },
)


def write_manifest(directory, name: str, manifest: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{name}.json").write_text(json.dumps(manifest), encoding="utf-8")


@pytest.fixture
def manifests_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(manifests_module, "MANIFESTS_DIR", tmp_path)
    return tmp_path


def sample_artifact(**overrides) -> dict:
    artifact = {
        "name": "server",
        "kind": "tar_gz",
        "directory": "server",
        "file": "server-{version}.tar.gz",
        "digest": "sha256:" + "a" * 64,
        "sources": ["https://vendor.example/v{version}/{file}"],
    }
    artifact.update(overrides)
    return artifact


def sample_manifest() -> dict:
    """One valid module manifest: a system entry on Debian, a hub entry on amd64."""
    return {
        "name": "sample",
        "title": "Sample",
        "description": "A sample module",
        "publisher": "vendor/sample",
        "license": "MIT",
        "corresponding_source": "https://vendor.example/tree/v{version}",
        "uninstall_data": {
            "is_deleted": False,
            "text": {"en": "Data stays.", "zh-CN": "数据留下。"},
        },
        "platforms": {
            "linux-debian": {
                "runner": "sample",
                "install": {
                    "method": "system",
                    "params": {
                        "version": "system",
                        "packages": ["sample"],
                        "verify": "sample --version",
                        "uninstall": {"packages": ["sample"], "post_uninstall": []},
                    },
                },
            },
            "windows-amd64": {
                "runner": "sample_machine",
                "min_version": "19041",
                "install": {
                    "method": "hub",
                    "params": {
                        "version": "2.0",
                        "releases": [
                            {
                                "kind": "github",
                                "sources": ["https://api.example"],
                                "repository": "vendor/sample",
                                "tag": "v{version}",
                            }
                        ],
                        "artifacts": [
                            sample_artifact(),
                            sample_artifact(
                                name="cli",
                                kind="npm",
                                package="@vendor/cli",
                                digest="sha512-" + "b" * 86 + "==",
                                source_set="npm",
                                sources=None,
                                hosts={
                                    "npm_config_cli_binary_host": ["https://h.example"]
                                },
                                directory=None,
                                file=None,
                            ),
                        ],
                        "verify": "sample --version",
                        "uninstall": {"post_uninstall": [], "is_data_kept": True},
                    },
                },
            },
        },
    }


def _without_nones(value):
    if isinstance(value, dict):
        return {
            key: _without_nones(item) for key, item in value.items() if item is not None
        }
    if isinstance(value, list):
        return [_without_nones(item) for item in value]
    return value


def valid_manifest() -> dict:
    return _without_nones(sample_manifest())


def hub_params(manifest: dict) -> dict:
    return manifest["platforms"]["windows-amd64"]["install"]["params"]


def system_params(manifest: dict) -> dict:
    return manifest["platforms"]["linux-debian"]["install"]["params"]


def packaging_constants():
    """The packaging pins, read from their file as the build reads them."""
    path = Path(__file__).resolve().parents[4] / "packaging/shared/constants.py"
    spec = importlib.util.spec_from_file_location("packaging_pins", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- the shipped manifests ---


def test_the_manifests_come_back_in_the_order_both_surfaces_draw():
    """What the agent carries, then what the system holds or installs, then
    what the module's installer fetches, then container images, and by title
    inside each."""
    assert list(load_module_manifests()) == [
        "remote_desktop",
        "ssh_server",
        "terminal",
        "podman",
        "samba",
        "cloudcli",
        "code_server",
        "codeg",
        "gitea",
        "siyuan",
        "vscode",
        "hermes_webui",
    ]


def test_every_shipped_entry_names_its_runner_and_method():
    shipped = {
        name: {
            key: (entry["runner"], entry["install"]["method"])
            for key, entry in manifest["platforms"].items()
        }
        for name, manifest in load_module_manifests().items()
    }

    agent = {key: None for key in ("linux", "windows", "darwin")}
    assert shipped["terminal"] == {key: ("terminal", "agent") for key in agent}
    assert shipped["remote_desktop"] == {
        key: ("remote_desktop", "agent") for key in agent
    }
    families = ("linux-debian", "linux-rhel", "linux-arch")
    assert shipped["samba"] == {
        **{key: ("samba", "system") for key in families},
        "windows": ("samba_native", "builtin"),
        "darwin": ("samba_native", "builtin"),
    }
    assert shipped["podman"] == {
        **{key: ("podman", "system") for key in families},
        **{key: ("podman_machine", "hub") for key in PODMAN_PINS},
    }
    for name, keys in (
        ("gitea", GITEA_DIGESTS),
        ("vscode", VSCODE_BUILDS),
        ("code_server", CODE_SERVER_BUILDS),
        ("cloudcli", NODE_BUILDS),
        ("codeg", CODEG_SERVER_BUILDS),
    ):
        assert shipped[name] == {key: (name, "hub") for key in keys}, name


def test_every_shipped_manifest_names_its_publisher():
    publishers = {
        name: manifest["publisher"]
        for name, manifest in load_module_manifests().items()
    }

    assert publishers == {
        "remote_desktop": "Neutrino",
        "ssh_server": "Neutrino",
        "terminal": "Neutrino",
        "podman": "podman-container-tools/podman",
        "samba": "Samba Team",
        "gitea": "go-gitea/gitea",
        "vscode": "Microsoft",
        "code_server": "coder/code-server",
        "cloudcli": "siteboon/claudecodeui",
        "codeg": "spacering-net/codeg",
        "siyuan": "siyuan-note/siyuan",
        "hermes_webui": "nesquena/hermes-webui and NousResearch/hermes-agent",
    }


@pytest.mark.parametrize(
    "name",
    ["samba_mount", "cc_switch", "rustdesk"],
)
def test_the_modules_that_left_are_not_shipped_any_more(name):
    assert name not in load_module_manifests()


@pytest.mark.parametrize(
    "name, debian, rhel",
    [
        ("samba", ["samba"], ["samba", "samba-client"]),
    ],
)
def test_a_system_module_names_its_packages_per_family(name, debian, rhel):
    manifest = load_module_manifests()[name]

    for platform, packages in ((DEBIAN, debian), (RHEL, rhel)):
        params = resolve_module(manifest, platform)["recipe"]["params"]
        assert params["version"] == "system"
        assert params["packages"] == packages
        assert params["uninstall"] == {"packages": packages, "post_uninstall": []}


def test_containers_on_linux_names_podman_and_runc_and_keeps_runc():
    """podman-docker adds a docker command and conflicts with Docker CE. Every
    unit runs runc, since Ubuntu 22.04's crun 0.17 answers EPERM to
    fchmodat2; an uninstall keeps runc, which another program can run on."""
    manifest = load_module_manifests()["podman"]

    for key in ("linux-debian", "linux-rhel", "linux-arch"):
        assert entry_params(manifest["platforms"][key]) == {
            "version": "system",
            "packages": ["podman", "runc"],
            "verify": "podman --version && runc --version",
            "uninstall": {"packages": ["podman"], "post_uninstall": []},
        }, key
    shipped = json.dumps(load_module_manifests())
    assert "podman-docker" not in shipped


@pytest.mark.parametrize("platform", [WINDOWS, MAC])
def test_samba_is_the_system_s_own_server_on_windows_and_macos(platform):
    key, entry = resolve_platform_entry(load_module_manifests()["samba"], platform)

    assert key == platform["os"]
    assert entry == {
        "runner": "samba_native",
        "install": {"method": "builtin", "params": {}},
    }


def test_terminal_and_remote_desktop_are_the_agent_s_on_every_system():
    for name in ("terminal", "remote_desktop"):
        manifest = load_module_manifests()[name]
        for platform in (DEBIAN, WINDOWS, MAC):
            assert resolve_module(manifest, platform)["recipe"] == {
                "runner": name,
                "method": "agent",
                "params": {},
            }, (name, platform)


def test_gitea_pins_the_release_binary_and_its_published_digest_per_machine():
    manifest = load_module_manifests()["gitea"]

    assert manifest["license"] == "MIT"
    assert manifest["corresponding_source"] == (
        "https://github.com/go-gitea/gitea/tree/v{version}"
    )
    assert manifest["is_data_forward_only"] is True
    assert set(manifest["platforms"]) == set(GITEA_DIGESTS)
    for key, (asset, digest) in GITEA_DIGESTS.items():
        entry = manifest["platforms"][key]
        params = entry_params(entry)
        assert params["version"] == GITEA_VERSION
        assert params["releases"] == [
            {
                "kind": "github",
                "sources": ["https://api.github.com"],
                "repository": "go-gitea/gitea",
                "tag": "v{version}",
            }
        ]
        (artifact,) = entry_artifacts(manifest, entry)
        assert artifact["kind"] == "binary" and "directory" not in artifact
        assert artifact["digest"] == f"sha256:{digest}"
        file = f"gitea-{GITEA_VERSION}-{asset}"
        assert artifact_file(artifact, GITEA_VERSION) == file
        assert artifact_sources(artifact, GITEA_VERSION) == [
            f"https://dl.gitea.com/gitea/{GITEA_VERSION}/{file}",
            f"https://github.com/go-gitea/gitea/releases/download/v{GITEA_VERSION}/{file}",
        ]
        assert params.get("packages", []) == (
            ["git"] if key.startswith("linux") else []
        )
        assert params["uninstall"] == {"post_uninstall": [], "is_data_kept": True}
    assert entry_params(manifest["platforms"]["linux-amd64"])["verify"] == (
        "/usr/local/bin/gitea --version"
    )
    assert entry_params(manifest["platforms"]["darwin-arm64"])["verify"] == (
        '"/Library/Application Support/Neutrino/agent/state/gitea/gitea" --version'
    )


def test_gitea_resolves_by_machine_and_refuses_the_rest():
    manifest = load_module_manifests()["gitea"]

    assert resolve_platform_entry(manifest, DEBIAN)[0] == "linux-amd64"
    assert resolve_platform_entry(manifest, {**RHEL, "arch": "arm64"})[0] == (
        "linux-arm64"
    )
    assert resolve_platform_entry(manifest, {**DEBIAN, "arch": "armhf"}) == ("", None)
    assert resolve_platform_entry(manifest, WINDOWS)[0] == "windows-amd64"
    assert resolve_platform_entry(manifest, {**WINDOWS, "arch": "arm64"}) == ("", None)
    for arch in ("arm64", "amd64"):
        assert resolve_platform_entry(manifest, {**MAC, "arch": arch})[0] == (
            f"darwin-{arch}"
        )


@pytest.mark.parametrize(
    ("name", "program"),
    [
        ("cloudcli", "cloudcli\\node\\node.exe"),
        ("codeg", "codeg\\server\\codeg-server.exe"),
        ("siyuan", "siyuan\\app\\resources\\kernel\\SiYuan-Kernel.exe"),
        ("gitea", "gitea\\gitea.exe"),
        ("vscode", "vscode\\code.exe"),
    ],
)
def test_a_windows_verify_runs_the_unpacked_program_through_cmd(name, program):
    """The agent's shell on Windows is cmd.exe: it expands ``%ProgramData%``,
    and a program that is not there exits non-zero."""
    entries = load_module_manifests()[name]["platforms"]
    windows = [key for key in entries if key.startswith("windows")]

    assert windows
    for key in windows:
        assert entry_params(entries[key])["verify"] == (
            f'"%ProgramData%\\Neutrino\\agent\\state\\{program}" --version'
        ), key


def test_no_windows_verify_starts_powershell():
    for name, manifest in load_module_manifests().items():
        for key, entry in manifest["platforms"].items():
            verify = str(entry_params(entry).get("verify", "")).lower()
            if key.startswith("windows"):
                assert "powershell" not in verify, (name, key)


def test_vscode_pins_microsofts_cli_per_platform_at_one_build():
    """Microsoft's address is the one source, and the CLI lands directly in
    the module's own directory, so its artifact names no directory."""
    manifest = load_module_manifests()["vscode"]

    assert manifest["corresponding_source"] == (
        "https://github.com/microsoft/vscode/tree/{version}/cli"
    )
    assert set(manifest["platforms"]) == set(VSCODE_BUILDS)
    for key, (platform_name, kind, file, digest) in VSCODE_BUILDS.items():
        entry = manifest["platforms"][key]
        params = entry_params(entry)
        assert params["version"] == VSCODE_VERSION
        assert params["releases"] == [
            {
                "kind": "vscode_update",
                "sources": ["https://update.code.visualstudio.com"],
                "platform": platform_name,
            }
        ]
        (artifact,) = entry_artifacts(manifest, entry)
        assert (artifact["name"], artifact["kind"]) == ("cli", kind)
        assert "directory" not in artifact
        assert artifact["digest"] == f"sha256:{digest}"
        assert artifact_sources(artifact, VSCODE_VERSION) == [
            "https://vscode.download.prss.microsoft.com/dbazure/download/stable/"
            f"{VSCODE_COMMIT}/{file}"
        ]
        assert "min_version" not in entry


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
    verify = entry_params(load_module_manifests()["vscode"]["platforms"][key])["verify"]

    assert path in verify
    assert "--version" in verify


def test_code_server_pins_coders_release_per_platform_with_its_mirror():
    manifest = load_module_manifests()["code_server"]

    assert manifest["license"] == "MIT"
    assert set(manifest["platforms"]) == set(CODE_SERVER_BUILDS)
    for key, (build, digest) in CODE_SERVER_BUILDS.items():
        entry = manifest["platforms"][key]
        params = entry_params(entry)
        assert params["version"] == CODE_SERVER_VERSION
        (artifact,) = entry_artifacts(manifest, entry)
        assert (artifact["kind"], artifact["directory"]) == ("tar_gz", "release")
        assert artifact["digest"] == f"sha256:{digest}"
        name = f"code-server-{CODE_SERVER_VERSION}-{build}.tar.gz"
        assert artifact_sources(artifact, CODE_SERVER_VERSION) == [
            f"{CODE_SERVER_RELEASES}v{CODE_SERVER_VERSION}/{name}",
            f"{CODE_SERVER_MIRROR}v{CODE_SERVER_VERSION}/{name}",
        ]
        assert "code_server/release/lib/node" in params["verify"]
        assert "min_version" not in entry


def test_code_server_has_no_windows_entry_and_no_glibc_floor():
    manifest = load_module_manifests()["code_server"]

    assert resolve_platform_entry(manifest, WINDOWS) == ("", None)
    assert resolve_platform_entry(manifest, {**DEBIAN, "version": "2.27"})[0] == (
        "linux-amd64"
    )


def test_cloudcli_pins_node_and_its_npm_package_on_six_platforms():
    """Node.js unpacks under ``cloudcli/node`` with nodejs.org and npmmirror
    as its sources; the npm package keeps its registries and the hosts
    better-sqlite3's binary comes from, its digest npm's integrity."""
    manifest = load_module_manifests()["cloudcli"]

    assert manifest["license"] == "AGPL-3.0"
    assert manifest["corresponding_source"] == (
        "https://github.com/siteboon/claudecodeui/tree/v{version}"
    )
    assert set(manifest["platforms"]) == set(NODE_BUILDS)
    for key, (build, digest) in NODE_BUILDS.items():
        entry = manifest["platforms"][key]
        params = entry_params(entry)
        assert params["version"] == CLOUDCLI_VERSION
        assert params["releases"] == [
            {
                "kind": "npm",
                "sources": ["https://registry.npmjs.org"],
                "package": "@cloudcli-ai/cloudcli",
            }
        ]
        node, package = entry_artifacts(manifest, entry)
        assert (node["name"], node["directory"]) == ("node", "node")
        assert node["kind"] == ("zip" if build.endswith(".zip") else "tar_gz")
        assert node["file"] == f"node-v{NODE_VERSION}-{build}"
        assert node["digest"] == f"sha256:{digest}"
        assert node["sources"] == NODE_SOURCES
        assert package == {
            "name": "cloudcli",
            "kind": "npm",
            "package": "@cloudcli-ai/cloudcli",
            "digest": CLOUDCLI_INTEGRITY,
            "source_set": "npm",
            "hosts": {
                "npm_config_better_sqlite3_binary_host": [
                    "https://github.com/WiseLibs/better-sqlite3/releases/download",
                    "https://registry.npmmirror.com/-/binary/better-sqlite3",
                ]
            },
        }
        assert "node-v" not in params["verify"]
        assert "min_version" not in entry
    assert entry_params(manifest["platforms"]["linux-amd64"])["verify"] == (
        "/var/lib/neutrino/agent/cloudcli/node/bin/node --version"
    )
    assert entry_params(manifest["platforms"]["darwin-arm64"])["verify"] == (
        '"/Library/Application Support/Neutrino/agent/state/cloudcli/node/bin/node"'
        " --version"
    )


def test_codeg_pins_the_server_bundle_and_cloudclis_node_per_platform():
    """The server bundle from the publisher's release, its one source, and
    the Node.js build CloudCLI's manifest pins, each under its own
    directory; no Windows arm64, and no glibc floor."""
    manifest = load_module_manifests()["codeg"]
    cloudcli = load_module_manifests()["cloudcli"]

    assert manifest["license"] == "Apache-2.0"
    assert manifest["corresponding_source"] == (
        "https://github.com/spacering-net/codeg/tree/v{version}"
    )
    assert set(manifest["platforms"]) == set(CODEG_SERVER_BUILDS)
    for key, (build, digest) in CODEG_SERVER_BUILDS.items():
        entry = manifest["platforms"][key]
        assert entry_params(entry)["version"] == CODEG_VERSION
        assert "min_version" not in entry
        server, node = entry_artifacts(manifest, entry)
        assert (server["name"], server["directory"]) == ("server", "server")
        assert server["kind"] == ("zip" if build.endswith(".zip") else "tar_gz")
        assert server["digest"] == f"sha256:{digest}"
        assert artifact_sources(server, CODEG_VERSION) == [
            "https://github.com/spacering-net/codeg/releases/download/"
            f"v{CODEG_VERSION}/codeg-server-{build}"
        ]
        cloudcli_node, _ = entry_artifacts(cloudcli, cloudcli["platforms"][key])
        assert node == cloudcli_node
        assert entry_params(entry)["uninstall"] == {
            "post_uninstall": [],
            "is_data_kept": True,
        }
    assert entry_params(manifest["platforms"]["linux-amd64"])["verify"] == (
        "/var/lib/neutrino/agent/codeg/server/codeg-server --version"
    )
    assert resolve_platform_entry(manifest, {**WINDOWS, "arch": "arm64"}) == ("", None)


SIYUAN_VERSION = "3.8.8"
SIYUAN_BUILDS = {
    "linux-amd64": (
        "siyuan-{version}-linux.tar.gz",
        "tar_gz",
        "499516eac85cd711a6b1406f075ffa82d640a6a9a55734bebb0c3d3cb6d95247",  # scan: allow
    ),
    "linux-arm64": (
        "siyuan-{version}-linux-arm64.tar.gz",
        "tar_gz",
        "2ac2bd147429425289810d941e52d787e53fbd58fa46e0e20dffc8c5732720f5",  # scan: allow
    ),
    "darwin-arm64": (
        "siyuan-{version}-mac-arm64.dmg",
        "dmg",
        "835257eeed0e661ef9e6d245a430d1188f897539876b9448aa22b802b501826d",  # scan: allow
    ),
    "darwin-amd64": (
        "siyuan-{version}-mac.dmg",
        "dmg",
        "743b826e5fb319ecabcdd1119d046296ab73ddcc0c700ee30818c010c87a5bce",  # scan: allow
    ),
    "windows-amd64": (
        "siyuan-{version}-win.exe",
        "nsis",
        "dd96a360af003257caa41eaa8332b723bf3bb9bfae0b6a37e4be8b2c16a046d2",  # scan: allow
    ),
}


def test_siyuan_pins_the_publishers_desktop_build_per_platform_from_two_sources():
    """One artifact per platform under app, GitHub's release then the
    publisher's own mirror, each digest GitHub's; the disk image's resources
    copied out; no floor; the notes kept at an uninstall."""
    manifest = load_module_manifests()["siyuan"]

    assert manifest["license"] == "AGPL-3.0"
    assert manifest["corresponding_source"] == (
        "https://github.com/siyuan-note/siyuan/tree/v{version}"
    )
    assert manifest["uninstall_data"] == {
        "is_deleted": False,
        "text": {
            "en": "Each account's notes stay in {data_dir}.",
            "zh-CN": "每个账户的笔记留在 {data_dir}。",
        },
    }
    assert "web_share" not in manifest
    assert set(manifest["platforms"]) == set(SIYUAN_BUILDS)
    for key, (file, kind, digest) in SIYUAN_BUILDS.items():
        entry = manifest["platforms"][key]
        params = entry_params(entry)
        assert params["version"] == SIYUAN_VERSION
        assert params["releases"] == [
            {
                "kind": "github",
                "sources": ["https://api.github.com"],
                "repository": "siyuan-note/siyuan",
                "tag": "v{version}",
            }
        ]
        assert "min_version" not in entry
        (artifact,) = entry_artifacts(manifest, entry)
        assert (artifact["name"], artifact["directory"], artifact["kind"]) == (
            "app",
            "app",
            kind,
        )
        assert artifact.get("member") == (
            "SiYuan.app/Contents/Resources" if kind == "dmg" else None
        )
        assert artifact["digest"] == f"sha256:{digest}"
        name = file.format(version=SIYUAN_VERSION)
        assert artifact_sources(artifact, SIYUAN_VERSION) == [
            f"https://github.com/siyuan-note/siyuan/releases/download/v3.8.8/{name}",
            f"https://release.liuyun.io/siyuan/{name}",
        ]
        assert params["uninstall"] == {"post_uninstall": [], "is_data_kept": True}
    assert entry_params(manifest["platforms"]["linux-amd64"])["verify"] == (
        "/var/lib/neutrino/agent/siyuan/app/resources/kernel/SiYuan-Kernel --version"
    )
    assert entry_params(manifest["platforms"]["darwin-arm64"])["verify"] == (
        '"/Library/Application Support/Neutrino/agent/state/siyuan/app/kernel/'
        'SiYuan-Kernel" --version'
    )
    recipe = module_recipe(manifest["platforms"]["darwin-arm64"])
    assert recipe["params"]["artifacts"][0]["member"] == (
        "SiYuan.app/Contents/Resources"
    )
    assert "sources" not in recipe["params"]["artifacts"][0]


# The line each shipped module's uninstall dialog shows (ui_text.md, "The
# uninstall dialog's words"), and whether it is in the error tone.
SHIPPED_UNINSTALL_LINES = {
    "samba": (
        False,
        "The shared folders and the files in them stay where they are.",
        "共享的文件夹和里面的文件都原样保留。",
    ),
    "podman": (
        False,
        "The declared containers' volumes stay, and on Windows and macOS so does "
        "the Podman machine.",
        "声明的容器的卷都保留，Windows 和 macOS 上的 Podman 虚拟机也保留。",
    ),
    "gitea": (
        False,
        "The repositories, Gitea's accounts and its database stay in its data "
        "directory.",
        "仓库、Gitea 的账户和数据库都留在它的数据目录里。",
    ),
    "vscode": (
        False,
        "Each account's settings and extensions stay in its home folder.",
        "每个账户的设置和扩展都留在它的主目录里。",
    ),
    "code_server": (
        False,
        "Each account's code-server settings and extensions stay in its home folder.",
        "每个账户的 code-server 设置和扩展都留在它的主目录里。",
    ),
    "cloudcli": (
        False,
        "Each account's CloudCLI data stays in {data_dir}.",
        "每个账户的 CloudCLI 数据留在 {data_dir}。",
    ),
    "codeg": (
        False,
        "Each account's Codeg data stays in {data_dir}.",
        "每个账户的 Codeg 数据留在 {data_dir}。",
    ),
    "siyuan": (
        False,
        "Each account's notes stay in {data_dir}.",
        "每个账户的笔记留在 {data_dir}。",
    ),
    "hermes_webui": (
        True,
        "The conversations, settings and workspace files are deleted and cannot be "
        "recovered.",
        "对话、设置和工作区里的文件都会删除，无法恢复。",
    ),
    "ayakaleaf": (
        True,
        "The papers and projects are deleted and cannot be recovered.",
        "论文和项目都会删除，无法恢复。",
    ),
}


def test_every_shipped_module_a_person_can_uninstall_names_its_line():
    """Each manifest with an entry of another method than ``agent`` carries
    the line of ui_text.md; the agent's own modules carry none."""
    manifests = load_module_manifests()

    for name, manifest in manifests.items():
        if manifest_methods(manifest) == ["agent"]:
            assert "uninstall_data" not in manifest, name
            continue
        is_deleted, english, chinese = SHIPPED_UNINSTALL_LINES[name]
        assert manifest["uninstall_data"] == {
            "is_deleted": is_deleted,
            "text": {"en": english, "zh-CN": chinese},
        }, name


def test_every_shipped_uninstall_data_agrees_with_its_entries(manifests_dir):
    manifest = valid_manifest()
    manifest["uninstall_data"] = {
        "is_deleted": False,
        "text": {"en": "Data stays.", "zh-CN": "数据留下。"},
    }
    write_manifest(manifests_dir, "sample", manifest)

    assert load_module_manifests()["sample"]["uninstall_data"]["is_deleted"] is False


def test_containers_pins_podmans_release_per_platform_off_linux():
    manifest = load_module_manifests()["podman"]
    off_linux = {
        key: entry
        for key, entry in manifest["platforms"].items()
        if not key.startswith("linux")
    }

    assert manifest["license"] == "Apache-2.0"
    assert set(off_linux) == set(PODMAN_PINS)
    for key, (version, floor, verify, artifacts) in PODMAN_PINS.items():
        entry = off_linux[key]
        params = entry_params(entry)
        assert entry["min_version"] == floor
        assert params["version"] == version
        assert params["verify"] == verify
        assert params["packages"] == []
        assert params["uninstall"] == {"post_uninstall": [], "is_data_kept": True}
        assert [
            (
                artifact["name"],
                artifact["kind"],
                artifact["file"],
                artifact["digest"],
                artifact_sources(artifact, version)[0],
            )
            for artifact in entry_artifacts(manifest, entry)
        ] == [
            (name, kind, file, f"sha256:{digest}", source)
            for name, kind, file, digest, source in artifacts
        ], key
        assert all(
            artifact["directory"] == artifact["name"]
            for artifact in entry_artifacts(manifest, entry)
        ), key
        resolved = resolve_module(
            manifest, {"os": key.split("-")[0], "arch": key.split("-")[1]}
        )
        assert resolved["corresponding_source"] == (
            f"https://github.com/podman-container-tools/podman/tree/v{version}"
        )


@pytest.mark.parametrize(
    ("platform", "expected"),
    [
        ({"os": "windows", "family": "", "arch": "amd64", "version": "19041"}, True),
        ({"os": "windows", "family": "", "arch": "amd64", "version": "18363"}, False),
        ({"os": "windows", "family": "", "arch": "arm64", "version": "26100"}, False),
        ({"os": "darwin", "family": "", "arch": "arm64", "version": "13.0"}, True),
        ({"os": "darwin", "family": "", "arch": "amd64", "version": "12.7.6"}, False),
    ],
)
def test_containers_resolves_off_linux_from_each_entrys_floor(platform, expected):
    _, entry = resolve_platform_entry(load_module_manifests()["podman"], platform)

    assert (entry is not None) is expected


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
    manifest = load_tool_manifests()["cc_switch"]
    version = pins.PACKAGING_CC_SWITCH_VERSION

    assert manifest["version"] == version
    assert set(manifest["platforms"]) == {
        CC_SWITCH_KEYS[key] for key in pins.PACKAGING_CC_SWITCH_ASSETS
    }
    for key, (asset, digest) in pins.PACKAGING_CC_SWITCH_ASSETS.items():
        entry = manifest["platforms"][CC_SWITCH_KEYS[key]]
        (artifact,) = entry_artifacts(manifest, entry)
        upstream = pins.PACKAGING_CC_SWITCH_URL.format(version=version, asset=asset)
        file = upstream.rsplit("/", 1)[-1]
        assert artifact["digest"] == f"sha256:{digest}"
        assert artifact["kind"] == ("zip" if asset.endswith(".zip") else "tar_gz")
        assert artifact_file(artifact, version) == file
        assert artifact_sources(
            artifact, version, hub_version="0.6.0", sites=SITES
        ) == [
            upstream,
            f"https://releases.example/a/download/v0.6.0/{file}",
            f"https://releases.example/b/download/v0.6.0/{file}",
        ]
        assert artifact_sources(artifact, version, sites=()) == [upstream]


def test_cc_switch_is_no_module():
    assert "cc_switch" not in load_module_manifests()
    assert list(load_tool_manifests()) == ["cc_switch"]
    manifest = load_tool_manifests()["cc_switch"]
    assert entry_version(manifest, manifest["platforms"]["linux-amd64"]) == (
        manifest["version"]
    )


def test_every_shipped_source_names_no_edition_or_country_key():
    texts = json.dumps(
        [load_module_manifests(), load_tool_manifests()], ensure_ascii=False
    )

    for retired in ("cn_url", "cn_latest_url", "components", "package_kind"):
        assert retired not in texts
    for manifest in load_module_manifests().values():
        assert "installer" not in manifest and "kind" not in manifest


# --- the catalog's row: only a hub or container entry shows a licence ---


def test_only_a_hub_entry_shows_a_licence_and_its_source_with_the_version():
    manifest = load_module_manifests()["podman"]

    linux = resolve_module(manifest, DEBIAN)
    windows = resolve_module(manifest, WINDOWS)

    assert (linux["method"], linux["license"], linux["corresponding_source"]) == (
        "system",
        "",
        "",
    )
    assert (windows["method"], windows["license"]) == ("hub", "Apache-2.0")
    assert windows["corresponding_source"] == (
        "https://github.com/podman-container-tools/podman/tree/v6.1.4"
    )
    assert windows["version"] == "6.1.4" and linux["version"] == "system"


def test_a_platform_with_no_entry_resolves_to_no_runner_and_no_recipe():
    resolved = resolve_module(load_module_manifests()["code_server"], WINDOWS)

    assert (resolved["runner"], resolved["method"], resolved["recipe"]) == ("", "", {})
    assert resolved["platform_key"] == ""


# --- resolve_platform_entry ---


def test_the_platform_keys_are_tried_in_their_order():
    assert platform_keys(DEBIAN) == [
        "linux-debian-amd64",
        "linux-debian",
        "linux-amd64",
        "linux",
    ]
    assert platform_keys(WINDOWS) == ["windows-amd64", "windows"]
    assert platform_keys({}) == []


@pytest.mark.parametrize(
    ("named", "expected"),
    [
        (
            ("linux-debian-amd64", "linux-debian", "linux-amd64", "linux"),
            "linux-debian-amd64",
        ),
        (("linux-debian", "linux-amd64", "linux"), "linux-debian"),
        (("linux-amd64", "linux"), "linux-amd64"),
        (("linux",), "linux"),
        (("linux-rhel", "linux-arm64"), ""),
    ],
)
def test_the_first_key_a_manifest_names_wins(named, expected):
    manifest = {"platforms": {key: {"runner": key} for key in named}}

    key, entry = resolve_platform_entry(manifest, DEBIAN)

    assert key == expected
    assert (entry or {}).get("runner", "") == expected


def test_a_floor_above_the_reported_version_resolves_no_entry():
    manifest = {"platforms": {"windows-amd64": {"runner": "r", "min_version": "19041"}}}

    assert resolve_platform_entry(manifest, {**WINDOWS, "version": "18363"}) == (
        "",
        None,
    )
    assert resolve_platform_entry(manifest, {**WINDOWS, "version": "19041"})[0] == (
        "windows-amd64"
    )
    # A machine that reported no version is not ruled out.
    assert resolve_platform_entry(manifest, {**WINDOWS, "version": ""})[0] == (
        "windows-amd64"
    )


def test_the_catalog_and_the_cache_read_the_one_entry(manifests_dir):
    """A more specific key wins in the catalog's row and recipe, and the
    cache knows only that entry's artifact."""
    manifest = valid_manifest()
    specific = copy.deepcopy(manifest["platforms"]["windows-amd64"])
    specific["runner"] = "specific"
    hub_params_of = specific["install"]["params"]
    hub_params_of["artifacts"][0]["digest"] = "sha256:" + "c" * 64
    manifest["platforms"] = {
        "linux-amd64": copy.deepcopy(specific),
        "linux-debian-amd64": specific,
    }
    manifest["platforms"]["linux-amd64"]["runner"] = "general"
    manifest["platforms"]["linux-amd64"]["install"]["params"]["artifacts"][0][
        "digest"
    ] = ("sha256:" + "d" * 64)
    write_manifest(manifests_dir, "sample", manifest)
    loaded = load_module_manifests()["sample"]

    resolved = resolve_module(loaded, DEBIAN)

    assert resolved["platform_key"] == "linux-debian-amd64"
    assert resolved["runner"] == resolved["recipe"]["runner"] == "specific"
    assert resolved["recipe"]["params"]["artifacts"][0]["digest"] == (
        "sha256:" + "c" * 64
    )
    with pytest.raises(AgentArtifactFetchError) as refused:
        AgentModuleCache(root=manifests_dir / "cache").artifact(
            module="sample",
            artifact="server",
            digest="sha256:" + "d" * 64,
            platform=DEBIAN,
        )
    assert refused.value.code == "module_artifact_unknown"


# --- module_recipe and artifact_sources ---


def test_the_recipe_drops_the_feeds_and_the_sources_the_package_stream_serves():
    recipe = module_recipe(valid_manifest()["platforms"]["windows-amd64"])

    assert recipe == {
        "runner": "sample_machine",
        "method": "hub",
        "params": {
            "version": "2.0",
            "artifacts": [
                {
                    "name": "server",
                    "kind": "tar_gz",
                    "digest": "sha256:" + "a" * 64,
                    "directory": "server",
                },
                {
                    "name": "cli",
                    "kind": "npm",
                    "package": "@vendor/cli",
                    "digest": "sha512-" + "b" * 86 + "==",
                    "source_set": "npm",
                    "hosts": {"npm_config_cli_binary_host": ["https://h.example"]},
                },
            ],
            "verify": "sample --version",
            "uninstall": {"post_uninstall": [], "is_data_kept": True},
        },
    }
    assert module_recipe(None) == {}


def test_a_system_recipe_is_the_entry_s_params():
    entry = valid_manifest()["platforms"]["linux-debian"]

    assert module_recipe(entry) == {
        "runner": "sample",
        "method": "system",
        "params": entry["install"]["params"],
    }


def test_the_sources_fill_the_file_and_the_version_and_expand_each_release_site():
    artifact = sample_artifact(
        sources=[
            "https://vendor.example/v{version}/{file}",
            "{release}/{file}",
        ]
    )

    assert artifact_file(artifact, "2.0") == "server-2.0.tar.gz"
    assert artifact_sources(artifact, "2.0", hub_version="0.6.0", sites=SITES) == [
        "https://vendor.example/v2.0/server-2.0.tar.gz",
        "https://releases.example/a/download/v0.6.0/server-2.0.tar.gz",
        "https://releases.example/b/download/v0.6.0/server-2.0.tar.gz",
    ]


def test_a_checkout_names_no_release_site():
    artifact = sample_artifact(sources=["{release}/{file}"])

    assert artifact_sources(artifact, "2.0", hub_version="0.6.0+dev", sites=()) == []
    # This test run is a checkout: the hub's own stamp names no site.
    assert artifact_sources(artifact, "2.0") == []


# --- the loader's gates ---


def test_the_loader_takes_a_manifest_of_the_shapes(manifests_dir):
    write_manifest(manifests_dir, "sample", valid_manifest())

    loaded = load_module_manifests()["sample"]

    assert loaded["platforms"]["windows-amd64"]["min_version"] == "19041"


def test_the_loader_takes_an_agent_and_a_builtin_entry_with_empty_params(manifests_dir):
    manifest = valid_manifest()
    del manifest["license"], manifest["corresponding_source"]
    manifest["platforms"] = {
        "linux": {"runner": "sample", "install": {"method": "agent", "params": {}}},
        "windows": {"runner": "sample", "install": {"method": "builtin", "params": {}}},
    }
    write_manifest(manifests_dir, "sample", manifest)

    assert "sample" in load_module_manifests()


def test_the_loader_takes_a_container_entry_of_images(manifests_dir):
    manifest = valid_manifest()
    manifest["uninstall_data"]["is_deleted"] = True
    manifest["platforms"] = {
        "linux": {
            "runner": "container",
            "install": {
                "method": "container",
                "params": {
                    "version": "7.0",
                    "releases": [
                        {
                            "kind": "oci",
                            "sources": ["https://registry.example"],
                            "repository": "library/mongo",
                            "tag": "{version}",
                        }
                    ],
                    "artifacts": [
                        {
                            "name": "mongo",
                            "kind": "image",
                            "digest": "sha256:" + "e" * 64,
                            "sources": ["docker.io/library/mongo"],
                        }
                    ],
                },
            },
        }
    }
    write_manifest(manifests_dir, "sample", manifest)

    loaded = load_module_manifests()["sample"]
    recipe = module_recipe(loaded["platforms"]["linux"])
    assert recipe["params"]["artifacts"][0]["sources"] == ["docker.io/library/mongo"]
    assert "releases" not in recipe["params"]


def _stray_top_key(manifest):
    manifest["installer"] = "hub"


def _missing_publisher(manifest):
    del manifest["publisher"]


def _missing_runner(manifest):
    del manifest["platforms"]["linux-debian"]["runner"]


def _stray_entry_key(manifest):
    manifest["platforms"]["linux-debian"]["kind"] = "system_package"


def _wrong_method(manifest):
    manifest["platforms"]["linux-debian"]["install"]["method"] = "platform"


def _system_version(manifest):
    system_params(manifest)["version"] = "1.0"


def _system_without_verify(manifest):
    del system_params(manifest)["verify"]


def _system_uninstall_keeps_data_key(manifest):
    system_params(manifest)["uninstall"]["is_data_kept"] = True


def _hub_without_releases(manifest):
    del hub_params(manifest)["releases"]


def _hub_without_uninstall(manifest):
    del hub_params(manifest)["uninstall"]


def _hub_uninstall_without_data_flag(manifest):
    del hub_params(manifest)["uninstall"]["is_data_kept"]


def _agent_with_params(manifest):
    manifest["platforms"]["linux-debian"]["install"] = {
        "method": "agent",
        "params": {"verify": "true"},
    }


def _image_in_hub(manifest):
    hub_params(manifest)["artifacts"][0] = {
        "name": "server",
        "kind": "image",
        "digest": "sha256:" + "a" * 64,
        "sources": ["docker.io/vendor/server"],
    }


def _bad_sha256(manifest):
    hub_params(manifest)["artifacts"][0]["digest"] = "sha256:abc"


def _bare_hex_digest(manifest):
    hub_params(manifest)["artifacts"][0]["digest"] = "a" * 64


def _bad_integrity(manifest):
    hub_params(manifest)["artifacts"][1]["digest"] = "sha256:" + "b" * 64


def _source_without_file(manifest):
    hub_params(manifest)["artifacts"][0]["sources"] = ["https://vendor.example/x"]


def _shared_name(manifest):
    artifacts = hub_params(manifest)["artifacts"]
    artifacts.append(sample_artifact(directory="other"))


def _shared_directory(manifest):
    artifacts = hub_params(manifest)["artifacts"]
    artifacts.append(sample_artifact(name="other"))


def _binary_with_directory(manifest):
    hub_params(manifest)["artifacts"][0]["kind"] = "binary"


def _msi_without_directory(manifest):
    artifact = hub_params(manifest)["artifacts"][0]
    artifact["kind"] = "msi"
    del artifact["directory"]


def _unknown_feed(manifest):
    hub_params(manifest)["releases"][0]["kind"] = "gitlab"


def _feed_without_its_key(manifest):
    del hub_params(manifest)["releases"][0]["tag"]


def _hub_without_license(manifest):
    del manifest["license"]


def _bad_floor(manifest):
    manifest["platforms"]["windows-amd64"]["min_version"] = "v19041"


def _unknown_system(manifest):
    manifest["platforms"]["solaris-amd64"] = manifest["platforms"].pop("linux-debian")


def _stray_params_key(manifest):
    hub_params(manifest)["url"] = "https://vendor.example/server.tar.gz"


def _no_artifacts(manifest):
    hub_params(manifest)["artifacts"] = []


def _dmg_without_member(manifest):
    hub_params(manifest)["artifacts"][0]["kind"] = "dmg"


def _member_on_a_tarball(manifest):
    hub_params(manifest)["artifacts"][0]["member"] = "App.app/Contents/Resources"


def _member_outside_the_image(manifest):
    artifact = hub_params(manifest)["artifacts"][0]
    artifact["kind"] = "dmg"
    artifact["member"] = "App.app/../../etc"


def _uninstall_data_of_another_shape(manifest):
    manifest["uninstall_data"] = {"is_deleted": False, "line": "x"}


def _uninstall_data_in_one_language(manifest):
    manifest["uninstall_data"] = {"is_deleted": False, "text": {"en": "Data stays."}}


def _uninstall_data_deleted_beside_kept_data(manifest):
    manifest["uninstall_data"] = {
        "is_deleted": True,
        "text": {"en": "Data goes.", "zh-CN": "数据会删除。"},
    }


def _without_uninstall_data(manifest):
    del manifest["uninstall_data"]


def _uninstall_data_on_an_agent_module(manifest):
    manifest["platforms"] = {
        "linux": {"runner": "sample", "install": {"method": "agent", "params": {}}}
    }


@pytest.mark.parametrize(
    "spoil, said",
    [
        (_stray_top_key, "installer"),
        (_missing_publisher, "publisher"),
        (_missing_runner, "runner"),
        (_stray_entry_key, "kind"),
        (_wrong_method, "method"),
        (_system_version, "system"),
        (_system_without_verify, "verify"),
        (_system_uninstall_keeps_data_key, "is_data_kept"),
        (_hub_without_releases, "releases"),
        (_hub_without_uninstall, "uninstall"),
        (_hub_uninstall_without_data_flag, "is_data_kept"),
        (_agent_with_params, "verify"),
        (_image_in_hub, "image"),
        (_bad_sha256, "digest"),
        (_bare_hex_digest, "digest"),
        (_bad_integrity, "digest"),
        (_source_without_file, "{file}"),
        (_shared_name, "twice"),
        (_shared_directory, "server"),
        (_binary_with_directory, "directory"),
        (_msi_without_directory, "directory"),
        (_unknown_feed, "gitlab"),
        (_feed_without_its_key, "tag"),
        (_hub_without_license, "license"),
        (_bad_floor, "min_version"),
        (_unknown_system, "solaris-amd64"),
        (_stray_params_key, "url"),
        (_no_artifacts, "artifact"),
        (_dmg_without_member, "member"),
        (_member_on_a_tarball, "member"),
        (_member_outside_the_image, "member"),
        (_uninstall_data_of_another_shape, "uninstall_data"),
        (_uninstall_data_in_one_language, "zh-CN"),
        (_uninstall_data_deleted_beside_kept_data, "disagrees"),
        (_without_uninstall_data, "uninstall_data is missing"),
        (_uninstall_data_on_an_agent_module, "carries"),
    ],
)
def test_the_loader_refuses_a_manifest_outside_the_shapes(spoil, said, manifests_dir):
    manifest = valid_manifest()
    spoil(manifest)
    write_manifest(manifests_dir, "sample", manifest)

    with pytest.raises(ValueError) as refusal:
        load_module_manifests()

    assert "sample.json" in str(refusal.value)
    assert said in str(refusal.value)


def test_the_loader_refuses_a_name_that_is_not_the_file_s(manifests_dir):
    write_manifest(manifests_dir, "other", valid_manifest())

    with pytest.raises(ValueError, match="other.json: name"):
        load_module_manifests()


def test_the_loader_refuses_a_file_that_is_no_json_object(manifests_dir):
    (manifests_dir / "broken.json").write_text("[1, 2]", encoding="utf-8")

    with pytest.raises(ValueError, match="broken.json"):
        load_module_manifests()


def tool_manifest(**entry_overrides) -> dict:
    artifact = sample_artifact(name="tool", directory=None)
    artifact.update(entry_overrides)
    return _without_nones(
        {
            "name": "tool",
            "title": "Tool",
            "description": "A program the agent runs",
            "is_module": False,
            "publisher": "vendor/tool",
            "license": "MIT",
            "corresponding_source": "https://vendor.example/tree/v{version}",
            "version": "1.0",
            "platforms": {"linux-amd64": {"artifacts": [artifact]}},
        }
    )


def test_the_loader_takes_a_tool_manifest_and_keeps_it_out_of_the_modules(
    manifests_dir,
):
    write_manifest(manifests_dir, "tool", tool_manifest())

    assert list(load_tool_manifests()) == ["tool"]
    assert load_module_manifests() == {}


@pytest.mark.parametrize(
    "manifest, said",
    [
        (tool_manifest(digest="a" * 64), "digest"),
        (tool_manifest(kind="npm"), "npm"),
        (tool_manifest(sources=["https://vendor.example/tool"]), "{file}"),
        ({**tool_manifest(), "version": ""}, "version"),
        (
            {
                **tool_manifest(),
                "platforms": {"linux-amd64": {"url": "u", "sha256": "s"}},
            },
            "url",
        ),
    ],
)
def test_the_loader_refuses_a_tool_manifest_outside_its_shape(
    manifest, said, manifests_dir
):
    write_manifest(manifests_dir, "tool", manifest)

    with pytest.raises(ValueError) as refusal:
        load_tool_manifests()

    assert "tool.json" in str(refusal.value)
    assert said in str(refusal.value)


# --- container entries and source sets ---


def container_manifest(**params) -> dict:
    """The sample module with one ``container`` entry on Linux of these params."""
    manifest = valid_manifest()
    manifest["uninstall_data"]["is_deleted"] = True
    manifest["platforms"] = {
        "linux": {
            "runner": "container",
            "install": {
                "method": "container",
                "params": {
                    "version": "1.0",
                    "artifacts": [
                        {
                            "name": "web",
                            "kind": "image",
                            "digest": "sha256:" + "e" * 64,
                            "sources": ["ghcr.io/acme/web"],
                        }
                    ],
                    **params,
                },
            },
        }
    }
    return manifest


def test_a_container_entry_with_no_releases_and_its_source_sets_loads(manifests_dir):
    write_manifest(manifests_dir, "sample", container_manifest(source_sets=["pypi"]))

    loaded = load_module_manifests()["sample"]
    recipe = module_recipe(loaded["platforms"]["linux"])

    assert recipe["params"]["source_sets"] == ["pypi"]
    assert "releases" not in entry_params(loaded["platforms"]["linux"])


def test_a_container_entry_naming_a_set_the_file_does_not_define_is_refused(
    manifests_dir,
):
    write_manifest(manifests_dir, "sample", container_manifest(source_sets=["conda"]))

    with pytest.raises(ValueError) as refusal:
        load_module_manifests()

    assert "conda" in str(refusal.value)


def _npm_with_sources(manifest):
    artifact = hub_params(manifest)["artifacts"][1]
    artifact["sources"] = ["https://registry.example"]


def _npm_without_its_set(manifest):
    del hub_params(manifest)["artifacts"][1]["source_set"]


def _npm_of_another_set(manifest):
    hub_params(manifest)["artifacts"][1]["source_set"] = "pypi"


@pytest.mark.parametrize(
    "spoil, said",
    [
        (_npm_with_sources, "sources"),
        (_npm_without_its_set, "source_set"),
        (_npm_of_another_set, "npm set"),
    ],
)
def test_an_npm_artifact_names_the_npm_set_alone(spoil, said, manifests_dir):
    manifest = valid_manifest()
    spoil(manifest)
    write_manifest(manifests_dir, "sample", manifest)

    with pytest.raises(ValueError) as refusal:
        load_module_manifests()

    assert said in str(refusal.value)


def test_every_shipped_npm_artifact_names_the_npm_set():
    for manifest in load_module_manifests().values():
        for entry in manifest["platforms"].values():
            for artifact in entry_params(entry).get("artifacts") or []:
                if artifact["kind"] == "npm":
                    assert artifact["source_set"] == "npm"
                    assert "sources" not in artifact
