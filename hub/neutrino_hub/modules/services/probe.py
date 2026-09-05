"""Measuring whether each declared service answers.

A declared service runs on a machine the hub does not manage, so the only
thing the hub can say about it is what a connection says: a TCP connect for
``samba`` and ``generic_tcp``, and a GET for ``http`` — where any answer
below 500 is a service that is up, because a 401 comes from something alive
enough to refuse.

Results are cached for a short while and never written to disk: health is
what the service is doing now, and a stored answer would only ever be stale.
"""

import socket
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from neutrino_hub.modules.services.config import DeclaredService
from neutrino_hub.modules.services.constants import (
    SERVICES_KIND_HTTP,
    SERVICES_PROBE_CACHE_TTL_S,
    SERVICES_PROBE_CONNECT_FAILED,
    SERVICES_PROBE_SERVER_ERROR,
    SERVICES_PROBE_TIMEOUT_S,
    SERVICES_PROBE_WORKER_LIMIT,
)


@dataclass
class DeclaredServiceHealth:
    """One declared service's measured health.

    Attributes:
        service_id: The declared service's id.
        is_healthy: Whether it answered; None when it was never probed.
        checked_at: ISO timestamp of the measurement, None before the first.
        detail_code: Why an unhealthy one was called that, None otherwise.
    """

    service_id: str
    is_healthy: bool | None
    checked_at: str | None
    detail_code: str | None


class DeclaredServiceProbe:
    """Probes declared services and caches the results for a short while.

    The Services page polls its view every few seconds; the cache keeps that
    from opening a connection to every declared machine each time.
    """

    def __init__(self, *, timeout_s: float = SERVICES_PROBE_TIMEOUT_S):
        """
        Args:
            timeout_s: How long to wait for an answer before calling the
                service unhealthy.
        """
        self._timeout_s = timeout_s
        self._cache: dict[str, DeclaredServiceHealth] = {}
        # None, not zero: `time.monotonic()` counts from boot on Linux, and a
        # panel started early in one would read the cache as fresh.
        self._probed_at: float | None = None

    def results(self, services: list[DeclaredService]) -> list[DeclaredServiceHealth]:
        """Read every service's health, probing only when the cache is stale.

        Args:
            services: The services to report on.

        Returns:
            One result per service, in the order given. A service declared
            since the last refresh reads as never probed.
        """
        if (
            self._probed_at is None
            or time.monotonic() - self._probed_at > SERVICES_PROBE_CACHE_TTL_S
        ):
            self.refresh(services)
        return [
            self._cache.get(
                service.id, DeclaredServiceHealth(service.id, None, None, None)
            )
            for service in services
        ]

    def refresh(self, services: list[DeclaredService]) -> list[DeclaredServiceHealth]:
        """Probe every service now, replacing the cache whole.

        Args:
            services: The services to probe.

        Returns:
            One fresh result per service.
        """
        if not services:
            self._cache = {}
            self._probed_at = time.monotonic()
            return []
        worker_count = min(SERVICES_PROBE_WORKER_LIMIT, len(services))
        with ThreadPoolExecutor(max_workers=worker_count) as pool:
            results = list(pool.map(self._measure, services))
        self._cache = {result.service_id: result for result in results}
        self._probed_at = time.monotonic()
        return results

    def probe(self, service: DeclaredService) -> DeclaredServiceHealth:
        """Measure one service now; the result replaces its cached one.

        Args:
            service: The service to reach.

        Returns:
            The fresh measurement.
        """
        result = self._measure(service)
        self._cache[service.id] = result
        return result

    def cached(self, service_id: str) -> DeclaredServiceHealth | None:
        """Read one service's cached health without probing.

        Args:
            service_id: The declared service's id.

        Returns:
            The cached result, or None when the service was never probed.
        """
        return self._cache.get(service_id)

    def _measure(self, service: DeclaredService) -> DeclaredServiceHealth:
        if service.kind == SERVICES_KIND_HTTP:
            detail_code = self._http_detail(service)
        else:
            detail_code = self._tcp_detail(service)
        return DeclaredServiceHealth(
            service_id=service.id,
            is_healthy=detail_code is None,
            checked_at=datetime.now(timezone.utc).isoformat(),
            detail_code=detail_code,
        )

    def _tcp_detail(self, service: DeclaredService) -> str | None:
        try:
            with socket.create_connection(
                (service.host, service.port), timeout=self._timeout_s
            ):
                return None
        except OSError:
            return SERVICES_PROBE_CONNECT_FAILED

    def _http_detail(self, service: DeclaredService) -> str | None:
        url = f"{service.scheme}://{service.host}:{service.port}{service.path or '/'}"
        try:
            # Unverified: the probe measures reachability, and a declared
            # machine's certificate is usually self-signed.
            response = httpx.get(url, timeout=self._timeout_s, verify=False)
        except httpx.HTTPError:
            return SERVICES_PROBE_CONNECT_FAILED
        if response.status_code < 500:
            return None
        return SERVICES_PROBE_SERVER_ERROR
