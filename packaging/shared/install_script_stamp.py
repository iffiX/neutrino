"""The one-command install scripts a release publishes.

``packaging/install/install.sh`` and ``packaging/install/install.ps1`` hold
their edition and the release sites on one line each near their top:
``intl`` and no site in the committed files. A build stamps both lines, and
a release publishes each script under its edition's name: ``install.sh`` and
``install.ps1`` for ``intl``, ``install-cn.sh`` and ``install-cn.ps1`` for
``cn``.

Not pure: reads and writes the scripts.
"""

from pathlib import Path

from shared.constants import (
    PACKAGING_EDITION_SUFFIXES,
    PACKAGING_INSTALL_EDITION_LINES,
    PACKAGING_INSTALL_SITES_LINES,
)


def release_name(relative: str, edition: str) -> str:
    """The name a release publishes one script under.

    Args:
        relative: The script's path in the tree, a key of
            :data:`PACKAGING_INSTALL_EDITION_LINES`.
        edition: ``intl`` or ``cn``.

    Returns:
        Its file name, ``-cn`` before the extension for ``cn``.
    """
    path = Path(relative)
    return f"{path.stem}{PACKAGING_EDITION_SUFFIXES[edition]}{path.suffix}"


def sites_text(relative: str, sites: tuple) -> str:
    """The release sites as one script's language spells them.

    Args:
        relative: The script's path in the tree.
        sites: ``{files, latest}`` per site.

    Returns:
        For ``install.sh`` each site's two addresses, every one parted by a
        space; for ``install.ps1`` one hashtable per site, parted by commas.
    """
    if relative.endswith(".ps1"):
        return ", ".join(
            f"@{{ Files = '{site['files']}'; Latest = '{site['latest']}' }}"
            for site in sites
        )
    return " ".join(f"{site['files']} {site['latest']}" for site in sites)


def stamped_text(text: str, relative: str, *, edition: str, sites: tuple) -> str:
    """One committed script's text, stamped with an edition and the sites.

    Args:
        text: The script as committed: ``intl`` and no site.
        relative: Its path in the tree.
        edition: ``intl`` or ``cn``.
        sites: ``{files, latest}`` per site.

    Returns:
        The text with both lines stamped.

    Raises:
        SystemExit: When the text holds no committed line to stamp.
    """
    edition_line = PACKAGING_INSTALL_EDITION_LINES[relative]
    sites_line = PACKAGING_INSTALL_SITES_LINES[relative]
    text = _replace_line(
        text,
        relative,
        edition_line.format(edition="intl"),
        edition_line.format(edition=edition),
    )
    return _replace_line(
        text,
        relative,
        sites_line.format(sites=""),
        sites_line.format(sites=sites_text(relative, sites)),
    )


def stamp_tree(root: Path, *, edition: str, sites: tuple) -> None:
    """Stamp both scripts of a tree in place.

    Args:
        root: The tree's root.
        edition: ``intl`` or ``cn``.
        sites: ``{files, latest}`` per site.

    Raises:
        SystemExit: When a script holds no committed line to stamp.
    """
    for relative in PACKAGING_INSTALL_EDITION_LINES:
        path = root / relative
        path.write_text(
            stamped_text(
                path.read_text(encoding="utf-8"), relative, edition=edition, sites=sites
            ),
            encoding="utf-8",
        )


def write_release_scripts(
    root: Path, output_dir: Path, *, edition: str, sites: tuple
) -> list:
    """Write both scripts of a tree, stamped, under their release names.

    Args:
        root: The tree, its scripts as committed.
        output_dir: The directory of release files.
        edition: ``intl`` or ``cn``.
        sites: ``{files, latest}`` per site.

    Returns:
        The files written.

    Raises:
        SystemExit: When a script holds no committed line to stamp.
    """
    written = []
    for relative in PACKAGING_INSTALL_EDITION_LINES:
        target = output_dir / release_name(relative, edition)
        target.write_text(
            stamped_text(
                (root / relative).read_text(encoding="utf-8"),
                relative,
                edition=edition,
                sites=sites,
            ),
            encoding="utf-8",
        )
        written.append(target)
    return written


def _replace_line(text: str, relative: str, committed: str, stamped: str) -> str:
    """Replace the first line that is exactly the committed one.

    Args:
        text: The script.
        relative: Its path in the tree, for the refusal.
        committed: The line as committed.
        stamped: The line that replaces it.

    Returns:
        The text with that line replaced and its line ending kept.

    Raises:
        SystemExit: When no line is the committed one.
    """
    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        content = line.rstrip("\r\n")
        if content == committed:
            lines[index] = stamped + line[len(content) :]
            return "".join(lines)
    raise SystemExit(f"{relative} holds no line {committed!r} to stamp")
