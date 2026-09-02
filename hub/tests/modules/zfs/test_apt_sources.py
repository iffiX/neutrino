"""Whose apt repositories the ZFS install is allowed to edit.

ZFS lives in Debian's own `contrib`, and enabling it means adding a component
to the entries that have one. A vendor repository — NetBird's, docker's, one
the panel itself installed a moment earlier — has no such component, so adding
it there makes every later `apt-get update` 404 on a file that was never
published. The update the panel runs swallows that, so nothing says why
installing anything stopped working.
"""

from neutrino_hub.modules.zfs.provisioner import _line_with_component

DEBIAN_STANZA = "Types: deb\nURIs: http://deb.debian.org/debian\nComponents: main\n"
VENDOR_STANZA = "Types: deb\nURIs: https://pkgs.netbird.io/debian\nComponents: main\n"


def test_a_debian_line_gains_the_component():
    line = "deb http://deb.debian.org/debian bookworm main"

    assert _line_with_component(line, "contrib").endswith("main contrib")


def test_a_security_line_gains_it_too():
    line = "deb http://security.debian.org/debian-security bookworm-security main"

    assert _line_with_component(line, "contrib").endswith("main contrib")


def test_a_vendor_line_is_left_alone():
    line = "deb https://pkgs.netbird.io/debian stable main"

    assert _line_with_component(line, "contrib") == line


def test_a_debian_stanza_gains_the_component():
    assert (
        _line_with_component("Components: main", "contrib", stanza=DEBIAN_STANZA)
        == "Components: main contrib"
    )


def test_a_vendor_stanza_is_left_alone():
    assert (
        _line_with_component("Components: main", "contrib", stanza=VENDOR_STANZA)
        == "Components: main"
    )


def test_a_line_that_already_names_it_is_unchanged():
    line = "deb http://deb.debian.org/debian bookworm main contrib"

    assert _line_with_component(line, "contrib") == line


def test_a_comment_is_not_a_repository():
    line = "# deb http://deb.debian.org/debian bookworm main"

    assert _line_with_component(line, "contrib") == line


# --- the mirror Debian's own cloud images point at rather than name ---

MIRROR_STANZA = (
    "Types: deb\nURIs: mirror+file:///etc/apt/mirrors/debian.list\n"
    "Suites: bookworm\nComponents: main\n"
)


def test_a_stanza_that_points_at_a_debian_mirror_file_gains_the_component(
    tmp_path, monkeypatch
):
    """Debian's generic cloud image writes no mirror into the stanza at all:
    `URIs: mirror+file:///etc/apt/mirrors/debian.list`, with the address in
    that file. Reading only the stanza finds no Debian hostname, so `contrib`
    was never enabled and every ZFS install ended with "Unable to locate
    package zfs-dkms" — measured on Debian 12."""
    mirrors = tmp_path / "etc/apt/mirrors"
    mirrors.mkdir(parents=True)
    (mirrors / "debian.list").write_text("https://deb.debian.org/debian\n")
    stanza = MIRROR_STANZA.replace("/etc/apt/mirrors", str(mirrors))

    assert (
        _line_with_component("Components: main", "contrib", stanza=stanza)
        == "Components: main contrib"
    )


def test_a_mirror_file_naming_somebody_else_is_left_alone(tmp_path):
    mirrors = tmp_path / "mirrors"
    mirrors.mkdir()
    (mirrors / "vendor.list").write_text("https://pkgs.netbird.io/debian\n")
    stanza = (
        f"Types: deb\nURIs: mirror+file://{mirrors}/vendor.list\nComponents: main\n"
    )

    assert (
        _line_with_component("Components: main", "contrib", stanza=stanza)
        == "Components: main"
    )


def test_a_mirror_file_that_is_not_there_is_left_alone():
    """A source pointing at a file nobody wrote is not one to add a component
    to either."""
    stanza = (
        "Types: deb\nURIs: mirror+file:///etc/apt/mirrors/gone.list\n"
        "Components: main\n"
    )

    assert (
        _line_with_component("Components: main", "contrib", stanza=stanza)
        == "Components: main"
    )
