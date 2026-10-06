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


def test_the_deb_carries_the_host_and_registers_nothing_of_it(tmp_path, carried):
    """The agent writes RustDesk's unit when the hub's switch goes on."""
    build_deb._lay_out(tmp_path, "9.9.9", "amd64", "somebody")

    assert (tmp_path / "lib/systemd/system/neutrino_agent.service").is_file()
    assert (tmp_path / "usr/lib/neutrino/agent/rustdesk/rustdesk").is_file()
    for units in ("lib/systemd", "usr/lib/systemd", "etc/systemd"):
        assert not list((tmp_path / units).rglob("rustdesk*"))
    assert not (tmp_path / "usr/bin/rustdesk").exists()
    assert not (tmp_path / "usr/share/applications").exists()
    assert not (tmp_path / "usr/share/icons").exists()


def test_the_deb_starts_nothing_of_rustdesk(tmp_path, carried):
    build_deb._lay_out(tmp_path, "9.9.9", "amd64", "somebody")

    for script in ("postinst", "prerm", "postrm"):
        assert "rustdesk" not in (tmp_path / "DEBIAN" / script).read_text()


@pytest.mark.parametrize(
    "argument, owner, is_stopped",
    [
        ("upgrade", "neutrino-agent: /lib/systemd/system/rustdesk.service", True),
        ("upgrade", "rustdesk: /lib/systemd/system/rustdesk.service", False),
        ("upgrade", "", False),
        ("install", "neutrino-agent: /lib/systemd/system/rustdesk.service", False),
    ],
)
def test_an_upgrade_stops_the_unit_an_earlier_agent_package_owned_and_no_other(
    tmp_path, carried, argument, owner, is_stopped
):
    build_deb._lay_out(tmp_path / "tree", "9.9.9", "amd64", "somebody")

    calls = _run_with_fakes(
        tmp_path, tmp_path / "tree/DEBIAN/preinst", argument, owner=owner
    )

    assert ("systemctl disable --now rustdesk.service" in calls) is is_stopped


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


def test_a_removal_shows_what_the_leave_and_the_uninstall_print(tmp_path, carried):
    """A removal's output carries each account's switch back, so neither the
    leave nor the uninstall has its standard output thrown away."""
    build_deb._lay_out(tmp_path / "tree", "9.9.9", "amd64", "somebody")
    prerm = (tmp_path / "tree/DEBIAN/prerm").read_text()
    for line in prerm.splitlines() + _spec().splitlines():
        if "nagent leave" in line or "nagent service uninstall" in line:
            assert ">/dev/null" not in line, line


def test_the_deb_restarts_the_agent_on_an_upgrade(tmp_path, carried):
    build_deb._lay_out(tmp_path, "9.9.9", "amd64", "somebody")

    postinst = (tmp_path / "DEBIAN/postinst").read_text()
    upgrade = postinst.split('if [ "$1" = configure ] && [ -n "$2" ]; then')[1]
    upgrade = upgrade.split("\nfi\n")[0]

    assert "systemctl try-restart neutrino_agent.service" in upgrade


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
    for units in ("lib/systemd", "usr/lib/systemd", "etc/systemd"):
        assert not list((tmp_path / units).rglob("rustdesk*"))
    assert not (tmp_path / "usr/bin/rustdesk").exists()
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
        rustdesk_unit=payload.RUSTDESK_UNIT_NAME,
        bound_test=payload.AGENT_BOUND_TEST.format(path=payload.AGENT_BINDING_PATH),
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
    assert "/usr/share/doc/neutrino-agent" in spec
    files = spec.split("%files\n")[1].split("\n%pre\n")[0]
    assert "rustdesk.service" not in files
    assert "/usr/bin/rustdesk" not in files
    for scriptlet in ("%post\n", "%preun\n", "%postun\n"):
        body = spec.split(scriptlet)[1].split("\n%")[0]
        assert "rustdesk" not in body


@pytest.mark.parametrize(
    "count, owner, is_stopped",
    [
        ("2", "neutrino-agent", True),
        ("2", "rustdesk", False),
        ("2", "file /usr/lib/systemd/system/rustdesk.service is not owned", False),
        ("1", "neutrino-agent", False),
    ],
)
def test_an_rpm_upgrade_stops_the_unit_an_earlier_agent_package_owned_and_no_other(
    tmp_path, count, owner, is_stopped
):
    pre = _spec().split("\n%pre\n")[1].split("\n%post\n")[0]
    script = tmp_path / "pre"
    script.write_text("#!/bin/sh\n" + pre.replace("%%{NAME}", "%{NAME}"))

    calls = _run_with_fakes(tmp_path, script, count, owner=owner)

    assert ("systemctl disable --now rustdesk.service" in calls) is is_stopped


def test_the_packages_live_beside_a_person_s_own_rustdesk_package():
    assert "Conflicts" not in build_deb.CONTROL
    assert "Replaces" not in build_deb.CONTROL
    assert "Conflicts" not in build_rpm.SPEC


def test_the_rpm_build_allows_the_viewers_upstream_runpath_and_nothing_else():
    assert build_rpm.RPMBUILD_ENVIRONMENT == {"QA_RPATHS": "0x0002"}


def _run_with_fakes(tmp_path, script, argument, owner=""):
    """Run one maintainer script with nagent and systemctl recording calls,
    and dpkg-query and rpm naming one owner for any file.

    Args:
        tmp_path: Where the fakes and their record go.
        script: The script to run.
        argument: Its first argument.
        owner: What the package database answers for a file.

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
    for name in ("dpkg-query", "rpm"):
        fake = fakes / name
        fake.write_text(f'#!/bin/sh\n[ -n "{owner}" ] || exit 1\necho "{owner}"\n')
        fake.chmod(0o755)
    environment = dict(os.environ, PATH=f"{fakes}:/usr/bin:/bin")
    subprocess.run(["sh", str(script), argument], env=environment, check=True)
    return record.read_text().splitlines() if record.exists() else []


def test_the_agent_package_carries_no_cc_switch(tmp_path, carried):
    """The agent fetches cc-switch from its hub when its AI tools are used."""
    build_deb._lay_out(tmp_path, "9.9.9", "amd64", "somebody")

    assert not list(tmp_path.rglob("cc-switch*"))
    assert "cc_switch.txt" not in payload.CARRIED_LICENSES


# --- a machine that has joined is not told to join ---

BINDING = (
    '{\n  "gateway_url": "https://hub:8443",\n  "id": "d1",\n  "token": "t0k"\n}\n'
)


def _run_printing(tmp_path, text, argument):
    """Run a maintainer script with systemctl faked, the binding read from
    tmp_path; what it printed."""
    fakes = tmp_path / "fakes"
    fakes.mkdir(exist_ok=True)
    systemctl = fakes / "systemctl"
    systemctl.write_text("#!/bin/sh\nexit 0\n")
    systemctl.chmod(0o755)
    script = tmp_path / "script"
    script.write_text(
        text.replace(payload.AGENT_BINDING_PATH, str(tmp_path / "agent.json"))
    )
    result = subprocess.run(
        ["sh", str(script), *argument],
        env=dict(os.environ, PATH=f"{fakes}:/usr/bin:/bin"),
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


@pytest.mark.parametrize("is_bound", [False, True])
def test_the_deb_tells_only_a_machine_that_has_not_joined_to_join(
    tmp_path, carried, is_bound
):
    build_deb._lay_out(tmp_path / "tree", "9.9.9", "amd64", "somebody")
    if is_bound:
        (tmp_path / "agent.json").write_text(BINDING)

    printed = _run_printing(
        tmp_path,
        (tmp_path / "tree/DEBIAN/postinst").read_text(),
        ["configure", "9.9.8"],
    )

    assert ("sudo nagent join" in printed) is (not is_bound)


@pytest.mark.parametrize("is_bound", [False, True])
def test_the_rpm_tells_only_a_machine_that_has_not_joined_to_join(tmp_path, is_bound):
    if is_bound:
        (tmp_path / "agent.json").write_text(BINDING)
    post = _spec().split("%post\n")[1].split("\n%preun")[0]

    printed = _run_printing(tmp_path, "#!/bin/sh\n" + post, ["1"])

    assert ("nagent join" in printed) is (not is_bound)


def test_the_packages_read_the_binding_where_the_agent_writes_it():
    from neutrino_agent.constants import AGENT_CONFIG_NAME, AGENT_DATA_DIR_POSIX

    assert payload.AGENT_BINDING_PATH == os.path.join(
        AGENT_DATA_DIR_POSIX, AGENT_CONFIG_NAME
    )


def test_the_deb_names_its_installed_size(tmp_path, carried):
    build_deb._lay_out(tmp_path, "9.9.9", "amd64", "somebody")

    control = (tmp_path / "DEBIAN/control").read_text()
    size = int(control.split("Installed-Size: ")[1].split("\n")[0])
    assert size > 0
