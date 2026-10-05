"""NetBird's part of the client packages.

The packages are laid out with the downloads and the compile faked, as the
other packaging tests do. Pinned here: the payload takes the part while the
tree holds it; NetBird's binary is pinned for every system and machine and
lands where the runtime looks; a tarball without it is refused; its daemon
is a unit on Linux, a service on Windows and a LaunchDaemon on macOS, each
running the carried binary on the client's own state; the Linux packages
take it off its network before they go and conflict with the netbird
package; its licence and version travel with every package.
"""

import plistlib
import xml.etree.ElementTree

import pytest

import build_client_macos
import bundled
import netbird_payload
import payload
from neutrino_client.constants import CLIENT_INSTALL_PREFIX_LINUX
from neutrino_client.netbird.constants import (
    CLIENT_NETBIRD_CONFIG_PATH_LINUX,
    CLIENT_NETBIRD_SERVICE_LINUX,
    NETBIRD_BUNDLED_PATHS,
)
from tests.packaging.test_bundled import (
    _tarball,
    attached_image,
    downloads,
)  # noqa: F401
from tests.packaging.test_bundled import unpacked_viewer  # noqa: F401
from tests.packaging.test_linux_packages import carried, deb, rpm, spec  # noqa: F401
from tests.packaging.test_windows_installer import WXS, services, source  # noqa: F401


def test_the_payload_takes_the_part_while_the_tree_holds_it():
    assert netbird_payload in payload.parts()
    assert "netbird.txt" in payload.CARRIED_LICENSES
    assert payload.CONFLICTS == ("netbird",)


@pytest.mark.parametrize(
    "key",
    [
        ("linux", "x86_64"),
        ("linux", "aarch64"),
        ("windows", "x86_64"),
        ("darwin", "aarch64"),
        ("darwin", "x86_64"),
    ],
)
def test_every_platform_has_netbird_pinned(key):
    asset, digest = netbird_payload.NETBIRD_ASSETS[key]
    assert asset
    assert len(digest) == 64
    assert digest == digest.lower()


def test_the_url_names_the_version_the_pins_are_for():
    url = netbird_payload.NETBIRD_URL.format(
        version=netbird_payload.NETBIRD_VERSION,
        asset=netbird_payload.NETBIRD_ASSETS[("windows", "x86_64")][0],
    )

    assert url.endswith("v0.78.1/netbird_0.78.1_windows_amd64.tar.gz")


def test_the_binary_lands_where_the_runtime_looks(
    tmp_path, downloads, unpacked_viewer, attached_image
):
    bundled.stage_linux_binaries(tmp_path / "linux", "amd64")
    bundled.stage_windows_binaries(tmp_path / "windows", "x64")
    contents = tmp_path / "Neutrino Client.app" / "Contents"
    bundled.stage_darwin_binaries(contents, "arm64")

    linux = (
        tmp_path
        / "linux/opt/neutrino/client"
        / NETBIRD_BUNDLED_PATHS["linux"]["netbird"]
    )
    assert linux.stat().st_mode & 0o111
    assert (tmp_path / "windows" / "bin" / "netbird.exe").is_file()
    assert (contents / NETBIRD_BUNDLED_PATHS["darwin"]["netbird"]).is_file()
    assert "netbird_0.78.1_darwin_arm64.tar.gz" in [
        url.rsplit("/", 1)[-1] for url in downloads
    ]


def test_a_tarball_without_its_binary_is_refused(tmp_path, monkeypatch):
    def fetch(url, digest, what):
        return _tarball("README.md")

    monkeypatch.setattr(payload, "fetch", fetch)

    with pytest.raises(SystemExit) as refused:
        netbird_payload.stage(tmp_path / "netbird", "linux", "x86_64")

    assert "carries no netbird" in str(refused.value)


def test_the_linux_unit_runs_the_carried_binary_on_its_own_state(deb):
    unit = (deb / "usr/lib/systemd/system" / CLIENT_NETBIRD_SERVICE_LINUX).read_text()

    assert (
        f"ExecStart={CLIENT_INSTALL_PREFIX_LINUX}/"
        f"{NETBIRD_BUNDLED_PATHS['linux']['netbird']} service run "
        f"--config {CLIENT_NETBIRD_CONFIG_PATH_LINUX}"
    ) in unit


def test_the_linux_packages_take_it_off_its_network_and_conflict(deb, spec):
    prerm = (deb / "DEBIAN/prerm").read_text()
    on_remove = prerm.split('if [ "$1" = remove ]; then')[1]
    files = spec.split("%files")[1].split("%pre")[0]

    assert "/opt/neutrino/client/netbird/netbird down" in on_remove
    assert "Conflicts: netbird\n" in (deb / "DEBIAN/control").read_text()
    assert "Conflicts:      netbird" in spec
    assert f"/usr/lib/systemd/system/{CLIENT_NETBIRD_SERVICE_LINUX}" in files


def test_the_windows_service_runs_the_binary_on_its_own_state(source):
    root = xml.etree.ElementTree.fromstring(source)
    components = {
        component.get("Id"): component for component in root.iter(f"{WXS}Component")
    }
    directories = {node.get("Id"): node for node in root.iter(f"{WXS}Directory")}
    excluded = [element.get("Files") for element in root.iter(f"{WXS}Exclude")]

    assert services(source)["NeutrinoClientNetbird"].get("Arguments") == (
        "service run --config "
        '"[CommonAppDataFolder]Neutrino\\client\\state\\netbird\\config.json"'
        ' --log-file "[CommonAppDataFolder]Neutrino\\client\\log\\netbird.log"'
    )
    assert services(source)["NeutrinoClientNetbird"].get("Account") == "LocalSystem"
    assert components["NetbirdService"].get("Subdirectory") == "bin"
    assert "C:/build/payload/bin/netbird.exe" in [
        name.replace("\\", "/") for name in excluded
    ]
    assert directories["NETBIRDDATAFOLDER"] in list(directories["CLIENTSTATEFOLDER"])
    assert components["NetbirdDataFolder"].get("Directory") == "NETBIRDDATAFOLDER"


def test_the_netbird_service_stop_is_waited_for_and_its_start_is_not(source):
    """netbird.exe must be free before the files are written, or the upgrade
    owes a restart; a start that fails because another NetBird holds the
    machine must not fail the install."""
    root = xml.etree.ElementTree.fromstring(source)
    controls = {
        element.get("Id"): element
        for element in root.iter(f"{WXS}ServiceControl")
        if element.get("Name") == "NeutrinoClientNetbird"
    }

    assert set(controls) == {"NetbirdServiceStop", "NetbirdServiceStart"}
    stop, start = controls["NetbirdServiceStop"], controls["NetbirdServiceStart"]
    assert (stop.get("Stop"), stop.get("Remove"), stop.get("Wait")) == (
        "both",
        "uninstall",
        "yes",
    )
    assert stop.get("Start") is None
    assert (start.get("Start"), start.get("Wait")) == ("install", "no")
    assert start.get("Stop") is None and start.get("Remove") is None


def test_the_macos_daemon_runs_unless_another_holds_the_socket(tmp_path):
    build_client_macos.write_daemons(tmp_path)
    plist = tmp_path / "Library/LaunchDaemons/com.neutrino.client.netbird.plist"
    job = plistlib.loads(plist.read_bytes())
    shell, flag, command = job["ProgramArguments"]

    assert (shell, flag) == ("/bin/sh", "-c")
    assert command.startswith("[ -S /var/run/netbird.sock ] && exit 0; ")
    assert (
        "exec '/Applications/Neutrino Client.app/Contents/Resources/netbird/netbird'"
        " service run --config"
        " '/Library/Application Support/Neutrino/client/state/netbird/config.json'"
        " --log-file console"
    ) in command
    assert job["RunAtLoad"] is True
    assert job["KeepAlive"] == {"SuccessfulExit": False}
    assert job["StandardOutPath"] == "/Library/Logs/Neutrino/client/netbird.log"
    assert "com.neutrino.client.netbird" in build_client_macos.PREINSTALL
    assert (
        '"/Library/Application Support/Neutrino/client/state/netbird"'
        in build_client_macos.POSTINSTALL
    )


def test_the_version_is_stamped_for_the_about_card(tmp_path):
    staged = payload.stage_client_tree(tmp_path / "site-packages", "9.9.9")

    stamped = {}
    exec((staged / "_version.py").read_text(), stamped)
    assert stamped["CLIENT_CARRIED_VERSIONS"]["netbird"] == "0.78.1"
