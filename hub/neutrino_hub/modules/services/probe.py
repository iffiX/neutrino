"""Measuring whether each entry of a declared app answers.

A declared app runs on a machine the hub does not manage, so the only thing
the hub can say about an entry is what an exchange with it says: a TCP
connect for a TCP ``port`` entry, a GET for a ``web`` entry, where any answer
below 500 is a service that is up, because a 401 comes from something alive
enough to refuse, and for a ``file`` entry the server's own list of exports.
A share may be called missing only off a listing that actually shows shares;
a server that refuses anonymous listing degrades to the port answering,
healthy with the share itself marked unverified. A UDP ``port`` entry has no
exchange to try and is never probed; its health stays empty.

Results are cached for a short while and never written to disk: health is
what the entry is doing now, and a stored answer would only ever be stale.
"""

import socket
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import partial

import httpx

from neutrino_hub.modules.services.apps import entry_id
from neutrino_hub.modules.services.config import DeclaredApp, DeclaredEntry
from neutrino_hub.modules.services.constants import (
    SERVICES_PROBE_CACHE_TTL_S,
    SERVICES_PROBE_CONNECT_FAILED,
    SERVICES_PROBE_LIST_REFUSED,
    SERVICES_PROBE_SERVER_ERROR,
    SERVICES_PROBE_SHARE_MISSING,
    SERVICES_PROBE_SHARE_UNVERIFIED,
    SERVICES_PROBE_TIMEOUT_S,
    SERVICES_PROBE_TOOL_MISSING,
    SERVICES_PROBE_WORKER_LIMIT,
    SERVICES_PROTOCOL_UDP,
    SERVICES_TYPE_FILE,
    SERVICES_TYPE_PORT,
    SERVICES_TYPE_WEB,
)
from neutrino_hub.modules.services.ops import SambaShareListing, list_shares


@dataclass
class DeclaredEntryHealth:
    """One declared entry's measured health.

    Attributes:
        entry_id: The entry's id, ``<app id>_<name>``.
        is_healthy: Whether it answered as declared; None when it was never
            probed, and when the hub had no way to look.
        checked_at: ISO timestamp of the measurement, None before the first.
        detail_code: What the measurement found, None on one that answered
            as declared.
    """

    entry_id: str
    is_healthy: bool | None
    checked_at: str | None
    detail_code: str | None

    @classmethod
    def measured(cls, entry_id: str, detail_code: str | None) -> "DeclaredEntryHealth":
        """Build a result from what one measurement found.

        Args:
            entry_id: The entry's id.
            detail_code: What the measurement found, None when it answered
                as declared.

        Returns:
            The result, stamped now. A hub that lacks the tool to look has
            no opinion rather than a bad one, so its health is None; a share
            the server hides from anonymous listing is healthy with
            ``share_unverified`` beside it.
        """
        return cls(
            entry_id=entry_id,
            is_healthy=(
                None
                if detail_code == SERVICES_PROBE_TOOL_MISSING
                else detail_code in (None, SERVICES_PROBE_SHARE_UNVERIFIED)
            ),
            checked_at=datetime.now(timezone.utc).isoformat(),
            detail_code=detail_code,
        )


def is_probed(entry: DeclaredEntry) -> bool:
    """Whether an entry is probed: every one but a UDP ``port`` entry."""
    return not (
        entry.type == SERVICES_TYPE_PORT and entry.protocol == SERVICES_PROTOCOL_UDP
    )


def probed_entries(apps: list) -> list:
    """Every probed entry of every app, as ``(app, entry)`` pairs."""
    return [(app, entry) for app in apps for entry in app.entries if is_probed(entry)]


class DeclaredServiceProbe:
    """Probes declared apps' entries and caches the results for a short while.

    The Services page polls its view every few seconds; the cache keeps that
    from opening a connection to every declared machine each time.
    """

    def __init__(self, *, timeout_s: float = SERVICES_PROBE_TIMEOUT_S):
        """
        Args:
            timeout_s: How long to wait for an answer before calling the
                entry unhealthy.
        """
        self._timeout_s = timeout_s
        self._cache: dict = {}
        # None, not zero: `time.monotonic()` counts from boot on Linux, and a
        # panel started early in one would read the cache as fresh.
        self._probed_at: float | None = None

    def results(self, apps: list) -> dict:
        """Read every entry's health, probing only when the cache is stale.

        Args:
            apps: The declared apps.

        Returns:
            Entry id to its result, for every entry of every app; an entry
            declared since the last refresh reads as never probed.
        """
        if (
            self._probed_at is None
            or time.monotonic() - self._probed_at > SERVICES_PROBE_CACHE_TTL_S
        ):
            self.refresh(apps)
        return {
            entry_id(app.id, entry.name): self._cache.get(
                entry_id(app.id, entry.name),
                DeclaredEntryHealth(entry_id(app.id, entry.name), None, None, None),
            )
            for app in apps
            for entry in app.entries
        }

    def refresh(self, apps: list) -> list:
        """Probe every entry now, replacing the cache whole.

        Args:
            apps: The declared apps.

        Returns:
            One fresh result per probed entry.
        """
        pairs = probed_entries(apps)
        if not pairs:
            self._cache = {}
            self._probed_at = time.monotonic()
            return []
        listings = self._listings(pairs)
        worker_count = min(SERVICES_PROBE_WORKER_LIMIT, len(pairs))
        with ThreadPoolExecutor(max_workers=worker_count) as pool:
            results = list(pool.map(partial(self._measure, listings=listings), pairs))
        self._cache = {result.entry_id: result for result in results}
        self._probed_at = time.monotonic()
        return results

    def probe(self, app: DeclaredApp) -> list:
        """Measure one app's entries now; the results replace their cached ones.

        Args:
            app: The app to reach.

        Returns:
            The fresh measurements, one per probed entry; a UDP entry gets
            none.
        """
        pairs = probed_entries([app])
        listings = self._listings(pairs)
        results = [self._measure(pair, listings=listings) for pair in pairs]
        for result in results:
            self._cache[result.entry_id] = result
        return results

    def cached(self, held_entry_id: str) -> "DeclaredEntryHealth | None":
        """Read one entry's cached health without probing.

        Args:
            held_entry_id: The entry's id.

        Returns:
            The cached result, or None when the entry was never probed.
        """
        return self._cache.get(held_entry_id)

    def _listings(self, pairs: list) -> dict:
        """List the exports of every server the file entries name.

        One call per host, not per share: a server exporting four declared
        shares is asked once, and every share is read off the one answer.

        Args:
            pairs: The ``(app, entry)`` pairs about to be measured.

        Returns:
            Host to what it answered; empty when no file entry is declared.
        """
        hosts = sorted(
            {
                app.host
                for app, entry in pairs
                if entry.type == SERVICES_TYPE_FILE and app.host
            }
        )
        if not hosts:
            return {}
        worker_count = min(SERVICES_PROBE_WORKER_LIMIT, len(hosts))
        with ThreadPoolExecutor(max_workers=worker_count) as pool:
            listings = list(pool.map(self._list_shares, hosts))
        return dict(zip(hosts, listings))

    def _list_shares(self, host: str) -> SambaShareListing:
        return list_shares(host, timeout_s=self._timeout_s)

    def _measure(self, pair: tuple, *, listings: dict) -> DeclaredEntryHealth:
        app, entry = pair
        if entry.type == SERVICES_TYPE_WEB:
            detail_code = self._http_detail(app.host, entry)
        elif entry.type == SERVICES_TYPE_FILE:
            detail_code = self._samba_detail(app.host, entry, listings)
        else:
            detail_code = self._tcp_detail(app.host, entry.port)
        return DeclaredEntryHealth.measured(entry_id(app.id, entry.name), detail_code)

    def _samba_detail(self, host: str, entry: DeclaredEntry, listings: dict):
        listing = listings.get(host)
        if listing is None:
            listing = self._list_shares(host)
        if listing.error_code == SERVICES_PROBE_LIST_REFUSED:
            # The server hides its exports from an anonymous asker, so the
            # only honest measure left is whether it answers at all.
            if self._tcp_detail(host, entry.port) is None:
                return SERVICES_PROBE_SHARE_UNVERIFIED
            return SERVICES_PROBE_CONNECT_FAILED
        if listing.error_code is not None:
            return listing.error_code
        if entry.share not in listing.names:
            return SERVICES_PROBE_SHARE_MISSING
        return None

    def _tcp_detail(self, host: str, port: int) -> str | None:
        try:
            with socket.create_connection((host, port), timeout=self._timeout_s):
                return None
        except OSError:
            return SERVICES_PROBE_CONNECT_FAILED

    def _http_detail(self, host: str, entry: DeclaredEntry) -> str | None:
        url = f"{entry.scheme}://{host}:{entry.port}{entry.path or '/'}"
        try:
            # Unverified: the probe measures reachability, and a declared
            # machine's certificate is usually self-signed.
            response = httpx.get(url, timeout=self._timeout_s, verify=False)
        except httpx.HTTPError:
            return SERVICES_PROBE_CONNECT_FAILED
        if response.status_code < 500:
            return None
        return SERVICES_PROBE_SERVER_ERROR
