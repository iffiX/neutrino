"""The tree each Linux package lays down, with the carried parts faked.

Fetching an interpreter needs a build container; what it produces is stood
in for here, so what is asserted is the shape around it — where the payload
goes, what runs it, and what the package still asks the machine for.
"""

import pytest

import build_deb
import build_rpm
import payload


@pytest.fixture
def carried(monkeypatch):
    """A staged interpreter and desktop host, without fetching either.

    Returns:
        What each build asked to be compiled, and where it is installed.
    """
    compiled = []

    def stage(staged_python, architecture):
        (staged_python / "bin").mkdir(parents=True)
        (staged_python / "bin" / "python3").write_text("")
        (staged_python / "lib" / "python3.13" / "site-packages").mkdir(parents=True)

    def compile_bytecode(staged_python, install_python):
        compiled.append((staged_python, install_python))

    def stage_rustdesk(tree, architecture, kind):
        vendor = tree / str(payload.RUSTDESK_VENDOR_DIR).lstrip("/")
        vendor.mkdir(parents=True)
        (vendor / "rustdesk").write_text("")
        link = tree / payload.RUSTDESK_LINK
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(payload.RUSTDESK_VENDOR_DIR / "rustdesk")

    for module in (build_deb, build_rpm):
        monkeypatch.setattr(module.payload, "stage_linux_interpreter", stage)
        monkeypatch.setattr(module.payload, "compile_bytecode", compile_bytecode)
        monkeypatch.setattr(module.payload, "stage_rustdesk", stage_rustdesk)
    return compiled


def test_the_deb_puts_the_agent_inside_the_interpreter_it_carries(tmp_path, carried):
    build_deb._lay_out(tmp_path, "9.9.9", "amd64", "somebody")

    package = (
        tmp_path
        / "opt/neutrino_agent/python/lib/python3.13/site-packages/neutrino_agent"
    )
    assert (package / "cli" / "entry.py").is_file()
    assert 'AGENT_VERSION = "9.9.9"' in (package / "_version.py").read_text()


def test_the_deb_entry_point_runs_the_carried_interpreter(tmp_path, carried):
    """Never the machine's own."""
    build_deb._lay_out(tmp_path, "9.9.9", "amd64", "somebody")

    wrapper = (tmp_path / "usr/bin/nagent").read_text()

    assert (
        "exec /opt/neutrino_agent/python/bin/python3 -m neutrino_agent.cli.entry"
        in (wrapper)
    )
    assert "/usr/bin/python3" not in wrapper


def test_the_deb_asks_for_systemd_and_no_python(tmp_path, carried):
    """The interpreter is the package's own; what the machine still owes is
    the init system that runs the service, and the C libraries the desktop
    host loads."""
    build_deb._lay_out(tmp_path, "9.9.9", "amd64", "somebody")

    control = (tmp_path / "DEBIAN/control").read_text()

    assert "Architecture: amd64" in control
    assert "Depends: systemd" in control
    assert "libgtk-3-0t64 | libgtk-3-0" in control
    assert "gstreamer1.0-pipewire" in control
    assert "Recommends" not in control
    assert "python3" not in control.split("Description:")[0]


def test_the_deb_carries_both_units_and_nothing_for_a_desktop(tmp_path, carried):
    build_deb._lay_out(tmp_path, "9.9.9", "amd64", "somebody")

    assert (tmp_path / "lib/systemd/system/neutrino_agent.service").is_file()
    unit = (tmp_path / "lib/systemd/system/rustdesk.service").read_text()
    assert "ExecStart=/opt/neutrino_agent/vendor/rustdesk/rustdesk --service" in unit
    assert not (tmp_path / "usr/share/applications").exists()
    assert not (tmp_path / "usr/share/icons").exists()


def test_the_deb_starts_the_desktop_host_and_stops_it_on_removal(tmp_path, carried):
    """RustDesk's own code runs `systemctl enable rustdesk`, so the unit is
    named that and no other."""
    build_deb._lay_out(tmp_path, "9.9.9", "amd64", "somebody")

    postinst = (tmp_path / "DEBIAN/postinst").read_text()
    prerm = (tmp_path / "DEBIAN/prerm").read_text()

    assert "systemctl enable --now rustdesk.service" in postinst
    assert "systemctl stop rustdesk.service" in prerm


def test_the_deb_carries_the_licence_of_what_it_ships(tmp_path, carried):
    build_deb._lay_out(tmp_path, "9.9.9", "amd64", "somebody")

    licence = tmp_path / "usr/share/doc/neutrino-agent/licenses/rustdesk.txt"

    assert "GNU AFFERO GENERAL PUBLIC LICENSE" in licence.read_text()
    assert "https://github.com/rustdesk/rustdesk/tree/1.4.9" in licence.read_text()


def test_the_deb_compiles_the_tree_at_the_path_it_installs_it_at(tmp_path, carried):
    """Bytecode the package ships is bytecode the package replaces."""
    build_deb._lay_out(tmp_path, "9.9.9", "amd64", "somebody")

    assert carried == [(tmp_path / "opt/neutrino_agent/python", payload.PYTHON_DIR)]


def test_the_deb_prunes_what_the_package_did_not_install(tmp_path, carried):
    """dpkg's own file list says what the package put under the prefix."""
    build_deb._lay_out(tmp_path, "9.9.9", "amd64", "somebody")

    postinst = (tmp_path / "DEBIAN/postinst").read_text()

    assert payload.PRUNE_UNTRACKED in postinst
    assert "/var/lib/dpkg/info/neutrino-agent.list" in postinst
    assert "prune_untracked /opt/neutrino_agent" in postinst


def test_the_rpm_prunes_from_its_own_file_list_after_the_transaction(tmp_path, carried):
    build_rpm._lay_out(tmp_path, "9.9.9", "x86_64")
    spec = _spec()

    assert payload.PRUNE_UNTRACKED in spec
    assert "%posttrans" in spec
    assert "rpm -ql neutrino-agent | prune_untracked /opt/neutrino_agent" in spec
    assert carried == [(tmp_path / "opt/neutrino_agent/python", payload.PYTHON_DIR)]


def test_the_deb_removes_its_own_payload_and_never_the_hub_s(tmp_path, carried):
    """A machine may run both, and /opt/neutrino is the hub package's."""
    build_deb._lay_out(tmp_path, "9.9.9", "amd64", "somebody")

    postrm = (tmp_path / "DEBIAN/postrm").read_text()
    postinst = (tmp_path / "DEBIAN/postinst").read_text()

    assert "rm -rf /opt/neutrino_agent" in postrm
    assert "rm -rf /opt/neutrino\n" not in postrm
    assert "rm -rf" not in postinst
    assert "prune_untracked /opt/neutrino\n" not in postinst


@pytest.mark.parametrize(
    "architecture, named", [("amd64", "amd64"), ("arm64", "arm64")]
)
def test_the_deb_names_the_machine_it_was_built_for(
    tmp_path, carried, architecture, named
):
    build_deb._lay_out(tmp_path, "9.9.9", named, "somebody")

    assert f"Architecture: {named}" in (tmp_path / "DEBIAN/control").read_text()


def test_the_rpm_lays_the_same_payload_under_the_same_prefix(tmp_path, carried):
    build_rpm._lay_out(tmp_path, "9.9.9", "x86_64")

    package = (
        tmp_path
        / "opt/neutrino_agent/python/lib/python3.13/site-packages/neutrino_agent"
    )
    assert 'AGENT_VERSION = "9.9.9"' in (package / "_version.py").read_text()
    assert (tmp_path / "usr/lib/systemd/system/neutrino_agent.service").is_file()
    assert (tmp_path / "usr/lib/systemd/system/rustdesk.service").is_file()
    assert (tmp_path / "opt/neutrino_agent/vendor/rustdesk/rustdesk").is_file()
    assert not (tmp_path / "usr/share/applications").exists()
    wrapper = (tmp_path / "usr/bin/nagent").read_text()
    assert "/opt/neutrino_agent/python/bin/python3" in wrapper
    assert "PYTHONPATH" not in wrapper


def _spec(architecture="aarch64"):
    """The spec as the build writes it.

    Args:
        architecture: The machine to name in it.

    Returns:
        The rendered spec file.
    """
    return build_rpm.SPEC.format(
        name="neutrino-agent",
        version="9.9.9",
        architecture=architecture,
        requires="\n".join(f"Requires:       {n}" for n in build_rpm.RUNTIME_REQUIRES),
        packager="somebody",
        staged="/staged",
        prefix=payload.INSTALL_PREFIX,
        unit_dir=build_rpm.UNIT_DIR,
        rustdesk_link=payload.RUSTDESK_LINK,
        rustdesk_unit=payload.RUSTDESK_UNIT_NAME,
        prune=payload.PRUNE_UNTRACKED,
    )


def test_the_rpm_spec_names_the_machine_and_asks_for_no_python():
    """A payload with an interpreter in it is not noarch any more."""
    spec = _spec()

    assert "BuildArch:      aarch64" in spec
    assert "noarch" not in spec
    assert "Requires:       systemd" in spec
    assert "Requires:       gtk3" in spec
    assert "Requires:       pipewire-gstreamer" in spec
    assert "Requires:       python3" not in spec
    assert "Recommends" not in spec
    assert "/opt/neutrino_agent" in spec


def test_the_rpm_owns_the_desktop_host_it_carries():
    spec = _spec()

    assert "/usr/bin/rustdesk" in spec
    assert "/usr/lib/systemd/system/rustdesk.service" in spec
    assert "/usr/share/doc/neutrino-agent" in spec
    assert "systemctl enable --now rustdesk.service" in spec
    assert "systemctl stop rustdesk.service" in spec


def test_the_packages_replace_the_upstream_rustdesk_package():
    assert "Conflicts: rustdesk\nReplaces: rustdesk\n" in build_deb.CONTROL
    assert "Conflicts:      rustdesk" in build_rpm.SPEC
