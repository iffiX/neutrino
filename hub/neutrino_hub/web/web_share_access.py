"""The Web shares as the panel and the transport meet them.

The Clients page lists the shares with their state and the visitors online,
the entries a new share can offer and the sites that serve the page; it
makes a share and revokes one. A share ends at its expiry, at a revoke, and
with its machine, its module or its declared app. An end sends the
transport ``shares_set`` without it and ``session_close {code:
share_unknown}`` for each of its sessions, and pushes its machine the state
without its guest (protocol.md, "Web shares").
"""

import asyncio
import concurrent.futures
import logging
import socket
import threading
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

from neutrino_hub.exceptions import AgentOfflineError, StreamRefusedError
from neutrino_hub.modules.channel.constants import (
    CHANNEL_CODE_CONTROL_UNAVAILABLE,
    CHANNEL_COMMAND_SESSION_CLOSE,
)
from neutrino_hub.modules.clients.constants import (
    WEB_SHARE_CODE_SHARE_UNKNOWN,
    WEB_SHARE_SITES,
    WEB_SHARE_SWEEP_INTERVAL_S,
)
from neutrino_hub.modules.clients.web_shares import (
    WebShare,
    WebShareRegistry,
    live_pairs,
    share_state,
)
from neutrino_hub.modules.devices.constants import (
    DEVICE_GUEST_LOGIN_APP,
    DEVICE_GUEST_LOGIN_RUN_ACCOUNT,
    DEVICE_HERMES_WEBUI_USER,
)
from neutrino_hub.modules.devices.manifests import (
    guest_login_of,
    load_module_manifests,
)
from neutrino_hub.modules.devices.module_table import DEVICE_MODULE_ROWS
from neutrino_hub.modules.frp.constants import FRP_VENDORS
from neutrino_hub.modules.overlay.direct_config import read_direct
from neutrino_hub.modules.services.constants import (
    SERVICES_APP_SOURCE_ORDER,
    SERVICES_DESCRIPTION_CONTAINER,
    SERVICES_DESCRIPTION_HERMES_WEBUI_MODULE,
    SERVICES_SOURCE_MODULE,
    SERVICES_TYPE_WEB,
)
from neutrino_hub.web.channel_addresses import (
    channel_url,
    channel_urls,
    frp_url,
    relay_url,
)
from neutrino_hub.web.constants import WEB_EVENT_CLIENTS

LOGGER = logging.getLogger(__name__)

# The command that replaces the transport's table of live shares.
COMMAND_SHARES_SET = "shares_set"
# How long a thread waits for a command the loop sends the transport.
COMMAND_WAIT_S = 6.0


class WebShareGuestSessions:
    """The admitted guest sessions, by the transport's session id.

    The hub keeps no record of a visitor: this lives in memory, and a
    session ends with its page.
    """

    def __init__(self):
        self._lock = threading.Lock()
        # (share id, session) by the transport's session id.
        self._sessions: dict = {}

    def add(self, share_id: str, session) -> None:
        """Count one admitted guest session of a share."""
        with self._lock:
            self._sessions[session.session_id] = (share_id, session)

    def end(self, session_id: str) -> bool:
        """Forget a session the transport ended.

        Returns:
            True when it was a guest session.
        """
        with self._lock:
            held = self._sessions.pop(session_id, None)
        if held is None:
            return False
        held[1].mark_ended()
        return True

    def share_of(self, session_id: str) -> str:
        """The share a guest session was admitted to, empty for none."""
        with self._lock:
            held = self._sessions.get(session_id)
        return held[0] if held is not None else ""

    def count(self, share_id: str) -> int:
        """How many guest sessions of a share are open."""
        with self._lock:
            return sum(1 for held in self._sessions.values() if held[0] == share_id)

    def sessions_of(self, share_id: str) -> list:
        """The open guest sessions of a share."""
        with self._lock:
            return [held[1] for held in self._sessions.values() if held[0] == share_id]


def entry_guest_login(entry: dict, manifests: dict) -> tuple:
    """How a share's visitor signs in to one published entry, and its module.

    Args:
        entry: A published entry.
        manifests: The module manifests.

    Returns:
        ``(guest_login, module)``: ``app`` and an empty module for a declared
        app's or a container's ``web`` entry; for a module's page, what its
        manifest's ``web_share`` names and the module, empty when it names
        none; ``("", "")`` for an entry of another type.
    """
    if entry.get("type") != SERVICES_TYPE_WEB:
        return "", ""
    code = str(entry.get("description_code", "") or "")
    if entry.get("source") != SERVICES_SOURCE_MODULE or (
        code == SERVICES_DESCRIPTION_CONTAINER
    ):
        return DEVICE_GUEST_LOGIN_APP, ""
    for row in DEVICE_MODULE_ROWS:
        if row.description_code and row.description_code == code:
            return guest_login_of(manifests, row.name), row.name
    return "", ""


def visitor_account(entry: dict, guest_login: str) -> str:
    """The account a visitor uses an app as, for ``run_account``; else empty."""
    if guest_login != DEVICE_GUEST_LOGIN_RUN_ACCOUNT:
        return ""
    if entry.get("description_code") == SERVICES_DESCRIPTION_HERMES_WEBUI_MODULE:
        return DEVICE_HERMES_WEBUI_USER
    params = entry.get("description_params") or {}
    return str(params.get("account", "") or "")


def offerable_entries(runtime) -> list:
    """The ``web`` entries a new share can offer now.

    Args:
        runtime: The shared runtime.

    Returns:
        ``[{entry, app, guest_login, module, visitor_account}]``, the
        entry unresolved, in the order the Services page lists its apps.
    """
    manifests = load_module_manifests()
    entries, _ = runtime.published_services.entries()
    apps = {app["id"]: app for app in runtime.published_services.apps()}
    offered = []
    for entry in entries:
        app = apps.get(str(entry.get("app_id", "") or ""))
        if app is None:
            continue
        guest_login, module = entry_guest_login(entry, manifests)
        if not guest_login:
            continue
        offered.append(
            {
                "entry": entry,
                "app": app,
                "guest_login": guest_login,
                "module": module,
                "visitor_account": visitor_account(entry, guest_login),
            }
        )
    offered.sort(
        key=lambda item: (
            _source_rank(item["app"]["source"]),
            str(item["app"]["title"]).lower(),
        )
    )
    return offered


def share_views(runtime, now: "float | None" = None) -> list:
    """Every stored share as the Clients page draws it, newest first.

    Args:
        runtime: The shared runtime.
        now: Unix seconds; None reads the clock.

    Returns:
        ``[{id, name, app_id, entry_id, app_title, device_name, expires_at,
        expires_in_s, state, code, params, online_count, guest_email}]``.
    """
    moment = time.time() if now is None else now
    entries, _ = runtime.published_services.entries()
    published = {str(entry.get("id", "")) for entry in entries}
    apps = {app["id"]: app for app in runtime.published_services.apps()}
    names = runtime.device_names()
    reports = runtime.agent_sessions.reports()
    views = []
    shares = sorted(
        WebShareRegistry().all(), key=lambda share: share.created_at, reverse=True
    )
    for share in shares:
        if share.is_expired(moment):
            continue
        app = apps.get(share.app_id) or {}
        state, code, params = share_state(
            share,
            is_published=share.entry_id in published,
            is_online=not share.device_id
            or runtime.agent_sessions.is_online(share.device_id),
            guests_reported=guests_reported(reports, share),
        )
        views.append(
            {
                "id": share.id,
                "name": share.name,
                "app_id": share.app_id,
                "entry_id": share.entry_id,
                "app_title": str(app.get("title", "") or share.app_title),
                "device_name": names.get(share.device_id, "")
                or str(app.get("device_name", "") or ""),
                "expires_at": (
                    None
                    if share.expires_at is None
                    else datetime.fromtimestamp(
                        share.expires_at, timezone.utc
                    ).isoformat()
                ),
                "expires_in_s": (
                    None
                    if share.expires_at is None
                    else max(0, int(share.expires_at - moment))
                ),
                "state": state,
                "code": code,
                "params": params,
                "online_count": runtime.web_share_guests.count(share.id),
                "guest_email": share.guest.email if share.guest is not None else "",
            }
        )
    return views


def web_share_fields(runtime) -> dict:
    """The Web share fields of the Clients page's list.

    Returns:
        ``{web_shares, web_share_entries, web_share_sites}``.
    """
    return {
        "web_shares": share_views(runtime),
        "web_share_entries": entry_views(runtime),
        "web_share_sites": site_views(),
    }


def entry_views(runtime) -> list:
    """The entries a new share can offer, as the Clients page draws them.

    Returns:
        ``[{entry_id, app_id, title, device_name, guest_login,
        visitor_account}]``.
    """
    names = runtime.device_names()
    return [
        {
            "entry_id": item["entry"]["id"],
            "app_id": item["app"]["id"],
            "title": item["app"]["title"],
            "device_name": item["app"].get("device_name")
            or names.get(item["app"].get("device_id", ""), ""),
            "guest_login": item["guest_login"],
            "visitor_account": item["visitor_account"],
        }
        for item in offerable_entries(runtime)
    ]


def site_views() -> list:
    """The sites that serve the share page, ``[{url, title}]``."""
    return [dict(site) for site in WEB_SHARE_SITES]


def share_site(site: str) -> str:
    """A site a share may name, in the form its link takes.

    Args:
        site: One of :data:`WEB_SHARE_SITES` or the ``https://`` origin of a
            copy of the page.

    Returns:
        The site with no trailing slash; empty when it is neither.
    """
    listed = {entry["url"] for entry in WEB_SHARE_SITES}
    trimmed = site.strip().rstrip("/")
    if trimmed in listed:
        return trimmed
    try:
        parts = urlsplit(trimmed)
    except ValueError:
        return ""
    if parts.scheme != "https" or not parts.hostname:
        return ""
    if parts.path or parts.query or parts.fragment or parts.username:
        return ""
    return trimmed


def share_address(runtime) -> tuple:
    """The one address a new share's link names.

    The first public address in ``urls`` order: Direct's, then SakuraFrp's,
    OpenFrp's and the relay's, each while it is a member of ``urls``; else
    the first member of ``urls``. A host name is resolved to its IP address
    now (transport.md, "The links").

    Args:
        runtime: The shared runtime.

    Returns:
        ``(ip, port)``; ``("", 0)`` when the hub has no address or the host
        does not resolve.
    """
    urls = channel_urls(runtime)
    if not urls:
        return "", 0
    publics = [_direct_url(), *(frp_url(vendor) for vendor in FRP_VENDORS)]
    publics.append(relay_url())
    chosen = next((url for url in publics if url and url in urls), urls[0])
    parts = urlsplit(chosen)
    if not parts.hostname or not parts.port:
        return "", 0
    try:
        found = socket.getaddrinfo(parts.hostname, parts.port, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError):
        return "", 0
    addresses = [info[4][0] for info in found]
    ipv4 = [address for address in addresses if ":" not in address]
    return (ipv4 or addresses or [""])[0], parts.port


def entry_path(entry: dict) -> str:
    """The path a shared app opens at, empty for its root."""
    url = str((entry.get("payload") or {}).get("url", "") or "")
    try:
        path = urlsplit(url).path
    except ValueError:
        return ""
    return "" if path in ("", "/") else path


async def push_shares(runtime) -> None:
    """Send the transport the ICE pair of every live share.

    Raises:
        StreamRefusedError: When the transport did not take the command.
    """
    pairs = await asyncio.to_thread(live_pairs)
    await runtime.channel.send_command(COMMAND_SHARES_SET, shares=pairs)


def push_shares_from_thread(runtime) -> None:
    """:func:`push_shares` for a caller outside the loop; a failure is logged."""
    _on_loop(runtime, push_shares(runtime))


def end_shares(runtime, shares: list) -> None:
    """End shares that are gone from the store, from outside the loop.

    The transport gets the table without them and closes each of their
    sessions with ``share_unknown``; each machine whose guest went is pushed
    its state.

    Args:
        runtime: The shared runtime.
        shares: The :class:`WebShare` records just removed.
    """
    if not shares:
        return
    push_shares_from_thread(runtime)
    for share in shares:
        for session in runtime.web_share_guests.sessions_of(share.id):
            _on_loop(
                runtime,
                runtime.channel.send_command(
                    CHANNEL_COMMAND_SESSION_CLOSE,
                    session=session.session_id,
                    code=WEB_SHARE_CODE_SHARE_UNKNOWN,
                    params={},
                ),
            )
    push_guest_devices(runtime, shares)
    runtime.events.publish(WEB_EVENT_CLIENTS)


def push_guest_devices(runtime, shares: list) -> None:
    """Push the state to each machine a share with a guest names.

    Args:
        runtime: The shared runtime.
        shares: The shares that were made or ended.
    """
    devices = {share.device_id for share in shares if share.guest and share.device_id}
    for device_id in sorted(devices):
        try:
            runtime.push_desired_state(device_id)
        except (AgentOfflineError, StreamRefusedError):
            continue


def end_shares_where(runtime, predicate) -> list:
    """Remove and end every share a predicate picks.

    Args:
        runtime: The shared runtime.
        predicate: Called with each :class:`WebShare`.

    Returns:
        The ended shares.
    """
    try:
        removed = WebShareRegistry().remove_where(predicate)
    except OSError as error:
        LOGGER.warning("web shares not ended: %s", error)
        return []
    end_shares(runtime, removed)
    return removed


def end_device_shares(runtime, device_id: str, module: str = "") -> list:
    """End the shares of one machine's entries, or of one module's there.

    Args:
        runtime: The shared runtime.
        device_id: The machine forgotten, or whose module is uninstalled.
        module: The module uninstalled; empty for every share of the machine.

    Returns:
        The ended shares.
    """

    def is_picked(share: WebShare) -> bool:
        if share.device_id != device_id:
            return False
        return not module or share.module == module

    return end_shares_where(runtime, is_picked)


def end_app_shares(runtime, app_id: str) -> list:
    """End the shares of one app, a declared app removed.

    Returns:
        The ended shares.
    """
    return end_shares_where(runtime, lambda share: share.app_id == app_id)


class PanelWebShareSweeper:
    """Ends the expired Web shares on a daemon thread."""

    def __init__(self, *, runtime, interval_s: float = WEB_SHARE_SWEEP_INTERVAL_S):
        """
        Args:
            runtime: The shared runtime.
            interval_s: Seconds between sweeps.
        """
        self._runtime = runtime
        self._interval_s = interval_s
        self._is_stopped = threading.Event()
        self._thread: "threading.Thread | None" = None

    def start(self) -> None:
        """Run the sweep loop on a daemon thread; a second start is a no-op."""
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._loop, name="panel_web_share_sweep", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the loop; the sweep in flight finishes."""
        self._is_stopped.set()

    def sweep_once(self, now: "float | None" = None) -> list:
        """End every share whose ``expires_at`` passed.

        Args:
            now: Unix seconds; None reads the clock.

        Returns:
            The ended shares.
        """
        moment = time.time() if now is None else now
        ended = end_shares_where(self._runtime, lambda share: share.is_expired(moment))
        if ended:
            LOGGER.info("web shares: %d expired share(s) ended", len(ended))
        return ended

    def _loop(self) -> None:
        while not self._is_stopped.wait(self._interval_s):
            self.sweep_once()


def guests_reported(reports: dict, share: WebShare) -> list:
    """The ``details.guests`` a share's machine last reported for its module.

    Args:
        reports: The latest report of every online machine, by device id.
        share: The share.

    Returns:
        ``[{account, code, params}]``; empty for a share with no guest.
    """
    if share.guest is None or not share.device_id:
        return []
    report = reports.get(share.device_id) or {}
    modules = report.get("modules") if isinstance(report, dict) else None
    status = modules.get(share.module) if isinstance(modules, dict) else None
    details = status.get("details") if isinstance(status, dict) else None
    guests = details.get("guests") if isinstance(details, dict) else None
    return list(guests) if isinstance(guests, list) else []


def _direct_url() -> str:
    """Direct's public address while it is on, empty otherwise."""
    try:
        direct = read_direct()
    except ValueError:
        return ""
    if not direct.is_enabled or not direct.public_host:
        return ""
    return channel_url(direct.public_host, direct.public_port)


def _source_rank(source: str) -> int:
    """A module's apps first, then the declared, then the manual."""
    try:
        return SERVICES_APP_SOURCE_ORDER.index(source)
    except ValueError:
        return len(SERVICES_APP_SOURCE_ORDER)


def _on_loop(runtime, coroutine) -> None:
    """Run a command on the channel's loop from another thread; a failure is logged."""
    loop = runtime.channel.loop
    if loop is None or not runtime.channel.is_connected:
        coroutine.close()
        return
    future = asyncio.run_coroutine_threadsafe(coroutine, loop)
    try:
        future.result(COMMAND_WAIT_S)
    except StreamRefusedError as error:
        LOGGER.warning("the transport refused a web share command: %s", error.code)
    except (concurrent.futures.TimeoutError, RuntimeError):
        future.cancel()
        LOGGER.warning(
            "the transport refused a web share command: %s",
            CHANNEL_CODE_CONTROL_UNAVAILABLE,
        )
