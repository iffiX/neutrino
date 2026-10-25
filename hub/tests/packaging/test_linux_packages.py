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


def _spec(geodata="/var/lib/neutrino/hub/geodata\n"):
    """The spec as the build writes it.

    Args:
        geodata: The `%files` line of the geodata, empty for a hub without it.

    Returns:
        The rendered spec file.
    """
    return build_rpm.SPEC.format(
        name=venv_tree.PACKAGE_NAME,
        version="9.9.9",
        architecture="x86_64",
        packager="somebody",
        payload="/payload",
        geodata=geodata,
        unit_dir=build_rpm.UNIT_DIR,
        requires="systemd",
        recommends="hostapd",
        prune=venv_tree.PRUNE_UNTRACKED,
        desktop=venv_tree.DESKTOP_ENTRY_NAME,
        first_install=venv_tree.FIRST_INSTALL,
        is_set_up=venv_tree.HUB_IS_SET_UP,
    )


def test_the_rpm_lists_the_geodata_a_payload_carries(tmp_path):
    """rpmbuild fails on a `%files` line naming a path the payload lacks."""
    (tmp_path / str(venv_tree.GEODATA_DIR).lstrip("/")).mkdir(parents=True)

    line = build_rpm.geodata_line(tmp_path)

    assert line == f"{venv_tree.GEODATA_DIR}\n"
    assert f"\n{venv_tree.GEODATA_DIR}\n" in _spec(line)


def test_the_rpm_of_a_hub_without_the_proxy_lists_no_geodata(tmp_path):
    """The cn hub carries no proxy, so its payload has no geodata."""
    line = build_rpm.geodata_line(tmp_path)

    assert line == ""
    assert "/var/lib/neutrino/hub/geodata" not in _spec(line)
    assert "/var/lib/neutrino/hub/agent_cache" in _spec(line)


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


def test_the_deb_starts_the_panel_after_the_upgrade_of_a_set_up_hub_left(tmp_path):
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


def test_the_rpm_starts_the_panel_where_the_upgrade_of_a_set_up_hub_does_not():
    spec = _spec()
    post = spec[spec.index("%post\n") : spec.index("%preun")]

    assert post.index("else\n") < post.index(venv_tree.FIRST_INSTALL)


def test_the_arch_package_starts_the_panel_before_the_upgrade_of_a_set_up_hub():
    script = build_pkg.install_script()
    install = script[script.index("post_install()") : script.index("post_upgrade()")]
    upgrade = script[script.index("post_upgrade()") : script.index("pre_remove()")]

    assert venv_tree.FIRST_INSTALL in install
    assert upgrade.index("if ! hub_is_set_up; then") < upgrade.index(
        venv_tree.FIRST_INSTALL
    )
    assert upgrade.index(venv_tree.FIRST_INSTALL) < upgrade.index(
        "    nhub apply >/dev/null"
    )


def test_a_first_install_restarts_a_wizard_already_running_onto_this_version():
    first = venv_tree.FIRST_INSTALL

    assert first.startswith(
        "systemctl try-restart neutrino_hub_web.service >/dev/null 2>&1 || true\n"
        "systemctl enable --now neutrino_hub_web.service"
    )


def test_the_set_up_check_reads_the_settings_where_the_hub_keeps_them():
    from neutrino_hub.cli.password import PASSWORD_SETTINGS_FILE
    from neutrino_hub.platforms.constants import (
        PLATFORM_OS_LINUX,
        PLATFORM_ROOT_CONFIG,
        PLATFORM_ROOTS,
    )

    config = PLATFORM_ROOTS[PLATFORM_OS_LINUX][PLATFORM_ROOT_CONFIG]
    assert venv_tree.HUB_SETTINGS_LINUX == f"{config}/{PASSWORD_SETTINGS_FILE}"
    assert venv_tree.HUB_SETTINGS_LINUX in venv_tree.HUB_IS_SET_UP


# What a set-up hub's panel settings hold, and what a fresh one's do.
SET_UP_SETTINGS = (
    '{\n  "admin_password_hash": "scrypt$73616c74$6b6579"\n}\n'  # scan: allow
)
FRESH_SETTINGS = (
    '{\n  "admin_password_hash": "PLACEHOLDER_ARGON2ID_HASH"\n}\n'  # scan: allow
)


def _upgrade_calls(tmp_path, upgrade: str, command: list, settings) -> list:
    """Run the upgrade part of a maintainer script against this test's settings.

    Args:
        tmp_path: Where the script, the settings and the fakes go.
        upgrade: The script's text from its upgrade on, the set-up check
            first.
        command: How the script is run.
        settings: The panel settings' text, or None for no settings.

    Returns:
        The commands it ran.
    """
    path = tmp_path / "settings.json"
    if settings is not None:
        path.write_text(settings)
    script = tmp_path / "upgrade.sh"
    script.write_text(upgrade.replace(venv_tree.HUB_SETTINGS_LINUX, str(path)))
    return _run_with_fakes(tmp_path, [*command[:1], str(script), *command[1:]])


def _deb_upgrade(tmp_path) -> str:
    build_deb._lay_out(tmp_path / "tree", "9.9.9", "amd64", "somebody")
    postinst = (tmp_path / "tree/DEBIAN/postinst").read_text()
    return venv_tree.HUB_IS_SET_UP + postinst[postinst.index("# An upgrade can") :]


def _rpm_upgrade() -> str:
    spec = _spec()
    post = spec[spec.index("# An upgrade can") : spec.index("\n%preun")]
    return venv_tree.HUB_IS_SET_UP + post


def _arch_upgrade() -> str:
    return build_pkg.install_script() + "\npost_upgrade\n"


@pytest.mark.parametrize(
    "package, command",
    [
        ("deb", ["sh", "configure", "0.5.2"]),
        ("rpm", ["sh", "2"]),
        ("arch", ["sh"]),
    ],
)
@pytest.mark.parametrize("settings", [None, FRESH_SETTINGS])
def test_an_upgrade_over_a_hub_nobody_set_up_shows_the_wizard_and_applies_nothing(
    tmp_path, package, command, settings
):
    upgrade = {
        "deb": lambda: _deb_upgrade(tmp_path),
        "rpm": _rpm_upgrade,
        "arch": _arch_upgrade,
    }[package]()

    calls = _upgrade_calls(tmp_path, upgrade, command, settings)

    assert "nhub apply" not in calls
    assert "systemctl try-restart neutrino_hub_web.service" in calls
    assert "systemctl enable --now neutrino_hub_web.service" in calls
    assert "nhub open --print" in calls


@pytest.mark.parametrize(
    "package, command",
    [
        ("deb", ["sh", "configure", "0.5.2"]),
        ("rpm", ["sh", "2"]),
        ("arch", ["sh"]),
    ],
)
def test_an_upgrade_over_a_hub_set_up_applies_and_shows_no_wizard(
    tmp_path, package, command
):
    upgrade = {
        "deb": lambda: _deb_upgrade(tmp_path),
        "rpm": _rpm_upgrade,
        "arch": _arch_upgrade,
    }[package]()

    calls = _upgrade_calls(tmp_path, upgrade, command, SET_UP_SETTINGS)

    assert "nhub apply" in calls
    assert "systemctl restart neutrino_hub_router.service" in calls
    assert "systemctl try-restart neutrino_hub_web.service" in calls
    assert "nhub open --print" not in calls
    assert "systemctl enable --now neutrino_hub_web.service" not in calls


def test_the_panel_unit_starts_again_when_the_wizard_exits_into_the_panel():
    unit = venv_tree.panel_unit()

    assert "Restart=on-failure\n" in unit
    assert "RestartForceExitStatus=75\n" in unit


def _run_with_fakes(tmp_path, command: list) -> list:
    """Run a maintainer script with nhub, systemctl, nft, ip and install
    recording calls.

    Args:
        tmp_path: Where the fakes and their record go.
        command: The script's command line.

    Returns:
        The commands it ran, one line each.
    """
    fakes = tmp_path / "fakes"
    fakes.mkdir(exist_ok=True)
    record = tmp_path / "calls"
    for name in ("nhub", "systemctl", "nft", "ip", "install"):
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
