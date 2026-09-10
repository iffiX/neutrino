"""What the Windows installer declares, read off its generated source.

wix is not run here — it needs Windows and the .NET tool — so what is
asserted is the document the build writes: a product identity of its own, no
service, no autostart Run entry, the
PATH entry, the shortcut, and the bootstrapper chained only where the
runtime's key is absent. The payload's own laying out is checked with the
downloads faked.
"""

import xml.etree.ElementTree

import pytest

import build_msi
import payload

# The agent's own upgrade code, which this one must not be.
AGENT_UPGRADE_CODE = "9F4E4A1C-9C0B-4C0E-9E2E-6C5A2C7C1E33"


@pytest.fixture
def source():
    """The .wxs the build writes, with the staged paths stood in for."""
    staged = {
        "payload": "C:\\build\\payload",
        "bootstrapper": "C:\\build\\MicrosoftEdgeWebview2Setup.exe",
        "icon": "C:\\build\\neutrino_client.ico",
    }
    return build_msi._wix_source(staged, "9.9.9", "iffiX <someone@example.com>")


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
        root.find("{http://wixtoolset.org/schemas/v4/wxs}Package").get("Manufacturer")
        == "iffiX <someone@example.com>"
    )


def test_a_running_resident_is_closed_before_its_files_are_replaced(source):
    """An upgrade over a live resident is what lands half-applied."""
    root = xml.etree.ElementTree.fromstring(source)
    closes = list(
        root.iter("{http://wixtoolset.org/schemas/v4/wxs/util}CloseApplication")
    )
    assert len(closes) == 1
    assert closes[0].get("Target") == build_msi.RESIDENT_IMAGE
    assert closes[0].get("RebootPrompt") == "no"
    assert build_msi.RESIDENT_IMAGE.endswith(".exe")


def test_the_build_loads_the_extension_that_element_comes_from():
    assert build_msi.WIX_UTIL_EXTENSION.startswith("WixToolset.Util.wixext/")
    assert "wix extension add" in build_msi.__doc__


def test_the_installer_registers_no_autostart(source):
    """The client runs when the person opens it, not with the session."""
    assert r"Software\Microsoft\Windows\CurrentVersion\Run" not in source
    assert "gui --hidden" not in source
    assert not hasattr(build_msi, "RUN_ENTRY_VALUE")


def test_the_install_goes_on_the_path(source):
    assert '<Environment Id="ClientPath"' in source
    assert 'Name="PATH"' in source
    assert 'Value="[INSTALLFOLDER]"' in source
    assert 'System="yes"' in source


def test_the_start_menu_shortcut_opens_the_window(source):
    assert 'Name="Neutrino Client"' in source
    assert "-m neutrino_client.cli.entry gui" in source


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


def test_the_embeddable_interpreter_is_opened_to_the_client_beside_it(tmp_path):
    python_dir = tmp_path / "python"
    python_dir.mkdir()
    (python_dir / "python313._pth").write_text("python313.zip\n.\n", encoding="utf-8")

    build_msi._open_import_path(python_dir)

    assert (python_dir / "python313._pth").read_text().splitlines() == [
        "python313.zip",
        ".",
        "..",
        "..\\lib",
    ]


def test_an_interpreter_with_no_import_file_is_refused(tmp_path):
    with pytest.raises(SystemExit) as refused:
        build_msi._open_import_path(tmp_path)

    assert "._pth" in str(refused.value)


def test_the_licences_travel_beside_the_payload(tmp_path):
    build_msi._stage_licenses(tmp_path)

    carried = tmp_path / "licenses"
    assert sorted(path.name for path in carried.iterdir()) == [
        "cc_switch.txt",
        "rustdesk.txt",
    ]


def test_the_console_wrapper_runs_the_carried_interpreter():
    assert "python\\python.exe" in build_msi.CONSOLE_WRAPPER
    assert "neutrino_client.cli.entry" in build_msi.CONSOLE_WRAPPER


def test_the_windows_wheels_are_pinned_to_the_file():
    for _name, _version, url, digest in build_msi.WINDOWS_WHEELS:
        assert url.startswith("https://files.pythonhosted.org/")
        assert len(digest) == 64
    for machine in ("amd64", "arm64"):
        _name, _version, url, digest = build_msi.WINDOWS_CFFI[machine]
        assert machine in url
        assert len(digest) == 64
        assert len(build_msi.WINDOWS_PYTHON_SHA256[machine]) == 64
