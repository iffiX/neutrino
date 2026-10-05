"""What every .deb of the project's writes into its control file alike.

Not pure: reads a package tree.
"""

from pathlib import Path

# The control directory, which installs nothing.
DEB_CONTROL_DIR = "DEBIAN"
# The unit Installed-Size counts in, and what each entry that is not a
# regular file counts for, as dpkg-gencontrol counts them.
DEB_SIZE_UNIT_BYTES = 1024
DEB_SIZE_OTHER_ENTRY_KIB = 1


def installed_size_kib(tree: Path) -> int:
    """The package's Installed-Size: what its files take once installed.

    Each regular file counts its size in KiB rounded up, and each directory
    and link one KiB; the control directory counts nothing.

    Args:
        tree: The package tree, standing in for the filesystem root.

    Returns:
        The size in KiB.
    """
    total = 0
    for path in tree.rglob("*"):
        if path.relative_to(tree).parts[0] == DEB_CONTROL_DIR:
            continue
        if path.is_file() and not path.is_symlink():
            total += -(-path.stat().st_size // DEB_SIZE_UNIT_BYTES)
        else:
            total += DEB_SIZE_OTHER_ENTRY_KIB
    return total
