"""The container engine as a module: packages, declared and hub units, verbs.

Podman comes from the distribution, so the install rides the
system-package runner, and ``podman.socket`` is turned on at the install
and at every apply under ``running``, and off by **Stop**. What makes it
this hub's engine, the declared containers and the hub containers as units
and the registry mirrors, is applied here; a module's hub containers are
rendered once its images are in the store. Every container podman knows is
read back with its owner, image, ports, volumes and environment, which is
what the hub imports the first time it configures an engine somebody set
up by hand. The names of the declared and hub containers are kept in a
root-only record, read until the first apply after a start. Every step of
the module's task takes the step lock ``containers`` alone. **Stop** stops
and disables every declared and hub unit, and an apply under ``stopped``
enables and starts none of them.

Not pure: drives podman and systemd through the applier.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import contextlib
import dataclasses
import functools
import os
import shutil
import subprocess

from neutrino_agent.constants import AGENT_STEP_CONFIGURE, AGENT_WANT_STOPPED
from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.shared.base import command_outcome
from neutrino_agent.modules.podman.applier import (
    PodmanContainerController,
    PodmanRegistriesApplier,
    PodmanStatusReader,
    PodmanUnitApplier,
    ensure_network,
    fastest_sources,
    image_references,
    journal_lines,
    network_gateway,
    podman_version,
    ready_hub_containers,
)
from neutrino_agent.modules.podman.config import (
    CONTAINER_NAME_PATTERN,
    PodmanConfig,
)
from neutrino_agent.modules.podman.constants import (
    PODMAN_API_UNIT,
    PODMAN_BINARY,
    PODMAN_COMMAND_CONTROL,
    PODMAN_COMMAND_JOURNAL,
    PODMAN_CONTAINER_ACTIONS,
    PODMAN_DEFAULT_NETWORK,
    PODMAN_JOURNAL_LINES,
    PODMAN_RECORD_ACCOUNT,
    PODMAN_RECORD_FIELDS,
    PODMAN_RUNTIME,
    PODMAN_UNIT,
)
from neutrino_agent.modules.podman.page_ports import PodmanPagePortStore
from neutrino_agent.modules.podman.renderer import (
    PodmanRegistriesRenderer,
    PodmanRenderContext,
    PodmanUnitRenderer,
)
from neutrino_agent.modules.podman.service_probe import PodmanServiceProbe
from neutrino_agent.modules.shared.record_store import InstanceRecordStore
from neutrino_agent.modules.shared.step_locks import CONTAINERS_ALONE_LOCKS
from neutrino_agent.modules.shared.subprocess_run import command_detail, run, unit_state
from neutrino_agent.modules.shared.system_package import SystemPackageModuleRunner


def without_present_runtime(recipe: dict) -> dict:
    """A recipe whose packages leave out ``runc`` while a ``runc`` is on the path.

    Docker CE's ``containerd.io`` includes its own ``runc`` and conflicts
    with the distribution's package.

    Args:
        recipe: The module's recipe.

    Returns:
        A copy with ``runc`` out of ``params.packages`` where one is on the
        path; the recipe as it is otherwise.
    """
    params = recipe.get("params") if isinstance(recipe, dict) else None
    if not isinstance(params, dict) or shutil.which(PODMAN_RUNTIME) is None:
        return recipe
    packages = [name for name in params.get("packages") or [] if name != PODMAN_RUNTIME]
    return {**recipe, "params": {**params, "packages": packages}}


class PodmanModuleRunner(SystemPackageModuleRunner):
    """Installs podman by package and keeps the declared and hub containers running."""

    runner = "podman"
    name = "podman"
    binary = PODMAN_BINARY

    def __init__(self, *, platform, log=print, publish=None):
        super().__init__(platform=platform, log=log, publish=publish)
        self._config: "PodmanConfig | None" = None
        self._written: "PodmanConfig | None" = None
        self._wanted: "PodmanConfig | None" = None
        self._source_sets: dict = {}
        self._probe = PodmanServiceProbe()
        var_dir = platform.agent_var_dir()
        self._records = InstanceRecordStore(
            directory=os.path.join(var_dir, self.name), fields=PODMAN_RECORD_FIELDS
        )
        self._page_ports = PodmanPagePortStore(directory=var_dir)

    def take_config(self, config: dict) -> None:
        """Take the configuration the state names, before any apply of it.

        Args:
            config: The module's configuration in the state.
        """
        self._wanted = PodmanConfig.from_dict(config)

    def take_source_sets(self, source_sets: dict) -> None:
        """Take the state's ``source_sets`` section.

        Args:
            source_sets: ``{name: {probe, sources, variables}}``.
        """
        self._source_sets = dict(source_sets)

    def install(self, recipe: dict) -> None:
        """Install the packages, then turn ``podman.socket`` on.

        ``runc`` is left out where a ``runc`` is already on the path.

        Args:
            recipe: The module's recipe.

        Raises:
            InstallError: If a step or the package manager refuses.
            PlatformUnsupportedError: If this platform installs nothing.
            subprocess.CalledProcessError: If systemd refuses the socket.
        """
        super().install(without_present_runtime(recipe))
        run(["systemctl", "enable", "--now", PODMAN_UNIT])

    def step_locks(self, step: str) -> tuple:
        """``containers`` alone, for every step of the module's own task.

        Args:
            step: The step's name.

        Returns:
            The ``(lock, mode)`` pair.
        """
        return CONTAINERS_ALONE_LOCKS

    def configure_steps(self, config: dict, want: str, steps: list) -> list:
        """The core's steps, the ``configure`` under ``stopped`` applying with no container started.

        Args:
            config: The configuration the task's entry carries.
            want: ``running`` or ``stopped``.
            steps: ``configure``, then ``start`` or ``stop``.

        Returns:
            The steps.
        """
        if want != AGENT_WANT_STOPPED:
            return steps
        return [
            (
                dataclasses.replace(
                    step, run=functools.partial(self._run_apply_stopped, dict(config))
                )
                if step.name == AGENT_STEP_CONFIGURE
                else step
            )
            for step in steps
        ]

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

        Each module's hub containers are rendered once every one of its
        images is in the store, on its network, which is made when missing,
        with the gateway of each container's network as
        ``host.containers.internal``, its page port on loopback and its
        source sets' fastest sources in its environment. A declared
        container the checks refuse is left out, and the rest is applied.

        Args:
            config: The desired configuration.

        Raises:
            ModuleApplyError: When the configuration is refused or systemd
                refuses a unit; the first left-out container's refusal once
                the rest is applied.
        """
        self._apply(config, is_started=True)

    def apply_stopped(self, config: dict) -> None:
        """Render the units and the mirror drop-in under ``stopped``, every unit disabled and none started.

        Args:
            config: The desired configuration.

        Raises:
            ModuleApplyError: As :meth:`apply` does.
        """
        self._apply(config, is_started=False)

    def start(self) -> None:
        """Turn ``podman.socket`` on, so Podman starts with the machine.

        Raises:
            ModuleApplyError: ``apply_failed`` when systemd refuses.
        """
        try:
            run(["systemctl", "enable", "--now", PODMAN_UNIT])
        except (OSError, subprocess.SubprocessError) as error:
            raise ModuleApplyError(
                "apply_failed", {"detail": command_detail(error)[:500]}
            )

    def stop(self) -> None:
        """Stop and disable every declared and hub container, then ``podman.service`` and ``podman.socket``.

        A container a person started by hand keeps running; images and
        volumes stay.

        Raises:
            ModuleApplyError: ``apply_failed`` when systemd refuses the socket.
        """
        PodmanUnitApplier().stop_all()
        run(["systemctl", "disable", "--now", PODMAN_API_UNIT], is_checked=False)
        try:
            run(["systemctl", "disable", "--now", PODMAN_UNIT])
        except (OSError, subprocess.SubprocessError) as error:
            raise ModuleApplyError(
                "apply_failed", {"detail": command_detail(error)[:500]}
            )

    def remove_configuration(self) -> None:
        """Take the rendered units and the mirror drop-in away; keep the data.

        Every declared and hub container is stopped, its unit disabled and
        its unit and environment files removed; images, volumes and
        containers somebody started by hand stay.
        """
        self._config = None
        PodmanUnitApplier().remove_all()
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            run(["systemctl", "daemon-reload"], is_checked=False)
        PodmanRegistriesApplier().apply("")
        self._records.remove(PODMAN_RECORD_ACCOUNT)

    def is_active(self) -> bool:
        """Whether the engine's own unit is active."""
        return unit_state(PODMAN_UNIT) == "active"

    def journal_units(self) -> list:
        """The engine's unit and one per declared container."""
        return [PODMAN_UNIT] + [f"{name}.service" for name in self._declared_names()]

    def details(self, recipe: dict) -> dict:
        """Every container podman knows, and the engine's own state.

        Args:
            recipe: The module's recipe.

        Returns:
            ``{"containers", "mirrors", "version", "is_active"}``, each
            container ``{"name", "image", "status", "is_running", "source",
            "module", "host_ports", "ports", "volumes", "environment",
            "has_unit", "host_bindings"}``, each binding with what the
            service probe detected on it.
        """
        config = self._config or PodmanConfig()
        states = PodmanStatusReader(probe=self._probe).survey(
            declared_names=self._declared_names(), hub_names=self.hub_names()
        )
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
            args: ``{"name", "action"}`` for control, ``{"name"}`` for one
                container's journal, ``{"lines"}`` for the module's own.
            on_line: Called with each output line.

        Returns:
            ``{"exit_code", "code", "params", "output"}``.
        """
        # A journal that names no container is the module's own.
        if verb not in (PODMAN_COMMAND_CONTROL, PODMAN_COMMAND_JOURNAL) or (
            verb == PODMAN_COMMAND_JOURNAL and not args.get("name")
        ):
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
        states = PodmanStatusReader().survey(
            declared_names=self._declared_names(), hub_names=self.hub_names()
        )
        state = next((entry for entry in states if entry.name == name), None)
        if state is None:
            return command_outcome(1, "container_unknown", {"name": name})
        try:
            PodmanContainerController().control(name, action, source=state.source)
        except (OSError, subprocess.SubprocessError) as error:
            return command_outcome(
                1, "command_failed", {"detail": command_detail(error)[:500]}
            )
        return command_outcome(0, output=f"{action} {name}\n")

    # --- what a container module asks of the engine ---

    def podman_command(self) -> tuple:
        """The podman command a container module reaches the engine with.

        Returns:
            This machine's ``podman``.
        """
        return (PODMAN_BINARY,)

    def image_references(self) -> set:
        """Every image reference with a digest in Podman's store, for a container module's presence check.

        Returns:
            The references this machine's Podman lists; empty when Podman
            cannot say.
        """
        return image_references(podman=self.podman_command())

    def hub_names(self) -> dict:
        """The hub containers rendered by the last apply, by module.

        Returns:
            Module name to its containers' names: the last apply's in this
            process, else the record's after a start.
        """
        if self._config is not None:
            return self._config.hub_names()
        record = self._records.read(PODMAN_RECORD_ACCOUNT)
        held = record.get("hub_names")
        if not isinstance(held, dict):
            return {}
        return {
            str(module): [str(name) for name in names]
            for module, names in held.items()
            if isinstance(names, list)
        }

    def is_applied(self, module: str) -> bool:
        """Whether the last apply wrote a module's hub containers as the state names them.

        Args:
            module: The container module.

        Returns:
            True as well while no apply ran since the start.
        """
        if self._written is None or self._wanted is None:
            return True
        return self._written.hub_containers_of(
            module
        ) == self._wanted.hub_containers_of(module)

    def is_engine_active(self) -> bool:
        """Whether Podman's socket is active, which **Stop** turns off."""
        return self.is_active()

    @contextlib.contextmanager
    def engine_awake(self):
        """Hold nothing for a container module's uninstall. Podman runs with its socket off.

        Yields:
            Nothing.
        """
        yield

    def drive_hub_containers(self, names: list, action: str) -> None:
        """Start, stop or restart the units of some hub containers.

        Args:
            names: The containers.
            action: ``start``, ``stop`` or ``restart``.

        Raises:
            ValueError: For an action outside those.
            subprocess.CalledProcessError: If systemd refuses a unit.
        """
        PodmanUnitApplier().drive(names, action)

    def drop_hub_containers(self, module: str) -> None:
        """Stop and delete the units of one module's hub containers, and forget them.

        Args:
            module: The container module.
        """
        names = self.hub_names().get(module, [])
        PodmanUnitApplier().remove(names)
        if self._config is not None:
            self._config = self._config.with_hub_containers(
                [
                    container
                    for container in self._config.hub_containers
                    if container.module != module
                ]
            )
        record = self._records.read(PODMAN_RECORD_ACCOUNT)
        if record:
            held = dict(record.get("hub_names") or {})
            held.pop(module, None)
            with contextlib.suppress(OSError):
                self._records.write({**record, "hub_names": held})
        self._page_ports.remove(module)

    def hub_journal(self, names: list, lines: int) -> list:
        """The journals of some hub containers' units, one after another.

        Args:
            names: The containers, in the order their journals come.
            lines: How many lines of each to read at most.

        Returns:
            The lines, each container's oldest first.
        """
        held = []
        for name in names:
            held += journal_lines(name, lines)
        return held

    def page_port(self, module: str, name: str) -> int:
        """The loopback port a hub container's page is published at.

        Args:
            module: The container module.
            name: The hub container.

        Returns:
            The port its module's record keeps, picked the first time.

        Raises:
            OSError: When no port can be picked or kept.
        """
        return self._page_ports.port_for(module, name)

    def _run_apply_stopped(self, config: dict, context) -> None:
        """The ``configure`` step under ``stopped``."""
        self.apply_stopped(config)

    def _apply(self, config: dict, *, is_started: bool) -> None:
        """Render and write the configuration. With ``is_started`` false no container starts with the box."""
        # A failed first apply after a start leaves every module unwritten.
        if self._written is None:
            self._written = PodmanConfig()
        parsed, refused = PodmanConfig.from_dict(config).without_refused()
        parsed.validate()
        # Held before the units are started: a start waits on the image
        # pull, and a report taken meanwhile lists the declared container
        # as not created yet rather than not at all.
        self._config = parsed
        try:
            mirror_note = PodmanRegistriesApplier().apply(
                PodmanRegistriesRenderer(config=parsed).render()
            )
            rendered, context = self._rendered_config(parsed)
            renderer = PodmanUnitRenderer(config=rendered, context=context)
            note = PodmanUnitApplier().apply(
                renderer.render(),
                renderer.environment_files(),
                autostart_names=[
                    container.name
                    for container in [*rendered.containers, *rendered.hub_containers]
                    if container.is_autostart and is_started
                ],
                source_keys=renderer.source_keys(),
            )
            self._config = rendered
            self._written = rendered
            self._write_record(rendered)
        except (OSError, subprocess.SubprocessError) as error:
            raise ModuleApplyError(
                "apply_failed", {"detail": command_detail(error)[:500]}
            )
        line = f"podman: {note}; {mirror_note}"
        if refused:
            line += "; left out " + ", ".join(name for name, _ in refused)
        self._log(line)
        if refused:
            raise refused[0][1]

    def _rendered_config(self, parsed: PodmanConfig) -> tuple:
        """The configuration this apply renders, and what its files name.

        Returns:
            ``(config, context)``: the configuration with the hub containers
            whose module has every image, and the gateways, stored images,
            page ports and source sets' sources the renderer writes.

        Raises:
            subprocess.CalledProcessError: If podman refuses to make a
                network.
            OSError: When podman cannot start or a page port cannot be kept.
        """
        references = image_references() if parsed.hub_containers else set()
        ready, images = ready_hub_containers(parsed, references)
        networks = []
        for container in ready:
            if container.network not in networks:
                networks.append(container.network)
        for network in networks:
            if ensure_network(network):
                self._log(f"podman: made the network {network}")
        gateways = {}
        default = [PODMAN_DEFAULT_NETWORK] if parsed.containers else []
        for network in [*default, *networks]:
            gateway = network_gateway(network)
            if gateway:
                gateways[network] = gateway
        page_ports = {
            container.name: self.page_port(container.module, container.name)
            for container in ready
            if container.page_port
        }
        set_names = []
        for container in ready:
            set_names += [
                name for name in container.source_sets if name not in set_names
            ]
        sources, variables = fastest_sources(set_names, self._source_sets)
        context = PodmanRenderContext(
            gateways=gateways,
            images=images,
            page_ports=page_ports,
            sources=sources,
            variables=variables,
        )
        return parsed.with_hub_containers(ready), context

    def _declared_names(self) -> list:
        """The declared containers' names: the last apply's, else the record's after a start."""
        if self._config is not None:
            return self._config.declared_names
        record = self._records.read(PODMAN_RECORD_ACCOUNT)
        return [str(name) for name in record.get("names") or []]

    def _write_record(self, config: PodmanConfig) -> None:
        """Keep the names of the declared and hub containers the apply rendered.

        Raises:
            OSError: When the record cannot be written.
        """
        self._records.write(
            {
                "account": PODMAN_RECORD_ACCOUNT,
                "names": config.declared_names,
                "hub_names": config.hub_names(),
            }
        )
