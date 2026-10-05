"""What the agent's Windows installer declares, read off its generated source.

wix is not run here, and neither is the compiler, so what is asserted is the
document the build writes and the payload it lays out with the compile and
the download stood in for: the agent registered as a LocalSystem service
started at boot with ``service run`` and recovered when it ends, RustDesk's
own installer run silently as the system after the files land and run with
``--uninstall`` only on a removal, the data folder closed to everyone but
SYSTEM and the administrators, the agent on PATH, and the name the release
publishes it under.
"""

import xml.etree.ElementTree
from pathlib import Path

import pytest

import build_agent_windows
import payload
from shared import wix_build

# The client's own upgrade code, which this one must not be.
CLIENT_UPGRADE_CODE = "0221A508-0A7E-4CFE-B517-B901D9318962"

WXS = "{http://wixtoolset.org/schemas/v4/wxs}"
UTIL = "{http://wixtoolset.org/schemas/v4/wxs/util}"


@pytest.fixture
def document():
    """The .wxs the build writes, parsed, with the staged paths stood in for."""
    staged = {
        "payload": "C:\\build\\payload",
        "binary": "C:\\build\\nagent.exe",
        "rustdesk": "C:\\build\\rustdesk\\rustdesk-1.4.9-x86_64.exe",
    }
    source = build_agent_windows.wix_source(
        staged, "9.9.9", "iffiX <someone@example.com>"
    )
    return source, xml.etree.ElementTree.fromstring(source)


def by_id(root, tag, identifier):
    found = [node for node in root.iter(tag) if node.get("Id") == identifier]
    assert len(found) == 1, f"{identifier}: {found}"
    return found[0]


def test_the_installer_has_a_product_identity_of_its_own(document):
    source, root = document

    package = root.find(WXS + "Package")
    assert package.get("UpgradeCode") == build_agent_windows.UPGRADE_CODE
    assert build_agent_windows.UPGRADE_CODE != CLIENT_UPGRADE_CODE
    assert package.get("Name") == "Neutrino Agent"
    assert package.get("Version") == "9.9.9"
    assert package.get("Manufacturer") == "iffiX <someone@example.com>"


def test_the_agent_is_a_localsystem_service_started_at_boot(document):
    _source, root = document

    install = by_id(root, WXS + "ServiceInstall", "AgentServiceInstall")
    assert install.get("Name") == "neutrino_agent"
    assert install.get("Account") == "LocalSystem"
    assert install.get("Start") == "auto"
    assert install.get("Arguments") == "service run"
    assert install.get("Type") == "ownProcess"

    control = by_id(root, WXS + "ServiceControl", "AgentServiceControl")
    assert control.get("Name") == "neutrino_agent"
    assert (control.get("Start"), control.get("Stop"), control.get("Remove")) == (
        "install",
        "both",
        "uninstall",
    )

    binary = by_id(root, WXS + "File", "AgentServiceFile")
    assert binary.get("Source") == "C:\\build\\nagent.exe"


def test_an_agent_that_ends_by_itself_is_started_again(document):
    _source, root = document

    install = by_id(root, WXS + "ServiceInstall", "AgentServiceInstall")
    recovery = install.find(UTIL + "ServiceConfig")
    assert recovery is not None
    for action in ("First", "Second", "Third"):
        assert recovery.get(f"{action}FailureActionType") == "restart"


def test_rustdesk_installs_itself_silently_as_the_system_after_the_files(document):
    _source, root = document

    action = by_id(root, WXS + "CustomAction", "InstallRustDesk")
    assert action.get("FileRef") == "RustDeskInstaller"
    assert action.get("ExeCommand") == "--silent-install"
    assert action.get("Execute") == "deferred"
    assert action.get("Impersonate") == "no"
    assert action.get("Return") == "check"

    scheduled = [
        node
        for node in root.iter(WXS + "Custom")
        if node.get("Action") == "InstallRustDesk"
    ]
    assert scheduled[0].get("After") == "InstallFiles"
    assert scheduled[0].get("Condition") == "NOT REMOVE"

    carried = by_id(root, WXS + "File", "RustDeskInstaller")
    assert carried.get("Name") == "rustdesk-1.4.9-x86_64.exe"


def test_rustdesk_is_uninstalled_on_a_removal_and_kept_through_an_upgrade(document):
    _source, root = document

    action = by_id(root, WXS + "CustomAction", "UninstallRustDesk")
    assert action.get("ExeCommand") == "--uninstall"
    assert action.get("Impersonate") == "no"
    assert action.get("Return") == "ignore"

    scheduled = [
        node
        for node in root.iter(WXS + "Custom")
        if node.get("Action") == "UninstallRustDesk"
    ]
    assert scheduled[0].get("Before") == "RemoveFiles"
    assert scheduled[0].get("Condition") == (
        'REMOVE~="ALL" AND NOT UPGRADINGPRODUCTCODE'
    )


def test_a_removal_runs_the_agent_to_take_away_what_its_modules_added(document):
    """The agent's own binary runs while it is still on disk, as the system,
    on a removal alone: an upgrade keeps the tasks and the firewall rules."""
    _source, root = document

    action = by_id(root, WXS + "CustomAction", "UninstallAdded")
    assert action.get("FileRef") == "AgentServiceFile"
    assert action.get("ExeCommand") == "service uninstall --yes"
    assert action.get("Execute") == "deferred"
    assert action.get("Impersonate") == "no"
    assert action.get("Return") == "ignore"

    scheduled = [
        node
        for node in root.iter(WXS + "Custom")
        if node.get("Action") == "UninstallAdded"
    ]
    assert len(scheduled) == 1
    assert scheduled[0].get("Before") == "UninstallRustDesk"
    assert scheduled[0].get("Condition") == (
        'REMOVE~="ALL" AND NOT UPGRADINGPRODUCTCODE'
    )


def test_the_data_folder_admits_system_and_the_administrators_alone(document):
    _source, root = document

    folder = by_id(root, WXS + "Directory", "AGENTDATAFOLDER")
    assert folder.get("Name") == "agent"
    permission = root.find(f".//{WXS}CreateFolder/{WXS}PermissionEx")
    sddl = permission.get("Sddl")
    assert sddl == "D:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)"
    # Protected, so nothing ProgramData grants every account is inherited.
    assert sddl.startswith("D:P")
    for everyone_else in ("BU", "AU", "WD", "IU"):
        assert everyone_else not in sddl


def test_the_agent_is_on_the_machines_path(document):
    _source, root = document

    entry = by_id(root, WXS + "Environment", "AgentPath")
    assert (entry.get("Name"), entry.get("Value"), entry.get("System")) == (
        "PATH",
        "[INSTALLFOLDER]",
        "yes",
    )


def test_the_installer_is_named_the_way_the_release_publishes_it():
    assert build_agent_windows.msi_name("0.4.0", "amd64") == (
        "neutrino-agent-0.4.0-windows-amd64.msi"
    )
    assert build_agent_windows.windows_machine("x64") == "amd64"
    with pytest.raises(SystemExit):
        build_agent_windows.windows_machine("arm64")


def test_the_payload_keeps_the_agents_binary_for_the_service_component(
    tmp_path, monkeypatch
):
    compiled = []

    def compile_standalone(python, entry, output_dir, binary_name, **kwargs):
        compiled.append((entry, binary_name, kwargs["options"]))
        dist = output_dir / "entry.dist"
        dist.mkdir(parents=True)
        (dist / binary_name).write_bytes(b"MZ")
        (dist / "python313.dll").write_bytes(b"MZ")
        return dist

    def stage_windows_exe(dest_dir, *, name, machine="x86_64"):
        dest_dir.mkdir(parents=True, exist_ok=True)
        (dest_dir / name).write_bytes(b"MZ")
        return dest_dir / name

    monkeypatch.setattr(
        build_agent_windows, "_check_build_machine", lambda machine: None
    )
    monkeypatch.setattr(
        build_agent_windows, "_make_build_environment", lambda venv: Path("python")
    )
    monkeypatch.setattr(
        build_agent_windows.nuitka_build, "compile_standalone", compile_standalone
    )
    monkeypatch.setattr(
        build_agent_windows.rustdesk_assets, "stage_windows_exe", stage_windows_exe
    )

    staged = build_agent_windows._lay_out(tmp_path, "9.9.9", "amd64")

    assert (staged["payload"] / "python313.dll").is_file()
    assert not (staged["payload"] / "nagent.exe").exists()
    assert staged["binary"].name == "nagent.exe"
    assert staged["rustdesk"].name == "rustdesk-1.4.9-x86_64.exe"
    assert (staged["payload"] / "licenses" / "rustdesk.txt").is_file()
    assert (staged["payload"] / "licenses" / "cc_switch.txt").is_file()
    assert (staged["payload"] / "bin" / "cc-switch.exe").read_bytes() == (
        b"MZ cc-switch"
    )
    entry, binary_name, options = compiled[0]
    assert entry.parts[-3:] == ("neutrino_agent", "cli", "entry.py")
    assert binary_name == "nagent.exe"
    assert "--windows-console-mode=force" in options
    assert "--include-package=neutrino_agent" in options
    stamped = tmp_path / "tree" / "neutrino_agent" / "_version.py"
    assert 'AGENT_VERSION = "9.9.9"' in stamped.read_text()


def test_only_the_util_extension_is_loaded():
    source = Path(build_agent_windows.__file__).read_text(encoding="utf-8")

    assert "extensions=(wix_build.WIX_UTIL_EXTENSION,)" in source
    assert wix_build.WIX_UTIL_EXTENSION.startswith("WixToolset.Util.wixext/")
    assert payload.PACKAGE_NAME == "neutrino-agent"


def test_the_program_folder_is_the_agents_own_in_the_one_neutrino_tree(document):
    """C:\\Program Files\\Neutrino\\agent, beside the hub and the client."""
    _source, root = document

    install = by_id(root, WXS + "Directory", "INSTALLFOLDER")
    parent = by_id(root, WXS + "Directory", "NeutrinoProgramFolder")
    assert install.get("Name") == "agent"
    assert parent.get("Name") == "Neutrino"
    assert install in list(parent)
