"""Build the client's .rpm.

    python3 client/packaging/build_rpm.py --output-dir dist/ --architecture x86_64

The same payload the .deb carries, under /opt/neutrino_client: its own
interpreter, the window's bindings and the two binaries the client drives.
That fixes the package to one architecture, so it is built in a container of
the machine it is for.

The same maintainer scripts too: every resident is asked to quit before its
files are taken, and erasing the package takes each person's own
configuration with it.

Needs `rpmbuild`, from the `rpm` package on Debian family and `rpm-build` on
RHEL family, and `dpkg` for the viewer it unpacks out of upstream's own .deb.

Not pure: writes a package tree and runs rpmbuild.
"""

import argparse
import shutil
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import bundled  # noqa: E402
import payload  # noqa: E402
from gui_assets import ICONS_DIR  # noqa: E402

from neutrino_client.constants import (  # noqa: E402
    CLIENT_DESKTOP_NAME,
    CLIENT_MOUNT_HELPER_PATH,
    CLIENT_MOUNT_POLKIT_ACTION,
)

CLIENT_ROOT = payload.CLIENT_ROOT
PACKAGE_NAME = payload.PACKAGE_NAME

# The same C stack the .deb names, under the names the RHEL family gives
# those libraries.
RUNTIME_REQUIRES = (
    "webkit2gtk4.1",
    "gobject-introspection",
    "libayatana-appindicator-gtk3",
    "cifs-utils",
    "polkit",
    "gtk3",
    "libxcb",
    "xdotool",
    "libXfixes",
    "alsa-lib",
    "systemd-libs",
    "curl",
    "libva",
    "gstreamer1-plugins-base",
    "pam",
    "pipewire-gstreamer",
)

SPEC = """Name:           {name}
Version:        {version}
Release:        1
Summary:        Neutrino client
License:        MIT
URL:            https://github.com/iffiX/neutrino
BuildArch:      {architecture}
{requires}
Packager:       {packager}

# The payload is prebuilt and carries its own interpreter, so none of
# rpmbuild's opinions about Python belong to it: its shebangs name a path that
# exists only once installed, and its .so files are not ours to strip.
%global __brp_python_bytecompile %{{nil}}
%global __brp_mangle_shebangs %{{nil}}
%global __brp_strip %{{nil}}
%global __brp_strip_static_archive %{{nil}}
%global debug_package %{{nil}}

%description
A person's window onto the services a Neutrino Hub publishes for them: links,
ports forwarded to this machine, shares mounted under their home, the AI
gateway their tools point at, and desktops the fleet shares.

Carries its own interpreter and the window's bindings, so it installs on a
machine with no Python and touches none the machine already has.

%install
mkdir -p %{{buildroot}}
cp -a {staged}/. %{{buildroot}}/

%files
{prefix}
/usr/bin/nclient
{helper}
/usr/share/applications/{desktop}.desktop
/usr/share/icons/hicolor/*/apps/{desktop}.png
/usr/share/polkit-1/actions/{action}.policy
/usr/share/doc/{name}

%pre
{stop}
if [ "$1" -ge 2 ]; then
    stop_residents
fi

%post
if [ -d /usr/share/icons/hicolor ]; then
    gtk-update-icon-cache -f /usr/share/icons/hicolor >/dev/null 2>&1 || true
fi
update-desktop-database /usr/share/applications >/dev/null 2>&1 || true
if [ "$1" = 1 ]; then
    echo ""
    echo "  Neutrino client installed. Open it and join a hub:"
    echo ""
    echo "      nclient gui"
    echo ""
fi

%preun
{stop}
if [ "$1" = 0 ]; then
    stop_residents
fi

%postun
{wipe}
if [ "$1" = 0 ]; then
    rm -rf {prefix}
    wipe_personal_state
fi

%posttrans
{prune}
rpm -ql {name} | prune_untracked {prefix}
"""

WRAPPER = """#!/bin/sh
# The client runs from the interpreter the package carries, never the system
# one.
exec {python}/bin/python3 -m neutrino_client.cli.entry "$@"
"""

MOUNT_HELPER = """#!/bin/sh
exec {python}/bin/python3 -m neutrino_client.cli.mount_helper "$@"
"""


# RustDesk's Flutter plugins carry the runpath of upstream's build tree;
# rpm's check refuses a path that exists nowhere, and the loader ignores it.
RPMBUILD_ENVIRONMENT = {"QA_RPATHS": "0x0002"}


def main() -> int:
    """Build the package.

    Returns:
        The process exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", default="dist", help="where to write the .rpm")
    parser.add_argument(
        "--architecture",
        default=_host_architecture(),
        help="the architecture to build for",
    )
    parser.add_argument(
        "--packager",
        default="iffiX <muhanli2022@u.northwestern.edu>",
        help="the Packager tag",
    )
    arguments = parser.parse_args()

    version = payload.version()
    architecture = payload.RPM_ARCHITECTURES[
        payload.machine_name(arguments.architecture)
    ]
    output_dir = Path(arguments.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as workdir:
        root = Path(workdir)
        staged = root / "staged"
        _lay_out(staged, version, architecture)
        spec = root / f"{PACKAGE_NAME}.spec"
        spec.write_text(
            SPEC.format(
                name=PACKAGE_NAME,
                version=version,
                architecture=architecture,
                requires="\n".join(f"Requires:       {n}" for n in RUNTIME_REQUIRES),
                packager=arguments.packager,
                staged=staged,
                prefix=payload.INSTALL_PREFIX,
                helper=CLIENT_MOUNT_HELPER_PATH,
                desktop=CLIENT_DESKTOP_NAME,
                action=CLIENT_MOUNT_POLKIT_ACTION,
                prune=payload.PRUNE_UNTRACKED,
                stop=payload.STOP_RESIDENTS,
                wipe=payload.WIPE_PERSONAL_STATE,
            ),
            encoding="utf-8",
        )
        target = _build(spec, root, output_dir, version, architecture)

    print(f"wrote {target} ({target.stat().st_size // 1024 // 1024} MiB)")
    return 0


def _lay_out(staged: Path, version: str, architecture: str) -> None:
    """Write everything the package installs.

    Args:
        staged: The directory standing in for the filesystem root.
        version: The version being packaged.
        architecture: The rpm architecture name.
    """
    staged_python = staged / str(payload.PYTHON_DIR).lstrip("/")
    payload.stage_linux_interpreter(staged_python, architecture)
    payload.stage_client_tree(payload.site_packages_of(staged_python), version)
    payload.stage_linux_gui_bindings(staged_python)
    payload.compile_bytecode(staged_python, payload.PYTHON_DIR)
    payload.strip_build_paths(staged_python, staged)
    bundled.stage_linux_binaries(staged, architecture)
    payload.stage_licenses(staged)
    _lay_out_desktop(staged)

    payload.write(
        staged / "usr/bin/nclient",
        WRAPPER.format(python=payload.PYTHON_DIR),
        is_executable=True,
    )
    payload.write(
        staged / str(CLIENT_MOUNT_HELPER_PATH).lstrip("/"),
        MOUNT_HELPER.format(python=payload.PYTHON_DIR),
        is_executable=True,
    )
    payload.write(
        staged / f"usr/share/polkit-1/actions/{CLIENT_MOUNT_POLKIT_ACTION}.policy",
        (
            CLIENT_ROOT
            / "neutrino_client/data/polkit"
            / f"{CLIENT_MOUNT_POLKIT_ACTION}.policy"
        ).read_text(encoding="utf-8"),
    )


def _lay_out_desktop(staged: Path) -> None:
    """Install the launcher and the icons.

    Args:
        staged: The directory standing in for the filesystem root.
    """
    desktop = CLIENT_ROOT / "neutrino_client/data/desktop"
    payload.write(
        staged / f"usr/share/applications/{CLIENT_DESKTOP_NAME}.desktop",
        (desktop / f"{CLIENT_DESKTOP_NAME}.desktop").read_text(encoding="utf-8"),
    )
    for source, edge in (("neutrino_256.png", 256), ("neutrino_48.png", 48)):
        destination = (
            staged
            / f"usr/share/icons/hicolor/{edge}x{edge}/apps/{CLIENT_DESKTOP_NAME}.png"
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ICONS_DIR / source, destination)
        destination.chmod(0o644)


def _build(
    spec: Path, topdir: Path, output_dir: Path, version: str, architecture: str
) -> Path:
    """Run rpmbuild over the spec and move the result where it was asked for.

    Args:
        spec: The spec file to build.
        topdir: The directory rpmbuild may use for its own trees.
        output_dir: Where the .rpm should land.
        version: The version being packaged, which names the file.
        architecture: The rpm architecture name, which names it too.

    Returns:
        The path written.

    Raises:
        SystemExit: If rpmbuild refuses, or writes nothing.
    """
    result = subprocess.run(
        [
            "rpmbuild",
            "-bb",
            "--define",
            f"_topdir {topdir}",
            "--target",
            architecture,
            str(spec),
        ],
        capture_output=True,
        text=True,
        env={**os.environ, **RPMBUILD_ENVIRONMENT},
    )
    if result.returncode != 0:
        raise SystemExit((result.stderr or result.stdout).strip())

    built = (
        topdir
        / "RPMS"
        / architecture
        / f"{PACKAGE_NAME}-{version}-1.{architecture}.rpm"
    )
    if not built.is_file():
        raise SystemExit(f"rpmbuild wrote no {built.name}")
    target = output_dir / built.name
    shutil.copyfile(built, target)
    return target


def _host_architecture() -> str:
    """The rpm architecture name for the machine this runs on."""
    result = subprocess.run(["uname", "-m"], capture_output=True, text=True)
    return result.stdout.strip() or "x86_64"


if __name__ == "__main__":
    raise SystemExit(main())
