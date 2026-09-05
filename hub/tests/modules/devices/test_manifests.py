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
