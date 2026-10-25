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
                :meth:`mirrors`, :meth:`hub_names`, :meth:`is_engine_active`,
                :meth:`drive_hub_containers`, :meth:`drop_hub_containers`
                and :meth:`hub_journal` reach Podman through it.
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
        hooks_class = CONTAINER_MODULE_HOOKS.get(name, ContainerHooks)
        self._hooks = hooks_class(
            platform=platform, name=name, containers=containers, log=self._log
        )

    def verify(self, recipe: dict) -> bool:
        """Whether every image the recipe pins is in Containers' Podman store.

        Args:
            recipe: The module's recipe.

        Returns:
            False for a recipe that pins no image, and while Podman cannot
            be asked.
        """
        images = recipe_images(recipe)
        command = self._command()
        if not images or not command:
            return False
        references = image_references(podman=command)
        return all(
            stored_reference(image["digest"], image["sources"], references)
            for image in images
        )

    def install(self, recipe: dict) -> None:
        """Pull every image the store lacks, each from the fastest source that serves it.

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
        is_mirrored = bool(self._containers.mirrors())
        for image in recipe_images(recipe):
            if stored_reference(image["digest"], image["sources"], references):
                continue
            self._pull(command, image, is_docker_mirrored=is_mirrored)

    def uninstall(self, recipe: dict) -> None:
        """Remove the module's containers, units, network, named volumes and unused images.

        Args:
            recipe: The module's recipe.
        """
        self._containers.drop_hub_containers(self.name)
        command = self._command()
        if command:
            for name in self._states(command):
                self._quietly([*command, "rm", "-f", name])
            self._quietly([*command, "network", "rm", PODMAN_HUB_PREFIX + self.name])
            for volume in self._volumes(command):
                self._quietly([*command, "volume", "rm", "-f", volume])
            references = image_references(podman=command)
            for image in recipe_images(recipe):
                reference = stored_reference(
                    image["digest"], image["sources"], references
                )
                if reference:
                    self._quietly([*command, "rmi", reference])
        self._hooks.remove()

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

        Raises:
            ModuleInstallPending: While Containers has not rendered the
                module's containers, or the hooks wait on their first start.
            ModuleApplyError: When systemd refuses a unit.
        """
        names = self._names()
        if not names:
            raise ModuleInstallPending("containers_pending")
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

    def _pull(self, command: tuple, image: dict, *, is_docker_mirrored: bool) -> None:
        """Pull one image from the fastest source that serves it.

        Raises:
            ModuleApplyError: ``download_failed {file, sources}`` when no
                source serves it.
        """
        digest = image["digest"]
        chosen, failures = source_fetch.rank_images(
            image["sources"],
            digest,
            is_docker_mirrored=is_docker_mirrored,
            probe_one=self._probe_one,
        )
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
