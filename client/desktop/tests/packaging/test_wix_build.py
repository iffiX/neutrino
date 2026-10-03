"""The WiX pieces an installer adds to its body, read back as XML.

wix is not run here; what is asserted is the document the helpers write and
the command the build is given.
"""

import subprocess
import xml.etree.ElementTree

import pytest

from shared import wix_build

WXS = "{http://wixtoolset.org/schemas/v4/wxs}"
UTIL = "{http://wixtoolset.org/schemas/v4/wxs/util}"


def _document(body: str) -> xml.etree.ElementTree.Element:
    return xml.etree.ElementTree.fromstring(
        wix_build.package_source(
            name="Neutrino Agent",
            manufacturer="iffiX <someone@example.com>",
            version="9.9.9",
            upgrade_code="9F4E4A1C-9C0B-4C0E-9E2E-6C5A2C7C1E33",
            body=body,
        )
    )


def test_the_package_wraps_the_body_and_upgrades_over_earlier_versions():
    root = _document(wix_build.element("Property", {"Id": "X", "Value": "1"}))

    package = root.find(WXS + "Package")
    assert package.get("Name") == "Neutrino Agent"
    assert package.get("Manufacturer") == "iffiX <someone@example.com>"
    assert package.get("Scope") == "perMachine"
    assert package.find(WXS + "MajorUpgrade").get("DowngradeErrorMessage") == (
        "A newer Neutrino Agent is already installed."
    )
    assert package.find(WXS + "Property").get("Id") == "X"


def test_a_service_is_installed_controlled_and_permitted():
    body = wix_build.element(
        "StandardDirectory",
        {"Id": "ProgramFiles64Folder"},
        (
            wix_build.directory(
                "INSTALLFOLDER",
                "agent",
                (
                    wix_build.service_component(
                        component_id="AgentService",
                        source="C:\\build\\nagent.exe",
                        service_name="neutrino_agent",
                        display_name="Neutrino Agent",
                        description="Keeps this machine in step with its hub",
                        arguments="service run",
                        permissions=(wix_build.permission_ex("Administrators"),),
                    ),
                ),
            ),
        ),
    )
    root = _document(body)

    install = next(root.iter(WXS + "ServiceInstall"))
    assert install.get("Name") == "neutrino_agent"
    assert install.get("Account") == "LocalSystem"
    assert install.get("Start") == "auto"
    assert install.get("Arguments") == "service run"
    permission = next(install.iter(UTIL + "PermissionEx"))
    assert permission.get("User") == "Administrators"
    assert permission.get("GenericAll") == "yes"
    control = next(root.iter(WXS + "ServiceControl"))
    assert control.get("Name") == "neutrino_agent"
    assert (control.get("Start"), control.get("Stop"), control.get("Remove")) == (
        "install",
        "both",
        "uninstall",
    )
    assert next(root.iter(WXS + "File")).get("KeyPath") == "yes"
    assert next(root.iter(WXS + "Directory")).get("Name") == "agent"


def test_a_service_can_be_registered_and_left_stopped():
    """The hub's service is started by its setup, never by the install."""
    root = _document(
        wix_build.element(
            "StandardDirectory",
            {"Id": "ProgramFiles64Folder"},
            (
                wix_build.directory(
                    "INSTALLFOLDER",
                    "hub",
                    (
                        wix_build.service_component(
                            component_id="HubService",
                            source="C:\\build\\nhub.exe",
                            service_name="neutrino_hub",
                            display_name="Neutrino Hub",
                            description="The hub",
                            arguments="service run",
                            is_started_on_install=False,
                        ),
                    ),
                ),
            ),
        )
    )

    control = next(root.iter(WXS + "ServiceControl"))
    assert control.get("Start") is None
    assert (control.get("Stop"), control.get("Remove")) == ("both", "uninstall")
    assert next(root.iter(WXS + "ServiceInstall")).get("Start") == "auto"


def test_a_deferred_custom_action_runs_as_the_system_unless_asked():
    root = _document(
        wix_build.custom_action(
            "InstallRustDesk",
            FileRef="RustDeskExe",
            ExeCommand='--silent-install "quoted"',
        )
    )

    action = next(root.iter(WXS + "CustomAction"))
    assert action.get("Execute") == "deferred"
    assert action.get("Impersonate") == "no"
    assert action.get("Return") == "check"
    assert action.get("ExeCommand") == '--silent-install "quoted"'


def test_an_immediate_custom_action_carries_no_impersonation():
    action = wix_build.custom_action(
        "Quit", execute="immediate", is_failure_ignored=True, Directory="X"
    )

    assert "Impersonate" not in action
    assert 'Return="ignore"' in action


def test_fill_escapes_every_value():
    assert wix_build.fill('<A B="@V@" />', {"V": 'a "b" <c>'}) == (
        '<A B="a &quot;b&quot; &lt;c&gt;" />'
    )


def test_the_licence_becomes_rich_text(tmp_path):
    source = tmp_path / "LICENSE"
    source.write_text("one {braces}\ntwo \\ back\n")

    written = wix_build.write_license_rtf(source, tmp_path / "license.rtf")

    text = written.read_text(encoding="ascii")
    assert text.startswith("{\\rtf1")
    assert "one \\{braces\\}\\par\ntwo \\\\ back" in text


def test_a_missing_licence_is_refused(tmp_path):
    with pytest.raises(SystemExit):
        wix_build.write_license_rtf(tmp_path / "LICENSE", tmp_path / "license.rtf")


def test_the_build_names_the_platform_and_each_extension(monkeypatch, tmp_path):
    commands = []

    def run(command, capture_output, text):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(wix_build.shutil, "which", lambda name: "wix")
    monkeypatch.setattr(wix_build.subprocess, "run", run)

    wix_build.build(tmp_path / "a.wxs", tmp_path / "a.msi", "amd64")

    assert commands == [
        [
            "wix",
            "build",
            "-arch",
            "x64",
            "-ext",
            wix_build.WIX_UTIL_EXTENSION,
            "-ext",
            wix_build.WIX_UI_EXTENSION,
            "-out",
            str(tmp_path / "a.msi"),
            str(tmp_path / "a.wxs"),
        ]
    ]


def test_a_machine_without_wix_is_told_what_to_install(monkeypatch, tmp_path):
    monkeypatch.setattr(wix_build.shutil, "which", lambda name: None)

    with pytest.raises(SystemExit) as refused:
        wix_build.build(tmp_path / "a.wxs", tmp_path / "a.msi", "amd64")

    assert "dotnet tool install --global wix --version 6.0.2" in str(refused.value)
    assert f"wix extension add -g {wix_build.WIX_UI_EXTENSION}" in str(refused.value)
