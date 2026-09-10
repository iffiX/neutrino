"""The tree each Linux package lays down, with the carried parts faked.

Fetching an interpreter and a viewer needs a build container; what they
produce is stood in for here, so what is asserted is the shape around them —
where the payload goes, what runs it, what the desktop gets, the root helper
and the policy that gates it, that no unit is registered at all, and what the
package still asks the machine for.
"""

import pytest

import build_deb
import build_rpm
import payload


@pytest.fixture
def carried(monkeypatch):
    """A staged interpreter, bindings and binaries, without fetching any.

    Returns:
        What each build asked to be compiled, and where it is installed.
    """
    compiled = []

    def stage(staged_python, architecture):
        (staged_python / "bin").mkdir(parents=True)
        (staged_python / "bin" / "python3").write_text("")
        (staged_python / "lib" / "python3.13" / "site-packages").mkdir(parents=True)

    def stage_bindings(staged_python):
        return None

    def compile_bytecode(staged_python, install_python):
        compiled.append((staged_python, install_python))

    def stage_binaries(tree, architecture):
        prefix = tree / str(payload.INSTALL_PREFIX).lstrip("/")
        (prefix / "bin").mkdir(parents=True, exist_ok=True)
        (prefix / "bin" / "cc-switch").write_text("")
        (prefix / "rustdesk" / "lib").mkdir(parents=True, exist_ok=True)
        (prefix / "rustdesk" / "rustdesk").write_text("")

    for module in (build_deb, build_rpm):
        monkeypatch.setattr(module.payload, "stage_linux_interpreter", stage)
        monkeypatch.setattr(module.payload, "stage_linux_gui_bindings", stage_bindings)
        monkeypatch.setattr(module.payload, "compile_bytecode", compile_bytecode)
        monkeypatch.setattr(module.bundled, "stage_linux_binaries", stage_binaries)
    return compiled


@pytest.fixture
def deb(tmp_path, carried):
    """One laid-out .deb tree."""
    build_deb._lay_out(tmp_path, "9.9.9", "amd64", "somebody")
    return tmp_path


@pytest.fixture
def rpm(tmp_path, carried):
    """One laid-out .rpm tree."""
    build_rpm._lay_out(tmp_path, "9.9.9", "x86_64")
    return tmp_path


def test_the_deb_puts_the_client_inside_the_interpreter_it_carries(deb):
    package = (
        deb / "opt/neutrino_client/python/lib/python3.13/site-packages/neutrino_client"
    )

    assert (package / "cli" / "entry.py").is_file()
    assert 'CLIENT_VERSION = "9.9.9"' in (package / "_version.py").read_text()


def test_the_deb_entry_point_runs_the_carried_interpreter(deb):
    """Never the machine's own."""
    wrapper = (deb / "usr/bin/nclient").read_text()

    assert (
        "exec /opt/neutrino_client/python/bin/python3 -m neutrino_client.cli.entry"
        in wrapper
    )
    assert "/usr/bin/python3" not in wrapper


def test_the_deb_registers_no_unit_at_all(deb):
    """The client is a person's application, not a service."""
    assert not (deb / "lib/systemd/system").exists()
    assert not (deb / "usr/lib/systemd/system").exists()
    for script in ("postinst", "postrm"):
        assert "systemctl" not in (deb / "DEBIAN" / script).read_text()
    assert not (deb / "DEBIAN/prerm").exists()


def test_the_deb_lays_down_the_launcher_and_the_autostart_entry(deb):
    launcher = deb / "usr/share/applications/neutrino_client.desktop"
    autostart = deb / "etc/xdg/autostart/neutrino_client.desktop"

    assert "Exec=nclient gui\n" in launcher.read_text()
    assert "Exec=nclient gui --hidden" in autostart.read_text()
    assert launcher.stat().st_mode & 0o777 == 0o644


def test_the_deb_carries_both_icon_sizes_under_the_installed_name(deb):
    for edge in (48, 256):
        icon = deb / f"usr/share/icons/hicolor/{edge}x{edge}/apps/neutrino_client.png"
        assert icon.is_file()
        assert icon.read_bytes().startswith(b"\x89PNG")


def test_the_deb_lays_down_the_mount_helper_and_the_policy_that_gates_it(deb):
    helper = deb / "usr/libexec/neutrino_client/mount_helper"
    policy = deb / "usr/share/polkit-1/actions/com.neutrino.client.mount.policy"

    assert helper.stat().st_mode & 0o777 == 0o755
    assert helper.read_text().splitlines() == [
        "#!/bin/sh",
        "exec /opt/neutrino_client/python/bin/python3 "
        '-m neutrino_client.cli.mount_helper "$@"',
    ]
    assert '<action id="com.neutrino.client.mount">' in policy.read_text()
    assert "/usr/libexec/neutrino_client/mount_helper" in policy.read_text()


def test_the_deb_carries_the_binaries_the_client_drives(deb):
    assert (deb / "opt/neutrino_client/bin/cc-switch").is_file()
    assert (deb / "opt/neutrino_client/rustdesk/rustdesk").is_file()


def test_the_deb_carries_the_licences_of_both(deb):
    carried = deb / "usr/share/doc/neutrino-client/licenses"

    assert sorted(path.name for path in carried.iterdir()) == [
        "cc_switch.txt",
        "rustdesk.txt",
    ]


def test_the_deb_names_the_c_stack_and_no_python(deb):
    control = (deb / "DEBIAN/control").read_text()

    assert "Architecture: amd64" in control
    assert "gir1.2-webkit2-4.1" in control
    assert "gir1.2-ayatanaappindicator3-0.1" in control
    assert "cifs-utils" in control
    assert "polkitd | policykit-1" in control
    assert "libgtk-3-0t64 | libgtk-3-0" in control
    assert "gstreamer1.0-pipewire" in control
    assert "python3" not in control.split("Description:")[0]


def test_the_deb_prunes_what_it_did_not_install(deb):
    postinst = (deb / "DEBIAN/postinst").read_text()

    assert "prune_untracked() {" in postinst
    assert "prune_untracked /opt/neutrino_client" in postinst


def test_the_bytecode_is_compiled_for_the_path_it_is_installed_at(tmp_path, carried):
    build_deb._lay_out(tmp_path, "9.9.9", "amd64", "somebody")

    staged_python, install_python = carried[0]
    assert install_python == payload.PYTHON_DIR


def test_the_rpm_lays_the_same_payload_under_the_same_prefix(rpm):
    package = (
        rpm / "opt/neutrino_client/python/lib/python3.13/site-packages/neutrino_client"
    )

    assert (package / "cli" / "entry.py").is_file()
    assert (rpm / "usr/bin/nclient").stat().st_mode & 0o777 == 0o755
    assert (rpm / "usr/libexec/neutrino_client/mount_helper").is_file()
    assert (
        rpm / "usr/share/polkit-1/actions/com.neutrino.client.mount.policy"
    ).is_file()
    assert (rpm / "etc/xdg/autostart/neutrino_client.desktop").is_file()


def test_the_rpm_registers_no_unit_either(rpm):
    assert not (rpm / "usr/lib/systemd/system").exists()
    assert "systemctl" not in build_rpm.SPEC


def test_the_rpm_names_the_fedora_libraries(rpm):
    assert "webkit2gtk4.1" in build_rpm.RUNTIME_REQUIRES
    assert "libayatana-appindicator-gtk3" in build_rpm.RUNTIME_REQUIRES
    assert "cifs-utils" in build_rpm.RUNTIME_REQUIRES
    assert "polkit" in build_rpm.RUNTIME_REQUIRES
    assert "pipewire-gstreamer" in build_rpm.RUNTIME_REQUIRES
    assert not [name for name in build_rpm.RUNTIME_REQUIRES if "python" in name]


def test_the_rpm_files_list_names_everything_the_package_lays_down():
    spec = build_rpm.SPEC.format(
        name="neutrino-client",
        version="9.9.9",
        architecture="x86_64",
        requires="",
        packager="somebody",
        staged="/staged",
        prefix=payload.INSTALL_PREFIX,
        helper="/usr/libexec/neutrino_client/mount_helper",
        desktop="neutrino_client",
        action="com.neutrino.client.mount",
        prune=payload.PRUNE_UNTRACKED,
    )
    files = spec.split("%files")[1].split("%post")[0]

    assert "/opt/neutrino_client" in files
    assert "/usr/bin/nclient" in files
    assert "/usr/libexec/neutrino_client/mount_helper" in files
    assert "/usr/share/applications/neutrino_client.desktop" in files
    assert "/etc/xdg/autostart/neutrino_client.desktop" in files
    assert "/usr/share/polkit-1/actions/com.neutrino.client.mount.policy" in files
    assert "/usr/share/doc/neutrino-client" in files
