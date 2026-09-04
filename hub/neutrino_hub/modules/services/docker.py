"""Listing and driving containers on the declared Docker engines.

Every declared ``docker_engine`` service exposes the daemon's own HTTP API,
and the hub's podman is one more source when it is installed. Listings are
cached for a short while and shared by every caller — the Services page, the
device catalog's port offers — so a heartbeat never opens a connection of
its own.
"""

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from neutrino_hub.modules.podman.constants import PODMAN_BINARY
from neutrino_hub.modules.podman.ops import PodmanStatusReader
from neutrino_hub.modules.services.config import DeclaredService
from neutrino_hub.modules.services.constants import (
    SERVICES_DOCKER_CACHE_TTL_S,
    SERVICES_DOCKER_PODMAN_SOURCE,
    SERVICES_DOCKER_TIMEOUT_S,
    SERVICES_ERROR_DOCKER_REFUSED,
    SERVICES_ERROR_DOCKER_UNREACHABLE,
    SERVICES_KIND_DOCKER_ENGINE,
)


class DockerEngineError(ValueError):
    """A container action a daemon refused or never answered.

    Attributes:
        code: Machine name of the refusal; the pages do the wording.
        params: The values the refusal's sentence needs.
    """

    def __init__(self, code: str, params: dict | None = None):
        super().__init__(code)
        self.code = code
        self.params = params or {}


@dataclass
class DockerContainer:
    """One container as its engine reports it.

    Attributes:
        id: The engine's container id.
        name: The container's name.
        image: The image it runs.
        state: The engine's state word, for example ``running``.
        is_running: Whether it is running.
        host_ports: The published host ports.
    """

    id: str
    name: str
    image: str
    state: str
    is_running: bool
    host_ports: list[int] = field(default_factory=list)


class DockerContainerCache:
    """Lists every source's containers and keeps the batch for a short while.

    The whole batch refreshes together when it is stale, so the page poll and
    the catalog composition share one round of connections.
    """

    def __init__(self, *, timeout_s: float = SERVICES_DOCKER_TIMEOUT_S):
        """
        Args:
            timeout_s: How long to wait for a daemon before calling it
                unreachable.
        """
        self._timeout_s = timeout_s
        self._cache: dict[str, list[DockerContainer]] = {}
        # None, not zero: `time.monotonic()` counts from boot on Linux, and a
        # panel started early in one would read the cache as fresh.
        self._refreshed_at: float | None = None
        self._generation = 0

    @property
    def generation(self) -> int:
        """A counter that moves whenever the enumerated containers change."""
        return self._generation

    def results(
        self, services: list[DeclaredService]
    ) -> dict[str, list[DockerContainer]]:
        """Read every source's containers, refreshing only when stale.

        Args:
            services: The declared services; kinds other than
                ``docker_engine`` are ignored.

        Returns:
            Containers keyed by declared service id, plus
            :data:`SERVICES_DOCKER_PODMAN_SOURCE` when podman is installed.
            An unreachable engine reads as an empty list.
        """
        if (
            self._refreshed_at is None
            or time.monotonic() - self._refreshed_at > SERVICES_DOCKER_CACHE_TTL_S
        ):
            self.refresh(services)
        return dict(self._cache)

    def refresh(
        self, services: list[DeclaredService]
    ) -> dict[str, list[DockerContainer]]:
        """List every source now, replacing the cache whole.

        Args:
            services: The declared services.

        Returns:
            The fresh batch.
        """
        batch: dict[str, list[DockerContainer]] = {}
        for service in services:
            if service.kind != SERVICES_KIND_DOCKER_ENGINE:
                continue
            batch[service.id] = self._engine_containers(service)
        if Path(PODMAN_BINARY).is_file():
            batch[SERVICES_DOCKER_PODMAN_SOURCE] = self._podman_containers()
        if self._fingerprint(batch) != self._fingerprint(self._cache):
            self._generation += 1
        self._cache = batch
        self._refreshed_at = time.monotonic()
        return dict(batch)

    def refresh_one(self, service: DeclaredService) -> list[DockerContainer]:
        """Re-list one engine now; the result replaces its cached entry.

        Args:
            service: The declared ``docker_engine`` service.

        Returns:
            Its fresh container list.
        """
        containers = self._engine_containers(service)
        if self._cache.get(service.id) != containers:
            self._generation += 1
        self._cache[service.id] = containers
        return containers

    def _engine_containers(self, service: DeclaredService) -> list[DockerContainer]:
        try:
            response = httpx.get(
                f"http://{service.host}:{service.port}/containers/json",
                params={"all": "true"},
                timeout=self._timeout_s,
            )
        except httpx.HTTPError:
            return []
        if not response.is_success:
            return []
        try:
            entries = response.json()
        except ValueError:
            return []
        if not isinstance(entries, list):
            return []
        return [_parse_engine_container(entry) for entry in entries]

    def _podman_containers(self) -> list[DockerContainer]:
        return [
            DockerContainer(
                id=state.name,
                name=state.name,
                image=state.image,
                state="running" if state.is_running else state.status,
                is_running=state.is_running,
                host_ports=state.host_ports,
            )
            for state in PodmanStatusReader().survey(declared_names=[])
        ]

    def _fingerprint(self, batch: dict[str, list[DockerContainer]]) -> str:
        serialized = {
            source: [vars(container) for container in containers]
            for source, containers in batch.items()
        }
        return json.dumps(serialized, sort_keys=True)


class DockerContainerController:
    """Starts and stops containers over a declared engine's own API."""

    def __init__(self, *, timeout_s: float = SERVICES_DOCKER_TIMEOUT_S):
        """
        Args:
            timeout_s: How long to wait for the daemon's answer.
        """
        self._timeout_s = timeout_s

    def control(self, service: DeclaredService, container_id: str, action: str) -> None:
        """Start or stop one container.

        Args:
            service: The declared ``docker_engine`` service.
            container_id: The engine's container id.
            action: ``start`` or ``stop``.

        Raises:
            DockerEngineError: When the daemon does not answer, or refuses.
        """
        url = (
            f"http://{service.host}:{service.port}"
            f"/containers/{container_id}/{action}"
        )
        try:
            response = httpx.post(url, timeout=self._timeout_s)
        except httpx.HTTPError as error:
            raise DockerEngineError(
                SERVICES_ERROR_DOCKER_UNREACHABLE, {"host": service.host}
            ) from error
        # 304 means the container is already in the asked-for state.
        if response.status_code in (204, 304):
            return
        raise DockerEngineError(
            SERVICES_ERROR_DOCKER_REFUSED,
            {"action": action, "status": response.status_code},
        )


def _parse_engine_container(entry: dict) -> DockerContainer:
    """One row of the daemon's ``/containers/json`` answer.

    Args:
        entry: The raw row.

    Returns:
        The parsed container.
    """
    names = entry.get("Names") or []
    name = str(names[0]).lstrip("/") if names else ""
    ports = set()
    for port in entry.get("Ports") or []:
        if not isinstance(port, dict):
            continue
        public = port.get("PublicPort")
        if isinstance(public, int) and public > 0:
            ports.add(public)
    state = str(entry.get("State", ""))
    return DockerContainer(
        id=str(entry.get("Id", "")),
        name=name,
        image=str(entry.get("Image", "")),
        state=state,
        is_running=state == "running",
        host_ports=sorted(ports),
    )
