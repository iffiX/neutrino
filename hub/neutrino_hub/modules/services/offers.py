"""Rendering the services half of the device catalog.

An offer is one thing a machine's people can take: a share to mount, a link
to open, a port to forward, the AI service. Offers are fleet-global and carry
no secrets — a share's login and an account's gateway key travel only in a
device's own heartbeat reply.

Pure: everything rendered comes in through the constructor. Reading the
configs and enumerating the containers is the caller's.
"""

from neutrino_hub.modules.services.config import DeclaredService
from neutrino_hub.modules.services.constants import (
    SERVICES_DOCKER_PODMAN_SOURCE,
    SERVICES_KIND_GENERIC_TCP,
    SERVICES_KIND_HTTP,
    SERVICES_KIND_SAMBA,
    SERVICES_OFFER_AI_DESCRIPTION,
    SERVICES_OFFER_AI_ID,
    SERVICES_OFFER_AI_PLATFORMS,
    SERVICES_OFFER_AI_TITLE,
    SERVICES_OFFER_KIND_AI,
    SERVICES_OFFER_KIND_LINK,
    SERVICES_OFFER_KIND_MOUNT,
    SERVICES_OFFER_KIND_PORT,
)


class ServiceOfferRenderer:
    """Renders every offer the hub currently extends."""

    def __init__(
        self,
        *,
        hub_address: str,
        hub_share_names: list[str],
        declared_services: list[DeclaredService],
        is_gitea_installed: bool,
        gitea_url: str,
        docker_containers: dict,
        is_ai_served: bool,
    ):
        """
        Args:
            hub_address: The address devices reach the hub's own services on.
            hub_share_names: The hub's own Samba share names.
            declared_services: Every declared service.
            is_gitea_installed: Whether the hub hosts a git server.
            gitea_url: The URL that opens it.
            docker_containers: Containers keyed by source — declared service
                ids, plus the hub's podman under
                :data:`SERVICES_DOCKER_PODMAN_SOURCE`.
            is_ai_served: Whether the AI gateway has anything to serve with.
        """
        self._hub_address = hub_address
        self._hub_share_names = hub_share_names
        self._declared_services = declared_services
        self._is_gitea_installed = is_gitea_installed
        self._gitea_url = gitea_url
        self._docker_containers = docker_containers
        self._is_ai_served = is_ai_served

    def render(self) -> dict:
        """Every offer, keyed by a stable readable id.

        Returns:
            Offer id to ``{"kind", "title", ...}``; the fields past the two
            are the kind's own.
        """
        offers = {}
        offers.update(self._mount_offers())
        offers.update(self._link_offers())
        offers.update(self._port_offers())
        offers.update(self._ai_offer())
        return offers

    def _mount_offers(self) -> dict:
        offers = {}
        if self._hub_address:
            for name in self._hub_share_names:
                offers[f"hub_share_{name}"] = {
                    "kind": SERVICES_OFFER_KIND_MOUNT,
                    "title": name,
                    "host": self._hub_address,
                    "share": name,
                }
        for service in self._declared_services:
            if service.kind != SERVICES_KIND_SAMBA:
                continue
            for share in service.shares:
                offers[f"svc_{service.id}_{share.name}"] = {
                    "kind": SERVICES_OFFER_KIND_MOUNT,
                    "title": share.name,
                    "host": service.host,
                    "share": share.name,
                }
        return offers

    def _link_offers(self) -> dict:
        offers = {}
        for service in self._declared_services:
            if service.kind != SERVICES_KIND_HTTP:
                continue
            url = (
                f"{service.scheme}://{service.host}:{service.port}"
                f"{service.path or '/'}"
            )
            offers[f"svc_{service.id}"] = {
                "kind": SERVICES_OFFER_KIND_LINK,
                "title": service.name,
                "url": url,
            }
        if self._is_gitea_installed and self._gitea_url:
            offers["hub_gitea"] = {
                "kind": SERVICES_OFFER_KIND_LINK,
                "title": "Gitea",
                "url": self._gitea_url,
            }
        return offers

    def _port_offers(self) -> dict:
        offers = {}
        for service in self._declared_services:
            if service.kind == SERVICES_KIND_GENERIC_TCP:
                offers[f"svc_{service.id}"] = {
                    "kind": SERVICES_OFFER_KIND_PORT,
                    "title": service.name,
                    "host": service.host,
                    "port": service.port,
                }
        by_id = {service.id: service for service in self._declared_services}
        for source, containers in sorted(self._docker_containers.items()):
            if source == SERVICES_DOCKER_PODMAN_SOURCE:
                host = self._hub_address
                prefix = SERVICES_DOCKER_PODMAN_SOURCE
            else:
                service = by_id.get(source)
                if service is None:
                    continue
                host = service.host
                prefix = f"svc_{source}"
            if not host:
                continue
            for container in containers:
                for port in container.host_ports:
                    offers[f"{prefix}_{container.name}_{port}"] = {
                        "kind": SERVICES_OFFER_KIND_PORT,
                        "title": container.name,
                        "host": host,
                        "port": port,
                    }
        return offers

    def _ai_offer(self) -> dict:
        if not self._is_ai_served:
            return {}
        return {
            SERVICES_OFFER_AI_ID: {
                "kind": SERVICES_OFFER_KIND_AI,
                "title": SERVICES_OFFER_AI_TITLE,
                "description": SERVICES_OFFER_AI_DESCRIPTION,
                "platforms": SERVICES_OFFER_AI_PLATFORMS,
            }
        }
