"""Compiling a Python package into a standalone program with Nuitka.

The caller stages the package in a directory of its own, names the module
that becomes the program, and gets back the directory Nuitka wrote: the
binary and everything it loads beside it, or an app bundle on macOS. The
interpreter compiled in is the one the caller hands over, with the compiler
installed into it at :data:`NUITKA_VERSION`.

Not pure: runs the compiler.
"""

import os
import subprocess
from pathlib import Path

# The compiler, at a version that built every compiled package. A build tool
# rather than something carried, so pinned by version.
NUITKA_VERSION = "4.2.1"


def pip_install_command(python: Path) -> list:
    """The command that installs the pinned compiler into an interpreter.

    Args:
        python: The interpreter the program is compiled against.

    Returns:
        The argument vector.
    """
    return [str(python), "-m", "pip", "install", "--quiet", f"nuitka=={NUITKA_VERSION}"]


def windows_options(
    *, product_name: str, version: str, icon: Path, console_mode: str
) -> tuple:
    """The options that stamp a Windows binary's own properties.

    Args:
        product_name: The product the binary's properties name.
        version: The product and file version.
        icon: The ``.ico`` the binary shows.
        console_mode: Nuitka's ``--windows-console-mode`` value: ``force``
            for a console program, ``disable`` for a windowed one.

    Returns:
        The options, to pass as ``options`` to :func:`compile_standalone`.
    """
    return (
        f"--windows-console-mode={console_mode}",
        f"--windows-icon-from-ico={icon}",
        f"--product-name={product_name}",
        f"--product-version={version}",
        f"--file-version={version}",
    )


def compile_standalone(
    python: Path,
    entry: Path,
    output_dir: Path,
    binary_name: str,
    *,
    source_root: Path,
    options: tuple = (),
    is_output_captured: bool = False,
) -> Path:
    """One Nuitka standalone build.

    Args:
        python: The interpreter the program is compiled against.
        entry: The module that becomes the program.
        output_dir: Where the compiler works.
        binary_name: What the binary is called.
        source_root: The directory the staged package is in, which the
            compiler resolves the package from.
        options: Options beyond what every standalone build passes.
        is_output_captured: Whether the compiler's output is kept for the
            refusal rather than shown as it runs.

    Returns:
        The standalone directory: the binary and everything it loads.

    Raises:
        SystemExit: When the compiler refuses or writes no binary.
    """
    _run(
        python,
        entry,
        output_dir,
        binary_name,
        ("--standalone", "--assume-yes-for-downloads", *options),
        source_root,
        is_output_captured,
    )
    dist = output_dir / f"{entry.stem}.dist"
    if not (dist / binary_name).is_file():
        raise SystemExit(f"nuitka wrote no {binary_name} under {dist}")
    return dist


def compile_app_bundle(
    python: Path,
    entry: Path,
    output_dir: Path,
    binary_name: str,
    *,
    source_root: Path,
    app_name: str,
    icon: Path,
    version: str,
    options: tuple = (),
) -> Path:
    """One Nuitka standalone build into a macOS app bundle.

    Args:
        python: The interpreter the program is compiled against.
        entry: The module that becomes the program.
        output_dir: Where the compiler works.
        binary_name: What the binary under ``Contents/MacOS`` is called.
        source_root: The directory the staged package is in.
        app_name: The name the bundle carries.
        icon: The ``.icns`` the bundle shows.
        version: The version stamped into the bundle's own properties.
        options: Options beyond what every bundle build passes.

    Returns:
        The bundle: the binary under ``Contents/MacOS`` and everything
        beside it.

    Raises:
        SystemExit: When the compiler refuses, or writes no single bundle
            holding the binary.
    """
    _run(
        python,
        entry,
        output_dir,
        binary_name,
        (
            "--standalone",
            "--macos-create-app-bundle",
            "--assume-yes-for-downloads",
            *options,
            f"--macos-app-name={app_name}",
            f"--macos-app-icon={icon}",
            f"--macos-app-version={version}",
        ),
        source_root,
        False,
    )
    bundles = sorted(output_dir.glob("*.app"))
    if len(bundles) != 1:
        raise SystemExit(f"nuitka wrote no single app bundle under {output_dir}")
    if not (bundles[0] / "Contents" / "MacOS" / binary_name).is_file():
        raise SystemExit(f"nuitka wrote no {binary_name} under {bundles[0]}")
    return bundles[0]


def _run(
    python: Path,
    entry: Path,
    output_dir: Path,
    binary_name: str,
    options: tuple,
    source_root: Path,
    is_output_captured: bool,
) -> None:
    """Run the compiler once.

    Args:
        python: The interpreter the program is compiled against.
        entry: The module that becomes the program.
        output_dir: Where the compiler works.
        binary_name: What the binary is called.
        options: Every option before the output naming.
        source_root: The directory the staged package is in.
        is_output_captured: Whether the output is kept for the refusal.

    Raises:
        SystemExit: When the compiler exits non-zero.
    """
    command = [
        str(python),
        "-m",
        "nuitka",
        *options,
        f"--output-filename={binary_name}",
        f"--output-dir={output_dir}",
        str(entry),
    ]
    result = subprocess.run(
        command,
        capture_output=is_output_captured,
        text=True,
        env={**os.environ, "PYTHONPATH": str(source_root)},
    )
    if result.returncode == 0:
        return
    if is_output_captured:
        raise SystemExit(
            f"compiling {entry.name} failed:\n{(result.stderr or result.stdout).strip()}"
        )
    raise SystemExit(f"nuitka exited {result.returncode}")
