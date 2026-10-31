"""The tree each Linux package lays down, with the carried parts faked.

Fetching an interpreter needs a build container; what it produces is stood
in for here, so what is asserted is the shape around it — where the payload
goes, what runs it, and what the package still asks the machine for.
"""

import os
import subprocess

import pytest

import build_deb
import build_pkg
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

    for module in (build_deb, build_rpm, build_pkg):
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


# --- the Arch package ---


def _run_install_hook(tmp_path, hook, *arguments, listed=""):
    """Run one function of the pacman install script with its commands faked.

    Args:
        tmp_path: Where the fakes and their record go.
        hook: The function to run.
        *arguments: Its arguments.
        listed: What ``pacman -Qlq`` prints.

    Returns:
        What the hook ran, one line each, and what it printed.
    """
    fakes = tmp_path / "fakes"
    fakes.mkdir(exist_ok=True)
    record = tmp_path / "calls"
    for name in ("nagent", "systemctl"):
        fake = fakes / name
        fake.write_text(f'#!/bin/sh\necho "{name} $*" >>"{record}"\n')
        fake.chmod(0o755)
    pacman = fakes / "pacman"
    listing = tmp_path / "listing"
    listing.write_text(listed)
    pacman.write_text(f'#!/bin/sh\ncat "{listing}"\n')
    pacman.chmod(0o755)
    script = tmp_path / "hook"
    script.write_text(
        build_pkg.install_script().replace(
            payload.AGENT_BINDING_PATH, str(tmp_path / "agent.json")
        )
        + f"\n{hook} {' '.join(arguments)}\n"
    )
    result = subprocess.run(
        ["sh", str(script)],
        env=dict(os.environ, PATH=f"{fakes}:/usr/bin:/bin"),
        capture_output=True,
        text=True,
        check=True,
    )
    calls = record.read_text().splitlines() if record.exists() else []
    return calls, result.stdout


def test_the_arch_package_lays_the_same_payload_under_the_same_prefix(
    tmp_path, carried
):
    build_pkg._lay_out(tmp_path, "9.9.9", "x86_64")

    site = tmp_path / "opt/neutrino/agent/python/lib/python3.13/site-packages"
    assert (
        'AGENT_VERSION = "9.9.9"'
        in (site / "neutrino_agent" / "_version.py").read_text()
    )
    assert carried == [(tmp_path / "opt/neutrino/agent/python", payload.PYTHON_DIR)]
    assert (tmp_path / "usr/lib/neutrino/agent/rustdesk/rustdesk").is_file()
    assert (tmp_path / "usr/share/doc/neutrino-agent/licenses/rustdesk.txt").is_file()
    assert (
        "python/bin/python3 -m neutrino_agent.cli.entry"
        in (tmp_path / "usr/bin/nagent").read_text()
    )


def test_the_arch_package_keeps_its_unit_out_of_a_lib_directory(tmp_path, carried):
    """/lib on Arch is a link, and pacman refuses a directory over it."""
    build_pkg._lay_out(tmp_path, "9.9.9", "x86_64")

    assert (tmp_path / "usr/lib/systemd/system/neutrino_agent.service").is_file()
    assert not (tmp_path / "lib").exists()


def test_the_pkgbuild_names_the_machine_and_asks_for_no_python(tmp_path):
    text = build_pkg.pkgbuild(tmp_path, "9.9.9", architecture="x86_64")

    assert "pkgname=neutrino-agent\n" in text
    assert "pkgver=9.9.9\n" in text
    assert "arch=('x86_64')\n" in text
    assert "install=neutrino-agent.install\n" in text
    for name in ("systemd", "gtk3", "xdotool", "gst-plugin-pipewire"):
        assert f"'{name}'" in text
    assert "python" not in text.split("depends=")[1].split("\n")[0]


def test_the_pkgbuild_leaves_the_payload_as_it_was_staged(tmp_path):
    """Debian's and Arch's makepkg.conf each strip and purge by default."""
    text = build_pkg.pkgbuild(tmp_path, "9.9.9", architecture="x86_64")

    for option in ("'!strip'", "'!debug'", "'!purge'", "'!zipman'", "'emptydirs'"):
        assert option in text


@pytest.mark.parametrize("machine", ["arm64", "aarch64"])
def test_no_arch_package_is_published_for_arm(machine):
    with pytest.raises(SystemExit, match="no Arch package"):
        build_pkg._architecture(machine)


def test_the_arch_install_starts_the_agent(tmp_path):
    calls, printed = _run_install_hook(tmp_path, "post_install", "9.9.9-1")

    assert calls == [
        "systemctl daemon-reload",
        "systemctl enable --now neutrino_agent.service",
    ]
    assert "sudo nagent join" in printed


def test_the_arch_install_tells_a_joined_machine_nothing(tmp_path):
    (tmp_path / "agent.json").write_text(BINDING)

    _, printed = _run_install_hook(tmp_path, "post_install", "9.9.9-1")

    assert "nagent join" not in printed


def test_the_arch_upgrade_restarts_the_agent(tmp_path):
    calls, printed = _run_install_hook(tmp_path, "post_upgrade", "9.9.9-1", "9.9.8-1")

    assert calls.index("systemctl daemon-reload") < calls.index(
        "systemctl try-restart neutrino_agent.service"
    )
    assert "nagent join" not in printed


def test_the_arch_upgrade_prunes_what_the_package_did_not_install():
    """pacman's own file list says what the package put under the prefix."""
    script = build_pkg.install_script()

    assert payload.PRUNE_UNTRACKED in script
    assert (
        "pacman -Qlq neutrino-agent | sed 's:/*$::' | prune_untracked "
        "/opt/neutrino/agent" in script
    )


def test_the_arch_removal_leaves_the_hub_and_takes_the_modules_units(tmp_path):
    calls, _ = _run_install_hook(tmp_path, "pre_remove", "9.9.9-1")

    assert calls == [
        "nagent leave --yes",
        "systemctl stop neutrino_agent.service",
        "systemctl disable neutrino_agent.service",
        "nagent service uninstall --yes",
    ]


def test_the_arch_removal_shows_what_the_leave_and_the_uninstall_print():
    for line in build_pkg.install_script().splitlines():
        if "nagent leave" in line or "nagent service uninstall" in line:
            assert ">/dev/null" not in line, line


def test_the_arch_removal_takes_its_own_payload_and_never_the_hub_s():
    script = build_pkg.install_script()

    assert "rm -rf /opt/neutrino/agent\n" in script
    assert "rm -rf /usr/lib/neutrino/agent\n" in script
    assert "rm -rf /opt/neutrino\n" not in script
    assert "rm -rf /opt/neutrino/hub" not in script
    assert "Leaving /etc/neutrino/agent in place" in script


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


@pytest.mark.parametrize(
    "module, architecture, target",
    [
        (build_deb, "amd64", "linux-amd64"),
        (build_deb, "arm64", "linux-arm64"),
        (build_rpm, "x86_64", "linux-amd64"),
        (build_rpm, "aarch64", "linux-arm64"),
    ],
)
def test_the_packages_carry_the_go_programs_under_the_agents_bin(
    tmp_path, carried, module, architecture, target
):
    if module is build_deb:
        module._lay_out(tmp_path, "9.9.9", architecture, "somebody")
    else:
        module._lay_out(tmp_path, "9.9.9", architecture)

    for name in payload.GO_PROGRAM_NAMES:
        staged = tmp_path / "opt/neutrino/agent/bin" / name
        assert staged.read_bytes() == f"{name} for {target}".encode()
        assert os.access(staged, os.X_OK)


def test_a_linux_package_without_its_go_programs_stops_before_staging(
    tmp_path, carried, go_programs
):
    (go_programs / "linux-amd64" / "neutrino_transport").unlink()

    with pytest.raises(SystemExit, match="neutrino_transport"):
        build_deb._lay_out(tmp_path, "9.9.9", "amd64", "somebody")

    assert not (tmp_path / "opt").exists()
