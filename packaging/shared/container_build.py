"""Running one Linux package build inside a container of its own family.

The hub, the agent and the desktop client each carry an interpreter or
compiled extensions, so each is built in a container of the family and the
machine it is for, and the result does not depend on whatever machine runs
the build. The target scripts under ``packaging/build`` name the image and
the commands; this runs them.

Not pure: runs podman or docker.
"""

import os
import subprocess
from pathlib import Path

from shared.constants import PACKAGING_ARCHITECTURE_NAMES, PACKAGING_EDITION_ENV

REPO_ROOT = Path(__file__).resolve().parents[2]

# The distribution families a Linux package is built for.
CONTAINER_FAMILIES = ("debian", "rhel", "arch")

# Where the install step's output waits inside the container.
INSTALL_LOG = "/tmp/neutrino_install.log"

# The container platform for each architecture the packages are published
# for. Building for anything but the host's own needs QEMU registered with
# binfmt_misc, which is what the tag workflow does before it calls a build.
# 32-bit ARM is not on the list: nothing carried is published for it.
BUILD_PLATFORMS = {"amd64": "linux/amd64", "arm64": "linux/arm64"}

# The Debian name of the machine the kernel reports, the default target.
HOST_ARCHITECTURES = {"x86_64": "amd64", "aarch64": "arm64", "arm64": "arm64"}

# What the hub's build reads to learn where a release publishes the agent
# packages it seeds its cache with. Passed into the container only when it is
# given: without it the hub package carries the entries it seeded and no URL,
# which is what makes a local build refuse a platform it did not make rather
# than reach for a file nobody published.
AGENT_PACKAGE_URL_BASE_ENV = "NEUTRINO_AGENT_PACKAGE_URL_BASE"
# And what it reads to find agent packages already built, for every machine.
AGENT_PACKAGES_DIR_ENV = "NEUTRINO_AGENT_PACKAGES_DIR"


def families(requested: str) -> list:
    """The families to build, checked against the ones this project has.

    Args:
        requested: The comma-separated list from the command line.

    Returns:
        The family names, in the order asked for.

    Raises:
        SystemExit: When one of them is not a family at all. A family a
            package has no build for is not that: its script says so and
            moves on.
    """
    names = [name.strip() for name in requested.split(",") if name.strip()]
    for name in names:
        if name not in CONTAINER_FAMILIES:
            raise SystemExit(
                f"no build for {name}; there is one for: "
                f"{', '.join(CONTAINER_FAMILIES)}"
            )
    return names


def build_in_container(
    build: dict,
    script: str,
    output_dir: Path,
    architecture: str,
    family: str,
    *,
    agent_package_url_base: str = "",
    agent_packages: str = "",
    edition: str = "intl",
) -> None:
    """Run one packaging build inside a container of its own family.

    Args:
        build: The family's entry in the target script's table: ``image``,
            ``install``, ``script`` and, optionally, ``architecture`` and
            ``extra``.
        script: The shell command template to run inside it.
        output_dir: Where the package should land.
        architecture: The architecture to build for, named the Debian way.
        family: Which family is being built, which names the architecture.
        agent_package_url_base: Where a release publishes the agent packages
            the hub's build seeds its cache with; nothing is stamped without
            it.
        agent_packages: A directory of agent packages already built, mounted
            into the container for the hub's build to seed from; empty has
            the hub's build make its own machine's.
        edition: The edition being built, handed in as ``NEUTRINO_EDITION``.

    Raises:
        SystemExit: If the architecture is not one the packages are published
            for, no container tool is available, or the build fails.
    """
    names = PACKAGING_ARCHITECTURE_NAMES.get(architecture, {})
    platform = BUILD_PLATFORMS.get(architecture)
    if platform is None:
        raise SystemExit(
            f"the packages are published for {', '.join(BUILD_PLATFORMS)}, "
            f"not {architecture}"
        )
    engine = container_engine()
    if engine is None:
        raise SystemExit(
            "podman or docker is needed: both packages carry an interpreter "
            "and compiled extensions, so both are built on their baseline "
            "distribution"
        )
    stamp = ["-e", f"{PACKAGING_EDITION_ENV}={edition}"]
    if agent_package_url_base:
        stamp += ["-e", f"{AGENT_PACKAGE_URL_BASE_ENV}={agent_package_url_base}"]
    if agent_packages:
        stamp += [
            "-v",
            f"{Path(agent_packages).resolve()}:/agent_packages:ro",
            "-e",
            f"{AGENT_PACKAGES_DIR_ENV}=/agent_packages",
        ]
    # --network=host because this machine's own nftables rules are what a
    # container network would otherwise have to negotiate with.
    run(
        [
            engine,
            "run",
            "--rm",
            "--network=host",
            "--platform",
            platform,
            "-v",
            f"{REPO_ROOT}:/src:ro",
            "-v",
            f"{output_dir}:/out",
        ]
        + stamp
        + [
            build["image"],
            "sh",
            "-c",
            script.format(
                install=install_step(build["install"]),
                script=build["script"],
                architecture=names.get(family, architecture),
                extra=build.get("extra", ""),
            ),
        ]
    )


def container_engine() -> "str | None":
    """Whichever container tool is installed, or None."""
    for name in ("podman", "docker"):
        if has_tool(name):
            return name
    return None


def has_tool(name: str) -> bool:
    """Whether a build tool is on the path.

    Args:
        name: The executable to look for.

    Returns:
        True when it can be run.
    """
    return subprocess.run(["which", name], capture_output=True).returncode == 0


def host_architecture() -> str:
    """The Debian architecture name for this machine."""
    machine = os.uname().machine
    return HOST_ARCHITECTURES.get(machine, machine)


def install_step(install: str) -> str:
    """The shell that installs a build's tools inside its container.

    The install runs up to three times, 30 seconds apart, with its output kept
    in a file; the file's last lines are printed when the third try fails,
    and the build stops there.

    Args:
        install: The family's install command.

    Returns:
        The shell to run before the build.
    """
    return (
        "for try in 1 2 3; do "
        f"({install}) >{INSTALL_LOG} 2>&1 && break; "
        f'if [ "$try" = 3 ]; then tail -n 40 {INSTALL_LOG} >&2; exit 1; fi; '
        "sleep 30; done"
    )


def run(command: list) -> None:
    """Run a build step, failing loudly.

    Args:
        command: The argument vector.

    Raises:
        SystemExit: If the command fails.
    """
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(
            f"{' '.join(command[:2])} failed:\n{(result.stderr or result.stdout).strip()}"
        )
    if result.stdout.strip():
        print(f"  {result.stdout.strip().splitlines()[-1]}")
