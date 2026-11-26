"""Subscription accounts, over the gateway's management API.

An account is a login against the provider rather than a key somebody types,
so it is not configuration: the gateway writes the token file into its auth
directory under the state root and picks it up without a restart. The hub
starts a flow, hands the person the URL to open, passes the code back, and
lists what the gateway reports. It holds no OAuth client secrets of its own
and never reads a token file.

An account's quota windows come from the gateway: the signals it kept from
the vendor's answers, and a read of the vendor's usage endpoint the gateway
sends with the account's token at a press of **Refresh**. The last read of
each account is kept under the state root (hub_components/ai.md, "Quota on
an account row").

Not pure: every client method is a call to the running gateway, and the
quota read store is a file. The parsing of the windows is pure.
"""

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

import httpx

from neutrino_hub.exceptions import AiAccountRefusedError
from neutrino_hub.modules.cliproxyapi.constants import (
    CLIPROXYAPI_ACCOUNT_QUOTA_RELATIVE,
    CLIPROXYAPI_ACCOUNT_TIMEOUT_S,
    CLIPROXYAPI_API_CALL_PATH,
    CLIPROXYAPI_API_CALL_TIMEOUT_S,
    CLIPROXYAPI_AUTH_FILE_MODELS_PATH,
    CLIPROXYAPI_AUTH_FILE_STATUS_PATH,
    CLIPROXYAPI_AUTH_FILES_PATH,
    CLIPROXYAPI_AUTH_STATUS_PATH,
    CLIPROXYAPI_AUTH_URL_PATH,
    CLIPROXYAPI_CODEX_ACCOUNT_HEADER,
    CLIPROXYAPI_LOGIN_KINDS,
    CLIPROXYAPI_MODEL_DEFINITIONS_PATH,
    CLIPROXYAPI_OAUTH_CALLBACK_PATH,
    CLIPROXYAPI_OAUTH_SESSION_PATH,
    CLIPROXYAPI_QUOTA_READS,
    CLIPROXYAPI_TOKEN_WORD,
    CLIPROXYAPI_WINDOW_NAMES,
    CLIPROXYAPI_WINDOW_READ,
    CLIPROXYAPI_WINDOW_SIGNAL,
)
from neutrino_hub.utils import constants
from neutrino_hub.utils.json_file import write_generated

# What the gateway answers a poll with, mapped to what the panel reports.
LOGIN_PENDING = "pending"
LOGIN_COMPLETE = "complete"
LOGIN_FAILED = "failed"
GATEWAY_STATUS_TO_LOGIN = {
    "wait": LOGIN_PENDING,
    "ok": LOGIN_COMPLETE,
    "error": LOGIN_FAILED,
}
# The gateway's own words for a flow it no longer holds, which is the
# sign-in session timing out rather than the provider refusing.
GATEWAY_EXPIRED_STATE = "unknown or expired state"
TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
# The signal headers of a Claude login's windows, by window.
CLAUDE_SIGNAL_WINDOWS = ("5h", "7d")
CLAUDE_SIGNAL_PREFIX = "anthropic-ratelimit-unified-"
# The signal header groups of a Codex login, each one window.
CODEX_SIGNAL_GROUPS = ("primary", "secondary")
CODEX_SIGNAL_PREFIX = "x-codex-"
# The windows a Claude read and a Kimi read name, by the field holding each.
CLAUDE_READ_WINDOWS = {"five_hour": "5h", "seven_day": "7d"}
KIMI_READ_WINDOWS = {"limit_5h": "5h", "limit_7d": "7d", "limit_month_total": "month"}
CODEX_READ_WINDOWS = ("primary_window", "secondary_window")
SHARE_DIGITS = 4
# Times before this are read as seconds, after it as milliseconds.
MILLISECONDS_FROM = 10**11


@dataclass
class CliproxyApiAccount:
    """One signed-in account, as the gateway reports it.

    The gateway refreshes its own tokens, so there is no expiry to show: what
    it reports instead is whether the account is serving right now.

    Attributes:
        name: The token file, and the account's id everywhere in the panel.
        auth_index: The gateway's own handle for the credential, carried by
            every usage record it serves, and what usage is attributed by. It
            survives a token refresh; an older gateway that lists auth files
            off disk sends none, and then nothing is attributed.
        next_retry_after: When the gateway serves the account again, while
            it cools the account; empty while it does not.
        plan: A Codex login's plan, as its ID token names it.
        subscription_ends_at: When that subscription ends.
        vendor_account_id: A Codex login's ChatGPT account id, which its
            quota read names.
        signal_windows: The windows the gateway's signals give, each
            ``{name, used_share, resets_at, seen_at, origin}``.
    """

    name: str
    auth_index: str
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
    next_retry_after: str = ""
    plan: str = ""
    subscription_ends_at: str = ""
    vendor_account_id: str = ""
    signal_windows: list = field(default_factory=list)


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
            AiAccountRefusedError: ``management_key_missing`` when there is
                no key, because every route below needs one.
        """
        if not management_key:
            raise AiAccountRefusedError("management_key_missing")
        self._base = f"http://127.0.0.1:{port}"
        self._headers = {"Authorization": f"Bearer {management_key}"}

    def list_accounts(self) -> list[CliproxyApiAccount]:
        """Every account the gateway is holding a token file for.

        Returns:
            The accounts, by name.

        Raises:
            AiAccountRefusedError: If the gateway does not answer.
        """
        payload = self._call("GET", CLIPROXYAPI_AUTH_FILES_PATH)
        return [_account(entry) for entry in payload.get("files") or []]

    def model_definitions(self, channel: str) -> list:
        """One channel's entries in the gateway's model catalog.

        Args:
            channel: ``claude``, ``codex``, ``gemini``, ``antigravity``,
                ``kimi`` or ``xai``.

        Returns:
            The catalog's entries, each as the gateway keeps it.

        Raises:
            AiAccountRefusedError: ``gateway_unreachable`` if the gateway
                does not answer, or answers with no list of models.
        """
        payload = self._call(
            "GET", CLIPROXYAPI_MODEL_DEFINITIONS_PATH.format(channel=channel)
        )
        models = payload.get("models")
        if not isinstance(models, list):
            raise AiAccountRefusedError(
                "gateway_unreachable", reason=f"no models for {channel}"
            )
        return [entry for entry in models if isinstance(entry, dict)]

    def account_models(self, name: str) -> list:
        """The names the gateway serves through one account.

        Args:
            name: The account's token file.

        Returns:
            The names, as the gateway registers them for the account.

        Raises:
            AiAccountRefusedError: ``unknown_account`` when the gateway does
                not have it, ``gateway_unreachable`` when it does not answer.
        """
        payload = self._call(
            "GET",
            CLIPROXYAPI_AUTH_FILE_MODELS_PATH,
            params={"name": name},
            missing_code="unknown_account",
            missing_params={"name": name},
        )
        names = []
        for entry in payload.get("models") or []:
            found = (
                entry.get("id") or entry.get("name")
                if isinstance(entry, dict)
                else entry
            )
            if isinstance(found, str) and found:
                names.append(found)
        return names

    def delete_account(self, name: str) -> None:
        """Delete one account's token file; whatever it served stops now.

        Args:
            name: The token file's name, as the list reports it.

        Raises:
            AiAccountRefusedError: ``unknown_account`` when the gateway does
                not have it, ``gateway_unreachable`` when it does not answer.
        """
        self._call(
            "DELETE",
            CLIPROXYAPI_AUTH_FILES_PATH,
            params={"name": name},
            missing_code="unknown_account",
            missing_params={"name": name},
        )

    def set_disabled(self, name: str, *, is_disabled: bool) -> None:
        """Pause an account, or resume it; the token file keeps the state across restarts.

        Args:
            name: The account's token file.
            is_disabled: True pauses, False resumes.

        Raises:
            AiAccountRefusedError: ``unknown_account`` when the gateway does
                not have it, ``gateway_unreachable`` when it does not answer.
        """
        self._call(
            "PATCH",
            CLIPROXYAPI_AUTH_FILE_STATUS_PATH,
            json={"name": name, "disabled": is_disabled},
            missing_code="unknown_account",
            missing_params={"name": name},
        )

    def read_quota(self, account: CliproxyApiAccount) -> list:
        """Read an account's windows from its vendor, through the gateway.

        The gateway puts the account's token in place of ``$TOKEN$`` and
        sends the request through the account's own proxy.

        Args:
            account: The account, as :meth:`list_accounts` lists it.

        Returns:
            The windows that parse, each ``{name, used_share, resets_at}``.

        Raises:
            AiAccountRefusedError: ``quota_read_unsupported {provider}`` for a
                login with no read, ``quota_read_failed {status}`` for a
                vendor's answer other than 2xx (0 for a request that reached
                no vendor), ``quota_read_unparsed`` for an answer with no
                window that parses, ``gateway_unreachable`` when the gateway
                does not answer.
        """
        provider = account.provider.lower()
        if provider not in CLIPROXYAPI_QUOTA_READS:
            raise AiAccountRefusedError(
                "quota_read_unsupported", provider=account.provider
            )
        method, url, headers, data = CLIPROXYAPI_QUOTA_READS[provider]
        header = {"Authorization": f"Bearer {CLIPROXYAPI_TOKEN_WORD}", **headers}
        if provider == "codex" and account.vendor_account_id:
            header[CLIPROXYAPI_CODEX_ACCOUNT_HEADER] = account.vendor_account_id
        status, body = self._api_call(
            {
                "auth_index": account.auth_index,
                "method": method,
                "url": url,
                "header": header,
                "data": data,
            }
        )
        if not 200 <= status < 300:
            raise AiAccountRefusedError("quota_read_failed", status=status)
        try:
            answer = json.loads(body)
        except ValueError:
            answer = None
        windows = read_windows(provider, answer)
        if not windows:
            raise AiAccountRefusedError("quota_read_unparsed")
        return windows

    def _api_call(self, request: dict) -> tuple:
        """One request the gateway sends on the hub's behalf.

        Args:
            request: ``{auth_index, method, url, header, data}``.

        Returns:
            ``(status, body)``: the vendor's status and body, and status 0
            when the gateway answered that the request reached no vendor.

        Raises:
            AiAccountRefusedError: ``gateway_unreachable`` when the gateway
                does not answer.
        """
        try:
            response = httpx.request(
                "POST",
                self._base + CLIPROXYAPI_API_CALL_PATH,
                headers=self._headers,
                json=request,
                timeout=CLIPROXYAPI_API_CALL_TIMEOUT_S,
            )
        except httpx.HTTPError as error:
            raise AiAccountRefusedError(
                "gateway_unreachable", reason=str(error)
            ) from error
        if not response.is_success:
            return 0, ""
        try:
            payload = response.json()
        except ValueError:
            return 0, ""
        if not isinstance(payload, dict):
            return 0, ""
        status = payload.get("status_code")
        if isinstance(status, bool) or not isinstance(status, int):
            return 0, ""
        return status, str(payload.get("body", "") or "")

    def start_login(self, kind: str) -> CliproxyApiLogin:
        """Begin a login and return what the person has to open.

        Args:
            kind: One of :data:`CLIPROXYAPI_LOGIN_KINDS`.

        Returns:
            The flow, carrying the URL and the handle to poll.

        Raises:
            AiAccountRefusedError: ``unsupported_kind`` for a flow this
                version does not carry, ``gateway_unreachable`` when the
                gateway does not answer.
        """
        if kind not in CLIPROXYAPI_LOGIN_KINDS:
            raise AiAccountRefusedError("unsupported_kind", kind=kind)
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
            AiAccountRefusedError: ``login_expired`` when the gateway no
                longer holds the flow, ``gateway_unreachable`` when it does
                not answer.
        """
        payload = self._call(
            "GET",
            CLIPROXYAPI_AUTH_STATUS_PATH,
            params={"state": state},
            missing_code="login_expired",
            missing_params={"state": state},
        )
        reported = str(payload.get("status", ""))
        if str(payload.get("error", "")).strip().lower() == GATEWAY_EXPIRED_STATE:
            raise AiAccountRefusedError("login_expired", state=state)
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
            AiAccountRefusedError: ``login_expired`` when the gateway no
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
            AiAccountRefusedError: ``login_expired`` when the gateway has
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
            AiAccountRefusedError: For a refusal or an unreachable gateway.
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
            raise AiAccountRefusedError(
                "gateway_unreachable", reason=str(error)
            ) from error
        if response.status_code == 404:
            raise AiAccountRefusedError(missing_code, **(missing_params or {}))
        if not response.is_success:
            raise AiAccountRefusedError(
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


def has_quota_read(provider: str) -> bool:
    """Whether a login's vendor can be read for its windows.

    Args:
        provider: The login, as the gateway names the account's provider.

    Returns:
        True for Claude, Codex, Kimi and Antigravity.
    """
    return provider.lower() in CLIPROXYAPI_QUOTA_READS


def signal_windows(provider: str, quota) -> list:
    """The windows the gateway's signals give for one account.

    Args:
        provider: The login, as the gateway names the account's provider.
        quota: The entry's ``quota``, ``{signals, observed_at}``.

    Returns:
        ``{name, used_share, resets_at, seen_at, origin}`` per window whose
        fields parse: a Claude login's ``5h`` and ``7d``, and a Codex
        login's primary and secondary groups, each named by its window.
    """
    if not isinstance(quota, dict) or not isinstance(quota.get("signals"), dict):
        return []
    seen_at = _moment(quota.get("observed_at")) or ""
    signals = {str(name).lower(): value for name, value in quota["signals"].items()}
    provider = provider.lower()
    windows = []
    if provider == "claude":
        for name in CLAUDE_SIGNAL_WINDOWS:
            prefix = f"{CLAUDE_SIGNAL_PREFIX}{name}-"
            windows.append(
                _window(
                    name,
                    _share(signals.get(prefix + "utilization"), percent=False),
                    signals.get(prefix + "reset"),
                )
            )
    elif provider == "codex":
        for group in CODEX_SIGNAL_GROUPS:
            prefix = f"{CODEX_SIGNAL_PREFIX}{group}-"
            minutes = _whole(signals.get(prefix + "window-minutes"))
            windows.append(
                _window(
                    _window_name(minutes),
                    _share(signals.get(prefix + "used-percent"), percent=True),
                    signals.get(prefix + "reset-at"),
                )
            )
    return [
        {**window, "seen_at": seen_at, "origin": CLIPROXYAPI_WINDOW_SIGNAL}
        for window in windows
        if window is not None
    ]


def read_windows(provider: str, answer) -> list:
    """The windows of a vendor's usage answer.

    Args:
        provider: The login, as the gateway names the account's provider.
        answer: The decoded answer; anything that is not one reads as none.

    Returns:
        ``{name, used_share, resets_at}`` per window whose fields parse.
    """
    if not isinstance(answer, dict):
        return []
    provider = provider.lower()
    windows = []
    if provider == "claude":
        for field_name, name in CLAUDE_READ_WINDOWS.items():
            held = _object(answer.get(field_name))
            windows.append(
                _window(
                    name,
                    _share(held.get("utilization"), percent=True),
                    held.get("resets_at"),
                )
            )
    elif provider == "codex":
        limits = _object(answer.get("rate_limit"))
        for field_name in CODEX_READ_WINDOWS:
            held = _object(limits.get(field_name))
            seconds = _whole(held.get("limit_window_seconds"))
            minutes = round(seconds / 60) if seconds else None
            windows.append(
                _window(
                    _window_name(minutes),
                    _share(held.get("used_percent"), percent=True),
                    held.get("reset_at"),
                )
            )
    elif provider == "kimi":
        usages = _object(answer.get("usages"))
        for field_name, name in KIMI_READ_WINDOWS.items():
            held = _object(usages.get(field_name))
            windows.append(
                _window(
                    name,
                    _share(held.get("used_ratio"), percent=False),
                    held.get("reset_time"),
                )
            )
    elif provider == "antigravity":
        for model, held in sorted(_object(answer.get("models")).items()):
            info = _object(_object(held).get("quotaInfo"))
            remaining = _share(info.get("remainingFraction"), percent=False)
            windows.append(
                _window(
                    str(model),
                    None if remaining is None else round(1 - remaining, SHARE_DIGITS),
                    info.get("resetTime"),
                )
            )
    return [window for window in windows if window is not None]


def merged_windows(signals: list, read: "dict | None") -> list:
    """An account's windows: each named by a signal or a read, the one seen later.

    Args:
        signals: The windows :func:`signal_windows` gives.
        read: The account's stored read, ``{read_at, windows}``; None while
            it has none.

    Returns:
        ``{name, used_share, resets_at, seen_at, origin}`` per window, the
        signals' first and then the read's, each in its own order.
    """
    found = {window["name"]: window for window in signals}
    order = [window["name"] for window in signals]
    if read is not None:
        for window in read.get("windows") or []:
            entry = {
                **window,
                "seen_at": read.get("read_at", ""),
                "origin": CLIPROXYAPI_WINDOW_READ,
            }
            held = found.get(window["name"])
            if held is None:
                order.append(window["name"])
                found[window["name"]] = entry
            elif entry["seen_at"] > held["seen_at"]:
                found[window["name"]] = entry
    return [found[name] for name in order]


def read_quota_store() -> dict:
    """Each account's last quota read.

    Returns:
        Token file to ``{read_at, windows: [{name, used_share,
        resets_at}]}``; empty while none is stored or the file does not
        read.
    """
    try:
        held = json.loads(_quota_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    accounts = held.get("accounts") if isinstance(held, dict) else None
    if not isinstance(accounts, dict):
        return {}
    found = {}
    for name, read in accounts.items():
        if not isinstance(read, dict) or not isinstance(read.get("windows"), list):
            continue
        windows = [
            {
                "name": str(window["name"]),
                "used_share": float(window["used_share"]),
                "resets_at": str(window.get("resets_at", "") or ""),
            }
            for window in read["windows"]
            if isinstance(window, dict)
            and window.get("name")
            and _is_share(window.get("used_share"))
        ]
        found[str(name)] = {"read_at": str(read.get("read_at", "")), "windows": windows}
    return found


def store_quota_read(name: str, windows: list, *, now=None) -> None:
    """Keep one account's read in place of its last.

    Args:
        name: The account's token file.
        windows: The windows read, each ``{name, used_share, resets_at}``.
        now: The moment of the read; None is the real clock.

    Raises:
        OSError: If the store cannot be written.
    """
    moment = now or datetime.now(timezone.utc)
    accounts = read_quota_store()
    accounts[name] = {"read_at": moment.strftime(TIME_FORMAT), "windows": windows}
    _write_quota_store(accounts)


def forget_quota_read(name: str) -> None:
    """Remove one account's read, as its account is removed.

    Args:
        name: The account's token file.

    Raises:
        OSError: If the store cannot be written.
    """
    accounts = read_quota_store()
    if accounts.pop(name, None) is not None:
        _write_quota_store(accounts)


def _write_quota_store(accounts: dict) -> None:
    write_generated(
        _quota_path(),
        json.dumps({"accounts": accounts}, sort_keys=True) + "\n",
        mode=0o600,
    )


def _quota_path():
    # Resolved per call, against the state root as it is right now.
    return constants.UTILS_STATE_ROOT / CLIPROXYAPI_ACCOUNT_QUOTA_RELATIVE


def _window(name, used_share, resets_at) -> "dict | None":
    """One window, None when its name or its share does not parse or a reset it names does not."""
    if not name or used_share is None:
        return None
    reset = _moment(resets_at)
    if reset is None:
        return None
    return {"name": str(name), "used_share": used_share, "resets_at": reset}


def _window_name(minutes) -> str:
    """A window's name by its length in minutes, empty for no length."""
    if not minutes:
        return ""
    return CLIPROXYAPI_WINDOW_NAMES.get(minutes, str(minutes))


def _share(value, *, percent: bool) -> "float | None":
    """A used share from 0 to 1, from a percent or a ratio; None for a value that is not a number of at least 0."""
    number = _number(value)
    if number is None or number < 0:
        return None
    share = number / 100 if percent else number
    return round(min(share, 1.0), SHARE_DIGITS)


def _is_share(value) -> bool:
    """Whether a stored value is a share from 0 to 1."""
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and 0 <= value <= 1
    )


def _number(value) -> "float | None":
    """A finite number from a JSON number or a header's text, None otherwise."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value.strip())
        except ValueError:
            return None
    else:
        return None
    return number if math.isfinite(number) else None


def _whole(value) -> "int | None":
    """A whole number above 0, None otherwise."""
    number = _number(value)
    if number is None or number <= 0 or number != int(number):
        return None
    return int(number)


def _moment(value) -> "str | None":
    """A time as ``YYYY-MM-DDTHH:MM:SSZ``: empty for none, None for one that does not parse.

    A number, or a text of digits, is a Unix time in seconds, or in
    milliseconds when it is that large; any other text is an ISO time.
    """
    if value is None or value == "":
        return ""
    number = _number(value)
    try:
        if number is not None:
            seconds = number / 1000 if number >= MILLISECONDS_FROM else number
            moment = datetime.fromtimestamp(seconds, tz=timezone.utc)
        elif isinstance(value, str):
            moment = _iso(value)
        else:
            return None
    except (OverflowError, OSError, ValueError):
        return None
    return moment.astimezone(timezone.utc).strftime(TIME_FORMAT)


def _iso(text: str) -> datetime:
    """An ISO time, a missing zone read as UTC.

    Raises:
        ValueError: If it is not one.
    """
    moment = datetime.fromisoformat(text.strip())
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def _object(value) -> dict:
    """A JSON object, empty for anything else."""
    return value if isinstance(value, dict) else {}


def _account(entry: dict) -> CliproxyApiAccount:
    """One account row, from the gateway's own record.

    The record also carries the token file's path, its size and a per-slot
    request history; none of that is the panel's business and none of it is
    read here.
    """
    provider = str(entry.get("provider", ""))
    is_unavailable = bool(entry.get("unavailable", False))
    claims = _object(entry.get("id_token"))
    return CliproxyApiAccount(
        name=str(entry.get("name", "")),
        auth_index=str(entry.get("auth_index", "")),
        provider=provider,
        label=str(entry.get("label", "")),
        email=str(entry.get("email", "")),
        account_type=str(entry.get("account_type", "")),
        status=str(entry.get("status", "")),
        status_message=str(entry.get("status_message", "")),
        is_disabled=bool(entry.get("disabled", False)),
        is_unavailable=is_unavailable,
        failed_count=int(entry.get("failed", 0) or 0),
        success_count=int(entry.get("success", 0) or 0),
        created_at=str(entry.get("created_at", "")),
        updated_at=str(entry.get("updated_at", "")),
        next_retry_after=(
            (_moment(entry.get("next_retry_after")) or "") if is_unavailable else ""
        ),
        plan=str(claims.get("plan_type", "") or ""),
        subscription_ends_at=_moment(claims.get("chatgpt_subscription_active_until"))
        or "",
        vendor_account_id=str(claims.get("chatgpt_account_id", "") or ""),
        signal_windows=signal_windows(provider, entry.get("quota")),
    )
