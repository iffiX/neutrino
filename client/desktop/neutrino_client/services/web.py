"""The web service type: a published link the person opens.

The rows render straight from the typed entries, and the platform's browser
is what opens the payload's url. An entry whose payload says
``is_local_only`` opens only from localhost: its token comes down the
``service`` stream, its address is forwarded to the loopback port the local
port table gives it, and the browser opens the forward with no token. The
forward hands the token to the page as its cookie on every request, so the
browser stores none. The forwards are runtime state and end with the client.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# client still imports on Python 3.9.
from __future__ import annotations

import socket
import threading
import urllib.parse

from neutrino_client.services.base import (
    ServiceTypeHandler,
    channel_refusal,
    find_entry,
    hub_of_key,
    service_key,
)
from neutrino_client.services.port import (
    FORWARD_BIND_HOST,
    FORWARD_CONNECT_TIMEOUT_S,
    PortLocalTable,
    _ForwardRelay,
    _pump,
)

# The cookie a local-only page takes its token in.
WEB_TOKEN_COOKIE = "vscode-tkn"
# How long a request's or a response's head may be.
WEB_HEAD_MAX_BYTES = 65536
WEB_HEAD_END = b"\r\n\r\n"


def rewrite_request_head(head: bytes, token: str) -> bytes:
    """A request's head with the token as its cookie and one request per connection.

    Args:
        head: The head as the browser sent it, up to and with the blank
            line.
        token: The entry's token.

    Returns:
        The head with every ``Cookie`` header folded into one that carries
        the token as ``vscode-tkn`` and no other ``vscode-tkn``, and
        ``Connection: close`` in place of any ``Connection`` header unless
        the request asks to upgrade the connection.
    """
    lines = head[: -len(WEB_HEAD_END)].split(b"\r\n")
    request_line, headers = lines[0], lines[1:]
    cookies = []
    kept = []
    is_upgrade = False
    for line in headers:
        name, _, value = line.partition(b":")
        lowered = name.strip().lower()
        if lowered == b"cookie":
            cookies.extend(
                part.strip()
                for part in value.split(b";")
                if part.strip() and not _is_token_cookie(part)
            )
            continue
        if lowered == b"connection" and b"upgrade" in value.lower():
            is_upgrade = True
        kept.append(line)
    if not is_upgrade:
        kept = [
            line
            for line in kept
            if line.partition(b":")[0].strip().lower() != b"connection"
        ]
        kept.append(b"Connection: close")
    cookies.append(WEB_TOKEN_COOKIE.encode() + b"=" + token.encode())
    kept.append(b"Cookie: " + b"; ".join(cookies))
    return b"\r\n".join([request_line] + kept) + WEB_HEAD_END


def rewrite_response_head(head: bytes) -> bytes:
    """A response's head without the ``Set-Cookie`` headers that set the token.

    Args:
        head: The head as the server sent it, up to and with the blank
            line.

    Returns:
        The head, every ``Set-Cookie`` naming ``vscode-tkn`` dropped.
    """
    lines = head[: -len(WEB_HEAD_END)].split(b"\r\n")
    kept = [lines[0]]
    for line in lines[1:]:
        name, _, value = line.partition(b":")
        if name.strip().lower() == b"set-cookie" and _is_token_cookie(value):
            continue
        kept.append(line)
    return b"\r\n".join(kept) + WEB_HEAD_END


def read_head(connection) -> "tuple[bytes, bytes] | None":
    """Read one HTTP head off a socket.

    Args:
        connection: The socket.

    Returns:
        The head with its blank line, and whatever came after it in the
        same reads; None when the socket ends first or the head runs past
        ``WEB_HEAD_MAX_BYTES``.
    """
    received = b""
    while WEB_HEAD_END not in received:
        if len(received) > WEB_HEAD_MAX_BYTES:
            return None
        try:
            data = connection.recv(WEB_HEAD_MAX_BYTES)
        except OSError:
            return None
        if not data:
            return None
        received += data
    cut = received.index(WEB_HEAD_END) + len(WEB_HEAD_END)
    return received[:cut], received[cut:]


def _is_token_cookie(text: bytes) -> bool:
    """Whether a cookie pair or a ``Set-Cookie`` value names the token cookie."""
    name = text.split(b";", 1)[0].partition(b"=")[0]
    return name.strip().decode("latin-1") == WEB_TOKEN_COOKIE


class WebServiceHandler(ServiceTypeHandler):
    """Opens a published link in the person's browser, through a forward when it must."""

    service_type = "web"

    def __init__(self, *, platform, open_service=None, log=print, ports=None):
        """
        Args:
            platform: The machine's platform, behind the contract.
            open_service: Callable ``(hub_id, entry_id) -> dict`` opening
                the ``service`` stream for one entry and returning its
                material; None where no entry is local-only.
            log: Callable used for progress messages.
            ports: The :class:`~neutrino_client.services.port.PortLocalTable`
                the forwards take their port from; None keeps one in memory.
        """
        self._platform = platform
        self._open_service = open_service
        self._log = log
        self._ports = ports if ports is not None else PortLocalTable()
        self._lock = threading.Lock()
        # The forwards of the local-only entries, by service key.
        self._relays: dict = {}

    def act(self, *, entries: list, body: dict):
        """Open one published link, or end a local-only entry's forward.

        Args:
            entries: The merged service list.
            body: ``{"hub_id", "id", "is_enabled"}``; ``is_enabled`` false
                ends the entry's forward, and is optional otherwise.

        Returns:
            Empty on success, ``{"code", "params"}`` on a refusal.
        """
        hub_id = str(body.get("hub_id", ""))
        entry_id = str(body.get("id", ""))
        entry = find_entry(entries, self.service_type, hub_id, entry_id)
        if entry is None:
            return {"code": "unknown_request", "params": {}}
        if body.get("is_enabled") is False:
            return self.stop(hub_id=hub_id, entry_id=entry_id)
        payload = entry.get("payload") or {}
        url = str(payload.get("url", ""))
        if not url:
            return {"code": "unknown_request", "params": {}}
        if payload.get("is_local_only") is True:
            return self._open_local(entry, url)
        self._platform.open_url(url)
        return {}

    def state(self) -> dict:
        """The forwards of the local-only entries, for the state payload.

        Returns:
            ``{"web_forwards": {service_key: {"local_port", "is_active"}}}``.
        """
        with self._lock:
            return {
                "web_forwards": {
                    key: {"local_port": relay.local_port, "is_active": relay.is_active}
                    for key, relay in self._relays.items()
                }
            }

    def stop(self, *, hub_id: str, entry_id: str) -> dict:
        """End one local-only entry's forward.

        Args:
            hub_id: The hub the entry came from.
            entry_id: The entry whose forward to end.

        Returns:
            Empty; ending what is not running is nothing.
        """
        with self._lock:
            relay = self._relays.pop(service_key(hub_id, entry_id), None)
        if relay is not None:
            relay.close()
            self._log(f"stopped forwarding to {relay.host}:{relay.port}")
        return {}

    def release(self) -> int:
        """Close every forward.

        Returns:
            How many forwards were closed.
        """
        with self._lock:
            relays, self._relays = self._relays, {}
        for relay in relays.values():
            relay.close()
        return len(relays)

    def release_hub(self, hub_id: str) -> int:
        """Close the forwards of one hub's entries.

        Args:
            hub_id: The hub whose forwards are closed.

        Returns:
            How many forwards were closed.
        """
        with self._lock:
            keys = [key for key in self._relays if hub_of_key(key) == hub_id]
            relays = [self._relays.pop(key) for key in keys]
        for relay in relays:
            relay.close()
        return len(relays)

    def _open_local(self, entry: dict, url: str) -> dict:
        """Take a local-only entry's token, forward it to the loopback, open it."""
        parts = urllib.parse.urlsplit(url)
        try:
            port = parts.port or (443 if parts.scheme == "https" else 80)
        except ValueError:
            return {"code": "unknown_request", "params": {}}
        if not parts.hostname or self._open_service is None:
            return {"code": "unknown_request", "params": {}}
        hub_id = str(entry.get("hub_id", ""))
        entry_id = str(entry.get("id", ""))
        try:
            material = self._open_service(hub_id, entry_id)
        except Exception as error:  # noqa: BLE001 - a refusal, never a crash
            return channel_refusal(error)
        token = str((material or {}).get("token", "") or "")
        if not token:
            return {"code": "web_token_missing", "params": {}}
        key = service_key(hub_id, entry_id)
        with self._lock:
            relay = self._relays.get(key)
            if relay is not None and relay.is_active:
                relay.token = token
            else:
                try:
                    relay = _WebTokenRelay(
                        host=parts.hostname,
                        port=port,
                        local_port=self._ports.take(key, port),
                        token=token,
                    )
                    relay.start()
                except OSError as error:
                    return {
                        "code": "forward_failed",
                        "params": {"detail": str(error)[:200]},
                    }
                self._relays[key] = relay
                self._log(
                    f"forwarding {FORWARD_BIND_HOST}:{relay.local_port} "
                    f"to {parts.hostname}:{port}"
                )
        self._platform.open_url(
            f"http://{FORWARD_BIND_HOST}:{relay.local_port}{parts.path or '/'}"
        )
        return {}


class _WebTokenRelay(_ForwardRelay):
    """A loopback forward that hands the page its token as a cookie."""

    def __init__(self, *, host: str, port: int, local_port: int, token: str):
        """
        Args:
            host: The address the page answers on.
            port: The page's port.
            local_port: The loopback number to listen on.
            token: The entry's token.
        """
        super().__init__(host=host, port=port, local_port=local_port)
        self.token = token

    def _serve(self, connection) -> None:
        """Pass one request with the token, its response without it, then bytes."""
        try:
            upstream = socket.create_connection(
                (self.host, self.port), timeout=FORWARD_CONNECT_TIMEOUT_S
            )
        except OSError:
            connection.close()
            return
        upstream.settimeout(None)
        with self._lock:
            self._connections.add(connection)
            self._connections.add(upstream)
        try:
            self._relay(connection, upstream)
        finally:
            with self._lock:
                self._connections.discard(connection)
                self._connections.discard(upstream)
            for side in (connection, upstream):
                try:
                    side.close()
                except OSError:
                    pass

    def _relay(self, connection, upstream) -> None:
        """Rewrite the two heads, then copy both directions until they end."""
        request = read_head(connection)
        if request is None:
            return
        try:
            upstream.sendall(rewrite_request_head(request[0], self.token) + request[1])
        except OSError:
            return
        outbound = threading.Thread(
            target=_pump, args=(connection, upstream), daemon=True
        )
        outbound.start()
        response = read_head(upstream)
        if response is not None:
            try:
                connection.sendall(rewrite_response_head(response[0]) + response[1])
            except OSError:
                response = None
        if response is not None:
            _pump(upstream, connection)
        else:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        outbound.join()
