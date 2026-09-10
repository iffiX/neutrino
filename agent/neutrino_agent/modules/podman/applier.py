"""Making the declared containers true on the machine, and reading what runs.

Declared containers live as unit files and are driven through systemd;
containers someone started by hand at a shell are still listed and still
controllable, through podman directly.

Not pure: writes unit files, runs podman and drives systemd.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, field

from neutrino_agent.modules.podman.config import PodmanConfig
from neutrino_agent.modules.podman.constants import (
    PODMAN_BINARY,
    PODMAN_CONTAINER_ACTIONS,
    PODMAN_GENERATED_MARKER,
    PODMAN_QUADLET_DIR,
    PODMAN_QUADLET_VERSION,
    PODMAN_REGISTRIES_CONF_PATH,
    PODMAN_UNIT_DIR,
)
from neutrino_agent.modules.podman.renderer import (
    PodmanQuadletRenderer,
    PodmanUnitRenderer,
)
from neutrino_agent.modules.subprocess_run import run, unit_state

VERSION_NUMBER_PATTERN = re.compile(r"\d+")


@dataclass
class PodmanContainerState:
    """One container as podman sees it right now.

    Attributes:
        name: The container's name.
        image: The image it runs.
        status: Podman's own words, for example ``Up 2 hours``.
        is_running: Whether it is running.
        is_declared: Whether the hub declares it.
        host_ports: The published host ports.
    """

    name: str
    image: str
    status: str
    is_running: bool
    is_declared: bool
    host_ports: list = field(default_factory=list)


def is_version_at_least(version: str, floor: str) -> bool:
    """Whether a version string reaches a floor, comparing numeric parts.

    Args:
        version: What ``podman --version`` printed last, distribution
            suffixes allowed.
        floor: The version to reach.

    Returns:
        True when ``version`` is the floor or above.
    """
    have = [int(part) for part in VERSION_NUMBER_PATTERN.findall(version.split("-")[0])]
    want = [int(part) for part in VERSION_NUMBER_PATTERN.findall(floor)]
    if not have:
        return False
    width = max(len(have), len(want))
    have += [0] * (width - len(have))
    want += [0] * (width - len(want))
    return have >= want


def is_quadlet_supported() -> bool:
    """Whether the installed podman turns a ``.container`` file into a unit.

    Returns:
        True from podman 4.4; False below it or when podman cannot run.
    """
    try:
        result = run([PODMAN_BINARY, "--version"], is_checked=False, timeout_s=30)
    except (OSError, subprocess.SubprocessError):
        return False
    if not result.is_success:
        return False
    words = result.stdout.split()
    return is_version_at_least(words[-1] if words else "", PODMAN_QUADLET_VERSION)


def podman_version() -> str:
    """The version podman prints, empty when it cannot run."""
    try:
        result = run([PODMAN_BINARY, "--version"], is_checked=False, timeout_s=30)
    except (OSError, subprocess.SubprocessError):
        return ""
    words = result.stdout.split()
    return words[-1] if result.is_success and words else ""


def container_renderer(config: PodmanConfig):
    """The renderer whose output this machine's podman understands."""
    if is_quadlet_supported():
        return PodmanQuadletRenderer(config=config)
    return PodmanUnitRenderer(config=config)


def container_applier() -> "PodmanUnitApplier":
    """The applier for whichever files :func:`container_renderer` produced."""
    if is_quadlet_supported():
        return PodmanUnitApplier(directory=PODMAN_QUADLET_DIR, suffix=".container")
    return PodmanUnitApplier(directory=PODMAN_UNIT_DIR, suffix=".service")


class PodmanUnitApplier:
    """Installs rendered container units and reconciles systemd with them."""

    def __init__(self, *, directory: str, suffix: str):
        """
        Args:
            directory: Where the files are written.
            suffix: What the rendered files are called, ``.container`` for
                Quadlet and ``.service`` without it.
        """
        self._directory = directory
        self._suffix = suffix

    @property
    def directory(self) -> str:
        """Where this applier writes."""
        return self._directory

    def apply(self, rendered: dict, *, autostart_names: list) -> str:
        """Write the rendered files, drop stale ones, and recreate what changed.

        Only files carrying the generated marker are ever removed: a file a
        person wrote by hand beside these is theirs.

        Args:
            rendered: File contents keyed by file name.
            autostart_names: Containers that should be running; a changed
                one of these is restarted even if it was stopped.

        Returns:
            A short summary of what changed.

        Raises:
            subprocess.CalledProcessError: If systemd refuses a unit.
        """
        os.makedirs(self._directory, exist_ok=True)
        changed = []
        for file_name, text in rendered.items():
            path = os.path.join(self._directory, file_name)
            if _read(path) != text:
                with open(path, "w", encoding="utf-8") as stream:
                    stream.write(text)
                changed.append(file_name)
        for file_name in self.generated_names():
            if file_name in rendered:
                continue
            unit = f"{file_name[: -len(self._suffix)]}.service"
            run(["systemctl", "disable", "--now", unit], is_checked=False)
            os.unlink(os.path.join(self._directory, file_name))
            changed.append(f"-{file_name}")
        run(["systemctl", "daemon-reload"])
        for file_name in rendered:
            if file_name not in changed:
                continue
            name = file_name[: -len(self._suffix)]
            unit = f"{name}.service"
            if name in autostart_names or unit_state(unit) == "active":
                run(["systemctl", "restart", unit], timeout_s=900)
        if not changed:
            return "containers unchanged"
        return f"containers: {', '.join(sorted(changed))}"

    def stop_all(self) -> None:
        """Stop every generated unit, leaving its file in place."""
        for file_name in self.generated_names():
            unit = f"{file_name[: -len(self._suffix)]}.service"
            run(["systemctl", "disable", "--now", unit], is_checked=False)

    def generated_names(self) -> list:
        """The rendered files this applier owns in its directory."""
        if not os.path.isdir(self._directory):
            return []
        names = []
        for file_name in sorted(os.listdir(self._directory)):
            if not file_name.endswith(self._suffix):
                continue
            text = _read(os.path.join(self._directory, file_name))
            if text is not None and text.startswith(PODMAN_GENERATED_MARKER):
                names.append(file_name)
        return names


class PodmanRegistriesApplier:
    """Installs the docker.io mirror drop-in, or removes it."""

    def apply(self, rendered: str) -> str:
        """Write the drop-in, or take it away when no mirrors are declared.

        Args:
            rendered: The drop-in text, empty for none.

        Returns:
            A short summary of what changed.
        """
        path = PODMAN_REGISTRIES_CONF_PATH
        if rendered == "":
            if os.path.isfile(path):
                os.unlink(path)
                return "mirrors removed"
            return "no mirrors"
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if _read(path) == rendered:
            return "mirrors unchanged"
        with open(path, "w", encoding="utf-8") as stream:
            stream.write(rendered)
        return "mirrors updated"


class PodmanStatusReader:
    """Reads what podman is running right now."""

    def survey(self, *, declared_names: list) -> list:
        """List every container, running or not.

        Args:
            declared_names: The names the hub declares, to mark ownership.

        Returns:
            One :class:`PodmanContainerState` per container podman knows,
            declared ones first. Empty when podman is absent.
        """
        try:
            result = run(
                [PODMAN_BINARY, "ps", "-a", "--format", "json"],
                is_checked=False,
                timeout_s=30,
            )
        except (OSError, subprocess.SubprocessError):
            return []
        if not result.is_success:
            return []
        try:
            entries = json.loads(result.stdout or "[]")
        except ValueError:
            return []
        states = []
        for entry in entries:
            names = entry.get("Names") or ["?"]
            states.append(
                PodmanContainerState(
                    name=names[0],
                    image=entry.get("Image", ""),
                    status=entry.get("Status", ""),
                    is_running=entry.get("State", "") == "running",
                    is_declared=names[0] in declared_names,
                    host_ports=_host_ports(entry.get("Ports") or []),
                )
            )
        # A declared container with autostart off exists only as a unit
        # until its first start, so podman has no row for it yet.
        present = {state.name for state in states}
        for name in declared_names:
            if name not in present:
                states.append(
                    PodmanContainerState(
                        name=name,
                        image="",
                        status="not created yet",
                        is_running=False,
                        is_declared=True,
                    )
                )
        states.sort(key=_declared_first)
        return states


class PodmanContainerController:
    """Starts and stops containers, each through its rightful owner."""

    def control(self, name: str, action: str, *, is_declared: bool) -> None:
        """Start, stop or restart one container.

        A declared container is driven through systemd, which supervises
        it; an ad-hoc container has no unit, so podman is the only handle.

        Args:
            name: The container's name.
            action: One of :data:`PODMAN_CONTAINER_ACTIONS`.
            is_declared: Whether the hub declares it.

        Raises:
            ValueError: For an action outside the list.
            subprocess.CalledProcessError: If the container refuses.
        """
        if action not in PODMAN_CONTAINER_ACTIONS:
            raise ValueError(action)
        if not is_declared:
            run([PODMAN_BINARY, action, name], timeout_s=120)
            return
        try:
            run(["systemctl", action, f"{name}.service"], timeout_s=900)
        except (OSError, subprocess.SubprocessError):
            # netavark's first veth of a boot sometimes fails and the unit's
            # own Restart heals it a second later.
            time.sleep(2)
            if unit_state(f"{name}.service") != "active" or action == "stop":
                raise


def journal_lines(name: str, lines: int) -> list:
    """The tail of one container unit's journal.

    Args:
        name: The container's name.
        lines: How many lines to read.

    Returns:
        The lines, in order.
    """
    try:
        result = run(
            [
                "journalctl",
                "-u",
                f"{name}.service",
                "-n",
                str(lines),
                "--no-pager",
                "--output",
                "short-iso",
            ],
            is_checked=False,
            timeout_s=30,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return (result.stdout or result.stderr).splitlines()


def _declared_first(state: PodmanContainerState) -> tuple:
    return (not state.is_declared, state.name)


def _host_ports(entries: list) -> list:
    ports = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        port = entry.get("host_port")
        if isinstance(port, int) and port > 0:
            ports.add(port)
    return sorted(ports)


def _read(path: str) -> "str | None":
    try:
        with open(path, "r", encoding="utf-8") as stream:
            return stream.read()
    except OSError:
        return None
