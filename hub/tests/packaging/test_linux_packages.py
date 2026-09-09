"""What each Linux package asks its package manager to do around the payload.

The environment itself is built in a container; what is asserted here is the
maintainer scripts written beside it.
"""

import build_deb
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
    )


def test_the_deb_prunes_what_the_package_did_not_install(tmp_path):
    """dpkg's own file list says what the package put under the prefix."""
    build_deb._lay_out(tmp_path, "9.9.9", "amd64", "somebody")

    postinst = (tmp_path / "DEBIAN/postinst").read_text()

    assert venv_tree.PRUNE_UNTRACKED in postinst
    assert "/var/lib/dpkg/info/neutrino-hub.list" in postinst
    assert "prune_untracked /opt/neutrino <" in postinst


def test_the_deb_prune_runs_before_the_upgrade_leaves_the_script(tmp_path):
    """The upgrade branch ends in `exit 0`, so a prune written after it would
    never run on the one path that needs it."""
    build_deb._lay_out(tmp_path, "9.9.9", "amd64", "somebody")

    postinst = (tmp_path / "DEBIAN/postinst").read_text()

    assert postinst.index("prune_untracked /opt/neutrino <") < postinst.index("exit 0")


def test_the_deb_touches_no_root_but_its_own_prefix(tmp_path):
    """Configuration, state and logs are not the package's to take away."""
    build_deb._lay_out(tmp_path, "9.9.9", "amd64", "somebody")

    postinst = (tmp_path / "DEBIAN/postinst").read_text()

    assert "rm -rf" not in postinst
    assert "prune_untracked /etc" not in postinst
    assert "prune_untracked /var" not in postinst


def test_the_rpm_prunes_from_its_own_file_list_after_the_transaction():
    spec = _spec()

    assert venv_tree.PRUNE_UNTRACKED in spec
    assert "%posttrans" in spec
    assert "rpm -ql neutrino-hub | prune_untracked /opt/neutrino" in spec


def test_the_rpm_leaves_the_configuration_where_a_reinstall_finds_it():
    """`purge` is the only thing that forgets, and rpm has no purge."""
    spec = _spec()

    assert "rm -rf /opt/neutrino\n" in spec
    assert "rm -rf /etc/neutrino" not in spec
