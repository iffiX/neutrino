"""What each Linux package asks its package manager to do around the payload.

The environment itself is built in a container; what is asserted here is the
maintainer scripts written beside it.
"""

import os
import subprocess

import pytest

import build_deb
import build_pkg
import build_rpm
import venv_tree
from neutrino_hub.system.constants import SYSTEM_MANAGED_UNITS


def _spec():
    """The spec as the build writes it.

    Returns:
        The rendered spec file.
    """
    return build_rpm.SPEC.format(
        name=venv_tree.PACKAGE_NAME,
        version="9.9.9",
        architecture="x86_64",
        packager="somebody",
        payload="/payload",
        unit_dir=build_rpm.UNIT_DIR,
        requires="systemd",
        recommends="hostapd",
        prune=venv_tree.PRUNE_UNTRACKED,
        desktop=venv_tree.DESKTOP_ENTRY_NAME,
        first_install=venv_tree.FIRST_INSTALL,
    )


def test_the_deb_prunes_what_the_package_did_not_install(tmp_path):
    """dpkg's own file list says what the package put under the prefix."""
    build_deb._lay_out(tmp_path, "9.9.9", "amd64", "somebody")

    postinst = (tmp_path / "DEBIAN/postinst").read_text()

    assert venv_tree.PRUNE_UNTRACKED in postinst
    assert "/var/lib/dpkg/info/neutrino-hub.list" in postinst
    assert "prune_untracked /opt/neutrino/hub <" in postinst


def test_the_deb_prune_runs_before_the_upgrade_leaves_the_script(tmp_path):
    """The upgrade branch ends in `exit 0`, so a prune written after it would
    never run on the one path that needs it."""
    build_deb._lay_out(tmp_path, "9.9.9", "amd64", "somebody")

    postinst = (tmp_path / "DEBIAN/postinst").read_text()

    assert postinst.index("prune_untracked /opt/neutrino/hub <") < postinst.index(
        "exit 0"
    )


def test_the_deb_touches_no_root_but_its_own_prefix(tmp_path):
    """Configuration, state and logs are not the package's to take away."""
    build_deb._lay_out(tmp_path, "9.9.9", "amd64", "somebody")

    postinst = (tmp_path / "DEBIAN/postinst").read_text()

    assert "rm -rf" not in postinst
    assert "prune_untracked /etc" not in postinst
    assert "prune_untracked /var" not in postinst


def test_the_deb_names_both_spellings_of_the_dhcp_client(tmp_path):
    """`a | b` is the control file's alternative: Debian and Ubuntu 24.04 have
    the client in `dhcpcd-base`, Ubuntu 22.04 in `dhcpcd5`, and one package
    installs on either."""
    build_deb._lay_out(tmp_path, "9.9.9", "amd64", "somebody")

    control = (tmp_path / "DEBIAN/control").read_text()
    depends = next(line for line in control.splitlines() if line.startswith("Depends:"))

    assert "dhcpcd-base | dhcpcd5" in depends
    assert "dnsmasq-base" in depends
    assert depends.startswith("Depends: systemd, ")


def test_the_deb_brings_the_pkexec_its_entry_asks_for_rights_through(tmp_path):
    """`nhub open` asks through pkexec, which Debian 12's and Ubuntu's
    `polkitd` no longer carries; `policykit-1` carries it on older releases."""
    build_deb._lay_out(tmp_path, "9.9.9", "amd64", "somebody")

    control = (tmp_path / "DEBIAN/control").read_text()
    depends = next(line for line in control.splitlines() if line.startswith("Depends:"))

    assert ", pkexec | policykit-1" in depends


def test_the_rpm_and_the_arch_package_bring_polkit():
    """Their `polkit` carries pkexec itself."""
    assert "polkit" in venv_tree.dependencies("rhel")
    assert "polkit" in venv_tree.dependencies("arch")


def test_the_rpm_prunes_from_its_own_file_list_after_the_transaction():
    spec = _spec()

    assert venv_tree.PRUNE_UNTRACKED in spec
    assert "%posttrans" in spec
    assert "rpm -ql neutrino-hub | prune_untracked /opt/neutrino/hub" in spec


def test_the_rpm_leaves_the_configuration_where_a_reinstall_finds_it():
    """`purge` is the only thing that forgets, and rpm has no purge."""
    spec = _spec()

    assert "rm -rf /opt/neutrino/hub\n" in spec
    assert "rm -rf /etc/neutrino" not in spec


def test_a_first_install_starts_the_panel_unit_and_prints_the_wizard_address():
    first = venv_tree.FIRST_INSTALL

    assert "systemctl enable --now neutrino_hub_web.service" in first
    assert 'address="$(nhub open --print 2>/dev/null)"' in first
    assert "sudo nhub setup" in first


def test_the_deb_starts_the_panel_on_a_first_install_and_not_on_an_upgrade(tmp_path):
    build_deb._lay_out(tmp_path, "9.9.9", "amd64", "somebody")

    postinst = (tmp_path / "DEBIAN/postinst").read_text()

    assert venv_tree.FIRST_INSTALL in postinst
    assert postinst.index("exit 0") < postinst.index(venv_tree.FIRST_INSTALL)


def test_every_linux_package_carries_the_neutrino_hub_entry(tmp_path):
    build_deb._lay_out(tmp_path, "9.9.9", "amd64", "somebody")

    entry = (tmp_path / "usr/share/applications/neutrino-hub.desktop").read_text()

    assert "Name=Neutrino Hub\n" in entry
    assert "Exec=nhub open\n" in entry
    assert "Icon=neutrino-hub\n" in entry
    assert "Categories=Network;\n" in entry
    for edge in venv_tree.DESKTOP_ICON_EDGES:
        icon = tmp_path / f"usr/share/icons/hicolor/{edge}x{edge}/apps/neutrino-hub.png"
        assert icon.read_bytes().startswith(b"\x89PNG")
    spec = _spec()
    assert "/usr/share/applications/neutrino-hub.desktop\n" in spec
    assert "/usr/share/icons/hicolor/*/apps/neutrino-hub.png\n" in spec


def test_the_rpm_starts_the_panel_on_a_first_install_alone():
    spec = _spec()
    post = spec[spec.index("%post\n") : spec.index("%preun")]

    assert post.index("else\n") < post.index(venv_tree.FIRST_INSTALL)


def test_the_arch_package_starts_the_panel_on_a_first_install_alone():
    script = build_pkg.INSTALL_SCRIPT.replace(
        "@FIRST_INSTALL@", venv_tree.FIRST_INSTALL
    )
    install = script[script.index("post_install()") : script.index("post_upgrade()")]
    upgrade = script[script.index("post_upgrade()") : script.index("pre_remove()")]

    assert venv_tree.FIRST_INSTALL in install
    assert "nhub open" not in upgrade


def test_the_panel_unit_starts_again_when_the_wizard_exits_into_the_panel():
    unit = venv_tree.panel_unit()

    assert "Restart=on-failure\n" in unit
    assert "RestartForceExitStatus=75\n" in unit


def _run_with_fakes(tmp_path, command: list) -> list:
    """Run a maintainer script with nhub, systemctl, nft and ip recording calls.

    Args:
        tmp_path: Where the fakes and their record go.
        command: The script's command line.

    Returns:
        The commands it ran, one line each.
    """
    fakes = tmp_path / "fakes"
    fakes.mkdir(exist_ok=True)
    record = tmp_path / "calls"
    for name in ("nhub", "systemctl", "nft", "ip"):
        fake = fakes / name
        fake.write_text(f'#!/bin/sh\necho "{name} $*" >>"{record}"\n')
        fake.chmod(0o755)
    environment = dict(os.environ, PATH=f"{fakes}:/usr/bin:/bin")
    subprocess.run(command, env=environment, check=True)
    return record.read_text().splitlines() if record.exists() else []


def _every_unit() -> list:
    return [unit for unit in SYSTEM_MANAGED_UNITS.values()]


def _assert_removal(calls: list) -> None:
    """The network is handed back first, then every unit of the code's list,
    the relay among them, is stopped and disabled."""
    assert calls[0] == "nhub reset network --yes"
    for unit in _every_unit():
        assert f"systemctl stop {unit}" in calls
        assert f"systemctl disable {unit}" in calls
    assert "systemctl stop neutrino_hub_relay.service" in calls
    assert calls.index("systemctl stop neutrino_hub_web.service") == 1


@pytest.mark.parametrize(
    "argument, is_removed",
    [("remove", True), ("deconfigure", True), ("upgrade", False)],
)
def test_the_deb_hands_back_and_stops_every_unit_on_a_removal_alone(
    tmp_path, argument, is_removed
):
    script = tmp_path / "prerm"
    script.write_text(build_deb.prerm_script())

    calls = _run_with_fakes(tmp_path, ["sh", str(script), argument])

    if is_removed:
        _assert_removal(calls)
    else:
        assert calls == []


@pytest.mark.parametrize("count, is_removed", [("0", True), ("1", False)])
def test_the_rpm_hands_back_and_stops_every_unit_on_a_removal_alone(
    tmp_path, count, is_removed
):
    spec = _spec().replace("@STOP_HUB@", venv_tree.stop_hub_lines())
    script = tmp_path / "preun"
    script.write_text("#!/bin/sh\n" + spec.split("%preun\n")[1].split("\n%postun")[0])

    calls = _run_with_fakes(tmp_path, ["sh", str(script), count])

    if is_removed:
        _assert_removal(calls)
    else:
        assert calls == []


def test_the_arch_package_hands_back_and_stops_every_unit_on_a_removal(tmp_path):
    script = tmp_path / "neutrino-hub.install"
    script.write_text(build_pkg.install_script())

    calls = _run_with_fakes(tmp_path, ["sh", "-c", f'. "{script}"; pre_remove'])

    _assert_removal(calls)


def test_the_removal_takes_the_units_drop_ins_too():
    """The relay's start line is a drop-in the hub wrote at runtime."""
    drop_ins = "rm -rf /etc/systemd/system/neutrino_hub_*.service.d"
    assert drop_ins in build_deb.POSTRM
    assert drop_ins in _spec()
    assert drop_ins in build_pkg.INSTALL_SCRIPT
