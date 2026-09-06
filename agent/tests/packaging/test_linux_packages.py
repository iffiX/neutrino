"""The tree each Linux package lays down, with the carried parts faked.

Fetching an interpreter and compiling the window's bindings need a build
container; what they produce is stood in for here, so what is asserted is the
shape around them — where the payload goes, what runs it, and what the
package still asks the machine for.
"""

import pytest

import build_deb
import build_rpm
import payload


@pytest.fixture
def carried(monkeypatch):
    """A staged interpreter, without fetching or compiling one."""

    def stage(staged_python, architecture):
        (staged_python / "bin").mkdir(parents=True)
        (staged_python / "bin" / "python3").write_text("")
        (staged_python / "lib" / "python3.13" / "site-packages").mkdir(parents=True)

    for module in (build_deb, build_rpm):
        monkeypatch.setattr(module.payload, "stage_linux_interpreter", stage)
        monkeypatch.setattr(
            module.payload, "stage_linux_gui_bindings", lambda staged_python: None
        )


def test_the_deb_puts_the_agent_inside_the_interpreter_it_carries(tmp_path, carried):
    build_deb._lay_out(tmp_path, "9.9.9", "amd64", "somebody")

    package = (
        tmp_path
        / "opt/neutrino_agent/python/lib/python3.13/site-packages/neutrino_agent"
    )
    assert (package / "cli" / "entry.py").is_file()
    assert 'AGENT_VERSION = "9.9.9"' in (package / "_version.py").read_text()
    assert (package / "data" / "gui" / "index.html").is_file()


def test_the_deb_entry_point_runs_the_carried_interpreter(tmp_path, carried):
    """Never the machine's own: the window process it starts inherits it."""
    build_deb._lay_out(tmp_path, "9.9.9", "amd64", "somebody")

    wrapper = (tmp_path / "usr/bin/nagent").read_text()

    assert (
        "exec /opt/neutrino_agent/python/bin/python3 -m neutrino_agent.cli.entry"
        in (wrapper)
    )
    assert "/usr/bin/python3" not in wrapper


def test_the_deb_asks_for_c_libraries_and_no_python(tmp_path, carried):
    """The bindings are the package's own, built for the interpreter it
    carries; what the machine still owes is the C stack under them."""
    build_deb._lay_out(tmp_path, "9.9.9", "amd64", "somebody")

    control = (tmp_path / "DEBIAN/control").read_text()

    assert "Architecture: amd64" in control
    assert "gir1.2-webkit2-4.1" in control
    assert "libgirepository-1.0-1" in control
    assert "python3" not in control.split("Description:")[0]
    assert "python3-gi" not in control


def test_the_deb_carries_the_unit_the_desktop_entry_and_the_icons(tmp_path, carried):
    build_deb._lay_out(tmp_path, "9.9.9", "amd64", "somebody")

    assert (tmp_path / "lib/systemd/system/neutrino_agent.service").is_file()
    assert (tmp_path / "usr/share/applications/neutrino_agent.desktop").is_file()
    for edge in (48, 256):
        icon = (
            tmp_path / f"usr/share/icons/hicolor/{edge}x{edge}/apps/neutrino_agent.png"
        )
        assert icon.is_file()
        assert icon.read_bytes().startswith(b"\x89PNG")


def test_the_deb_removes_its_own_payload_and_never_the_hub_s(tmp_path, carried):
    """A machine may run both, and /opt/neutrino is the hub package's."""
    build_deb._lay_out(tmp_path, "9.9.9", "amd64", "somebody")

    postrm = (tmp_path / "DEBIAN/postrm").read_text()
    postinst = (tmp_path / "DEBIAN/postinst").read_text()

    assert "rm -rf /opt/neutrino_agent" in postrm
    assert "rm -rf /opt/neutrino\n" not in postrm
    assert "/opt/neutrino_agent" not in postinst


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
    assert (tmp_path / "usr/share/applications/neutrino_agent.desktop").is_file()
    wrapper = (tmp_path / "usr/bin/nagent").read_text()
    assert "/opt/neutrino_agent/python/bin/python3" in wrapper
    assert "PYTHONPATH" not in wrapper


def test_the_rpm_spec_names_the_machine_and_the_c_stack():
    """A payload with an interpreter in it is not noarch any more."""
    spec = build_rpm.SPEC.format(
        name="neutrino-agent",
        version="9.9.9",
        architecture="aarch64",
        requires="\n".join(f"Requires:       {n}" for n in build_rpm.RUNTIME_REQUIRES),
        packager="somebody",
        staged="/staged",
        prefix=payload.INSTALL_PREFIX,
        unit_dir=build_rpm.UNIT_DIR,
    )

    assert "BuildArch:      aarch64" in spec
    assert "noarch" not in spec
    assert "webkit2gtk4.1" in spec
    assert "Requires:       python3" not in spec
    assert "/opt/neutrino_agent" in spec
