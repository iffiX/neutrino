"""The tree each Linux package lays down, with the carried parts faked.

Fetching an interpreter needs a build container; what it produces is stood
in for here, so what is asserted is the shape around it — where the payload
goes, what runs it, and what the package still asks the machine for.
"""

import os
import subprocess

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
        / "opt/neutrino/agent/python/lib/python3.13/site-packages/neutrino_agent"
    )
    assert (package / "cli" / "entry.py").is_file()
    assert 'AGENT_VERSION = "9.9.9"' in (package / "_version.py").read_text()


def test_the_deb_entry_point_runs_the_carried_interpreter(tmp_path, carried):
    """Never the machine's own."""
    build_deb._lay_out(tmp_path, "9.9.9", "amd64", "somebody")

    wrapper = (tmp_path / "usr/bin/nagent").read_text()

    assert (
        "exec /opt/neutrino/agent/python/bin/python3 -m neutrino_agent.cli.entry"
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
    assert "ExecStart=/usr/lib/neutrino/agent/rustdesk/rustdesk --service" in unit
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


@pytest.mark.parametrize(
    "argument, is_removed",
    [("remove", True), ("upgrade", False), ("deconfigure", False)],
)
def test_the_deb_takes_away_what_the_modules_added_on_a_removal_alone(
    tmp_path, carried, argument, is_removed
):
    """`nagent service uninstall` runs after the agent is stopped and before
    its files go, and an upgrade keeps the modules' units."""
    build_deb._lay_out(tmp_path / "tree", "9.9.9", "amd64", "somebody")

    calls = _run_with_fakes(tmp_path, tmp_path / "tree/DEBIAN/prerm", argument)

    uninstall = "nagent service uninstall --yes"
    assert (uninstall in calls) is is_removed
    if is_removed:
        assert calls.index("systemctl stop neutrino_agent.service") < calls.index(
            uninstall
        )


@pytest.mark.parametrize("count, is_removed", [("0", True), ("1", False)])
def test_the_rpm_takes_away_what_the_modules_added_on_a_removal_alone(
    tmp_path, count, is_removed
):
    preun = _spec().split("%preun\n")[1].split("\n%postun")[0]
    script = tmp_path / "preun"
    script.write_text("#!/bin/sh\n" + preun)

    calls = _run_with_fakes(tmp_path, script, count)

    uninstall = "nagent service uninstall --yes"
    assert (uninstall in calls) is is_removed
    if is_removed:
        assert calls.index("systemctl stop neutrino_agent.service") < calls.index(
            uninstall
        )


def test_the_deb_restarts_a_running_desktop_host_on_an_upgrade(tmp_path, carried):
    """An upgrade or a reinstall replaces the binary the running host has
    open; `try-restart` touches only a unit that exists and is active."""
    build_deb._lay_out(tmp_path, "9.9.9", "amd64", "somebody")

    postinst = (tmp_path / "DEBIAN/postinst").read_text()
    upgrade = postinst.split('if [ "$1" = configure ] && [ -n "$2" ]; then')[1]
    upgrade = upgrade.split("\nfi\n")[0]

    assert "systemctl try-restart rustdesk.service" in upgrade
    assert upgrade.index("neutrino_agent.service") < upgrade.index("rustdesk")


def test_the_deb_carries_the_licence_of_what_it_ships(tmp_path, carried):
    build_deb._lay_out(tmp_path, "9.9.9", "amd64", "somebody")

    licence = tmp_path / "usr/share/doc/neutrino-agent/licenses/rustdesk.txt"

    assert "GNU AFFERO GENERAL PUBLIC LICENSE" in licence.read_text()
    assert "https://github.com/rustdesk/rustdesk/tree/1.4.9" in licence.read_text()


def test_the_deb_compiles_the_tree_at_the_path_it_installs_it_at(tmp_path, carried):
    """Bytecode the package ships is bytecode the package replaces."""
    build_deb._lay_out(tmp_path, "9.9.9", "amd64", "somebody")

    assert carried == [(tmp_path / "opt/neutrino/agent/python", payload.PYTHON_DIR)]


def test_the_deb_prunes_what_the_package_did_not_install(tmp_path, carried):
    """dpkg's own file list says what the package put under the prefix."""
    build_deb._lay_out(tmp_path, "9.9.9", "amd64", "somebody")

    postinst = (tmp_path / "DEBIAN/postinst").read_text()

    assert payload.PRUNE_UNTRACKED in postinst
    assert "/var/lib/dpkg/info/neutrino-agent.list" in postinst
    assert "prune_untracked /opt/neutrino/agent" in postinst


def test_the_rpm_prunes_from_its_own_file_list_after_the_transaction(tmp_path, carried):
    build_rpm._lay_out(tmp_path, "9.9.9", "x86_64")
    spec = _spec()

    assert payload.PRUNE_UNTRACKED in spec
    assert "%posttrans" in spec
    assert "rpm -ql neutrino-agent | prune_untracked /opt/neutrino/agent" in spec
    assert carried == [(tmp_path / "opt/neutrino/agent/python", payload.PYTHON_DIR)]


def test_the_deb_removes_its_own_payload_and_never_the_hub_s(tmp_path, carried):
    """A machine may run both, and /opt/neutrino/hub is the hub package's."""
    build_deb._lay_out(tmp_path, "9.9.9", "amd64", "somebody")

    postrm = (tmp_path / "DEBIAN/postrm").read_text()
    postinst = (tmp_path / "DEBIAN/postinst").read_text()

    assert "rm -rf /opt/neutrino/agent" in postrm
    assert "rm -rf /usr/lib/neutrino/agent" in postrm
    assert "rm -rf /opt/neutrino\n" not in postrm
    assert "rm -rf /opt/neutrino/hub" not in postrm
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
        / "opt/neutrino/agent/python/lib/python3.13/site-packages/neutrino_agent"
    )
    assert 'AGENT_VERSION = "9.9.9"' in (package / "_version.py").read_text()
    assert (tmp_path / "usr/lib/systemd/system/neutrino_agent.service").is_file()
    assert (tmp_path / "usr/lib/systemd/system/rustdesk.service").is_file()
    assert (tmp_path / "usr/lib/neutrino/agent/rustdesk/rustdesk").is_file()
    assert not (tmp_path / "usr/share/applications").exists()
    wrapper = (tmp_path / "usr/bin/nagent").read_text()
    assert "/opt/neutrino/agent/python/bin/python3" in wrapper
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
        vendor=payload.VENDOR_PREFIX,
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
    assert "/opt/neutrino/agent" in spec


def test_the_rpm_owns_the_desktop_host_it_carries():
    spec = _spec()

    assert "%dir /usr/lib/neutrino/agent" in spec
    assert "/usr/lib/neutrino/agent/*" in spec
    assert "rm -rf /usr/lib/neutrino/agent" in spec
    assert "/usr/bin/rustdesk" in spec
    assert "/usr/lib/systemd/system/rustdesk.service" in spec
    assert "/usr/share/doc/neutrino-agent" in spec
    assert "systemctl enable --now rustdesk.service" in spec
    assert "systemctl stop rustdesk.service" in spec


def test_the_rpm_restarts_a_running_desktop_host_on_an_upgrade():
    spec = _spec()
    post = spec.split("%post\n")[1].split("%preun")[0]
    upgrade = post.split('if [ "$1" -ge 2 ]; then')[1].split("\nfi\n")[0]

    assert "systemctl try-restart rustdesk.service" in upgrade


def test_the_packages_replace_the_upstream_rustdesk_package():
    assert "Conflicts: rustdesk\nReplaces: rustdesk\n" in build_deb.CONTROL
    assert "Conflicts:      rustdesk" in build_rpm.SPEC


def test_the_rpm_build_allows_the_viewers_upstream_runpath_and_nothing_else():
    assert build_rpm.RPMBUILD_ENVIRONMENT == {"QA_RPATHS": "0x0002"}


def _run_with_fakes(tmp_path, script, argument):
    """Run one maintainer script with nagent and systemctl recording calls.

    Args:
        tmp_path: Where the fakes and their record go.
        script: The script to run.
        argument: Its first argument.

    Returns:
        The commands it ran, one line each.
    """
    fakes = tmp_path / "fakes"
    fakes.mkdir()
    record = tmp_path / "calls"
    for name in ("nagent", "systemctl"):
        fake = fakes / name
        fake.write_text(f'#!/bin/sh\necho "{name} $*" >>"{record}"\n')
        fake.chmod(0o755)
    environment = dict(os.environ, PATH=f"{fakes}:/usr/bin:/bin")
    subprocess.run(["sh", str(script), argument], env=environment, check=True)
    return record.read_text().splitlines() if record.exists() else []


@pytest.mark.parametrize("build", [build_deb, build_rpm], ids=["deb", "rpm"])
@pytest.mark.parametrize("architecture", ["amd64", "arm64"])
def test_every_linux_package_carries_cc_switch_at_the_shared_pin(
    tmp_path, carried, cc_switch_fetched, build, architecture
):
    from shared import cc_switch_assets

    if build is build_deb:
        build._lay_out(tmp_path, "9.9.9", architecture, "somebody")
    else:
        machine = payload.machine_name(architecture)
        build._lay_out(tmp_path, "9.9.9", payload.RPM_ARCHITECTURES[machine])

    binary = next(tmp_path.rglob("opt/neutrino/agent/bin/cc-switch"))
    assert binary.read_bytes() == b"cc-switch"
    assert binary.stat().st_mode & 0o777 == 0o755
    machine = payload.machine_name(architecture)
    assert cc_switch_fetched == [cc_switch_assets.asset_url("linux", machine)[0]]


def test_the_deb_carries_the_licence_of_cc_switch(tmp_path, carried):
    build_deb._lay_out(tmp_path, "9.9.9", "amd64", "somebody")

    licence = tmp_path / "usr/share/doc/neutrino-agent/licenses/cc_switch.txt"

    assert "MIT License" in licence.read_text()
