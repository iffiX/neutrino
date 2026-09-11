"""What the Windows installer declares, read off its generated source.

wix is not run here — it needs Windows and the .NET tool — and neither is
the compiler, so what is asserted is the document the build writes and the
command the compile is given: a product identity of its own, no
service, no autostart Run entry, the shortcut, the quit that comes before
anything ends a resident and opens no window doing it, the two questions and
what they answer to unasked, and the bootstrapper chained only where the
runtime's key is absent. The payload's own laying out is checked with the
downloads faked.
"""

import inspect
import subprocess
import xml.etree.ElementTree
from pathlib import Path

import pytest

import build_msi
import payload

# The agent's own upgrade code, which this one must not be.
AGENT_UPGRADE_CODE = "9F4E4A1C-9C0B-4C0E-9E2E-6C5A2C7C1E33"

# The two namespaces the document is written in.
WXS = "{http://wixtoolset.org/schemas/v4/wxs}"
UTIL = "{http://wixtoolset.org/schemas/v4/wxs/util}"


@pytest.fixture
def source():
    """The .wxs the build writes, with the staged paths stood in for."""
    staged = {
        "payload": "C:\\build\\payload",
        "bootstrapper": "C:\\build\\MicrosoftEdgeWebview2Setup.exe",
        "icon": "C:\\build\\neutrino_client.ico",
        "license": "C:\\build\\license.rtf",
    }
    return build_msi._wix_source(
        staged, "9.9.9", "iffiX <someone@example.com>", "amd64"
    )


def test_the_installer_has_a_product_identity_of_its_own(source):
    assert build_msi.UPGRADE_CODE != AGENT_UPGRADE_CODE
    assert len(build_msi.UPGRADE_CODE) == 36
    assert build_msi.UPGRADE_CODE.count("-") == 4
    assert f'UpgradeCode="{build_msi.UPGRADE_CODE}"' in source
    assert 'Name="Neutrino Client"' in source
    assert 'Version="9.9.9"' in source


def test_the_installer_registers_no_service(source):
    """The client is a person's application, not a service."""
    assert "ServiceInstall" not in source
    assert "ServiceControl" not in source


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
        [build_msi.CLIENT_WINDOWED_BINARY_NAME, build_msi.CLIENT_BINARY_NAME]
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
    assert build_msi.QUIT_COMMAND == '"[INSTALLFOLDER]nclientw.exe" quit'
    assert "powershell" not in build_msi.QUIT_COMMAND.lower()


def test_the_two_programs_are_the_two_subsystems():
    """One executable cannot serve both: a windowed one started with pipes
    but no console loses the pipes (Nuitka's attach mode clobbers the
    inherited handles when AttachConsole fails), and a console one started
    from a shortcut opens a window. The same split python.exe and pythonw.exe
    make."""
    assert build_msi.CLIENT_BINARY_NAME == "nclient.exe"
    assert build_msi.CLIENT_WINDOWED_BINARY_NAME == "nclientw.exe"
    source = inspect.getsource(build_msi._compile)
    assert '"force"' in source
    assert '"disable"' in source
    assert "attach" not in inspect.getsource(build_msi._compile_one)


def test_the_quit_runs_before_the_close_that_ends_what_did_not_answer(source):
    """CostFinalize is earlier than InstallInitialize, where the close goes."""
    root = xml.etree.ElementTree.fromstring(source)
    scheduled = [
        custom
        for custom in root.iter(WXS + "Custom")
        if custom.get("Action") == "QuitClientResident"
    ]

    assert len(scheduled) == 1
    assert scheduled[0].get("After") == "CostFinalize"
    assert scheduled[0].get("Condition") == "Installed OR WIX_UPGRADE_DETECTED"
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
    assert removals[0].get("Condition") == build_msi.CONFIG_GOES_CONDITION
    assert 'REMOVE~="ALL"' in build_msi.CONFIG_GOES_CONDITION


def test_a_kept_configuration_is_the_one_value_rather_than_a_true_reading():
    """A property set to "0" is a non-empty string, which the installer reads
    as true, so `NOT ISCONFIGKEPT` would take a configuration that was asked
    to stay."""
    assert 'ISCONFIGKEPT <> "1"' in build_msi.CONFIG_GOES_CONDITION
    assert "NOT ISCONFIGKEPT" not in build_msi.CONFIG_GOES_CONDITION


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
    assert build_msi.CLIENT_CONFIG_DIR_NAME in build_msi.REMOVE_CONFIG_COMMAND
    assert "AppDataFolder" in build_msi.REMOVE_CONFIG_COMMAND


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
    assert build_msi.WIX_UTIL_EXTENSION.startswith("WixToolset.Util.wixext/")
    assert build_msi.WIX_UI_EXTENSION.startswith("WixToolset.UI.wixext/")
    assert "wix extension add" in build_msi.__doc__


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
    assert not hasattr(build_msi, "RUN_ENTRY_VALUE")


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
    assert levels[0].get("Condition") == build_msi.PATH_DECLINED_CONDITION
    assert 'ISPATHADDED <> "1"' in build_msi.PATH_DECLINED_CONDITION


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
    assert build_msi.WEBVIEW2_REGISTRY_KEY in source
    assert 'Condition="NOT WEBVIEW2INSTALLED AND NOT REMOVE"' in source
    assert 'ExeCommand="/silent /install"' in source


def test_a_publisher_with_an_address_stays_a_name(source):
    assert "iffiX &lt;someone@example.com&gt;" in source
    assert "<someone@example.com>" not in source


def test_the_package_is_named_for_the_platform_it_installs_on():
    assert build_msi.MSI_PLATFORMS == {"amd64": "x64", "arm64": "arm64"}
    assert build_msi.WINDOWS_MACHINES["x86_64"] == "amd64"
    assert payload.PACKAGE_NAME == "neutrino-client"


def test_the_build_refuses_another_interpreter_than_the_pinned_one(monkeypatch):
    """What runs the script is what the client is compiled against."""
    monkeypatch.setattr(build_msi.sys, "version_info", (3, 12, 4, "final", 0))

    with pytest.raises(SystemExit) as refused:
        build_msi._check_build_machine("amd64")

    assert "3.13" in str(refused.value)


def test_the_build_refuses_a_machine_this_is_not(monkeypatch):
    """The compile is native: an arm64 installer comes off an arm64 box."""
    monkeypatch.setattr(build_msi.sys, "version_info", (3, 13, 7, "final", 0))
    monkeypatch.setattr(build_msi.platform, "machine", lambda: "AMD64")

    build_msi._check_build_machine("amd64")
    with pytest.raises(SystemExit) as refused:
        build_msi._check_build_machine("arm64")

    assert "arm64" in str(refused.value)


def test_the_compile_names_what_a_scanner_would_otherwise_find(monkeypatch, tmp_path):
    """Standalone, the package and its window backend included, the other
    platforms' backends kept out so the plugin and the user agree, the icon
    and the version in the binary; twice, one subsystem each, with the
    windowed executable taken into the console program's directory."""
    commands = []

    def fake_run(command, env=None):
        commands.append((command, env))
        build = Path(command[-2].split("=", 1)[1])
        name = command[-3].split("=", 1)[1]
        dist = build / "entry.dist"
        dist.mkdir(parents=True, exist_ok=True)
        (dist / name).write_bytes(b"MZ" + name.encode())
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(build_msi.subprocess, "run", fake_run)
    monkeypatch.setattr(build_msi.icons, "write_ico", lambda path: path)
    tree = tmp_path / "tree"
    (tree / "neutrino_client" / "cli").mkdir(parents=True)

    dist = build_msi._compile(Path("python.exe"), tree, tmp_path / "build", "9.9.9")

    assert dist == tmp_path / "build" / "console" / "entry.dist"
    assert (dist / "nclient.exe").read_bytes() == b"MZnclient.exe"
    assert (dist / "nclientw.exe").read_bytes() == b"MZnclientw.exe"
    (console, environment), (windowed, _) = commands
    for command in (console, windowed):
        assert command[:3] == ["python.exe", "-m", "nuitka"]
        assert "--standalone" in command
        assert "--include-package=neutrino_client" in command
        assert "--include-package=webview" in command
        for backend in build_msi.NUITKA_EXCLUDED_BACKENDS:
            assert f"--nofollow-import-to={backend}" in command
        assert "--product-version=9.9.9" in command
        assert command[-1] == str(tree / "neutrino_client" / "cli" / "entry.py")
    assert "--windows-console-mode=force" in console
    assert "--output-filename=nclient.exe" in console
    assert "--windows-console-mode=disable" in windowed
    assert "--output-filename=nclientw.exe" in windowed
    assert environment["PYTHONPATH"] == str(tree)


def test_a_compile_that_writes_no_binary_is_refused(monkeypatch, tmp_path):
    monkeypatch.setattr(
        build_msi.subprocess,
        "run",
        lambda command, env=None: subprocess.CompletedProcess(command, 0),
    )
    monkeypatch.setattr(build_msi.icons, "write_ico", lambda path: path)

    with pytest.raises(SystemExit) as refused:
        build_msi._compile(Path("python.exe"), tmp_path, tmp_path / "build", "1")

    assert build_msi.CLIENT_BINARY_NAME in str(refused.value)


def test_the_licences_travel_beside_the_payload(tmp_path):
    build_msi._stage_licenses(tmp_path)

    carried = tmp_path / "licenses"
    assert sorted(path.name for path in carried.iterdir()) == [
        "cc_switch.txt",
        "rustdesk.txt",
    ]


def test_the_payload_carries_no_wrapper_script_and_no_interpreter_of_its_own():
    """The binary is the command; a .cmd beside a carried python.exe was
    the shape before."""
    assert not hasattr(build_msi, "CONSOLE_WRAPPER_NAME")
    assert not hasattr(build_msi, "WINDOWS_PYTHON_URL")
    assert build_msi.BUILD_PYTHON_VERSION == (3, 13)
    assert build_msi.CLIENT_BINARY_NAME == "nclient.exe"


def test_the_windows_wheels_are_pinned_to_the_file():
    for _name, _version, url, digest in build_msi.WINDOWS_WHEELS:
        assert url.startswith("https://files.pythonhosted.org/")
        assert len(digest) == 64
    for machine in ("amd64", "arm64"):
        _name, _version, url, digest = build_msi.WINDOWS_CFFI[machine]
        assert machine in url
        assert len(digest) == 64
