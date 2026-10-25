"""The install scripts as a release publishes them: each stamped with its
edition and the release sites, under its edition's name."""

from pathlib import Path

import pytest

from shared import install_script_stamp
from shared.constants import (
    PACKAGING_INSTALL_EDITION_LINES,
    PACKAGING_INSTALL_SITES_LINES,
    PACKAGING_RELEASE_SITES,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
SITES = (
    {"files": "https://one.invalid/d/{tag}/", "latest": "https://one.invalid/l.json"},
    {"files": "https://two.invalid/d/{tag}/", "latest": "https://two.invalid/l.json"},
)


@pytest.mark.parametrize(
    ("relative", "edition", "name"),
    [
        ("packaging/install/install.sh", "intl", "install.sh"),
        ("packaging/install/install.ps1", "intl", "install.ps1"),
        ("packaging/install/install.sh", "cn", "install-cn.sh"),
        ("packaging/install/install.ps1", "cn", "install-cn.ps1"),
    ],
)
def test_each_script_is_published_under_its_editions_name(relative, edition, name):
    assert install_script_stamp.release_name(relative, edition) == name


def test_the_shell_script_names_each_site_as_two_addresses():
    assert install_script_stamp.sites_text("packaging/install/install.sh", SITES) == (
        "https://one.invalid/d/{tag}/ https://one.invalid/l.json "
        "https://two.invalid/d/{tag}/ https://two.invalid/l.json"
    )


def test_the_powershell_script_names_each_site_as_a_hashtable():
    assert install_script_stamp.sites_text("packaging/install/install.ps1", SITES) == (
        "@{ Files = 'https://one.invalid/d/{tag}/'; Latest = 'https://one.invalid/l.json' }, "
        "@{ Files = 'https://two.invalid/d/{tag}/'; Latest = 'https://two.invalid/l.json' }"
    )


@pytest.mark.parametrize("relative", sorted(PACKAGING_INSTALL_EDITION_LINES))
@pytest.mark.parametrize("edition", ["intl", "cn"])
def test_the_committed_script_is_stamped_on_its_two_lines_alone(relative, edition):
    committed = (REPO_ROOT / relative).read_text(encoding="utf-8")

    stamped = install_script_stamp.stamped_text(
        committed, relative, edition=edition, sites=PACKAGING_RELEASE_SITES
    )

    sites = install_script_stamp.sites_text(relative, PACKAGING_RELEASE_SITES)
    edition_line = PACKAGING_INSTALL_EDITION_LINES[relative].format(edition=edition)
    sites_line = PACKAGING_INSTALL_SITES_LINES[relative].format(sites=sites)
    changed = [
        (before, after)
        for before, after in zip(committed.splitlines(), stamped.splitlines())
        if before != after
    ]
    assert len(committed.splitlines()) == len(stamped.splitlines())
    assert [after for _before, after in changed] == (
        [sites_line] if edition == "intl" else [edition_line, sites_line]
    )


def test_a_script_with_no_committed_line_is_refused():
    with pytest.raises(SystemExit) as refused:
        install_script_stamp.stamped_text(
            'EDITION="intl"\n',
            "packaging/install/install.sh",
            edition="cn",
            sites=SITES,
        )

    assert str(refused.value) == (
        "packaging/install/install.sh holds no line 'RELEASE_SITES=\"\"' to stamp"
    )


def test_a_tree_s_scripts_are_written_stamped_under_their_release_names(tmp_path):
    for relative in PACKAGING_INSTALL_EDITION_LINES:
        (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / relative).write_text(
            (REPO_ROOT / relative).read_text(encoding="utf-8"), encoding="utf-8"
        )
    output = tmp_path / "dist"
    output.mkdir()

    written = install_script_stamp.write_release_scripts(
        tmp_path, output, edition="cn", sites=SITES
    )

    assert sorted(path.name for path in written) == ["install-cn.ps1", "install-cn.sh"]
    shell = (output / "install-cn.sh").read_text(encoding="utf-8")
    assert '\nEDITION="cn"\n' in shell
    assert '\nRELEASE_SITES="https://one.invalid/d/{tag}/ ' in shell
    assert (tmp_path / "packaging/install/install.sh").read_text(encoding="utf-8") == (
        (REPO_ROOT / "packaging/install/install.sh").read_text(encoding="utf-8")
    )
