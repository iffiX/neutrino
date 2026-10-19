"""The two vendors' APIs, as far as the hub calls them.

SakuraFrp's takes the access key as a bearer token. OpenFrp's takes the
``Authorization`` as the header itself, and may hand a new one back in the
header of any answer; its remote login trades an X25519 public key for an
authorization URL and polls until the person confirms. Every request names
the hub in its ``User-Agent``.

Each client takes its transport, so the tests answer from recorded
responses and never reach a vendor.
"""

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable

from neutrino_hub.exceptions import FrpVendorError
from neutrino_hub.modules.frp.constants import (
    FRP_CODE_CONFIG_UNUSABLE,
    FRP_CODE_CREDENTIAL_REFUSED,
    FRP_CODE_NOT_SIGNED_IN,
    FRP_CODE_VENDOR_UNREACHABLE,
    FRP_HTTP_TIMEOUT_S,
    FRP_OPENFRP,
    FRP_OPENFRP_API,
    FRP_OPENFRP_AUTHORIZATION_HEADER,
    FRP_OPENFRP_LOGIN_PENDING_STATUS,
    FRP_OPENFRP_LOGIN_POLL_URL,
    FRP_OPENFRP_LOGIN_REQUEST_URL,
    FRP_OPENFRP_PUBLIC_KEY_HEADER,
    FRP_SAKURAFRP,
    FRP_SAKURAFRP_API,
    FRP_SAKURAFRP_CODE_UNAUTHORIZED,
    FRP_TITLES,
    FRP_USER_AGENT,
    FRP_VERSION,
)
from neutrino_hub.utils.tls_trust import public_ssl_context

# The HTTP status a refused credential answers with.
FRP_HTTP_UNAUTHORIZED = 401
FRP_HTTP_OK = 200


@dataclass(frozen=True)
class FrpHttpAnswer:
    """One vendor answer.

    Attributes:
        status: The HTTP status.
        headers: The headers, by lower-case name.
        body: The body.
    """

    status: int
    headers: dict
    body: bytes


def http_call(method: str, url: str, *, headers: dict, body: "bytes | None"):
    """Make one HTTPS request to a vendor.

    Args:
        method: ``GET`` or ``POST``.
        url: The address.
        headers: The request's headers.
        body: The request's body; None for none.

    Returns:
        The :class:`FrpHttpAnswer`, whatever its status.

    Raises:
        ConnectionError: If the vendor could not be reached.
    """
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(
            request, timeout=FRP_HTTP_TIMEOUT_S, context=public_ssl_context()
        ) as response:
            return FrpHttpAnswer(
                status=response.status,
                headers={key.lower(): value for key, value in response.headers.items()},
                body=response.read(),
            )
    except urllib.error.HTTPError as error:
        return FrpHttpAnswer(
            status=error.code,
            headers={key.lower(): value for key, value in error.headers.items()},
            body=error.read(),
        )
    except (urllib.error.URLError, OSError, ValueError) as error:
        reason = getattr(error, "reason", error)
        raise ConnectionError(str(reason)) from error


class FrpVendorApi:
    """What both vendors' clients share: the header and the refusals."""

    def __init__(self, *, vendor: str, transport: "Callable | None" = None):
        """
        Args:
            vendor: ``sakurafrp`` or ``openfrp``.
            transport: ``transport(method, url, headers=, body=)`` returns a
                :class:`FrpHttpAnswer` or raises ``ConnectionError``; None
                makes real requests.
        """
        self._vendor = vendor
        self._transport = transport or http_call

    def _call(
        self, method: str, url: str, *, headers: dict, body: "bytes | None" = None
    ) -> FrpHttpAnswer:
        """Make a request with the hub's ``User-Agent``.

        Raises:
            FrpVendorError: ``frp_vendor_unreachable`` when the vendor
                could not be reached.
        """
        try:
            return self._transport(
                method,
                url,
                headers={"User-Agent": FRP_USER_AGENT, **headers},
                body=body,
            )
        except ConnectionError as error:
            raise self._refusal(
                FRP_CODE_VENDOR_UNREACHABLE, detail=str(error)
            ) from error

    def _refusal(self, code: str, **params) -> FrpVendorError:
        """One coded refusal naming this vendor."""
        return FrpVendorError(code, title=FRP_TITLES[self._vendor], **params)

    def _json(self, answer: FrpHttpAnswer):
        """An answer's body as JSON.

        Raises:
            FrpVendorError: ``frp_vendor_unreachable`` for a body that is not
                JSON.
        """
        try:
            return json.loads(answer.body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as error:
            raise self._refusal(
                FRP_CODE_VENDOR_UNREACHABLE,
                detail=f"HTTP {answer.status}: the answer is not JSON",
            ) from error


class SakuraFrpApi(FrpVendorApi):
    """SakuraFrp's API under one access key."""

    def __init__(self, access_key: str, *, transport: "Callable | None" = None):
        """
        Args:
            access_key: The account's access key.
            transport: As :class:`FrpVendorApi` takes it.
        """
        super().__init__(vendor=FRP_SAKURAFRP, transport=transport)
        self._access_key = access_key

    def user_info(self) -> dict:
        """``GET /v4/user/info``: the account, which checks the key.

        Raises:
            FrpVendorError: ``frp_credential_refused`` for a key SakuraFrp
                refuses, ``frp_vendor_unreachable`` otherwise.
        """
        return self._get("/user/info")

    def tunnels(self) -> list:
        """``GET /v4/tunnels``: every tunnel of the account.

        Raises:
            FrpVendorError: As :meth:`user_info`.
        """
        answer = self._get("/tunnels")
        return answer if isinstance(answer, list) else []

    def nodes(self) -> dict:
        """``GET /v4/nodes``: node id to node.

        Raises:
            FrpVendorError: As :meth:`user_info`.
        """
        answer = self._get("/nodes")
        return answer if isinstance(answer, dict) else {}

    def tunnel_config(self, tunnel_id: str) -> str:
        """``POST /v4/tunnel/config``: one tunnel's TOML for upstream frpc.

        Args:
            tunnel_id: The tunnel.

        Returns:
            The config, for ``FRP_VERSION``.

        Raises:
            FrpVendorError: As :meth:`user_info`.
        """
        answer = self._call(
            "POST",
            f"{FRP_SAKURAFRP_API}/tunnel/config",
            headers={
                **self._headers(),
                "Content-Type": "application/x-www-form-urlencoded",
            },
            body=urllib.parse.urlencode(
                {"query": tunnel_id, "frpc": FRP_VERSION}
            ).encode(),
        )
        self._refuse(answer)
        return answer.body.decode("utf-8", errors="replace")

    def _get(self, path: str):
        """One GET under the key, its answer as JSON."""
        answer = self._call(
            "GET", f"{FRP_SAKURAFRP_API}{path}", headers=self._headers()
        )
        self._refuse(answer)
        return self._json(answer)

    def _headers(self) -> dict:
        """The key, as a bearer token."""
        return {
            "Authorization": f"Bearer {self._access_key}",
            "Accept": "application/json",
        }

    def _refuse(self, answer: FrpHttpAnswer) -> None:
        """Raise for an answer that is not a 200.

        SakuraFrp refuses a key with HTTP 500 and ``{"code": 401}``.

        Raises:
            FrpVendorError: ``frp_credential_refused`` or
                ``frp_vendor_unreachable``.
        """
        if answer.status == FRP_HTTP_OK:
            return
        try:
            body = json.loads(answer.body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            body = {}
        if not isinstance(body, dict):
            body = {}
        if (
            answer.status == FRP_HTTP_UNAUTHORIZED
            or body.get("code") == FRP_SAKURAFRP_CODE_UNAUTHORIZED
        ):
            raise self._refusal(FRP_CODE_CREDENTIAL_REFUSED)
        message = str(body.get("msg") or "").strip()
        raise self._refusal(
            FRP_CODE_VENDOR_UNREACHABLE,
            detail=f"HTTP {answer.status}" + (f": {message}" if message else ""),
        )


class OpenFrpApi(FrpVendorApi):
    """OpenFrp's API under one ``Authorization``, and its remote login."""

    def __init__(
        self,
        authorization: str = "",
        *,
        on_rotated: "Callable[[str], None] | None" = None,
        transport: "Callable | None" = None,
    ):
        """
        Args:
            authorization: The stored ``Authorization``; empty for the login
                calls alone.
            on_rotated: Called with a new ``Authorization`` an answer hands
                back.
            transport: As :class:`FrpVendorApi` takes it.
        """
        super().__init__(vendor=FRP_OPENFRP, transport=transport)
        self._authorization = authorization
        self._on_rotated = on_rotated

    def user_proxies(self) -> list:
        """``getUserProxies``: every tunnel of the account.

        Raises:
            FrpVendorError: ``frp_not_signed_in`` when OpenFrp answers 401,
                ``frp_vendor_unreachable`` otherwise.
        """
        data = self._post("getUserProxies", {})
        listed = data.get("list") if isinstance(data, dict) else None
        return listed if isinstance(listed, list) else []

    def node_list(self) -> list:
        """``getNodeList``: every node.

        Raises:
            FrpVendorError: As :meth:`user_proxies`.
        """
        data = self._post("getNodeList", {})
        listed = data.get("list") if isinstance(data, dict) else None
        return listed if isinstance(listed, list) else []

    def node_conf(self, node_id: str) -> str:
        """``getNodeConf``: the TOML of every tunnel of the account on a node.

        Args:
            node_id: The node.

        Returns:
            The config.

        Raises:
            FrpVendorError: As :meth:`user_proxies`, and
                ``frp_config_unusable`` when the answer holds no text.
        """
        try:
            body = {"node_id": int(node_id)}
        except ValueError:
            body = {"node_id": node_id}
        data = self._post("getNodeConf", body)
        if not isinstance(data, str) or not data.strip():
            raise self._refusal(FRP_CODE_CONFIG_UNUSABLE)
        return data

    def request_login(self, public_key: str) -> tuple:
        """Ask for an authorization URL for a public key.

        Args:
            public_key: The X25519 public key, URL-safe base64 with padding.

        Returns:
            ``(authorization_url, request_uuid)``.

        Raises:
            FrpVendorError: ``frp_vendor_unreachable`` when OpenFrp refuses
                or does not answer.
        """
        answer = self._call(
            "POST",
            FRP_OPENFRP_LOGIN_REQUEST_URL,
            headers={"Content-Type": "application/json"},
            body=json.dumps({"public_key": public_key}).encode(),
        )
        body = self._json(answer) if answer.status == FRP_HTTP_OK else {}
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, dict) or not data.get("authorization_url"):
            raise self._refusal(
                FRP_CODE_VENDOR_UNREACHABLE, detail=f"HTTP {answer.status}"
            )
        return str(data["authorization_url"]), str(data.get("request_uuid") or "")

    def poll_login(self, request_uuid: str) -> "tuple | None":
        """Ask once whether the person confirmed.

        Args:
            request_uuid: The login request.

        Returns:
            None while the person has not confirmed; else
            ``(authorization_data, server_public_key)``, both base64.

        Raises:
            FrpVendorError: ``frp_vendor_unreachable`` for any other answer.
        """
        query = urllib.parse.urlencode({"request_uuid": request_uuid})
        answer = self._call("GET", f"{FRP_OPENFRP_LOGIN_POLL_URL}?{query}", headers={})
        if answer.status == FRP_OPENFRP_LOGIN_PENDING_STATUS:
            return None
        body = self._json(answer) if answer.status == FRP_HTTP_OK else {}
        data = body.get("data") if isinstance(body, dict) else None
        server_key = answer.headers.get(FRP_OPENFRP_PUBLIC_KEY_HEADER, "")
        if not isinstance(data, dict) or not data.get("authorization_data"):
            raise self._refusal(
                FRP_CODE_VENDOR_UNREACHABLE, detail=f"HTTP {answer.status}"
            )
        return str(data["authorization_data"]), str(server_key)

    def _post(self, name: str, payload: dict):
        """One API call under the ``Authorization``, its ``data`` back.

        A new ``Authorization`` in the answer's header is handed to
        ``on_rotated`` and used from then on.

        Raises:
            FrpVendorError: ``frp_not_signed_in`` for 401,
                ``frp_vendor_unreachable`` for any other refusal.
        """
        answer = self._call(
            "POST",
            f"{FRP_OPENFRP_API}/{name}",
            headers={
                "Authorization": self._authorization,
                "Content-Type": "application/json",
            },
            body=json.dumps(payload).encode(),
        )
        if answer.status == FRP_HTTP_UNAUTHORIZED:
            raise self._refusal(FRP_CODE_NOT_SIGNED_IN)
        rotated = answer.headers.get(FRP_OPENFRP_AUTHORIZATION_HEADER, "")
        if rotated and rotated != self._authorization:
            self._authorization = rotated
            if self._on_rotated is not None:
                self._on_rotated(rotated)
        body = self._json(answer)
        if answer.status != FRP_HTTP_OK or not isinstance(body, dict):
            raise self._refusal(
                FRP_CODE_VENDOR_UNREACHABLE, detail=f"HTTP {answer.status}"
            )
        if not body.get("flag"):
            raise self._refusal(
                FRP_CODE_VENDOR_UNREACHABLE,
                detail=str(body.get("msg") or "the answer says it failed"),
            )
        return body.get("data")
