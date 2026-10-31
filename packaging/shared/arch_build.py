"""Building one Arch package with makepkg.

Every Arch build writes a PKGBUILD and its install script into a directory
and hands that directory here. makepkg refuses to run as root, so a build in
a container steps down to an account the container's install step made.

Not pure: runs makepkg.
"""

import os
import pwd
import shutil
import subprocess
from pathlib import Path

# The account a build in a container runs makepkg as.
ARCH_BUILD_USER = "builder"

# The options makepkg runs with over any makepkg.conf. The payload is prebuilt
# and goes in as staged.
ARCH_PACKAGE_OPTIONS = (
    "'!strip' '!debug' '!lto' '!purge' '!zipman' 'docs' 'emptydirs' "
    "'libtool' 'staticlibs'"
)
# The format every Arch package is written in. Debian's makepkg.conf writes
# another one by default.
ARCH_PACKAGE_EXTENSION = ".pkg.tar.zst"


def builder_account(named: str = "") -> str:
    """The account makepkg runs as.

    Args:
        named: An account the command line named; empty for none.

    Returns:
        That account, else the invoking user, and :data:`ARCH_BUILD_USER`
        when the invoking user is root.
    """
    if named:
        return named
    if os.geteuid() == 0:
        return ARCH_BUILD_USER
    return pwd.getpwuid(os.geteuid()).pw_name


def build_package(
    root: Path, output_dir: Path, builder: str, *, built: str, name: str
) -> Path:
    """Run makepkg and move the result where it was asked for.

    Args:
        root: The directory holding the PKGBUILD.
        output_dir: Where the package should land.
        builder: The account makepkg runs as.
        built: The file makepkg is expected to write, so a build whose
            ``PKGEXT`` differs is refused rather than published under
            another name.
        name: The name a release holds the package under and the hub asks
            for.

    Returns:
        The path written.

    Raises:
        SystemExit: If makepkg refuses, or writes nothing under that name.
    """
    command = ["makepkg", "--nodeps", "--noconfirm", "--clean"]
    if os.geteuid() == 0:
        # makepkg will not run as root, and stepping down is `runuser`: sudo
        # is not on every Arch install and is not what this needs.
        shutil.chown(root, user=builder)
        command = ["runuser", "-u", builder, "--", *command]

    result = subprocess.run(
        command,
        cwd=root,
        capture_output=True,
        text=True,
        env={**os.environ, "PKGEXT": ARCH_PACKAGE_EXTENSION},
    )
    if result.returncode != 0:
        raise SystemExit(f"{result.stdout}\n{result.stderr}".strip()[-2000:])

    written = root / built
    if not written.is_file():
        found = ", ".join(path.name for path in sorted(root.glob("*.pkg.tar.*")))
        raise SystemExit(
            f"makepkg wrote no {built}" + (f" (found {found})" if found else "")
        )
    target = output_dir / name
    shutil.copyfile(written, target)
    return target
