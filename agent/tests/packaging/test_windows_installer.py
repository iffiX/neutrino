"""What the Windows installer declares, and what it lets the interpreter see.

Assembling the .msi needs WiX on Windows; the source it is assembled from is
generated here, and so is the import path the embeddable interpreter reads.
"""

import xml.sax.saxutils

import pytest

import build_msi
from neutrino_agent.constants import (
    AGENT_SERVICE_DISPLAY_NAME_WINDOWS,
    AGENT_SERVICE_NAME_WINDOWS,
)


def source(machine: str = "amd64") -> str:
    """The installer source as the build writes it.

    Args:
        machine: ``amd64`` or ``arm64``.

    Returns:
        The WiX source, with every placeholder filled.
    """
    return (
        build_msi.WIX_SOURCE.replace("@VERSION@", "9.9.9")
        .replace("@PUBLISHER@", "somebody")
        .replace("@UPGRADE_CODE@", build_msi.UPGRADE_CODE)
        .replace("@PAYLOAD@", r"C:\stage\payload")
        .replace("@SERVICE_HOST@", r"C:\stage\pythonw.exe")
        .replace("@BOOTSTRAPPER@", r"C:\stage\MicrosoftEdgeWebview2Setup.exe")
        .replace("@BOOTSTRAPPER_NAME@", build_msi.WEBVIEW2_BOOTSTRAPPER_NAME)
        .replace("@ICON@", r"C:\stage\neutrino_agent.ico")
        .replace("@SERVICE_NAME@", AGENT_SERVICE_NAME_WINDOWS)
        .replace("@SERVICE_DISPLAY_NAME@", AGENT_SERVICE_DISPLAY_NAME_WINDOWS)
        .replace("@WEBVIEW2_KEY@", build_msi.WEBVIEW2_REGISTRY_KEY)
    )


def test_the_installer_registers_a_service_and_not_a_task():
    """The agent answers the service control manager itself, so residency is
    a service the installer registers, starts and removes."""
    written = source()

    assert f'Name="{AGENT_SERVICE_NAME_WINDOWS}"' in written
    assert f'DisplayName="{AGENT_SERVICE_DISPLAY_NAME_WINDOWS}"' in written
    assert 'Start="auto"' in written
    assert "<ServiceControl" in written
    assert 'Start="install"' in written and 'Remove="uninstall"' in written
    assert "ScheduledTask" not in written


def test_the_service_starts_the_agent_behind_the_handshake():
    """What the manager launches is the same entry a person runs, with the
    one flag that says a manager is waiting to be answered."""
    written = source()

    assert 'Arguments="-m neutrino_agent.cli.entry run --windows-service"' in written


def test_the_installer_chains_the_webview2_bootstrapper_only_when_it_is_absent():
    """Windows 11 and an updated Windows 10 carry the runtime; LTSC and
    Server do not, and that is the only case this has anything to do."""
    written = source()

    assert build_msi.WEBVIEW2_REGISTRY_KEY in written
    assert 'ExeCommand="/silent /install"' in written
    assert 'Condition="NOT WEBVIEW2INSTALLED AND NOT REMOVE"' in written
    assert 'Return="ignore"' in written


def test_the_installer_carries_the_icon_for_the_window_and_the_program_entry():
    written = source()

    assert '<Icon Id="AgentIcon"' in written
    assert '<Property Id="ARPPRODUCTICON" Value="AgentIcon" />' in written
    assert 'Icon="AgentIcon"' in written


def test_the_shortcut_opens_the_window_through_the_carried_interpreter():
    written = source()

    assert r'Target="[INSTALLFOLDER]python\pythonw.exe"' in written
    assert 'Arguments="-m neutrino_agent.cli.entry gui"' in written


def test_the_upgrade_code_is_the_one_identity_across_versions():
    """Changing it makes an upgrade install beside the old one."""
    assert build_msi.UPGRADE_CODE == "9F4E4A1C-9C0B-4C0E-9E2E-6C5A2C7C1E33"
    assert "<MajorUpgrade" in source()


def test_both_machines_have_a_pinned_interpreter_and_a_pinned_cffi():
    """Everything compiled is per machine; nothing is fetched unpinned."""
    assert sorted(build_msi.WINDOWS_PYTHON_SHA256) == ["amd64", "arm64"]
    assert sorted(build_msi.WINDOWS_CFFI) == ["amd64", "arm64"]
    for _, _, url, digest in build_msi.WINDOWS_WHEELS:
        assert url.startswith("https://files.pythonhosted.org/")
        assert len(digest) == 64


def test_the_shell_chain_is_carried_whole():
    """pywebview reaches WebView2 through pythonnet, which reaches .NET
    through clr-loader and cffi; a missing link is an import error in a
    window nobody can open."""
    carried = {name for name, _, _, _ in build_msi.WINDOWS_WHEELS}

    assert carried == {
        "pywebview",
        "pythonnet",
        "clr-loader",
        "pycparser",
        "bottle",
        "typing_extensions",
        "proxy_tools",
    }


def test_the_interpreter_sees_the_agent_and_the_vendored_packages(tmp_path):
    """The embeddable package reads its ._pth and ignores PYTHONPATH, so
    everything beside it is invisible until that file says otherwise."""
    (tmp_path / "python313._pth").write_text(
        "python313.zip\n.\n\n# Uncomment to run site.main() automatically\n#import site\n"
    )

    build_msi._open_import_path(tmp_path)

    lines = (tmp_path / "python313._pth").read_text().splitlines()
    assert lines[:4] == ["python313.zip", ".", "..", "..\\lib"]


def test_an_interpreter_whose_path_file_is_not_the_expected_shape_is_refused(tmp_path):
    (tmp_path / "python313._pth").write_text("python313.zip\n")

    with pytest.raises(SystemExit):
        build_msi._open_import_path(tmp_path)


def test_an_interpreter_with_no_path_file_at_all_is_refused(tmp_path):
    with pytest.raises(SystemExit):
        build_msi._open_import_path(tmp_path)


def test_a_publisher_with_an_address_stays_a_name_and_not_markup():
    """The default publisher carries an address in angle brackets, and every
    value lands inside an XML attribute: unescaped it is a source file WiX
    cannot read at all."""
    import xml.etree.ElementTree as ElementTree

    source = build_msi.WIX_SOURCE.replace(
        "@PUBLISHER@", xml.sax.saxutils.escape("iffiX <someone@example.com>")
    )
    source = (
        source.replace("@VERSION@", "9.9.9")
        .replace("@UPGRADE_CODE@", build_msi.UPGRADE_CODE)
        .replace("@PAYLOAD@", r"C:\stage\payload")
        .replace("@SERVICE_HOST@", r"C:\stage\host.exe")
        .replace("@BOOTSTRAPPER@", r"C:\stage\web.exe")
        .replace("@BOOTSTRAPPER_NAME@", build_msi.WEBVIEW2_BOOTSTRAPPER_NAME)
        .replace("@ICON@", r"C:\stage\icon.ico")
        .replace("@SERVICE_NAME@", AGENT_SERVICE_NAME_WINDOWS)
        .replace("@SERVICE_DISPLAY_NAME@", AGENT_SERVICE_DISPLAY_NAME_WINDOWS)
        .replace("@WEBVIEW2_KEY@", build_msi.WEBVIEW2_REGISTRY_KEY)
    )

    tree = ElementTree.fromstring(source)

    package = tree.find("{http://wixtoolset.org/schemas/v4/wxs}Package")
    assert package.get("Manufacturer") == "iffiX <someone@example.com>"


def test_the_service_host_lives_beside_the_interpreter_it_is():
    """A copy of pythonw.exe finds python3xx.dll and the ._pth in its own
    directory and nowhere else. Placed at the install root it exits before
    reaching the service control manager, which then reports a start timeout
    and the installer rolls back. Found on a rented Windows Server 2025."""
    written = source()

    assert 'Id="ServiceHost" Guid="*" Subdirectory="python"' in written


def test_the_service_host_is_the_interpreter_under_its_own_name():
    """Not a renamed copy. An interpreter under another name, registered as
    a service, is the shape of a Python trojan; 360 flagged the first build
    on sight, and it would have on any machine."""
    written = source()

    assert 'Name="pythonw.exe"' in written
    assert "neutrino_agent_service" not in written
