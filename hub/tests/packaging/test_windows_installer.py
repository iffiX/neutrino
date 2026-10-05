"""What the hub's Windows installer declares, read off its generated source.

wix is not run here, and neither is the compiler, so what is asserted is the
document the build writes and the payload it lays out with the compile and
the downloads stood in for: the hub registered as a LocalSystem service with
``service run``, recovered when it ends and started by the install, the
``Neutrino Hub`` Start menu shortcut, the program folder and the data folder of the
one Neutrino tree, the data folder closed to everyone but SYSTEM and the
administrators, the programs with EasyTier's driver and the stand-in
``packet.dll`` under ``bin``, the agent's own installer in the state
directory, and the name the release publishes it under.
"""

import json
import xml.etree.ElementTree
from pathlib import Path

import pytest

import build_hub_windows
import compiled_tree

WXS = "{http://wixtoolset.org/schemas/v4/wxs}"
UTIL = "{http://wixtoolset.org/schemas/v4/wxs/util}"

# The agent's and the client's upgrade codes, which this one must not be.
OTHER_UPGRADE_CODES = (
    "9F4E4A1C-9C0B-4C0E-9E2E-6C5A2C7C1E33",
    "0221A508-0A7E-4CFE-B517-B901D9318962",
)


@pytest.fixture
def document():
    staged = {
        "payload": "C:\\build\\payload",
        "binary": "C:\\build\\nhub.exe",
        "state": "C:\\build\\state",
        "icon": "C:\\build\\neutrino_hub.ico",
    }
    source = build_hub_windows.wix_source(
        staged, "9.9.9", "iffiX <someone@example.com>"
    )
    return source, xml.etree.ElementTree.fromstring(source)


def by_id(root, tag, identifier):
    found = [node for node in root.iter(tag) if node.get("Id") == identifier]
    assert len(found) == 1, f"{identifier}: {found}"
    return found[0]


def test_the_installer_has_a_product_identity_of_its_own(document):
    _source, root = document

    package = root.find(WXS + "Package")
    assert package.get("Name") == "Neutrino Hub"
    assert package.get("UpgradeCode") == build_hub_windows.UPGRADE_CODE
    assert build_hub_windows.UPGRADE_CODE not in OTHER_UPGRADE_CODES
    assert package.get("Version") == "9.9.9"


def test_the_hub_is_a_localsystem_service_registered_and_started(document):
    _source, root = document

    install = by_id(root, WXS + "ServiceInstall", "HubServiceInstall")
    assert install.get("Name") == "neutrino_hub"
    assert install.get("Account") == "LocalSystem"
    assert install.get("Start") == "auto"
    assert install.get("Arguments") == "service run"
    control = by_id(root, WXS + "ServiceControl", "HubServiceControl")
    assert control.get("Start") == "install"
    assert (control.get("Stop"), control.get("Remove")) == ("both", "uninstall")
    assert by_id(root, WXS + "File", "HubServiceFile").get("Source") == (
        "C:\\build\\nhub.exe"
    )


def test_the_service_is_started_again_when_it_ends(document):
    _source, root = document

    (recovery,) = by_id(root, WXS + "ServiceInstall", "HubServiceInstall").iter(
        UTIL + "ServiceConfig"
    )
    for failure in ("First", "Second", "Third"):
        assert recovery.get(f"{failure}FailureActionType") == "restart"


def test_no_custom_action_starts_the_service_beside_its_control(document):
    _source, root = document

    assert list(root.iter(WXS + "CustomAction")) == []


def test_the_start_menu_entry_runs_nhub_open(document):
    _source, root = document

    shortcut = by_id(root, WXS + "Shortcut", "HubEntryShortcut")
    assert shortcut.get("Name") == "Neutrino Hub"
    assert shortcut.get("Directory") == "ProgramMenuFolder"
    assert shortcut.get("Target") == "[INSTALLFOLDER]nhub.exe"
    assert shortcut.get("Arguments") == "open"
    assert shortcut.get("Icon") == "HubIcon"
    assert by_id(root, WXS + "Icon", "HubIcon").get("SourceFile") == (
        "C:\\build\\neutrino_hub.ico"
    )


def test_the_folders_are_the_hubs_own_in_the_one_neutrino_tree(document):
    _source, root = document

    program = by_id(root, WXS + "Directory", "INSTALLFOLDER")
    data = by_id(root, WXS + "Directory", "HUBDATAFOLDER")
    state = by_id(root, WXS + "Directory", "HUBSTATEFOLDER")
    assert program.get("Name") == "hub"
    assert program in list(by_id(root, WXS + "Directory", "NeutrinoProgramFolder"))
    assert data.get("Name") == "hub"
    assert data in list(by_id(root, WXS + "Directory", "NeutrinoDataFolder"))
    assert state.get("Name") == "state"
    assert state in list(data)


def test_the_data_folder_admits_system_and_the_administrators_alone(document):
    _source, root = document

    folder = by_id(root, WXS + "Component", "HubDataFolder")
    (permission,) = folder.iter(WXS + "PermissionEx")
    assert permission.get("Sddl") == "D:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)"


def test_the_program_folder_goes_on_the_path(document):
    _source, root = document

    environment = by_id(root, WXS + "Environment", "HubPath")
    assert environment.get("Name") == "PATH"
    assert environment.get("Value") == "[INSTALLFOLDER]"
    assert environment.get("System") == "yes"


@pytest.fixture
def agent_packages(tmp_path):
    directory = tmp_path / "agents"
    directory.mkdir()
    for name in (
        "neutrino-agent-9.9.9-windows-amd64.msi",
        "neutrino-agent-9.9.9-macos-arm64.pkg",
        "neutrino-agent_9.9.9_arm64.deb",
    ):
        (directory / name).write_bytes(name.encode())
    return directory


@pytest.fixture
def packet_dll(tmp_path):
    path = tmp_path / "packet.dll"
    path.write_bytes(b"MZ stand-in")
    return path


@pytest.fixture
def laid_out(tmp_path, monkeypatch, agent_packages, packet_dll):
    calls = []

    def compile_standalone(python, entry, output_dir, binary_name, **kwargs):
        calls.append(("compile", kwargs["options"]))
        dist = output_dir / "entry.dist"
        dist.mkdir(parents=True)
        (dist / binary_name).write_bytes(b"MZ")
        (dist / "python313.dll").write_bytes(b"MZ")
        return dist

    def stage_programs(binaries, os_name, machine):
        calls.append((os_name, machine))
        binaries.mkdir(parents=True)
        for name in ("xray.exe", "easytier-core.exe", "wintun.dll"):
            (binaries / name).write_bytes(b"MZ")

    def stage_geodata(geodata):
        geodata.mkdir(parents=True)
        (geodata / "geosite.dat").write_bytes(b"db")

    monkeypatch.setattr(build_hub_windows, "_check_build_machine", lambda m: None)
    monkeypatch.setattr(compiled_tree.venv_tree, "require_built_frontend", lambda: None)
    monkeypatch.setattr(
        compiled_tree, "make_build_environment", lambda venv: Path("python.exe")
    )
    monkeypatch.setattr(
        compiled_tree.nuitka_build, "compile_standalone", compile_standalone
    )
    monkeypatch.setattr(build_hub_windows.hub_assets, "stage_programs", stage_programs)
    monkeypatch.setattr(build_hub_windows.hub_assets, "stage_geodata", stage_geodata)

    staged = build_hub_windows._lay_out(
        tmp_path / "work",
        "9.9.9",
        "amd64",
        agent_packages=agent_packages,
        url_base="",
        packet_dll=packet_dll,
    )
    return staged, calls


def test_the_binary_is_kept_out_of_the_payload_for_the_service_to_claim(laid_out):
    staged, _calls = laid_out

    assert staged["binary"].name == "nhub.exe"
    assert not (staged["payload"] / "nhub.exe").exists()
    assert (staged["payload"] / "python313.dll").is_file()
    assert (staged["payload"] / "neutrino_hub" / "data" / "manifests").is_dir()


def test_the_programs_have_the_driver_and_the_stand_in_beside_them(laid_out):
    staged, calls = laid_out
    programs = staged["payload"] / "bin"

    assert ("windows", "amd64") in calls
    for name in ("xray.exe", "easytier-core.exe", "wintun.dll", "packet.dll"):
        assert (programs / name).is_file(), name
    assert (programs / "packet.dll").read_bytes() == b"MZ stand-in"


def test_the_compile_is_a_console_program_with_its_version(laid_out):
    _staged, calls = laid_out

    (options,) = [call[1] for call in calls if call[0] == "compile"]
    assert "--windows-console-mode=force" in options
    assert "--product-version=9.9.9" in options
    assert "--include-package=neutrino_hub" in options


def test_the_state_seeds_the_agents_installer_and_a_build_with_no_release_names_it_alone(
    tmp_path, laid_out
):
    staged, _calls = laid_out

    cache = staged["state"] / "agent_cache"
    assert sorted(path.name for path in cache.iterdir()) == [
        "neutrino-agent-9.9.9-windows-amd64.msi"
    ]
    assert (staged["state"] / "geodata" / "geosite.dat").is_file()
    manifest = json.loads(
        (
            staged["payload"] / "neutrino_hub" / "data" / "agent_packages.json"
        ).read_text()
    )
    assert sorted(manifest) == ["msi-amd64"]
    assert manifest["msi-amd64"]["url"] == ""
    stamp = (tmp_path / "work" / "tree" / "neutrino_hub" / "_version.py").read_text()
    assert 'HUB_PACKAGE_ASSET = "neutrino-hub-{version}-windows-amd64.msi"' in stamp


@pytest.mark.parametrize("given", [None, "missing", "text"])
def test_the_build_refuses_to_package_without_the_stand_in(tmp_path, given):
    path = None
    if given == "missing":
        path = tmp_path / "absent.dll"
    elif given == "text":
        path = tmp_path / "packet.dll"
        path.write_text("not a library")

    with pytest.raises(SystemExit):
        build_hub_windows._check_packet_dll(path)


def test_the_package_is_named_the_way_the_release_publishes_it():
    assert build_hub_windows.msi_name("0.5.0", "amd64") == (
        "neutrino-hub-0.5.0-windows-amd64.msi"
    )
    assert build_hub_windows.windows_machine("x64") == "amd64"
    assert build_hub_windows.windows_machine("AMD64") == "amd64"
    with pytest.raises(SystemExit):
        build_hub_windows.windows_machine("arm64")


def test_the_build_refuses_anything_but_windows(monkeypatch):
    monkeypatch.setattr(build_hub_windows.sys, "platform", "linux")

    with pytest.raises(SystemExit) as refused:
        build_hub_windows._check_tools(True)

    assert "runs on Windows" in str(refused.value)


def test_the_build_refuses_another_interpreter_than_the_pinned_one(monkeypatch):
    monkeypatch.setattr(compiled_tree.sys, "version_info", (3, 12, 4, "final", 0))

    with pytest.raises(SystemExit) as refused:
        build_hub_windows._check_build_machine("amd64")

    assert "3.13" in str(refused.value)


def test_the_config_folder_is_made_with_the_data_folders_protection(document):
    """The hub writes its vault there from its first run, so the folder exists
    with SYSTEM and the administrators alone before anything is written."""
    _source, root = document

    config = by_id(root, WXS + "Directory", "HUBCONFIGFOLDER")
    assert config.get("Name") == "config"
    assert config in list(by_id(root, WXS + "Directory", "HUBDATAFOLDER"))
    folder = by_id(root, WXS + "Component", "HubConfigFolder")
    (permission,) = folder.iter(WXS + "PermissionEx")
    assert permission.get("Sddl") == "D:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)"
    feature = by_id(root, WXS + "Feature", "Main")
    assert "Config" in [
        ref.get("Id") for ref in feature.iter(WXS + "ComponentGroupRef")
    ]
