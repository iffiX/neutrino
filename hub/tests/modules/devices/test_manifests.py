"""The shipped manifests: one source of module truth under data/manifests.

What the panel offers, what the catalog resolves and what an agent installs
all read these files, so the modules the design names are pinned here as
shipped — cc-switch as a real module, the mount tooling as a distro package,
and the SSH server under its plain title.
"""

from neutrino_hub.modules.cliproxyapi.constants import CLIPROXYAPI_SWITCHER_NAME
from neutrino_hub.modules.devices.catalog import resolve_module
from neutrino_hub.modules.devices.manifests import load_module_manifests


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
    assert load_module_manifests()["openssh_server"]["title"] == "SSH server"


def test_windows_verify_commands_fail_when_the_software_is_absent():
    # PowerShell Test-Path prints False but exits 0, so a bare Test-Path
    # reads absent software as installed. A windows verify built on it must
    # turn the result into a nonzero exit.
    verified = []
    for name, manifest in load_module_manifests().items():
        command = manifest.get("verify", {}).get("windows", "")
        if "Test-Path" not in command:
            continue
        assert "exit 1" in command, f"{name} reads absent software as installed"
        verified.append(name)
    assert set(verified) == {"anydesk", "todesk"}
