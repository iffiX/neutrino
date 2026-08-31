"""Build the agent's .rpm.

    python3 agent/packaging/build_rpm.py --output-dir dist/

`BuildArch: noarch`: the agent is pure standard library, so one file covers
every architecture Fedora and RHEL run on. Python itself comes from
`Requires: python3`.

The package installs under /usr/share rather than into site-packages. A noarch
package cannot name site-packages, because that path carries the Python
version — /usr/lib/python3.9 on RHEL 9, /usr/lib/python3.13 on a current
Fedora — and a file list fixed at build time would miss it on every release
but one. /usr/bin/nagent and the unit put the directory on the path instead.

Needs `rpmbuild`, from the `rpm` package on Debian family and `rpm-build` on
RHEL family.

Not pure: writes a package tree and runs rpmbuild.
"""

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_NAME = "neutrino-agent"

# Where the package puts the agent, and what /usr/bin/nagent adds to the path.
INSTALL_DIR = "/usr/share/neutrino_agent"

# The oldest Python the agent is written against; RHEL 9 ships 3.9.
MINIMUM_PYTHON = "3.9"

# RHEL family keeps units here. Debian's /lib/systemd/system is a symlink to
# this, so the two packages disagree in spelling only.
UNIT_DIR = "usr/lib/systemd/system"

SPEC = """Name:           {name}
Version:        {version}
Release:        1
Summary:        Neutrino device agent
License:        MIT
URL:            https://github.com/iffiX/neutrino
BuildArch:      noarch
Requires:       python3 >= {python}
Requires:       systemd
Packager:       {packager}

# The agent ships as source outside site-packages, which is not a tree
# rpmbuild should be byte-compiling or scanning for provides.
%global __brp_python_bytecompile %{{nil}}
%global __brp_mangle_shebangs %{{nil}}

%description
Keeps a managed machine's modules in the state its Neutrino Hub asks for:
installs and removes software from the hub's catalog, reports metrics, and
offers a small local page for joining a hub.

Pure standard library, so it runs on whatever Python the machine already has.

%install
mkdir -p %{{buildroot}}
cp -a {payload}/. %{{buildroot}}/

%files
{install_dir}
/usr/bin/nagent
/{unit_dir}/neutrino_agent.service
/usr/share/applications/neutrino_agent.desktop
/usr/share/icons/hicolor/256x256/apps/neutrino_agent.png
/usr/share/icons/hicolor/48x48/apps/neutrino_agent.png

%post
systemctl daemon-reload >/dev/null 2>&1 || true
if [ -d /usr/share/icons/hicolor ]; then
    gtk-update-icon-cache -f /usr/share/icons/hicolor >/dev/null 2>&1 || true
fi
update-desktop-database /usr/share/applications >/dev/null 2>&1 || true
if [ "$1" = 1 ]; then
    echo ""
    echo "  Neutrino agent installed. Start it and join a hub from its page:"
    echo ""
    echo "      systemctl enable --now neutrino_agent.service"
    echo "      http://127.0.0.1:8765"
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
    echo "  Leaving /etc/neutrino_agent in place; remove it by hand if this"
    echo "  machine is not going to rejoin a hub."
fi
"""

WRAPPER = """#!/bin/sh
# The agent is installed outside the system's Python path, so the module has
# to be pointed at rather than found.
PYTHONPATH={install_dir} exec /usr/bin/python3 -m neutrino_agent.cli "$@"
"""


def main() -> int:
    """Build the package.

    Returns:
        The process exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", default="dist", help="where to write the .rpm")
    parser.add_argument(
        "--packager",
        default="iffiX <muhanli2022@u.northwestern.edu>",
        help="the Packager tag",
    )
    arguments = parser.parse_args()

    version = _version()
    output_dir = Path(arguments.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as workdir:
        root = Path(workdir)
        payload = root / "payload"
        _lay_out(payload, version)
        spec = root / f"{PACKAGE_NAME}.spec"
        spec.write_text(
            SPEC.format(
                name=PACKAGE_NAME,
                version=version,
                python=MINIMUM_PYTHON,
                packager=arguments.packager,
                payload=payload,
                install_dir=INSTALL_DIR,
                unit_dir=UNIT_DIR,
            ),
            encoding="utf-8",
        )
        target = _build(spec, root, output_dir, version)

    print(f"wrote {target} ({target.stat().st_size // 1024} KiB)")
    return 0


def _lay_out(payload: Path, version: str) -> None:
    """Write everything the package installs.

    Args:
        payload: The directory standing in for the filesystem root.
        version: The version being packaged.
    """
    package_dir = payload / INSTALL_DIR.lstrip("/") / "neutrino_agent"
    shutil.copytree(
        AGENT_ROOT / "neutrino_agent",
        package_dir,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "build_package.py"),
    )
    # rpm installs no .dist-info either, so the version is stamped in the way
    # the .deb's build does it and the hub compares it against its own.
    (package_dir / "_version.py").write_text(
        f'"""Written by the packaging build. Do not edit."""\n\n'
        f'AGENT_VERSION = "{version}"\n',
        encoding="utf-8",
    )

    # Whatever umask the build ran under does not belong in a package.
    for path in package_dir.rglob("*"):
        path.chmod(0o755 if path.is_dir() else 0o644)

    _write(
        payload / "usr/bin/nagent",
        WRAPPER.format(install_dir=INSTALL_DIR),
        is_executable=True,
    )
    _write(payload / UNIT_DIR / "neutrino_agent.service", _packaged_unit())

    desktop = AGENT_ROOT / "desktop"
    _write(
        payload / "usr/share/applications/neutrino_agent.desktop",
        (desktop / "neutrino_agent.desktop").read_text(encoding="utf-8"),
    )
    for source, edge in (("neutrino_agent.png", 256), ("neutrino_agent_48.png", 48)):
        destination = (
            payload / f"usr/share/icons/hicolor/{edge}x{edge}/apps/neutrino_agent.png"
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(desktop / source, destination)


def _packaged_unit() -> str:
    """The service file with the checkout's assumptions taken out.

    The unit starts the wrapper rather than the module: installed from this
    package the agent is not on the interpreter's path, and the wrapper is
    what puts it there.

    Returns:
        The unit file to ship.
    """
    text = (AGENT_ROOT / "systemd/neutrino_agent.service").read_text(encoding="utf-8")
    kept = [
        line
        for line in text.splitlines()
        if not line.startswith(("WorkingDirectory=", "Environment=PYTHONPATH="))
    ]
    return (
        "\n".join(kept)
        .replace(
            "Documentation=file:///opt/neutrino_agent/README.md",
            "Documentation=https://github.com/iffiX/neutrino",
        )
        .replace(
            "ExecStart=/usr/bin/python3 -m neutrino_agent.cli run",
            "ExecStart=/usr/bin/nagent run",
        )
        + "\n"
    )


def _build(spec: Path, topdir: Path, output_dir: Path, version: str) -> Path:
    """Run rpmbuild over the spec and move the result where it was asked for.

    Args:
        spec: The spec file to build.
        topdir: The directory rpmbuild may use for its own trees.
        output_dir: Where the .rpm should land.
        version: The version being packaged, which names the file.

    Returns:
        The path written.

    Raises:
        SystemExit: If rpmbuild refuses, or writes nothing.
    """
    result = subprocess.run(
        ["rpmbuild", "-bb", "--define", f"_topdir {topdir}", str(spec)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit((result.stderr or result.stdout).strip())

    built = topdir / "RPMS" / "noarch" / f"{PACKAGE_NAME}-{version}-1.noarch.rpm"
    if not built.is_file():
        raise SystemExit(f"rpmbuild wrote no {built.name}")
    target = output_dir / built.name
    shutil.copyfile(built, target)
    return target


def _version() -> str:
    """The version declared in the agent's pyproject."""
    for line in (
        (AGENT_ROOT / "pyproject.toml").read_text(encoding="utf-8").splitlines()
    ):
        if line.startswith("version = "):
            return line.split('"')[1]
    raise SystemExit("no version in agent/pyproject.toml")


def _write(path: Path, text: str, *, is_executable: bool = False) -> None:
    """Write one file into the tree, creating its parents.

    Args:
        path: Where to write.
        text: What to write.
        is_executable: Whether to mark it 0755.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755 if is_executable else 0o644)


if __name__ == "__main__":
    raise SystemExit(main())
