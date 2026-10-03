"""What each Linux package asks its package manager to do around the payload.

The environment itself is built in a container; what is asserted here is the
maintainer scripts written beside it.
"""

import build_deb
import build_pkg
import build_rpm
import venv_tree


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
