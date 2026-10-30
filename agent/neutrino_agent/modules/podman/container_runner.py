"""A container module: images the Containers module's Podman pulls, run as hub containers.

The ``container`` method. The module is present while every image its
recipe pins is in that Podman's store. Its install chooses a source for each
missing image by the registry's answer to the manifest request for the
digest, and has Podman pull ``<source>@<digest>`` from the fastest, the next
after a pull that fails. It runs while every hub container of the module
runs. Its uninstall removes the module's containers, their units, its
network ``neutrino_<module>``, its named volumes ``neutrino_<module>_*`` and
the images no other container uses. The Containers runner, on Linux or in
the Podman machine on Windows and macOS, is how the runner reaches Podman,
and it renders the hub containers. A module with a page or a step after its
first start adds :class:`ContainerHooks` of its own.

Not pure: runs podman.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import json
import subprocess

from neutrino_agent.exceptions import ModuleApplyError, ModuleInstallPending
from neutrino_agent.modules.podman.applier import image_references, stored_reference
from neutrino_agent.modules.podman.constants import (
    PODMAN_CONTAINER_PULL_TIMEOUT_S,
    PODMAN_HUB_PREFIX,
    PODMAN_MODULE_LABEL,
)
from neutrino_agent.modules.shared import source_fetch
from neutrino_agent.modules.shared.base import ModuleRunner
from neutrino_agent.modules.shared.package import params_of
from neutrino_agent.modules.shared.subprocess_run import command_detail, run

# The artifact kind a ``container`` recipe names.
IMAGE_KIND = "image"
# How much of a failed pull's words a source's ``detail`` keeps.
DETAIL_CHARS = 200


def recipe_images(recipe: dict) -> list:
    """The images a ``container`` recipe pins.

    Args:
        recipe: ``{runner, method, params}``.

    Returns:
        Each ``image`` artifact as ``{name, digest, sources}``.
    """
    images = []
    for artifact in params_of(recipe).get("artifacts") or []:
        if not isinstance(artifact, dict) or artifact.get("kind") != IMAGE_KIND:
            continue
        images.append(
            {
                "name": str(artifact.get("name", "") or ""),
                "digest": str(artifact.get("digest", "") or ""),
                "sources": [str(source) for source in artifact.get("sources") or []],
            }
        )
    return images


def module_references(images: list, references: set) -> list:
    """The store's references of a module's images, at every digest.

    Args:
        images: The recipe's images, as :func:`recipe_images` gives them.
        references: ``<repository>@<digest>`` of every image in the store.

    Returns:
        The references whose repository is a source of one of the images,
        the images in their order and each one's references sorted, each
        reference once.
    """
    found: list = []
    for image in images:
        sources = set(image["sources"])
        for reference in sorted(references):
            repository = reference.rsplit("@", 1)[0]
            if repository in sources and reference not in found:
                found.append(reference)
    return found


class ContainerHooks:
    """What one container module adds to the ``container`` runner.

    A module subclasses this in its ``hooks.py`` for its page's forwarder
    or a step after its first start; every method not overridden keeps the
    answer of a module with nothing of the kind.
    """

    def __init__(self, *, platform, name: str, containers, log=print):
        """
        Args:
            platform: The machine's platform.
            name: The module's name.
            containers: The Containers runner, which reaches Podman.
            log: Called with each progress line.
        """
        self._platform = platform
        self._name = name
        self._containers = containers
        self._log = log

    def apply(self, config: dict) -> None:
        """Take the module's configuration.

        Args:
            config: The module's configuration in the state.

        Raises:
            ModuleApplyError: When the configuration is refused.
        """

    def take_source_sets(self, source_sets: dict) -> None:
        """Take the state's ``source_sets`` section, for a step that ranks a set itself.

        Args:
            source_sets: ``{name: {probe, sources, variables}}``.
        """

    def installed(self, version: str) -> None:
        """Note the version the recipe names, once an install pulled its images and at each start.

        Args:
            version: The version the recipe names.
        """

    def start(self) -> None:
        """Do what follows once the module's containers run.

        Raises:
            ModuleInstallPending: While the containers' first start runs.
            ModuleApplyError: When a step fails.
        """

    def stop(self) -> None:
        """Take down what the module runs beside its containers."""

    def is_running(self) -> bool:
        """Whether the module's own check passes beside its containers running.

        Returns:
            True for a module with no check of its own.
        """
        return True

    def is_installing(self) -> bool:
        """Whether the module's start waits on its containers' first start.

        Returns:
            False for a module with no first start of its own.
        """
        return False

    def details(self) -> dict:
        """What the module adds to its row's details.

        Returns:
            The fields; empty for a module with none.
        """
        return {}

    def remove(self) -> None:
        """Delete what the module keeps of its own, at its uninstall."""


# The modules with hooks of their own, by name.
CONTAINER_MODULE_HOOKS: dict = {}


class ContainerModuleRunner(ModuleRunner):
    """Installs one container module's images and runs it as hub containers on Containers."""

    runner = "container"

    def __init__(
        self,
        *,
        platform,
        name: str,
        containers,
        log=print,
        publish=None,
        probe_one=source_fetch.probe,
        run_command=run,
    ):
        """
        Args:
            platform: The machine's platform.
            name: The module's name.
            containers: The Containers runner: :meth:`podman_command`,
                :meth:`image_references`, :meth:`hub_names`,
                :meth:`is_applied`, :meth:`is_engine_active`,
                :meth:`engine_awake`, :meth:`drive_hub_containers`,
                :meth:`drop_hub_containers` and :meth:`hub_journal` reach
                Podman through it.
            log: Callable used for progress messages.
            publish: Called with ``(name, status)`` for transient states.
            probe_one: Probes one source, as :func:`source_fetch.probe`.
            run_command: Runs one command, as :func:`subprocess_run.run`.
        """
        super().__init__(platform=platform, log=log, publish=publish)
        self.name = name
        self._containers = containers
        self._probe_one = probe_one
        self._run = run_command
        self._version = ""
        hooks_class = CONTAINER_MODULE_HOOKS.get(name, ContainerHooks)
        self._hooks = hooks_class(
            platform=platform, name=name, containers=containers, log=self._log
        )

    def verify(self, recipe: dict) -> bool:
        """Whether every image the recipe pins is in Containers' Podman store, as Containers reads it.

        Args:
            recipe: The module's recipe.

        Returns:
            False for a recipe that pins no image, and while Containers
            reads no store.
        """
        images = recipe_images(recipe)
        if not images:
            return False
        references = self._containers.image_references()
        return all(
            stored_reference(image["digest"], image["sources"], references)
            for image in images
        )

    def install(self, recipe: dict) -> None:
        """Pull every image the store lacks, each from the fastest source that serves it.

        The hooks are then told the version the images belong to.

        Args:
            recipe: The module's recipe.

        Raises:
            ModuleApplyError: ``download_failed {file, sources}`` when no
                source serves an image; ``install_failed {detail}`` while
                Containers has no Podman to pull with.
        """
        command = self._command()
        if not command:
            raise ModuleApplyError(
                "install_failed", {"detail": "Containers has no Podman to pull with"}
            )
        references = image_references(podman=command)
        for image in recipe_images(recipe):
            if stored_reference(image["digest"], image["sources"], references):
                continue
            self._pull(command, image)
        self._hooks.installed(str(params_of(recipe).get("version", "") or ""))

    def uninstall(self, recipe: dict) -> None:
        """Remove the module's containers, units, network, named volumes and unused images.

        Every image the store holds under a source of the recipe's images
        goes, an earlier version's among them; one a container uses stays.
        The steps run while Containers holds its engine awake.

        Args:
            recipe: The module's recipe.
        """
        with self._containers.engine_awake():
            self._containers.drop_hub_containers(self.name)
            command = self._command()
            if command:
                for name in self._states(command):
                    self._quietly([*command, "rm", "-f", name])
                self._quietly(
                    [*command, "network", "rm", PODMAN_HUB_PREFIX + self.name]
                )
                for volume in self._volumes(command):
                    self._quietly([*command, "volume", "rm", "-f", volume])
                references = image_references(podman=command)
                for reference in module_references(recipe_images(recipe), references):
                    self._quietly([*command, "rmi", reference])
        self._hooks.remove()

    def take_recipe(self, recipe: dict) -> None:
        """Take the version the recipe names, which each start tells the hooks.

        Args:
            recipe: ``{runner, method, params}``.
        """
        self._version = str(params_of(recipe).get("version", "") or "")

    def take_source_sets(self, source_sets: dict) -> None:
        """Hand the state's ``source_sets`` section to the module's hooks.

        Args:
            source_sets: ``{name: {probe, sources, variables}}``.
        """
        self._hooks.take_source_sets(dict(source_sets))

    def apply(self, config: dict) -> None:
        """Hand the module's configuration to its hooks.

        Args:
            config: The module's configuration.

        Raises:
            ModuleApplyError: When the hooks refuse it.
        """
        self._hooks.apply(dict(config))

    def start(self) -> None:
        """Start the module's containers that do not run, once Containers renders them.

        The hooks are told the recipe's version first, which starts a
        version change whose images the store already held.

        Raises:
            ModuleInstallPending: While Containers has not rendered the
                module's containers, or the hooks wait on their first start.
            ModuleApplyError: ``containers_not_applied`` when Containers'
                last apply did not write the containers the state names;
                ``apply_failed`` when systemd refuses a unit.
        """
        names = self._names()
        if not names:
            raise ModuleInstallPending("containers_pending")
        if not self._containers.is_applied(self.name):
            raise ModuleApplyError("containers_not_applied", {})
        if self._version:
            self._hooks.installed(self._version)
        if self._containers.is_engine_active():
            states = self._states(self._command())
            down = [name for name in names if not states.get(name)]
            if down:
                try:
                    self._containers.drive_hub_containers(down, "start")
                except (OSError, subprocess.SubprocessError) as error:
                    raise ModuleApplyError(
                        "apply_failed", {"detail": command_detail(error)[:500]}
                    ) from error
        self._hooks.start()

    def stop(self) -> None:
        """Stop the module's containers."""
        self._hooks.stop()
        names = self._names()
        if names:
            self._containers.drive_hub_containers(names, "stop")

    def is_installing(self) -> bool:
        """Whether the module's hooks wait on its containers' first start."""
        return bool(self._hooks.is_installing())

    def is_active(self) -> bool:
        """Whether every container of the module runs and its hooks' check passes."""
        names = self._names()
        if not names:
            return False
        states = self._states(self._command())
        return all(states.get(name) for name in names) and self._hooks.is_running()

    def details(self, recipe: dict) -> dict:
        """The version the recipe pins, and what the hooks add.

        Args:
            recipe: The module's recipe.

        Returns:
            ``{"version", ...}``.
        """
        return {
            "version": str(params_of(recipe).get("version", "") or ""),
            **self._hooks.details(),
        }

    def journal_text(self, lines: int) -> list:
        """The journals of the module's containers, each in its module's order.

        Args:
            lines: How many lines to return at most.

        Returns:
            The lines, oldest first within each container's.
        """
        return self._containers.hub_journal(self._names(), lines)[-lines:]

    def _pull(self, command: tuple, image: dict) -> None:
        """Pull one image from the fastest source that serves it, a source the probe missed last.

        Raises:
            ModuleApplyError: ``download_failed {file, sources}`` when every
                source's pull fails, each pull's failure listed.
        """
        digest = image["digest"]
        chosen = source_fetch.rank_images(
            image["sources"], digest, probe_one=self._probe_one
        )
        failures = []
        for source in chosen:
            reference = f"{source}@{digest}"
            self._log(f"{self.name}: pulling {reference}")
            try:
                self._run(
                    [*command, "pull", reference],
                    timeout_s=PODMAN_CONTAINER_PULL_TIMEOUT_S,
                )
            except (OSError, subprocess.SubprocessError) as error:
                said = command_detail(error).strip().splitlines()
                detail = (said[-1] if said else "")[:DETAIL_CHARS]
                self._log(f"{self.name}: {reference} failed: {detail}")
                failures.append(
                    {
                        "source": source,
                        "reason": source_fetch.REASON_PULL_FAILED,
                        "detail": detail,
                    }
                )
                continue
            return
        first = image["sources"][0] if image["sources"] else image["name"]
        raise ModuleApplyError(
            "download_failed", {"file": f"{first}@{digest}", "sources": failures}
        )

    def _names(self) -> list:
        """The module's hub containers as Containers last rendered them."""
        return list(self._containers.hub_names().get(self.name, []))

    def _command(self) -> tuple:
        """Containers' podman command; empty while it has none or cannot reach it."""
        try:
            return tuple(self._containers.podman_command())
        except (ModuleApplyError, KeyError):
            return ()

    def _states(self, command: tuple) -> dict:
        """Each container with the module's label, by name, to whether it runs."""
        if not command:
            return {}
        try:
            result = self._run(
                [
                    *command,
                    "ps",
                    "-a",
                    "--filter",
                    f"label={PODMAN_MODULE_LABEL}={self.name}",
                    "--format",
                    "json",
                ],
                is_checked=False,
                timeout_s=30,
            )
            entries = json.loads(result.stdout or "[]") if result.is_success else []
        except (OSError, subprocess.SubprocessError, ValueError):
            return {}
        states = {}
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict):
                continue
            names = entry.get("Names") or []
            if names:
                states[str(names[0])] = entry.get("State", "") == "running"
        return states

    def _volumes(self, command: tuple) -> list:
        """The named volumes of the module, ``neutrino_<module>_*``."""
        try:
            result = self._run(
                [*command, "volume", "ls", "--format", "json"],
                is_checked=False,
                timeout_s=30,
            )
            entries = json.loads(result.stdout or "[]") if result.is_success else []
        except (OSError, subprocess.SubprocessError, ValueError):
            return []
        prefix = PODMAN_HUB_PREFIX + self.name + "_"
        return [
            str(entry.get("Name", ""))
            for entry in (entries if isinstance(entries, list) else [])
            if isinstance(entry, dict) and str(entry.get("Name", "")).startswith(prefix)
        ]

    def _quietly(self, command: list) -> None:
        """Run one removal, a failure of which is a line in the log."""
        try:
            done = self._run(command, is_checked=False, timeout_s=300)
        except (OSError, subprocess.SubprocessError) as error:
            self._log(f"{self.name}: {' '.join(command[-3:])}: {error}")
            return
        if not done.is_success:
            said = (done.stderr or done.stdout or "").strip()
            self._log(f"{self.name}: {' '.join(command[-3:])}: {said[:DETAIL_CHARS]}")
