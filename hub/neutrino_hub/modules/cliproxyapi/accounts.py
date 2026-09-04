"""Subscription accounts, over the gateway's management API.

An account is a login against the provider rather than a key somebody types,
so it is not configuration: the gateway writes the token file into its auth
directory under the state root and picks it up without a restart. The hub
starts a flow, hands the person the URL to open, passes the code back, and
lists what the gateway reports. It holds no OAuth client secrets of its own
and never reads a token file.

Not pure: every method is a call to the running gateway.
"""

from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlparse

import httpx

from neutrino_hub.modules.cliproxyapi.constants import (
    CLIPROXYAPI_ACCOUNT_TIMEOUT_S,
    CLIPROXYAPI_AUTH_FILES_PATH,
    CLIPROXYAPI_AUTH_STATUS_PATH,
    CLIPROXYAPI_AUTH_URL_PATH,
    CLIPROXYAPI_LOGIN_KINDS,
    CLIPROXYAPI_OAUTH_CALLBACK_PATH,
    CLIPROXYAPI_OAUTH_SESSION_PATH,
)

# What the gateway answers a poll with, mapped to what the panel reports.
LOGIN_PENDING = "pending"
LOGIN_COMPLETE = "complete"
LOGIN_FAILED = "failed"
GATEWAY_STATUS_TO_LOGIN = {
    "wait": LOGIN_PENDING,
    "ok": LOGIN_COMPLETE,
    "error": LOGIN_FAILED,
}


class CliproxyApiAccountError(Exception):
    """A management API call the panel cannot carry out.

    Attributes:
        code: What the panel words, one of ``gateway_unreachable``,
            ``login_expired``, ``unsupported_kind``, ``unknown_account`` or
            ``management_key_missing``.
        params: What the wording needs, by name.
    """

    def __init__(self, code: str, **params):
        super().__init__(code)
        self.code = code
        self.params = params


@dataclass
class CliproxyApiAccount:
    """One signed-in account, as the gateway reports it.

    The gateway refreshes its own tokens, so there is no expiry to show: what
    it reports instead is whether the account is serving right now.
    """

    name: str
    provider: str
    label: str
    email: str
    account_type: str
    status: str
    status_message: str
    is_disabled: bool
    is_unavailable: bool
    failed_count: int
    success_count: int
    created_at: str
    updated_at: str


@dataclass
class CliproxyApiLogin:
    """A login flow in progress.

    Attributes:
        state: The gateway's handle for the flow, and the panel's too.
        kind: Which flow was started.
        url: What the person opens.
        flow: ``device`` where the provider shows a code to approve,
            ``redirect`` where the browser comes back with one to paste.
        user_code: What the person types at the provider, device flows only.
        expires_in: Seconds the flow stays open, 0 where none was given.
    """

    state: str
    kind: str
    url: str
    flow: str
    user_code: str = ""
    expires_in: int = 0


@dataclass
class CliproxyApiLoginState:
    """Where a flow has got to.

    Attributes:
        state: The handle polled.
        status: ``pending``, ``complete`` or ``failed``.
        message: The gateway's own reason, empty unless it failed.
    """

    state: str
    status: str
    message: str = ""


@dataclass
class CliproxyApiAccountsReport:
    """What the accounts endpoint answers with."""

    accounts: list[CliproxyApiAccount] = field(default_factory=list)
    login_kinds: list[str] = field(default_factory=list)


class CliproxyApiAccountClient:
    """Calls the gateway's management API on behalf of the panel."""

    def __init__(self, *, port: int, management_key: str):
        """
        Args:
            port: Where the gateway listens.
            management_key: The key that unlocks the management API.

        Raises:
            CliproxyApiAccountError: ``management_key_missing`` when there is
                no key, because every route below needs one.
        """
        if not management_key:
            raise CliproxyApiAccountError("management_key_missing")
        self._base = f"http://127.0.0.1:{port}"
        self._headers = {"Authorization": f"Bearer {management_key}"}

    def list_accounts(self) -> list[CliproxyApiAccount]:
        """Every account the gateway is holding a token file for.

        Returns:
            The accounts, by name.

        Raises:
            CliproxyApiAccountError: If the gateway does not answer.
        """
        payload = self._call("GET", CLIPROXYAPI_AUTH_FILES_PATH)
        return [_account(entry) for entry in payload.get("files") or []]

    def delete_account(self, name: str) -> None:
        """Delete one account's token file; whatever it served stops now.

        Args:
            name: The token file's name, as the list reports it.

        Raises:
            CliproxyApiAccountError: ``unknown_account`` when the gateway does
                not have it, ``gateway_unreachable`` when it does not answer.
        """
        self._call(
            "DELETE",
            CLIPROXYAPI_AUTH_FILES_PATH,
            params={"name": name},
            missing_code="unknown_account",
            missing_params={"name": name},
        )

    def start_login(self, kind: str) -> CliproxyApiLogin:
        """Begin a login and return what the person has to open.

        Args:
            kind: One of :data:`CLIPROXYAPI_LOGIN_KINDS`.

        Returns:
            The flow, carrying the URL and the handle to poll.

        Raises:
            CliproxyApiAccountError: ``unsupported_kind`` for a flow this
                version does not carry, ``gateway_unreachable`` when the
                gateway does not answer.
        """
        if kind not in CLIPROXYAPI_LOGIN_KINDS:
            raise CliproxyApiAccountError("unsupported_kind", kind=kind)
        payload = self._call(
            "GET",
            CLIPROXYAPI_AUTH_URL_PATH.format(kind=kind),
            missing_code="unsupported_kind",
            missing_params={"kind": kind},
        )
        return CliproxyApiLogin(
            state=str(payload.get("state", "")),
            kind=kind,
            url=str(payload.get("url", "")),
            flow=str(payload.get("flow", "") or "redirect"),
            user_code=str(payload.get("user_code", "")),
            expires_in=int(payload.get("expires_in", 0) or 0),
        )

    def read_login(self, state: str) -> CliproxyApiLoginState:
        """Ask where a flow has got to.

        Args:
            state: The handle the start returned.

        Returns:
            The flow's state.

        Raises:
            CliproxyApiAccountError: ``gateway_unreachable`` when the gateway
                does not answer.
        """
        payload = self._call(
            "GET", CLIPROXYAPI_AUTH_STATUS_PATH, params={"state": state}
        )
        reported = str(payload.get("status", ""))
        return CliproxyApiLoginState(
            state=state,
            status=GATEWAY_STATUS_TO_LOGIN.get(reported, LOGIN_PENDING),
            message=str(payload.get("error", "")),
        )

    def submit_code(self, state: str, code: str) -> None:
        """Hand the gateway the code the provider sent the browser back with.

        The gateway exchanges it behind the call, so a caller learns the
        outcome from :meth:`read_login` rather than from here.

        Args:
            state: The handle the start returned.
            code: What the person pasted; a whole redirect URL is accepted and
                the code taken out of it.

        Raises:
            CliproxyApiAccountError: ``login_expired`` when the gateway no
                longer holds the flow, ``gateway_unreachable`` when it does
                not answer.
        """
        self._call(
            "POST",
            CLIPROXYAPI_OAUTH_CALLBACK_PATH,
            json={"state": state, "code": code_of(code)},
            missing_code="login_expired",
            missing_params={"state": state},
        )

    def cancel_login(self, state: str) -> None:
        """Drop a flow nobody finished, so it stops waiting to be completed.

        Args:
            state: The handle the start returned.

        Raises:
            CliproxyApiAccountError: ``login_expired`` when the gateway has
                already forgotten it, ``gateway_unreachable`` when it does not
                answer.
        """
        self._call(
            "DELETE",
            CLIPROXYAPI_OAUTH_SESSION_PATH,
            params={"state": state},
            missing_code="login_expired",
            missing_params={"state": state},
        )

    def _call(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json: dict | None = None,
        missing_code: str = "gateway_unreachable",
        missing_params: dict | None = None,
    ) -> dict:
        """One management API call.

        Args:
            method: The HTTP method.
            path: The path under the gateway's base URL.
            params: Query parameters, when the route takes any.
            json: The body, when the route takes one.
            missing_code: What a 404 means for this route.
            missing_params: What that wording needs.

        Returns:
            The decoded body, empty when the answer carried none.

        Raises:
            CliproxyApiAccountError: For a refusal or an unreachable gateway.
        """
        try:
            response = httpx.request(
                method,
                self._base + path,
                headers=self._headers,
                params=params,
                json=json,
                timeout=CLIPROXYAPI_ACCOUNT_TIMEOUT_S,
            )
        except httpx.HTTPError as error:
            raise CliproxyApiAccountError(
                "gateway_unreachable", reason=str(error)
            ) from error
        if response.status_code == 404:
            raise CliproxyApiAccountError(missing_code, **(missing_params or {}))
        if not response.is_success:
            raise CliproxyApiAccountError(
                "gateway_unreachable", reason=f"answered {response.status_code}"
            )
        try:
            payload = response.json()
        except ValueError:
            return {}
        return payload if isinstance(payload, dict) else {}


def code_of(pasted: str) -> str:
    """The authorization code out of whatever the person pasted.

    The provider sends the browser to a loopback address on the gateway that
    the browser cannot reach, so what a person has to hand back is the address
    bar. Both that and the bare code are accepted.

    Args:
        pasted: The code, or the URL the browser was sent to.

    Returns:
        The code, stripped.
    """
    pasted = pasted.strip()
    if "://" not in pasted:
        return pasted
    parsed = urlparse(pasted)
    found = parse_qs(parsed.query).get("code") or parse_qs(parsed.fragment).get("code")
    return found[0].strip() if found else pasted


def _account(entry: dict) -> CliproxyApiAccount:
    """One account row, from the gateway's own record.

    The record also carries the token file's path, its size and a per-slot
    request history; none of that is the panel's business and none of it is
    read here.
    """
    return CliproxyApiAccount(
        name=str(entry.get("name", "")),
        provider=str(entry.get("provider", "")),
        label=str(entry.get("label", "")),
        email=str(entry.get("email", "")),
        account_type=str(entry.get("account_type", "")),
        status=str(entry.get("status", "")),
        status_message=str(entry.get("status_message", "")),
        is_disabled=bool(entry.get("disabled", False)),
        is_unavailable=bool(entry.get("unavailable", False)),
        failed_count=int(entry.get("failed", 0) or 0),
        success_count=int(entry.get("success", 0) or 0),
        created_at=str(entry.get("created_at", "")),
        updated_at=str(entry.get("updated_at", "")),
    )
