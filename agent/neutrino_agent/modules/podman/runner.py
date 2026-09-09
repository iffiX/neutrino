"""The container engine as a module: packages, declared units, commands.

Podman comes from the distribution, so orders ride the system-package
runner. What makes it this hub's engine, the declared containers as units
and the registry mirrors, is applied here.

Not pure: drives podman and systemd through the applier.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

from neutrino_agent.modules.base import ModuleApplyError, command_outcome
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
    PODMAN_COMMAND_CONTROL,
    PODMAN_COMMAND_JOURNAL,
    PODMAN_CONTAINER_ACTIONS,
    PODMAN_JOURNAL_LINES,
    PODMAN_UNIT,
)
from neutrino_agent.modules.podman.renderer import PodmanRegistriesRenderer
from neutrino_agent.modules.subprocess_run import CommandError, unit_state
from neutrino_agent.modules.system_package import SystemPackageModuleRunner


class PodmanModuleRunner(SystemPackageModuleRunner):
    """Installs podman by package and keeps the declared containers running."""

    name = "podman"

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
        except (CommandError, OSError) as error:
            raise ModuleApplyError("apply_failed", {"detail": str(error)[:500]})
        self._config = parsed
        self._log(f"podman: {note}; {mirror_note}")

    def stop(self) -> None:
        """Stop every declared container, leaving images and volumes."""
        container_applier().stop_all()

    def details(self, resolved: dict) -> dict:
        """Every container podman knows, and the engine's own state.

        Args:
            resolved: The module as the hub resolved it.

        Returns:
            ``{"containers", "mirrors", "version", "is_active"}``.
        """
        config = self._config or PodmanConfig()
        states = PodmanStatusReader().survey(declared_names=config.declared_names)
        return {
            "containers": [vars(state) for state in states],
            "mirrors": list(config.mirrors),
            "version": podman_version(),
            "is_active": unit_state(PODMAN_UNIT) == "active",
        }

    def command(self, action: str, args: dict, on_line=None) -> dict:
        """Run one of the engine's commands.

        Args:
            action: ``podman_control`` or ``podman_journal``.
            args: ``{"name", "action"}`` or ``{"name"}``.
            on_line: Called with each output line.

        Returns:
            ``{"exit_code", "code", "params", "output"}``.
        """
        name = str(args.get("name", ""))
        if not CONTAINER_NAME_PATTERN.match(name):
            return command_outcome(1, "container_name_invalid", {"name": name})
        if action == PODMAN_COMMAND_JOURNAL:
            lines = journal_lines(name, PODMAN_JOURNAL_LINES)
            for line in lines:
                if on_line is not None:
                    on_line(line)
            return command_outcome(0, output="\n".join(lines))
        if action != PODMAN_COMMAND_CONTROL:
            return super().command(action, args, on_line)
        verb = str(args.get("action", ""))
        if verb not in PODMAN_CONTAINER_ACTIONS:
            return command_outcome(1, "unsupported_action", {"action": verb})
        config = self._config or PodmanConfig()
        states = PodmanStatusReader().survey(declared_names=config.declared_names)
        state = next((entry for entry in states if entry.name == name), None)
        if state is None:
            return command_outcome(1, "container_unknown", {"name": name})
        try:
            PodmanContainerController().control(
                name, verb, is_declared=state.is_declared
            )
        except CommandError as error:
            return command_outcome(1, "command_failed", {"detail": error.detail[:500]})
        return command_outcome(0, output=f"{verb} {name}\n")
