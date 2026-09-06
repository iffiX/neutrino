"""Build the agent's .rpm.

    python3 agent/packaging/build_rpm.py --output-dir dist/ --architecture x86_64

The same payload the .deb carries, under /opt/neutrino_agent: its own
interpreter and the window's bindings built beside it. That fixes the package
to one architecture, so it is built in a container of the machine it is for.

Needs `rpmbuild`, from the `rpm` package on Debian family and `rpm-build` on
RHEL family, and the development headers the window's bindings compile
against.

Not pure: writes a package tree and runs rpmbuild.
"""

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import payload  # noqa: E402
from gui_assets import ICONS_DIR  # noqa: E402

AGENT_ROOT = payload.AGENT_ROOT
PACKAGE_NAME = payload.PACKAGE_NAME

# RHEL family keeps units here. Debian's /lib/systemd/system is a symlink to
# this, so the two packages disagree in spelling only.
UNIT_DIR = "usr/lib/systemd/system"

# The C stack the window loads through its own bindings. This family ships
# each library's typelib in the library's own package, so naming the web view
# names the whole chain.
RUNTIME_REQUIRES = ("webkit2gtk4.1", "gobject-introspection", "systemd")

SPEC = """Name:           {name}
Version:        {version}
Release:        1
Summary:        Neutrino device agent
License:        MIT
URL:            https://github.com/iffiX/neutrino
BuildArch:      {architecture}
{requires}
Recommends:     cifs-utils
Recommends:     openssh-server
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
Keeps a managed machine's modules in the state its Neutrino Hub asks for:
installs and removes software from the hub's catalog, reports metrics, and
offers a window for joining a hub and choosing what this machine runs.

Carries its own interpreter and the window's bindings, so it installs on a
machine with no Python and touches none the machine already has.

%install
mkdir -p %{{buildroot}}
cp -a {staged}/. %{{buildroot}}/

%files
{prefix}
/usr/bin/nagent
/{unit_dir}/neutrino_agent.service
/usr/share/applications/neutrino_agent.desktop
/usr/share/icons/hicolor/256x256/apps/neutrino_agent.png
/usr/share/icons/hicolor/48x48/apps/neutrino_agent.png

%pre
# Python writes __pycache__ into the carried tree while the agent runs; rpm
# does not own those files, and they would stay behind over the new ones.
if [ "$1" -ge 2 ] && [ -d {prefix} ]; then
    find {prefix} -type d -name __pycache__ -prune -print0 |
        xargs -0 -r rm -rf 2>/dev/null || true
fi

%post
systemctl daemon-reload >/dev/null 2>&1 || true
# An upgrade must restart the running agent: the self-update path ends
# here, and without the restart the old process goes on beating.
if [ "$1" -ge 2 ]; then
    systemctl try-restart neutrino_agent.service >/dev/null 2>&1 || true
fi
if [ -d /usr/share/icons/hicolor ]; then
    gtk-update-icon-cache -f /usr/share/icons/hicolor >/dev/null 2>&1 || true
fi
update-desktop-database /usr/share/applications >/dev/null 2>&1 || true
if [ "$1" = 1 ]; then
    echo ""
    echo "  Neutrino agent installed. Start it and join a hub from its window:"
    echo ""
    echo "      systemctl enable --now neutrino_agent.service"
    echo "      nagent gui"
    echo ""
fi

%preun
if [ "$1" = 0 ]; then
    systemctl stop neutrino_agent.service >/dev/null 2>&1 || true
    systemctl disable neutrino_agent.service >/dev/null 2>&1 || true
fi

%postun
systemctl daemon-reload >/dev/null 2>&1 || true
if [ "$1" = 0 ]; then
    rm -rf {prefix}
    echo "  Leaving /etc/neutrino/agent in place; remove it by hand if this"
    echo "  machine is not going to rejoin a hub."
fi
"""

WRAPPER = """#!/bin/sh
# The agent runs from the interpreter the package carries, never the system
# one; the window process it starts inherits the same one.
exec {python}/bin/python3 -m neutrino_agent.cli.entry "$@"
"""


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
                unit_dir=UNIT_DIR,
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
    payload.stage_agent_tree(payload.site_packages_of(staged_python), version)
    payload.stage_linux_gui_bindings(staged_python)
    payload.strip_build_paths(staged_python, staged)

    payload.write(
        staged / "usr/bin/nagent",
        WRAPPER.format(python=payload.PYTHON_DIR),
        is_executable=True,
    )
    payload.write(
        staged / UNIT_DIR / "neutrino_agent.service",
        (AGENT_ROOT / "neutrino_agent/data/systemd/neutrino_agent.service").read_text(
            encoding="utf-8"
        ),
    )

    desktop = AGENT_ROOT / "neutrino_agent/data/desktop"
    payload.write(
        staged / "usr/share/applications/neutrino_agent.desktop",
        (desktop / "neutrino_agent.desktop").read_text(encoding="utf-8"),
    )
    for source, edge in (("neutrino_256.png", 256), ("neutrino_48.png", 48)):
        destination = (
            staged / f"usr/share/icons/hicolor/{edge}x{edge}/apps/neutrino_agent.png"
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
