"""The Web shares: one app's ``web`` entry offered to anyone who holds a link.

A share is made on the Clients page and lasts until its ``expires_at`` or
until it is revoked. The hub keeps the SHA-256 of its ticket alone, its
ufrag in the clear and its pwd sealed under the vault's data key, and for an
app whose manifest names ``guest_login: guest_account`` the facts of the
share's guest account, its password and token secret sealed the same way
(protocol.md, "Web shares"). The link is composed once, at the share's
making, and the hub cannot read it back.

Not pure: reads and writes ``config/clients/web_shares.json``.
"""

import base64
import hashlib
import hmac
import json
import secrets
import time
import uuid
from dataclasses import dataclass, field

from neutrino_hub.exceptions import VaultLockedError
from neutrino_hub.modules.clients.constants import (
    WEB_SHARE_DAY_S,
    WEB_SHARE_GUEST_ALPHABET,
    WEB_SHARE_GUEST_CHARS,
    WEB_SHARE_GUEST_DOMAIN,
    WEB_SHARE_GUEST_PASSWORD_AAD,
    WEB_SHARE_GUEST_PASSWORD_BYTES,
    WEB_SHARE_GUEST_PREFIX,
    WEB_SHARE_GUEST_SECRET_AAD,
    WEB_SHARE_GUEST_SECRET_BYTES,
    WEB_SHARE_LINK_VERSION,
    WEB_SHARE_PAGE_PATH,
    WEB_SHARE_PWD_AAD,
    WEB_SHARE_PWD_BYTES,
    WEB_SHARE_STATE_ACTIVE,
    WEB_SHARE_STATE_FAILED,
    WEB_SHARE_STATE_PREPARING,
    WEB_SHARE_STATE_UNAVAILABLE,
    WEB_SHARE_TICKET_BYTES,
    WEB_SHARE_UFRAG_BYTES,
    WEB_SHARES_CONFIG_PATH,
)
from neutrino_hub.modules.credentials.vault import seal_bytes, unseal_bytes
from neutrino_hub.utils.json_file import CONFIG_WRITE_LOCK, read_config, write_config


@dataclass(frozen=True)
class WebShareGuest:
    """The account a share's visitors are signed in to the app as.

    Attributes:
        account: ``guest-`` and four characters.
        email: ``<account>@share.neutrino``.
        password_sealed: Its password, sealed.
        secret_sealed: The secret a visitor's token is minted with, sealed.
    """

    account: str
    email: str
    password_sealed: dict
    secret_sealed: dict

    @classmethod
    def from_dict(cls, data) -> "WebShareGuest | None":
        """Build from the stored record; None for a record that is not one."""
        if not isinstance(data, dict) or not data.get("account"):
            return None
        return cls(
            account=str(data["account"]),
            email=str(data.get("email", "") or ""),
            password_sealed=dict(data.get("password_sealed") or {}),
            secret_sealed=dict(data.get("secret_sealed") or {}),
        )

    def to_dict(self) -> dict:
        """Serialize to the stored shape."""
        return {
            "account": self.account,
            "email": self.email,
            "password_sealed": dict(self.password_sealed),
            "secret_sealed": dict(self.secret_sealed),
        }

    def opened(self) -> dict:
        """The guest as a machine's state takes it.

        Returns:
            ``{account, email, password, secret}``.

        Raises:
            VaultLockedError: While the vault is locked or a seal does not
                open under this box's data key.
        """
        return {
            "account": self.account,
            "email": self.email,
            "password": _opened(self.password_sealed, WEB_SHARE_GUEST_PASSWORD_AAD),
            "secret": _opened(self.secret_sealed, WEB_SHARE_GUEST_SECRET_AAD),
        }


@dataclass(frozen=True)
class WebShare:
    """One Web share as stored.

    Attributes:
        id: A uuid4 hex.
        name: What the person called it.
        app_id: The app its entry belongs to.
        app_title: The app's title when the share was made.
        entry_id: The ``web`` entry it offers.
        device_id: The machine providing the entry; empty for a declared
            app on a host no machine is.
        module: The module whose page the entry is; empty for a declared
            app or a container.
        created_at: Unix seconds.
        expires_at: Unix seconds; None for a share that lasts until it is
            revoked.
        ticket_sha256: The SHA-256 hex of its ticket.
        ufrag: Its ICE ufrag, 24 hex characters.
        pwd_sealed: Its ICE pwd, sealed.
        guest: Its guest account, None for an entry with no guest account.
    """

    id: str
    name: str
    app_id: str
    app_title: str
    entry_id: str
    device_id: str
    module: str
    created_at: int
    expires_at: "int | None"
    ticket_sha256: str
    ufrag: str
    pwd_sealed: dict
    guest: "WebShareGuest | None" = field(default=None)

    @classmethod
    def from_dict(cls, data) -> "WebShare | None":
        """Build from the stored record; None for a record that is not one."""
        if not isinstance(data, dict) or not data.get("id") or not data.get("ufrag"):
            return None
        expires_at = data.get("expires_at")
        return cls(
            id=str(data["id"]),
            name=str(data.get("name", "") or ""),
            app_id=str(data.get("app_id", "") or ""),
            app_title=str(data.get("app_title", "") or ""),
            entry_id=str(data.get("entry_id", "") or ""),
            device_id=str(data.get("device_id", "") or ""),
            module=str(data.get("module", "") or ""),
            created_at=int(data.get("created_at") or 0),
            expires_at=int(expires_at) if isinstance(expires_at, int) else None,
            ticket_sha256=str(data.get("ticket_sha256", "") or ""),
            ufrag=str(data["ufrag"]),
            pwd_sealed=dict(data.get("pwd_sealed") or {}),
            guest=WebShareGuest.from_dict(data.get("guest")),
        )

    def to_dict(self) -> dict:
        """Serialize to the stored shape."""
        stored = {
            "id": self.id,
            "name": self.name,
            "app_id": self.app_id,
            "app_title": self.app_title,
            "entry_id": self.entry_id,
            "device_id": self.device_id,
            "module": self.module,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "ticket_sha256": self.ticket_sha256,
            "ufrag": self.ufrag,
            "pwd_sealed": dict(self.pwd_sealed),
        }
        if self.guest is not None:
            stored["guest"] = self.guest.to_dict()
        return stored

    def is_expired(self, now: float) -> bool:
        """Whether its ``expires_at`` has passed at ``now``, in Unix seconds."""
        return self.expires_at is not None and self.expires_at <= now

    def is_ticket(self, ticket: str) -> bool:
        """Whether a ticket is this share's, compared in constant time."""
        digest = hashlib.sha256(ticket.encode("utf-8")).hexdigest()
        return hmac.compare_digest(digest, self.ticket_sha256)

    def pwd(self) -> str:
        """Its ICE pwd, opened.

        Raises:
            VaultLockedError: While the vault is locked or the seal does not
                open under this box's data key.
        """
        return _opened(self.pwd_sealed, WEB_SHARE_PWD_AAD)


@dataclass(frozen=True)
class WebShareSecrets:
    """What a new share's link carries and the hub keeps no copy of.

    Attributes:
        ticket: The ticket, as ``secrets.token_urlsafe`` gives it.
        pwd: The ICE pwd, 32 hex characters.
    """

    ticket: str
    pwd: str


class WebShareRegistry:
    """The stored Web shares, newest last in the file."""

    def all(self) -> list:
        """Every stored share, in the order made.

        Returns:
            The :class:`WebShare` records.
        """
        return self._read()

    def get(self, share_id: str) -> "WebShare | None":
        """The share with an id, or None."""
        for share in self._read():
            if share.id == share_id:
                return share
        return None

    def find_by_ufrag(self, ufrag: str) -> "WebShare | None":
        """The share whose ufrag is ``ufrag``, or None."""
        for share in self._read():
            if share.ufrag == ufrag:
                return share
        return None

    def add(self, share: WebShare) -> None:
        """Store a new share.

        Raises:
            OSError: When the file cannot be written.
        """
        with CONFIG_WRITE_LOCK:
            shares = self._read()
            shares.append(share)
            self._write(shares)

    def remove_where(self, predicate) -> list:
        """Remove every share a predicate picks.

        Args:
            predicate: Called with each :class:`WebShare`; True removes it.

        Returns:
            The removed shares.

        Raises:
            OSError: When the file cannot be written.
        """
        with CONFIG_WRITE_LOCK:
            shares = self._read()
            removed = [share for share in shares if predicate(share)]
            if removed:
                self._write([share for share in shares if share not in removed])
        return removed

    def _read(self) -> list:
        try:
            stored = read_config(WEB_SHARES_CONFIG_PATH)
        except FileNotFoundError:
            return []
        shares = []
        for data in stored.get("shares") or []:
            share = WebShare.from_dict(data)
            if share is not None:
                shares.append(share)
        return shares

    def _write(self, shares: list) -> None:
        write_config(
            WEB_SHARES_CONFIG_PATH, {"shares": [share.to_dict() for share in shares]}
        )


def make_share(
    *,
    name: str,
    app_id: str,
    app_title: str,
    entry_id: str,
    device_id: str,
    module: str,
    days: "int | None",
    taken_accounts,
    is_guest: bool,
    now: "float | None" = None,
) -> tuple:
    """A new share with its secrets made and sealed.

    Args:
        name: What the person called it.
        app_id: The app its entry belongs to.
        app_title: The app's title now.
        entry_id: The ``web`` entry it offers.
        device_id: The machine providing the entry, empty for none.
        module: The module whose page the entry is, empty for none.
        days: Its life in days; None lasts until it is revoked.
        taken_accounts: The guest accounts the machine's live shares hold.
        is_guest: Whether the share has a guest account.
        now: Unix seconds; None reads the clock.

    Returns:
        ``(share, secrets)``: the :class:`WebShare` to store and the
        :class:`WebShareSecrets` its link carries.

    Raises:
        VaultLockedError: While the vault is locked.
    """
    moment = int(time.time() if now is None else now)
    ticket = secrets.token_urlsafe(WEB_SHARE_TICKET_BYTES)
    pwd = secrets.token_hex(WEB_SHARE_PWD_BYTES)
    guest = None
    if is_guest:
        account = _new_guest_account(set(taken_accounts))
        guest = WebShareGuest(
            account=account,
            email=f"{account}@{WEB_SHARE_GUEST_DOMAIN}",
            password_sealed=_sealed(
                secrets.token_urlsafe(WEB_SHARE_GUEST_PASSWORD_BYTES),
                WEB_SHARE_GUEST_PASSWORD_AAD,
            ),
            secret_sealed=_sealed(
                secrets.token_urlsafe(WEB_SHARE_GUEST_SECRET_BYTES),
                WEB_SHARE_GUEST_SECRET_AAD,
            ),
        )
    share = WebShare(
        id=uuid.uuid4().hex,
        name=name,
        app_id=app_id,
        app_title=app_title,
        entry_id=entry_id,
        device_id=device_id,
        module=module,
        created_at=moment,
        expires_at=None if days is None else moment + days * WEB_SHARE_DAY_S,
        ticket_sha256=hashlib.sha256(ticket.encode("utf-8")).hexdigest(),
        ufrag=secrets.token_hex(WEB_SHARE_UFRAG_BYTES),
        pwd_sealed=_sealed(pwd, WEB_SHARE_PWD_AAD),
        guest=guest,
    )
    return share, WebShareSecrets(ticket=ticket, pwd=pwd)


def share_link(
    site: str,
    *,
    ip: str,
    port: int,
    fingerprint: str,
    share: WebShare,
    share_secrets: WebShareSecrets,
    title: str,
    path: str = "",
) -> str:
    """The link a share's visitors open.

    Args:
        site: The ``https://`` address of the page's site.
        ip: The hub's IP address the page dials.
        port: The agent port at that address.
        fingerprint: The DTLS certificate's fingerprint.
        share: The share.
        share_secrets: Its ticket and pwd.
        title: The app's title.
        path: The path the app opens at, empty for none.

    Returns:
        ``<site>/__neutrino/#<base64url>`` of the JSON the page reads
        (transport.md, "The links").
    """
    app = {"entry": share.entry_id, "title": title}
    if path:
        app["path"] = path
    facts = {
        "v": WEB_SHARE_LINK_VERSION,
        "hub": {"ip": ip, "port": int(port), "fp": fingerprint},
        "ice": {"ufrag": share.ufrag, "pwd": share_secrets.pwd},
        "ticket": share_secrets.ticket,
        "app": app,
    }
    encoded = json.dumps(facts, separators=(",", ":")).encode("utf-8")
    fragment = base64.urlsafe_b64encode(encoded).decode("ascii").rstrip("=")
    return f"{site.rstrip('/')}{WEB_SHARE_PAGE_PATH}#{fragment}"


def live_shares(now: "float | None" = None) -> list:
    """The stored shares that have not expired.

    Args:
        now: Unix seconds; None reads the clock.

    Returns:
        The :class:`WebShare` records.
    """
    moment = time.time() if now is None else now
    return [share for share in WebShareRegistry().all() if not share.is_expired(moment)]


def live_pairs(now: "float | None" = None) -> list:
    """The ICE pair of every live share, as ``shares_set`` sends them.

    A share whose pwd does not open is left out, so the guest door stays
    shut to it while the vault is locked.

    Args:
        now: Unix seconds; None reads the clock.

    Returns:
        ``[{ufrag, pwd}]``.
    """
    pairs = []
    for share in live_shares(now):
        try:
            pairs.append({"ufrag": share.ufrag, "pwd": share.pwd()})
        except VaultLockedError:
            continue
    return pairs


def guest_accounts(device_id: str, app_id: str) -> list:
    """The guest accounts of one app's live shares, opened for its state.

    Args:
        device_id: The machine the app runs on.
        app_id: The app.

    Returns:
        ``[{account, email, password, secret}]`` in the order the shares
        were made; empty while the vault is locked.
    """
    guests = []
    for share in live_shares():
        if share.guest is None or share.app_id != app_id:
            continue
        if share.device_id and share.device_id != device_id:
            continue
        try:
            guests.append(share.guest.opened())
        except VaultLockedError:
            return []
    return guests


def taken_guest_accounts(device_id: str) -> set:
    """The guest accounts one machine's stored shares hold."""
    return {
        share.guest.account
        for share in WebShareRegistry().all()
        if share.guest is not None and share.device_id == device_id
    }


def share_state(
    share: WebShare, *, is_published: bool, is_online: bool, guests_reported: list
) -> tuple:
    """Where a share stands now.

    Args:
        share: The share.
        is_published: Whether its entry is published now.
        is_online: Whether its machine has a session; True for an entry no
            machine provides.
        guests_reported: The machine's last ``details.guests`` of the
            share's module, ``[{account, code, params}]``.

    Returns:
        ``(state, code, params)``: ``unavailable`` while its entry is not
        published or its machine has no session; for a share with a guest,
        ``failed`` with the guest's code while the machine reports one and
        ``preparing`` until the machine reports the guest made; else
        ``active``.
    """
    if not is_online or not is_published:
        return WEB_SHARE_STATE_UNAVAILABLE, "", {}
    if share.guest is None:
        return WEB_SHARE_STATE_ACTIVE, "", {}
    for reported in guests_reported:
        if not isinstance(reported, dict):
            continue
        if reported.get("account") != share.guest.account:
            continue
        code = str(reported.get("code", "") or "")
        if code:
            params = reported.get("params")
            return (
                WEB_SHARE_STATE_FAILED,
                code,
                dict(params) if isinstance(params, dict) else {},
            )
        return WEB_SHARE_STATE_ACTIVE, "", {}
    return WEB_SHARE_STATE_PREPARING, "", {}


def guest_secret(share: WebShare) -> str:
    """The token secret of a share's guest, opened; empty for none.

    Raises:
        VaultLockedError: While the vault is locked or the seal does not
            open under this box's data key.
    """
    if share.guest is None:
        return ""
    return _opened(share.guest.secret_sealed, WEB_SHARE_GUEST_SECRET_AAD)


def _new_guest_account(taken: set) -> str:
    """A guest account no live share of the machine holds."""
    while True:
        suffix = "".join(
            secrets.choice(WEB_SHARE_GUEST_ALPHABET)
            for _ in range(WEB_SHARE_GUEST_CHARS)
        )
        account = WEB_SHARE_GUEST_PREFIX + suffix
        if account not in taken:
            return account


def _sealed(text: str, aad: bytes) -> dict:
    """A string sealed under the vault's data key.

    Raises:
        VaultLockedError: While the vault is locked.
    """
    try:
        return seal_bytes(text.encode("utf-8"), aad)
    except ValueError as error:
        raise VaultLockedError() from error


def _opened(sealed: dict, aad: bytes) -> str:
    """A sealed string opened.

    Raises:
        VaultLockedError: While the vault is locked or the seal does not
            open under this box's data key.
    """
    if not sealed:
        raise VaultLockedError()
    try:
        return unseal_bytes(sealed, aad).decode("utf-8")
    except ValueError as error:
        raise VaultLockedError() from error
