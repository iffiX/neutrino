"""Build the hub's .rpm.

    python3 hub/packaging/build_rpm.py --output-dir dist/

The package carries the same environment the .deb does, described the way RPM
wants it. The interpreter travels with it, so the only thing this depends on
from the distribution is what the hub itself drives; the compiled wheels
inside it are what fixes the architecture.

Needs `rpmbuild`, from `rpm-build` on the RHEL family and `rpm` on Debian's.

Not pure: creates a virtual environment, installs into it, runs rpmbuild.
"""

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path

from venv_tree import (
    PACKAGE_NAME,
    dependencies,
    recommendations,
    PYTHON_DIR,
    build_environment,
    panel_unit,
    require_built_frontend,
    version,
    write,
    WRAPPER,
)

# RHEL family keeps units here; Debian's /lib/systemd/system is a symlink to
# it, so the two packages disagree in spelling only.
UNIT_DIR = "usr/lib/systemd/system"

SPEC = """Name:           {name}
Version:        {version}
Release:        1
Summary:        Neutrino Hub, a personal developer infrastructure hub
License:        MIT AND MPL-2.0 AND CC-BY-SA-4.0
URL:            https://github.com/iffiX/neutrino
BuildArch:      {architecture}
Requires:       {requires}
Recommends:     {recommends}
Packager:       {packager}

# The environment is prebuilt and carries its own interpreter, so none of
# rpmbuild's opinions about Python belong to it: its shebangs name a path that
# exists only once installed, and its .so files are not ours to strip. What
# rpmbuild does keep doing is reading those files for the glibc symbols they
# need, which is a dependency the .deb has no way to declare.
%global __brp_python_bytecompile %{{nil}}
%global __brp_mangle_shebangs %{{nil}}
%global __brp_strip %{{nil}}
%global __brp_strip_static_archive %{{nil}}
%global debug_package %{{nil}}

%description
Transparent proxy routing, LAN device management, an AI gateway and a web
control panel, on one box. Carries its own Python environment, the proxy and
the AI gateway it drives, and touches nothing the system installed.

The licence above covers what the package contains: Neutrino itself is MIT,
Xray-core is MPL-2.0 and the address database is CC-BY-SA-4.0. Their full
texts are installed under %{{_docdir}}/{name}/licenses.

%install
mkdir -p %{{buildroot}}
cp -a {payload}/. %{{buildroot}}/

%files
/opt/neutrino
/usr/bin/nhub
/{unit_dir}/neutrino_hub_web.service
%dir /var/lib/neutrino
/var/lib/neutrino/geodata
%license /usr/share/doc/{name}/licenses/*
%dir /usr/share/doc/{name}/licenses

%post
install -d -m 755 /etc/neutrino
install -d -m 700 /etc/neutrino/hub
install -d -m 755 /var/lib/neutrino
install -d -m 755 /var/lib/neutrino/generated
install -d -m 755 /var/log/neutrino
systemctl daemon-reload >/dev/null 2>&1 || true

# An upgrade can change the unit files and the software they start, and
# `nhub apply` is what writes them onto a box somebody already set up.
if [ "$1" -ge 2 ]; then
    nhub apply >/dev/null 2>&1 ||
        echo "  Run 'sudo nhub apply' to pick up this version."
    # And the panel, because it is the process running the code this package
    # just replaced. `nhub apply` re-renders what the modules produce and
    # restarts what consumes it, but the panel serves itself: without this it
    # goes on running the old Python behind the new frontend, which is a strip
    # asking for fields the old API does not send. Only when it is already up
    # — a box nobody has set up has no panel to restart.
    systemctl try-restart neutrino_hub_web.service >/dev/null 2>&1 || true
else
    echo ""
    echo "  Neutrino Hub installed. Set it up with:"
    echo ""
    echo "      sudo nhub setup"
    echo ""
fi

%preun
if [ "$1" = 0 ]; then
    for unit in neutrino_hub_web neutrino_hub_router neutrino_hub_xray neutrino_hub_cliproxyapi; do
        systemctl stop "${{unit}}.service" >/dev/null 2>&1 || true
        systemctl disable "${{unit}}.service" >/dev/null 2>&1 || true
    done
fi

%postun
systemctl daemon-reload >/dev/null 2>&1 || true
if [ "$1" = 0 ]; then
    # What is left once rpm removes its own files is the bytecode the
    # interpreter wrote while it ran.
    rm -rf /opt/neutrino
    echo "  Leaving /etc/neutrino/hub in place; remove it by hand if you"
    echo "  no longer need the node credentials and device keys it holds."
fi
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
        help="the BuildArch field; must match the machine building it",
    )
    parser.add_argument(
        "--packager",
        default="iffiX <muhanli2022@u.northwestern.edu>",
        help="the Packager tag",
    )
    arguments = parser.parse_args()

    require_built_frontend()
    package_version = version()
    output_dir = Path(arguments.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as workdir:
        root = Path(workdir)
        payload = root / "payload"
        build_environment(payload, package_version, arguments.architecture)
        write(
            payload / "usr/bin/nhub",
            WRAPPER.format(python=PYTHON_DIR),
            is_executable=True,
        )
        write(payload / UNIT_DIR / "neutrino_hub_web.service", panel_unit())

        spec = root / f"{PACKAGE_NAME}.spec"
        spec.write_text(
            SPEC.format(
                name=PACKAGE_NAME,
                version=package_version,
                architecture=arguments.architecture,
                packager=arguments.packager,
                payload=payload,
                unit_dir=UNIT_DIR,
                requires=" ".join(dependencies("rhel")),
                recommends=" ".join(recommendations("rhel")),
            ),
            encoding="utf-8",
        )
        target = _build(spec, root, output_dir, package_version, arguments.architecture)

    print(f"wrote {target} ({target.stat().st_size // 1024 // 1024} MiB)")
    return 0


def _build(
    spec: Path, topdir: Path, output_dir: Path, package_version: str, architecture: str
) -> Path:
    """Run rpmbuild over the spec and move the result where it was asked for.

    Args:
        spec: The spec file to build.
        topdir: The directory rpmbuild may use for its own trees.
        output_dir: Where the .rpm should land.
        package_version: The version being packaged, which names the file.
        architecture: The architecture directory rpmbuild writes into.

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
        raise SystemExit((result.stderr or result.stdout).strip()[-2000:])

    name = f"{PACKAGE_NAME}-{package_version}-1.{architecture}.rpm"
    built = topdir / "RPMS" / architecture / name
    if not built.is_file():
        raise SystemExit(f"rpmbuild wrote no {name}")
    target = output_dir / name
    shutil.copyfile(built, target)
    return target


def _host_architecture() -> str:
    """The RPM architecture name for the machine running this."""
    result = subprocess.run(
        ["rpm", "--eval", "%{_arch}"], capture_output=True, text=True
    )
    return result.stdout.strip() or "x86_64"


if __name__ == "__main__":
    raise SystemExit(main())
