"""The container engine as a module: packages, declared units, verbs.

Podman comes from the distribution, so the install rides the
system-package runner. What makes it this hub's engine, the declared
containers as units and the registry mirrors, is applied here; every
container podman knows, declared or not, is read back with its image,
ports, volumes and environment, which is what the hub imports the first
time it configures an engine somebody set up by hand.

Not pure: drives podman and systemd through the applier.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import contextlib
import os
import subprocess

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.base import command_outcome
from neutrino_agent.modules.podman.applier import (
    PodmanContainerController,
    PodmanRegistriesApplier,
    PodmanStatusReader,
    container_applier,
    container_renderer,
    journal_lines,
    podman_version,
)
from neutrino_agent.modules.podman.config import (
    CONTAINER_NAME_PATTERN,
    PodmanConfig,
)
from neutrino_agent.modules.podman.constants import (
    PODMAN_BINARY,
    PODMAN_COMMAND_CONTROL,
    PODMAN_COMMAND_JOURNAL,
    PODMAN_CONTAINER_ACTIONS,
    PODMAN_JOURNAL_LINES,
    PODMAN_UNIT,
)
from neutrino_agent.modules.podman.renderer import PodmanRegistriesRenderer
from neutrino_agent.modules.subprocess_run import command_detail, run, unit_state
from neutrino_agent.modules.system_package import SystemPackageModuleRunner


class PodmanModuleRunner(SystemPackageModuleRunner):
    """Installs podman by package and keeps the declared containers running."""

    name = "podman"
    binary = PODMAN_BINARY

    def __init__(self, *, platform, log=print, publish=None):
        super().__init__(platform=platform, log=log, publish=publish)
        self._config: "PodmanConfig | None" = None

    def validate(self, config: dict) -> None:
        """Parse, check and render a configuration.

        Args:
            config: The desired configuration.

        Raises:
            ModuleApplyError: Naming the first problem found.
        """
        parsed = PodmanConfig.from_dict(config)
        parsed.validate()
        PodmanRegistriesRenderer(config=parsed).render()

    def apply(self, config: dict) -> None:
        """Render the units and the mirror drop-in, and reconcile systemd.

        Args:
            config: The desired configuration.

        Raises:
            ModuleApplyError: When the configuration is refused or systemd
                refuses a unit.
        """
        parsed = PodmanConfig.from_dict(config)
        parsed.validate()
        # Held before the units are started: a start waits on the image
        # pull, and a report taken meanwhile lists the declared container
        # as not created yet rather than not at all.
        self._config = parsed
        try:
            mirror_note = PodmanRegistriesApplier().apply(
                PodmanRegistriesRenderer(config=parsed).render()
            )
            note = container_applier().apply(
                container_renderer(parsed).render(),
                autostart_names=[
                    container.name
                    for container in parsed.containers
                    if container.is_autostart
                ],
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise ModuleApplyError(
                "apply_failed", {"detail": command_detail(error)[:500]}
            )
        self._log(f"podman: {note}; {mirror_note}")

    def stop(self) -> None:
        """Stop every declared container, leaving images and volumes."""
        container_applier().stop_all()

    def remove_configuration(self) -> None:
        """Take the rendered units and the mirror drop-in away; keep the data.

        Every declared container is stopped and its unit file removed;
        images, volumes and containers somebody started by hand stay.
        """
        self._config = None
        applier = container_applier()
        applier.stop_all()
        for file_name in applier.generated_names():
            with contextlib.suppress(OSError):
                os.unlink(os.path.join(applier.directory, file_name))
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            run(["systemctl", "daemon-reload"], is_checked=False)
        PodmanRegistriesApplier().apply("")

    def is_active(self) -> bool:
        """Whether the engine's own unit is active."""
        return unit_state(PODMAN_UNIT) == "active"

    def details(self, resolved: dict) -> dict:
        """Every container podman knows, and the engine's own state.

        Args:
            resolved: The module as the hub resolved it.

        Returns:
            ``{"containers", "mirrors", "version", "is_active"}``, each
            container ``{"name", "image", "status", "is_running",
            "is_declared", "host_ports", "ports", "volumes",
            "environment", "has_unit"}``.
        """
        config = self._config or PodmanConfig()
        states = PodmanStatusReader().survey(declared_names=config.declared_names)
        return {
            "containers": [vars(state) for state in states],
            "mirrors": list(config.mirrors),
            "version": podman_version(),
            "is_active": unit_state(PODMAN_UNIT) == "active",
        }

    def command(self, verb: str, args: dict, on_line=None) -> dict:
        """Run one of the engine's verbs.

        Args:
            verb: ``control``, ``journal``, or ``validate``.
            args: ``{"name", "action"}`` for control, ``{"name"}`` for the
                journal.
            on_line: Called with each output line.

        Returns:
            ``{"exit_code", "code", "params", "output"}``.
        """
        if verb not in (PODMAN_COMMAND_CONTROL, PODMAN_COMMAND_JOURNAL):
            return super().command(verb, args, on_line)
        name = str(args.get("name", ""))
        if not CONTAINER_NAME_PATTERN.match(name):
            return command_outcome(1, "container_name_invalid", {"name": name})
        if verb == PODMAN_COMMAND_JOURNAL:
            lines = journal_lines(name, PODMAN_JOURNAL_LINES)
            for line in lines:
                if on_line is not None:
                    on_line(line)
            return command_outcome(0, output="\n".join(lines))
        action = str(args.get("action", ""))
        if action not in PODMAN_CONTAINER_ACTIONS:
            return command_outcome(
                1, "verb_unknown", {"module": self.name, "verb": action}
            )
        config = self._config or PodmanConfig()
        states = PodmanStatusReader().survey(declared_names=config.declared_names)
        state = next((entry for entry in states if entry.name == name), None)
        if state is None:
            return command_outcome(1, "container_unknown", {"name": name})
        try:
            PodmanContainerController().control(
                name, action, is_declared=state.is_declared
            )
        except (OSError, subprocess.SubprocessError) as error:
            return command_outcome(
                1, "command_failed", {"detail": command_detail(error)[:500]}
            )
        return command_outcome(0, output=f"{action} {name}\n")
