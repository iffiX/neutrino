"""Build the lab's two VMs and run the integration suite on a hub package.

    sg libvirt -c "python3 packaging/lab/run_lab.py <hub package> [--lifecycle]"

Runs on: a Linux machine with libvirt, qemu and KVM, by a member of the
``libvirt`` group. The lab's cloud images, disks, seeds and SSH key live
under the directory ``NEUTRINO_VM_LAB`` names (``~/.local/share/
neutrino_vm_lab`` when it is unset), which qemu's own user must be able to
reach: a directory under ``/home`` usually is not.

``setup_vms.sh`` builds the hub VM and the client VM on the named distro and
version, the suite under ``packaging/integration`` and the package are pushed
into the hub VM, and ``run_mode_matrix.sh --client`` runs there. With
``--lifecycle`` the two VMs are built again from their images and
``run_on_box.sh`` runs on the fresh hub in the named mode. Each run prints
its phases; the exit status is the number of phases that failed.

Not pure: creates and boots VMs, runs the suite inside them.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

LAB_DIR = Path(__file__).resolve().parent
SUITE_DIR = LAB_DIR.parent / "integration"

# Where the lab keeps its files unless NEUTRINO_VM_LAB says otherwise. It is
# outside every home directory because qemu runs as its own account, which
# cannot search /home, so a root under it fails at the first disk.
LAB_ROOT_ENV = "NEUTRINO_VM_LAB"
LAB_ROOT_DEFAULT = Path("/var/lib/neutrino_vm_lab")
LAB_ROOT_FORBIDDEN = Path("/home")

# The hub VM setup_vms.sh names with its default prefix, where the suite lands
# inside it, and the libvirt connection it uses.
LAB_HUB = "nmxhub"
LAB_SUITE_DIR = "/opt/integration"
LAB_LIBVIRT_URI = "qemu:///system"

# The direct resolver the lifecycle run gives the hub. The lab's way out
# drops UDP queries to the product's default, 223.5.5.5, and this one answers.
LAB_DIRECT_DNS = "119.29.29.29"  # scan: allow

# What a run prints at the start of each phase.
PHASE_LINE = re.compile(r"^== .+ ==")


def main() -> int:
    """Run the suite.

    Returns:
        The number of phases that failed, or 1 when the lab could not be built.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("package", help="the hub package, under its release name")
    parser.add_argument("--distro", default="debian", help="the VMs' distribution")
    parser.add_argument("--version", default="12", help="its version")
    parser.add_argument(
        "--lifecycle",
        action="store_true",
        help="after the matrix, run run_on_box.sh on a fresh pair",
    )
    parser.add_argument(
        "--mode",
        default="side_gateway",
        choices=("server", "side_gateway", "router"),
        help="the mode run_on_box.sh sets the hub up in",
    )
    arguments = parser.parse_args()
    package = Path(arguments.package).resolve()
    if not package.is_file():
        raise SystemExit(f"{package} is not a file")
    lab = Path(os.environ.get(LAB_ROOT_ENV) or LAB_ROOT_DEFAULT)
    if LAB_ROOT_FORBIDDEN in lab.resolve().parents:
        raise SystemExit(
            f"the lab root {lab} is under {LAB_ROOT_FORBIDDEN}, which qemu cannot "
            f"search; set {LAB_ROOT_ENV} to a directory outside it"
        )
    _check_tools()
    environment = dict(
        os.environ, NEUTRINO_VM_LAB=str(lab), LIBVIRT_DEFAULT_URI=LAB_LIBVIRT_URI
    )

    runs = [("matrix", f"run_mode_matrix.sh /tmp/{package.name} --client")]
    if arguments.lifecycle:
        runs.append(
            ("lifecycle", f"run_on_box.sh /tmp/{package.name} {arguments.mode}")
        )
    failed_total = 0
    for name, script in runs:
        _say(f"lab: {arguments.distro} {arguments.version}, {package.name}, {name}")
        setup = subprocess.run(
            [
                "bash",
                str(LAB_DIR / "setup_vms.sh"),
                arguments.distro,
                arguments.version,
            ],
            env=environment,
        )
        if setup.returncode != 0:
            print(f"setup_vms.sh exited {setup.returncode}")
            return 1
        _say("pushing the suite")
        _push_suite(lab, package, environment)
        _say(f"running {script.split()[0]}")
        phases, failed = _run_on_hub(
            f"NEUTRINO_DIRECT_DNS={LAB_DIRECT_DNS} bash {LAB_SUITE_DIR}/{script}",
            environment,
        )
        _say(f"{name} done: {phases} phases, {failed} failed")
        failed_total += failed
    return failed_total


def _push_suite(lab: Path, package: Path, environment: dict) -> None:
    """Copy the suite, the lab's key and the package into the hub VM.

    Args:
        lab: The lab's root directory, which holds ``id_lab``.
        package: The hub package.
        environment: What the lab's tools run with.

    Raises:
        SystemExit: When a copy fails.
    """
    _vm(["mkdir -p " + LAB_SUITE_DIR], environment)
    suite = sorted(SUITE_DIR.glob("*.py")) + sorted(SUITE_DIR.glob("*.sh"))
    for path in suite + [SUITE_DIR / "pytest.ini"]:
        _vm(["push", str(path), f"{LAB_SUITE_DIR}/{path.name}"], environment)
    _vm(["push", str(lab / "id_lab"), f"{LAB_SUITE_DIR}/id_lab"], environment)
    _vm([f"chmod 600 {LAB_SUITE_DIR}/id_lab"], environment)
    _vm(["push", str(package), f"/tmp/{package.name}"], environment)


def _run_on_hub(command: str, environment: dict) -> tuple:
    """Run one of the suite's scripts in the hub VM and count its phases.

    Args:
        command: The shell command, run as root in the guest.
        environment: What the lab's tools run with.

    Returns:
        The number of phases it printed and the number that failed, which is
        its exit status.
    """
    result = subprocess.run(
        [sys.executable, str(LAB_DIR / "vm_exec.py"), LAB_HUB, command],
        env=environment,
        capture_output=True,
        text=True,
    )
    print(result.stdout, end="")
    print(result.stderr, end="", file=sys.stderr)
    phases = sum(1 for line in result.stdout.splitlines() if PHASE_LINE.match(line))
    return phases, result.returncode


def _vm(arguments: list, environment: dict) -> None:
    """Run ``vm_exec.py`` against the hub VM, failing the run when it fails.

    Raises:
        SystemExit: When it fails.
    """
    result = subprocess.run(
        [sys.executable, str(LAB_DIR / "vm_exec.py"), LAB_HUB, *arguments],
        env=environment,
    )
    if result.returncode != 0:
        raise SystemExit(f"vm_exec.py {' '.join(arguments)} exited {result.returncode}")


def _check_tools() -> None:
    """Refuse to start without libvirt's tools and the right to use them.

    Raises:
        SystemExit: When a tool is missing or libvirt refuses this user.
    """
    for tool in (
        "virsh",
        "virt-install",
        "qemu-img",
        "cloud-localds",
        "ssh-keygen",
        "curl",
    ):
        if shutil.which(tool) is None:
            raise SystemExit(f"{tool} is needed for the lab and is not on the path")
    probe = subprocess.run(
        ["virsh", "-c", LAB_LIBVIRT_URI, "list"], capture_output=True, text=True
    )
    if probe.returncode != 0:
        raise SystemExit(
            "libvirt refuses this user; run as a member of the libvirt group, "
            'for example: sg libvirt -c "python3 packaging/lab/run_lab.py ..."'
        )


def _say(text: str) -> None:
    """Print one line of the run's own progress, with the time."""
    print(f"== {text} at {time.strftime('%H:%M:%S', time.gmtime())}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
