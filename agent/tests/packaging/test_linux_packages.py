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
    """A staged interpreter, without fetching or compiling one.

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

    for module in (build_deb, build_rpm):
        monkeypatch.setattr(module.payload, "stage_linux_interpreter", stage)
        monkeypatch.setattr(module.payload, "compile_bytecode", compile_bytecode)
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
    the init system that runs the service."""
    build_deb._lay_out(tmp_path, "9.9.9", "amd64", "somebody")

    control = (tmp_path / "DEBIAN/control").read_text()

    assert "Architecture: amd64" in control
    assert "Depends: systemd" in control
    assert "Recommends" not in control
    assert "python3" not in control.split("Description:")[0]


def test_the_deb_carries_the_unit_and_nothing_for_a_desktop(tmp_path, carried):
    build_deb._lay_out(tmp_path, "9.9.9", "amd64", "somebody")

    assert (tmp_path / "lib/systemd/system/neutrino_agent.service").is_file()
    assert not (tmp_path / "usr/share/applications").exists()
    assert not (tmp_path / "usr/share/icons").exists()


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
        prune=payload.PRUNE_UNTRACKED,
    )


def test_the_rpm_spec_names_the_machine_and_asks_for_no_python():
    """A payload with an interpreter in it is not noarch any more."""
    spec = _spec()

    assert "BuildArch:      aarch64" in spec
    assert "noarch" not in spec
    assert "Requires:       systemd" in spec
    assert "Requires:       python3" not in spec
    assert "Recommends" not in spec
    assert "/opt/neutrino_agent" in spec
