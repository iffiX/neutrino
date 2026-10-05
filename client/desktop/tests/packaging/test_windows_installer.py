"""What the Windows installer declares, read off its generated source.

wix is not run here — it needs Windows and the .NET tool — and neither is
the compiler, so what is asserted is the document the build writes and the
command the compile is given: a product identity of its own, the
overlay daemons as services, the EasyTier one the client run as its daemon, no autostart Run
entry, the shortcut, the quit that comes before
anything ends a resident and opens no window doing it, the two questions and
what they answer to unasked, and the bootstrapper chained only where the
runtime's key is absent. The payload's own laying out is checked with the
downloads faked.
"""

import inspect
import json
import re
import subprocess
import sys
import xml.etree.ElementTree
from pathlib import Path

import pytest

import build_client_windows
from shared import nuitka_build
import payload
from shared import wix_build

# The agent's own upgrade code, which this one must not be.
AGENT_UPGRADE_CODE = "9F4E4A1C-9C0B-4C0E-9E2E-6C5A2C7C1E33"

# The two namespaces the document is written in.
WXS = "{http://wixtoolset.org/schemas/v4/wxs}"
UTIL = "{http://wixtoolset.org/schemas/v4/wxs/util}"

# The services the installer registers: the EasyTier and files daemons, and
# those of the parts the tree holds.
DAEMON_SERVICES = {"NeutrinoClientEasytier", "NeutrinoClientFiles"} | {
    name for part in payload.parts() for name in part.WINDOWS_SERVICES
}
# The licences the parts the tree holds add.
PARTS_LICENSES = [name for part in payload.parts() for name in part.CARRIED_LICENSES]


@pytest.fixture
def source():
    """The .wxs the build writes, with the staged paths stood in for."""
    staged = {
        "payload": "C:\\build\\payload",
        "bootstrapper": "C:\\build\\MicrosoftEdgeWebview2Setup.exe",
        "icon": "C:\\build\\neutrino_client.ico",
        "license": "C:\\build\\license.rtf",
    }
    return build_client_windows._wix_source(
        staged, "9.9.9", "iffiX <someone@example.com>", "amd64"
    )


def test_the_installer_has_a_product_identity_of_its_own(source):
    assert build_client_windows.UPGRADE_CODE != AGENT_UPGRADE_CODE
    assert len(build_client_windows.UPGRADE_CODE) == 36
    assert build_client_windows.UPGRADE_CODE.count("-") == 4
    assert f'UpgradeCode="{build_client_windows.UPGRADE_CODE}"' in source
    assert 'Name="Neutrino Client"' in source
    assert 'Version="9.9.9"' in source


def services(source) -> dict:
    """Every ServiceInstall in the document, by the name the SCM knows."""
    root = xml.etree.ElementTree.fromstring(source)
    return {
        element.get("Name"): element for element in root.iter(f"{WXS}ServiceInstall")
    }


def controls(source) -> dict:
    """Every ServiceControl in the document, by the service it controls."""
    root = xml.etree.ElementTree.fromstring(source)
    return {
        element.get("Name"): element for element in root.iter(f"{WXS}ServiceControl")
    }


def test_the_installer_registers_the_daemons_and_no_other_service(source):
    assert set(services(source)) == DAEMON_SERVICES
    for element in services(source).values():
        assert element.get("Account") == "LocalSystem"
    assert "gui" not in " ".join(
        element.get("Arguments", "") for element in services(source).values()
    )


def test_every_daemon_starts_with_windows_and_goes_with_the_client(source):
    for name in DAEMON_SERVICES:
        assert services(source)[name].get("Start") == "auto"
        assert controls(source)[name].get("Start") == "install"
        assert controls(source)[name].get("Stop") == "both"
        assert controls(source)[name].get("Remove") == "uninstall"


def test_the_easytier_service_is_the_client_run_as_its_daemon(source):
    """The core is the daemon's child, never a service of its own."""
    root = xml.etree.ElementTree.fromstring(source)
    easytier = services(source)["NeutrinoClientEasytier"].get("Arguments")
    components = {
        component.get("Id"): component for component in root.iter(f"{WXS}Component")
    }
    (daemon_file,) = components["EasytierDaemon"].iter(f"{WXS}File")

    assert easytier == "easytier-daemon --service"
    assert (
        daemon_file.get("Source").replace("\\", "/") == "C:/build/payload/nclient.exe"
    )
    assert components["EasytierDaemon"].get("Subdirectory") is None
    assert "easytier-core" not in source.split("<Files")[0]
    assert "--config-dir" not in source


def test_the_files_service_is_the_client_run_as_its_files_daemon(source):
    """The same nclient.exe as the EasyTier daemon, so the same component."""
    root = xml.etree.ElementTree.fromstring(source)
    components = {
        component.get("Id"): component for component in root.iter(f"{WXS}Component")
    }
    files = services(source)["NeutrinoClientFiles"]

    assert files.get("Arguments") == "files-daemon --service"
    assert files.get("Account") == "LocalSystem"
    installs = [
        element.get("Name")
        for element in components["EasytierDaemon"].iter(f"{WXS}ServiceInstall")
    ]
    assert installs == ["NeutrinoClientEasytier", "NeutrinoClientFiles"]
    assert len(list(components["EasytierDaemon"].iter(f"{WXS}File"))) == 1
    assert "tun2socks" not in source.split("<Files")[0]
    (recovery,) = files.iter(f"{UTIL}ServiceConfig")
    assert recovery.get("FirstFailureActionType") == "restart"
    children = list(files.iter())[1:]
    assert [child.tag for child in children] == [f"{UTIL}ServiceConfig"]


def test_the_easytier_daemon_is_restarted_after_every_failure(source):
    """As Linux's Restart=always and macOS's KeepAlive keep it up."""
    (recovery,) = services(source)["NeutrinoClientEasytier"].iter(
        f"{UTIL}ServiceConfig"
    )

    for failure in ("First", "Second", "Third"):
        assert recovery.get(f"{failure}FailureActionType") == "restart"
    assert recovery.get("RestartServiceDelayInSeconds") == "10"


def test_users_are_granted_nothing_on_easytier(source):
    """The daemon's pipe is how a person reaches EasyTier; no service right,
    no writable folder."""
    root = xml.etree.ElementTree.fromstring(source)

    children = list(services(source)["NeutrinoClientEasytier"].iter())[1:]
    assert [child.tag for child in children] == [f"{UTIL}ServiceConfig"]
    assert "EASYTIERDATAFOLDER" not in source
    for granted in root.iter(f"{UTIL}PermissionEx"):
        assert granted.get("User") != "Users"


def test_the_daemon_binaries_are_service_components_and_not_files_of_the_glob(
    source,
):
    root = xml.etree.ElementTree.fromstring(source)
    excluded = [element.get("Files") for element in root.iter(f"{WXS}Exclude")]
    components = {
        component.get("Id"): component for component in root.iter(f"{WXS}Component")
    }

    parts_excluded = [
        str(path).replace("\\", "/")
        for part in payload.parts()
        for path in part.windows_excluded(Path("C:\\build\\payload"))
    ]
    assert [name.replace("\\", "/") for name in excluded] == parts_excluded + [
        "C:/build/payload/nclient.exe"
    ]
    assert components["EasytierDaemon"].get("Subdirectory") is None
    main = [
        feature for feature in root.iter(f"{WXS}Feature") if feature.get("Id") == "Main"
    ][0]
    assert {ref.get("Id") for ref in main.iter(f"{WXS}ComponentGroupRef")} == {
        "Payload",
        "Daemons",
        "Data",
    }


def test_the_source_is_well_formed_and_the_publisher_survives_its_brackets(source):
    """A publisher with an address in angle brackets is text, not markup."""
    root = xml.etree.ElementTree.fromstring(source)
    assert (
        root.find(WXS + "Package").get("Manufacturer") == "iffiX <someone@example.com>"
    )


def test_a_running_resident_is_closed_before_its_files_are_replaced(source):
    """An upgrade over a live resident is what lands half-applied."""
    root = xml.etree.ElementTree.fromstring(source)
    closes = list(root.iter(UTIL + "CloseApplication"))
    # A resident from the shortcut wears one image, one from a terminal the
    # other; both hold the files.
    assert sorted(close.get("Target") for close in closes) == sorted(
        [
            build_client_windows.CLIENT_WINDOWED_BINARY_NAME,
            build_client_windows.CLIENT_BINARY_NAME,
        ]
    )
    assert all(close.get("RebootPrompt") == "no" for close in closes)


def test_a_running_resident_is_asked_to_quit_before_anything_ends_it(source):
    """The client's services go with the resident, so the quit comes first."""
    root = xml.etree.ElementTree.fromstring(source)
    quits = [
        action
        for action in root.iter(WXS + "CustomAction")
        if action.get("Id") == "QuitClientResident"
    ]

    assert len(quits) == 1
    command = quits[0].get("ExeCommand")
    assert command.endswith("quit")
    assert quits[0].get("Directory") == "INSTALLFOLDER"
    assert quits[0].get("Execute") == "immediate"
    # No resident to answer is not a failed install.
    assert quits[0].get("Return") == "ignore"


def test_the_quit_opens_no_console_window_over_the_wizard(source):
    """A custom action has no console, and a console program it starts opens
    one; the windowed program opens nothing."""
    assert build_client_windows.QUIT_COMMAND == '"[INSTALLFOLDER]nclientw.exe" quit'
    assert "powershell" not in build_client_windows.QUIT_COMMAND.lower()


def test_the_two_programs_are_the_two_subsystems():
    """One executable cannot serve both: a windowed one started with pipes
    but no console loses the pipes (Nuitka's attach mode clobbers the
    inherited handles when AttachConsole fails), and a console one started
    from a shortcut opens a window. The same split python.exe and pythonw.exe
    make."""
    assert build_client_windows.CLIENT_BINARY_NAME == "nclient.exe"
    assert build_client_windows.CLIENT_WINDOWED_BINARY_NAME == "nclientw.exe"
    source = inspect.getsource(build_client_windows._compile)
    assert '"force"' in source
    assert '"disable"' in source
    assert "attach" not in inspect.getsource(build_client_windows._compile_one)


def test_the_quit_runs_before_the_close_that_ends_what_did_not_answer(source):
    """CostFinalize is earlier than InstallInitialize, where the close goes."""
    root = xml.etree.ElementTree.fromstring(source)
    scheduled = [
        custom
        for custom in root.iter(WXS + "Custom")
        if custom.get("Action") == "QuitClientResident"
    ]

    assert len(scheduled) == 1
    assert scheduled[0].get("After") == "QuitClientResidentForUpgrade"
    assert scheduled[0].get("Condition") == "Installed OR WIX_UPGRADE_DETECTED"
    (first,) = [
        custom
        for custom in root.iter(WXS + "Custom")
        if custom.get("Action") == "QuitClientResidentForUpgrade"
    ]
    assert first.get("After") == "CostFinalize"
    assert list(root.iter(UTIL + "CloseApplication"))


def test_an_uninstall_keeps_the_persons_own_configuration_unless_asked(source):
    """Uninstalling is a remove, not a purge, and the answer nobody gives is
    the one that keeps a binding rather than losing it."""
    root = xml.etree.ElementTree.fromstring(source)
    kept = [
        setting
        for setting in root.iter(WXS + "Property")
        if setting.get("Id") == "ISCONFIGKEPT"
    ]

    assert len(kept) == 1
    assert kept[0].get("Value") == "1"
    removals = [
        custom
        for custom in root.iter(WXS + "Custom")
        if custom.get("Action") == "RemoveClientConfig"
    ]
    assert len(removals) == 1
    assert removals[0].get("Condition") == build_client_windows.CONFIG_GOES_CONDITION
    assert 'REMOVE~="ALL"' in build_client_windows.CONFIG_GOES_CONDITION


def test_a_kept_configuration_is_the_one_value_rather_than_a_true_reading():
    """A property set to "0" is a non-empty string, which the installer reads
    as true, so `NOT ISCONFIGKEPT` would take a configuration that was asked
    to stay."""
    assert 'ISCONFIGKEPT <> "1"' in build_client_windows.CONFIG_GOES_CONDITION
    assert "NOT ISCONFIGKEPT" not in build_client_windows.CONFIG_GOES_CONDITION


def test_the_person_is_asked_before_their_configuration_goes(source):
    """A checkbox on a dialog of the removal's own, and the path it names."""
    root = xml.etree.ElementTree.fromstring(source)
    dialogs = {dialog.get("Id"): dialog for dialog in root.iter(WXS + "Dialog")}

    assert "ClientRemoveDlg" in dialogs
    boxes = [
        control
        for control in dialogs["ClientRemoveDlg"].iter(WXS + "Control")
        if control.get("Type") == "CheckBox"
    ]
    assert [box.get("Property") for box in boxes] == ["ISCONFIGKEPT"]
    assert (
        build_client_windows.CLIENT_CONFIG_DIR_NAME
        in build_client_windows.REMOVE_CONFIG_COMMAND
    )
    assert "AppDataFolder" in build_client_windows.REMOVE_CONFIG_COMMAND


def test_the_removal_runs_with_no_account_and_is_handed_the_path(source):
    """[AppDataFolder] is the installing person's while the installer is
    still them, so the expanded command travels as data to the deferred
    half."""
    root = xml.etree.ElementTree.fromstring(source)
    actions = {
        action.get("Id"): action
        for action in root.iter(WXS + "CustomAction")
        if action.get("Id") in ("SetRemoveClientConfig", "RemoveClientConfig")
    }

    assert actions["SetRemoveClientConfig"].get("Property") == "RemoveClientConfig"
    assert actions["SetRemoveClientConfig"].get("Execute") == "immediate"
    assert actions["RemoveClientConfig"].get("Execute") == "deferred"
    assert actions["RemoveClientConfig"].get("Impersonate") == "no"
    assert actions["RemoveClientConfig"].get("Return") == "ignore"


def test_the_build_loads_the_extensions_those_elements_come_from():
    assert wix_build.WIX_UTIL_EXTENSION == "WixToolset.Util.wixext/6.0.2"
    assert wix_build.WIX_UI_EXTENSION == "WixToolset.UI.wixext/6.0.2"
    assert "wix extension add" in build_client_windows.__doc__


def test_the_prefix_goes_whole_including_what_the_install_never_laid_down(source):
    """The carried interpreter writes bytecode beside the modules it runs,
    and a file the installer did not track is one it would otherwise leave
    in Program Files."""
    root = xml.etree.ElementTree.fromstring(source)
    prunes = list(root.iter(UTIL + "RemoveFolderEx"))

    assert len(prunes) == 1
    assert prunes[0].get("On") == "uninstall"
    assert prunes[0].get("Property") == "NEUTRINOINSTALLDIR"
    searches = [
        setting
        for setting in root.iter(WXS + "Property")
        if setting.get("Id") == "NEUTRINOINSTALLDIR"
    ]
    assert len(searches) == 1
    assert list(searches[0].iter(WXS + "RegistrySearch"))[0].get("Type") == "directory"


def test_the_installer_registers_no_autostart(source):
    """The client runs when the person opens it, not with the session."""
    assert r"Software\Microsoft\Windows\CurrentVersion\Run" not in source
    assert "gui --hidden" not in source
    assert not hasattr(build_client_windows, "RUN_ENTRY_VALUE")


def test_the_install_goes_on_the_path_when_it_is_asked_for(source):
    assert '<Environment Id="ClientPath"' in source
    assert 'Name="PATH"' in source
    assert 'Value="[INSTALLFOLDER]"' in source
    assert 'System="yes"' in source
    root = xml.etree.ElementTree.fromstring(source)
    asked = [
        setting
        for setting in root.iter(WXS + "Property")
        if setting.get("Id") == "ISPATHADDED"
    ]
    assert len(asked) == 1
    assert asked[0].get("Value") == "1"


def test_the_path_entry_is_a_feature_so_its_answer_outlives_the_install(source):
    """A component's condition is read again at uninstall, where the answer
    is gone; a feature's state is what the installer itself remembers."""
    root = xml.etree.ElementTree.fromstring(source)
    features = {feature.get("Id"): feature for feature in root.iter(WXS + "Feature")}

    assert "PathFeature" in features
    groups = [
        reference.get("Id")
        for reference in features["PathFeature"].iter(WXS + "ComponentGroupRef")
    ]
    assert groups == ["PathOption"]
    events = {
        publish.get("Event")
        for publish in root.iter(WXS + "Publish")
        if publish.get("Dialog") == "ClientOptionsDlg"
        and publish.get("Value") == "PathFeature"
    }
    assert events == {"AddLocal", "Remove"}


def test_a_silent_install_can_decline_the_path_entry_too(source):
    """The wizard drives the feature from its checkbox; a level condition is
    what makes the same answer reachable with no wizard at all."""
    root = xml.etree.ElementTree.fromstring(source)
    features = {feature.get("Id"): feature for feature in root.iter(WXS + "Feature")}
    levels = list(features["PathFeature"].iter(WXS + "Level"))

    assert len(levels) == 1
    assert levels[0].get("Value") == "0"
    assert levels[0].get("Condition") == build_client_windows.PATH_DECLINED_CONDITION
    assert 'ISPATHADDED <> "1"' in build_client_windows.PATH_DECLINED_CONDITION


def test_the_person_is_asked_before_the_path_changes(source):
    root = xml.etree.ElementTree.fromstring(source)
    dialogs = {dialog.get("Id"): dialog for dialog in root.iter(WXS + "Dialog")}

    assert "ClientOptionsDlg" in dialogs
    boxes = [
        control
        for control in dialogs["ClientOptionsDlg"].iter(WXS + "Control")
        if control.get("Type") == "CheckBox"
    ]
    assert [box.get("Property") for box in boxes] == ["ISPATHADDED"]


def test_the_start_menu_shortcut_opens_the_window(source):
    root = xml.etree.ElementTree.fromstring(source)
    shortcuts = list(root.iter(WXS + "Shortcut"))

    assert len(shortcuts) == 1
    # The windowed program: a shortcut to the console one would open a
    # console beside the window.
    assert shortcuts[0].get("Target") == "[INSTALLFOLDER]nclientw.exe"
    assert shortcuts[0].get("Arguments") == "gui"


def test_the_bootstrapper_runs_only_where_the_runtime_key_is_absent(source):
    assert build_client_windows.WEBVIEW2_REGISTRY_KEY in source
    assert 'Condition="NOT WEBVIEW2INSTALLED AND NOT REMOVE"' in source
    assert 'ExeCommand="/silent /install"' in source


def test_a_publisher_with_an_address_stays_a_name(source):
    assert "iffiX &lt;someone@example.com&gt;" in source
    assert "<someone@example.com>" not in source


def test_the_package_is_named_for_the_platform_it_installs_on():
    assert wix_build.MSI_PLATFORMS == {"amd64": "x64", "arm64": "arm64"}
    assert build_client_windows.WINDOWS_MACHINES["x86_64"] == "amd64"
    assert payload.PACKAGE_NAME == "neutrino-client"


def test_the_build_refuses_another_interpreter_than_the_pinned_one(monkeypatch):
    """What runs the script is what the client is compiled against."""
    monkeypatch.setattr(
        build_client_windows.sys, "version_info", (3, 12, 4, "final", 0)
    )

    with pytest.raises(SystemExit) as refused:
        build_client_windows._check_build_machine("amd64")

    assert "3.13" in str(refused.value)


def test_the_build_refuses_a_machine_this_is_not(monkeypatch):
    """The compile is native: an arm64 installer comes off an arm64 box."""
    monkeypatch.setattr(
        build_client_windows.sys, "version_info", (3, 13, 7, "final", 0)
    )
    monkeypatch.setattr(build_client_windows.platform, "machine", lambda: "AMD64")

    build_client_windows._check_build_machine("amd64")
    with pytest.raises(SystemExit) as refused:
        build_client_windows._check_build_machine("arm64")

    assert "arm64" in str(refused.value)


def test_the_compile_names_what_a_scanner_would_otherwise_find(monkeypatch, tmp_path):
    """Standalone, the package and its window backend included, the other
    platforms' backends kept out so the plugin and the user agree, the icon
    and the version in the binary; twice, one subsystem each, with the
    windowed executable taken into the console program's directory."""
    commands = []

    def fake_run(command, env=None, **kwargs):
        commands.append((command, env))
        build = Path(command[-2].split("=", 1)[1])
        name = command[-3].split("=", 1)[1]
        dist = build / "entry.dist"
        dist.mkdir(parents=True, exist_ok=True)
        (dist / name).write_bytes(b"MZ" + name.encode())
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(nuitka_build.subprocess, "run", fake_run)
    monkeypatch.setattr(build_client_windows.icons, "write_ico", lambda path: path)
    tree = tmp_path / "tree"
    (tree / "neutrino_client" / "cli").mkdir(parents=True)

    dist = build_client_windows._compile(
        Path("python.exe"), tree, tmp_path / "build", "9.9.9"
    )

    assert dist == tmp_path / "build" / "console" / "entry.dist"
    assert (dist / "nclient.exe").read_bytes() == b"MZnclient.exe"
    assert (dist / "nclientw.exe").read_bytes() == b"MZnclientw.exe"
    (console, environment), (windowed, _) = commands
    for command in (console, windowed):
        assert command[:3] == ["python.exe", "-m", "nuitka"]
        assert "--standalone" in command
        assert "--include-package=neutrino_client" in command
        assert "--include-package=webview" in command
        for backend in build_client_windows.NUITKA_EXCLUDED_BACKENDS:
            assert f"--nofollow-import-to={backend}" in command
        assert "--product-version=9.9.9" in command
        assert command[-1] == str(tree / "neutrino_client" / "cli" / "entry.py")
    assert "--product-name=Neutrino Client" in console
    assert "--windows-console-mode=force" in console
    assert "--output-filename=nclient.exe" in console
    assert "--windows-console-mode=disable" in windowed
    assert "--output-filename=nclientw.exe" in windowed
    assert environment["PYTHONPATH"] == str(tree)


def test_a_compile_that_writes_no_binary_is_refused(monkeypatch, tmp_path):
    monkeypatch.setattr(
        nuitka_build.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 0),
    )
    monkeypatch.setattr(build_client_windows.icons, "write_ico", lambda path: path)

    with pytest.raises(SystemExit) as refused:
        build_client_windows._compile(
            Path("python.exe"), tmp_path, tmp_path / "build", "1"
        )

    assert build_client_windows.CLIENT_BINARY_NAME in str(refused.value)


def test_the_licences_travel_beside_the_payload(tmp_path):
    build_client_windows._stage_licenses(tmp_path)

    carried = tmp_path / "licenses"
    assert sorted(path.name for path in carried.iterdir()) == sorted(
        PARTS_LICENSES
        + [
            "cc_switch.txt",
            "easytier.txt",
            "meslolgs_nf.txt",
            "packet_stub.txt",
            "rustdesk.txt",
            "tun2socks.txt",
            "wintun.txt",
            "xterm.txt",
        ]
    )
    assert "Prebuilt Binaries License" in (carried / "wintun.txt").read_text()
    note = (carried / "packet_stub.txt").read_text()
    assert "not Npcap's Packet.dll" in note
    assert "client/desktop/packaging/packet_stub.c" in note


# --- the stand-in packet.dll ---


@pytest.mark.parametrize("given", [None, "missing", "text"])
def test_the_build_refuses_to_package_without_the_stand_in(tmp_path, given):
    """Refused first, before a machine check, a compile or a download."""
    packet_dll = None
    if given == "missing":
        packet_dll = tmp_path / "packet.dll"
    if given == "text":
        packet_dll = tmp_path / "packet.dll"
        packet_dll.write_text("not a library")

    with pytest.raises(SystemExit) as refused:
        build_client_windows._lay_out(
            tmp_path, "9.9.9", "amd64", "x64", packet_dll=packet_dll
        )

    assert "packet" in str(refused.value).lower()
    assert not (tmp_path / "payload").exists()


def test_the_stand_in_lands_beside_the_core(monkeypatch, tmp_path):
    packet_dll = tmp_path / "built" / "packet.dll"
    packet_dll.parent.mkdir()
    packet_dll.write_bytes(b"MZ stub")
    compiled = tmp_path / "compiled"
    compiled.mkdir()
    (compiled / "nclient.exe").write_bytes(b"MZ")

    def stage_windows_binaries(installed, architecture):
        (installed / "bin").mkdir()
        (installed / "bin" / "easytier-core.exe").write_bytes(b"MZ")

    monkeypatch.setattr(
        build_client_windows, "_check_build_machine", lambda machine: None
    )
    monkeypatch.setattr(
        build_client_windows,
        "_make_build_environment",
        lambda venv, machine: Path("py"),
    )
    monkeypatch.setattr(
        build_client_windows, "_compile", lambda python, tree, build, version: compiled
    )
    monkeypatch.setattr(
        build_client_windows.bundled, "stage_windows_binaries", stage_windows_binaries
    )
    monkeypatch.setattr(build_client_windows, "_fetch_bootstrapper", lambda: b"MZ")
    monkeypatch.setattr(build_client_windows.icons, "write_ico", lambda path: path)
    monkeypatch.setattr(
        build_client_windows.wix_build,
        "write_license_rtf",
        lambda source, target: target,
    )

    staged = build_client_windows._lay_out(
        tmp_path / "root", "9.9.9", "amd64", "x64", packet_dll=packet_dll
    )

    carried = staged["payload"] / "bin" / "packet.dll"
    assert carried.read_bytes() == b"MZ stub"
    assert (staged["payload"] / "bin" / "easytier-core.exe").is_file()


def test_the_stand_in_exports_what_the_core_imports():
    """The eleven functions easytier-core loads from Packet.dll, each exported."""
    source = (Path(payload.__file__).parent / "packet_stub.c").read_text(
        encoding="utf-8"
    )
    exported = re.findall(
        r"^__declspec\(dllexport\)[^(]*?(\w+)\(", source, flags=re.MULTILINE
    )

    assert sorted(exported) == sorted(
        [
            "PacketGetAdapterNames",
            "PacketSendPacket",
            "PacketSetBuff",
            "PacketSetMinToCopy",
            "PacketReceivePacket",
            "PacketOpenAdapter",
            "PacketCloseAdapter",
            "PacketSetHwFilter",
            "PacketAllocatePacket",
            "PacketFreePacket",
            "PacketInitPacket",
        ]
    )


def test_the_release_builds_the_stand_in_with_msvc_before_the_installer():
    workflow = (
        Path(payload.__file__).resolve().parents[3]
        / ".github"
        / "workflows"
        / "release.yml"
    ).read_text(encoding="utf-8")
    job = workflow.split("  client_windows:")[1].split("\n  client_macos:")[0]

    assert "ilammy/msvc-dev-cmd" in job
    compile_at = job.index("cl /nologo /O2 /LD client/desktop/packaging/packet_stub.c")
    build_at = job.index("python packaging/build/build_client_windows.py")
    assert compile_at < build_at
    assert "--packet-dll build/packet_stub/packet.dll" in job


def test_the_payload_carries_no_wrapper_script_and_no_interpreter_of_its_own():
    """The binary is the command; a .cmd beside a carried python.exe was
    the shape before."""
    assert not hasattr(build_client_windows, "CONSOLE_WRAPPER_NAME")
    assert not hasattr(build_client_windows, "WINDOWS_PYTHON_URL")
    assert build_client_windows.BUILD_PYTHON_VERSION == (3, 13)
    assert build_client_windows.CLIENT_BINARY_NAME == "nclient.exe"


def test_the_windows_wheels_are_pinned_to_the_file():
    for _name, _version, url, digest in build_client_windows.WINDOWS_WHEELS:
        assert url.startswith("https://files.pythonhosted.org/")
        assert len(digest) == 64
    for machine in ("amd64", "arm64"):
        _name, _version, url, digest = build_client_windows.WINDOWS_CFFI[machine]
        assert machine in url
        assert len(digest) == 64


def test_the_client_takes_its_own_folders_of_the_one_neutrino_tree(source):
    """C:\\Program Files\\Neutrino\\client and C:\\ProgramData\\Neutrino\\client."""
    root = xml.etree.ElementTree.fromstring(source)
    directories = {node.get("Id"): node for node in root.iter(f"{WXS}Directory")}

    assert directories["INSTALLFOLDER"].get("Name") == "client"
    assert directories["INSTALLFOLDER"] in list(directories["NeutrinoProgramFolder"])
    assert directories["NeutrinoProgramFolder"].get("Name") == "Neutrino"
    assert directories["CLIENTDATAFOLDER"].get("Name") == "client"
    assert directories["CLIENTDATAFOLDER"] in list(directories["NeutrinoDataFolder"])
    assert directories["CLIENTSTATEFOLDER"].get("Name") == "state"
    assert "Neutrino Client" not in [node.get("Name") for node in directories.values()]


# --- the mainland tree ---

# Run inside the mainland tree: tun2socks staged with its download faked, the
# client tree stamped, the licences laid out and the installer's source
# written, each as far as Linux goes.
MAINLAND_STAGING = r"""
import io, json, sys, zipfile
from pathlib import Path

tree, work = Path(sys.argv[1]), Path(sys.argv[2])
for directory in (
    tree / "client" / "desktop" / "packaging",
    tree / "client" / "desktop",
    tree / "packaging",
    tree / "packaging" / "build",
):
    sys.path.insert(0, str(directory))
from shared import hub_assets
import build_client_windows
import payload


def fetch(url, digest, what):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr("tun2socks-windows-amd64.exe", b"MZ tun2socks")
    return buffer.getvalue()


hub_assets.fetch = fetch
staged = hub_assets.stage_program(work / "bin", "tun2socks", "windows", "amd64")
package = payload.stage_client_tree(work / "site", "9.9.9", is_windows=True)
stamp = {}
exec((package / "_version.py").read_text(), stamp)
build_client_windows._stage_licenses(work / "installed")
source = build_client_windows._wix_source(
    {
        "payload": "C:\\build\\payload",
        "bootstrapper": "C:\\build\\MicrosoftEdgeWebview2Setup.exe",
        "icon": "C:\\build\\neutrino_client.ico",
        "license": "C:\\build\\license.rtf",
    },
    "9.9.9",
    "iffiX",
    "amd64",
)
print(json.dumps({
    "staged": [path.name for path in staged],
    "has_tun_module": (tree / "hub" / "neutrino_hub" / "modules" / "tun").exists(),
    "edition": stamp["EDITION"],
    "carried": stamp["CLIENT_CARRIED_VERSIONS"],
    "licenses": sorted(p.name for p in (work / "installed" / "licenses").iterdir()),
    "source": source,
}))
"""

# The mainland tree is written from the intl checkout, and from nothing else.
from_intl_tree = pytest.mark.skipif(
    (Path(payload.__file__).resolve().parents[3] / "EDITION").read_text().strip()
    != "intl",
    reason="the mainland tree is written from the intl checkout",
)


@pytest.fixture(scope="module")
def mainland_staging(tmp_path_factory):
    """What the Windows client stages from the tree build_sources.py writes
    with --edition cn --tree."""
    repository = Path(payload.__file__).resolve().parents[3]
    tree = tmp_path_factory.mktemp("mainland") / "tree"
    subprocess.run(
        [
            sys.executable,
            str(repository / "packaging" / "build" / "build_sources.py"),
            "--edition",
            "cn",
            "--tree",
            str(tree),
        ],
        check=True,
        capture_output=True,
    )
    work = tmp_path_factory.mktemp("staging")
    result = subprocess.run(
        [sys.executable, "-c", MAINLAND_STAGING, str(tree), str(work)],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "NEUTRINO_EDITION": "cn", "HOME": str(work)},
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


@from_intl_tree
def test_the_mainland_tree_stages_the_files_adapter_s_tun2socks(mainland_staging):
    from shared.constants import PACKAGING_TUN2SOCKS_VERSION

    assert not mainland_staging["has_tun_module"]
    assert mainland_staging["staged"] == ["tun2socks.exe"]
    assert mainland_staging["edition"] == "cn"
    assert mainland_staging["carried"]["tun2socks"] == PACKAGING_TUN2SOCKS_VERSION


@from_intl_tree
def test_the_mainland_installer_carries_the_tun2socks_licence(mainland_staging):
    assert "tun2socks.txt" in mainland_staging["licenses"]


@from_intl_tree
def test_the_mainland_installer_registers_the_files_daemon(mainland_staging):
    document = xml.etree.ElementTree.fromstring(mainland_staging["source"])
    names = [install.get("Name") for install in document.iter(f"{WXS}ServiceInstall")]

    assert "NeutrinoClientFiles" in names


def test_the_data_folder_admits_system_and_the_administrators_alone(source):
    """NetBird's private key and EasyTier's networks are under it, and
    ProgramData's own grants let every account read."""
    root = xml.etree.ElementTree.fromstring(source)
    (folder,) = [
        node
        for node in root.iter(f"{WXS}Component")
        if node.get("Id") == "ClientDataFolder"
    ]
    (permission,) = folder.iter(f"{WXS}PermissionEx")
    assert permission.get("Sddl") == "D:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)"
    (feature,) = [
        node for node in root.iter(f"{WXS}Feature") if node.get("Id") == "Main"
    ]
    assert "Data" in [ref.get("Id") for ref in feature.iter(f"{WXS}ComponentGroupRef")]


def test_everything_under_the_data_folder_is_reset_to_what_it_inherits(source):
    """The folders the installer makes under it are made before the folder
    gets its descriptor, and one an earlier build left keeps its grants; so
    each access list under it is reset to the folder's alone, as SYSTEM, on
    every install, upgrade and repair."""
    root = xml.etree.ElementTree.fromstring(source)
    actions = {
        action.get("Id"): action
        for action in root.iter(WXS + "CustomAction")
        if action.get("Id") in ("SetSecureClientData", "SecureClientData")
    }
    scheduled = {
        custom.get("Action"): custom
        for custom in root.iter(WXS + "Custom")
        if custom.get("Action") in actions
    }

    assert actions["SetSecureClientData"].get("Property") == "SecureClientData"
    assert actions["SetSecureClientData"].get("Value") == (
        '"[SystemFolder]icacls.exe" "[CLIENTDATAFOLDER]*" /reset /T /C /Q'
    )
    assert actions["SecureClientData"].get("DllEntry") == "WixQuietExec"
    assert actions["SecureClientData"].get("Execute") == "deferred"
    assert actions["SecureClientData"].get("Impersonate") == "no"
    assert scheduled["SecureClientData"].get("Before") == "InstallFinalize"
    assert scheduled["SetSecureClientData"].get("Before") == "SecureClientData"
    for custom in scheduled.values():
        assert custom.get("Condition") == 'NOT REMOVE~="ALL"'


def test_the_reset_leaves_the_data_folder_its_own_descriptor():
    """``icacls <folder>\\* /reset`` names what is under the folder, never the
    folder, which would take ProgramData's grants back."""
    command = build_client_windows.SECURE_DATA_COMMAND
    assert '"[CLIENTDATAFOLDER]*"' in command
    assert '"[CLIENTDATAFOLDER]"' not in command
    assert "/T" in command.split()


def actions_and_scheduling(source, names):
    root = xml.etree.ElementTree.fromstring(source)
    actions = {
        action.get("Id"): action
        for action in root.iter(WXS + "CustomAction")
        if action.get("Id") in names
    }
    scheduled = {
        custom.get("Action"): custom
        for custom in root.iter(WXS + "Custom")
        if custom.get("Action") in names
    }
    return actions, scheduled


def test_an_install_that_keeps_the_client_asks_it_to_quit_for_an_upgrade(source):
    """The client registers its account's relaunch task before it goes; an
    older build refuses the flag and the plain quit after it quits that one."""
    actions, scheduled = actions_and_scheduling(
        source, ("QuitClientResidentForUpgrade",)
    )

    action = actions["QuitClientResidentForUpgrade"]
    assert action.get("ExeCommand") == '"[INSTALLFOLDER]nclientw.exe" quit --upgrade'
    assert action.get("Execute") == "immediate"
    assert action.get("Impersonate") is None
    assert action.get("Return") == "ignore"
    assert scheduled["QuitClientResidentForUpgrade"].get("Condition") == (
        '(Installed OR WIX_UPGRADE_DETECTED) AND NOT REMOVE~="ALL"'
    )


def test_the_last_step_starts_every_accounts_relaunch_task_as_system(source):
    """The task runs as its own account, limited, and only where it is signed
    in; SYSTEM only starts it."""
    actions, scheduled = actions_and_scheduling(
        source, ("SetRelaunchClients", "RelaunchClients")
    )

    command = actions["SetRelaunchClients"].get("Value")
    assert command.startswith(
        '"[System64Folder]WindowsPowerShell\\v1.0\\powershell.exe" -NoProfile'
    )
    assert (
        "Get-ScheduledTask -TaskName 'NeutrinoClientRelaunch_*' "
        "-ErrorAction SilentlyContinue | Start-ScheduledTask" in command
    )
    assert actions["RelaunchClients"].get("DllEntry") == "WixQuietExec"
    assert actions["RelaunchClients"].get("Impersonate") == "no"
    assert actions["RelaunchClients"].get("Return") == "ignore"
    assert scheduled["RelaunchClients"].get("After") == "SecureClientData"
    assert scheduled["RelaunchClients"].get("Condition") == 'NOT REMOVE~="ALL"'


def test_a_removal_deletes_every_relaunch_task_but_an_upgrades_removal_keeps_them(
    source,
):
    actions, scheduled = actions_and_scheduling(
        source, ("SetForgetRelaunches", "ForgetRelaunches")
    )

    command = actions["SetForgetRelaunches"].get("Value")
    assert "Unregister-ScheduledTask -Confirm:$false" in command
    assert scheduled["ForgetRelaunches"].get("Condition") == (
        'REMOVE~="ALL" AND NOT UPGRADINGPRODUCTCODE'
    )
    assert actions["ForgetRelaunches"].get("Impersonate") == "no"
