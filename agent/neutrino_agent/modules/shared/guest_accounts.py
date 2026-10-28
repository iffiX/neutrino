"""The guest accounts of a module's Web shares: the three hooks a module answers, and what every such module shares around them.

A module whose manifest names ``web_share: {guest_login: guest_account}``
is sent ``guests`` in its configuration, the account of each live Web
share of its page, each ``{account, email, password, secret}``. Its hooks
answer three calls, :class:`GuestAccountHooks`: ``make_guest`` makes one
account in the app, ``remove_guest`` removes one, and ``sign_in_guest``
signs a visitor in as one. :class:`ShareGuestAccounts` does the rest the
same way for every such module: at each start it makes each guest the
module's record does not hold and removes each one the state no longer
names, keeping the guests made under ``guests`` and each failure under
``guest_failures``; it finds the made guest a visitor's token verifies
under; and it lists every guest for the report's ``details.guests``, each
``{account, code, params}``, ``code`` empty once made.

Not pure: calls the module's hooks.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import threading
from dataclasses import dataclass

from neutrino_agent.exceptions import ModuleApplyError

# The record's fields: the guests made, each failure by account.
GUESTS_FIELD = "guests"
GUEST_FAILURES_FIELD = "guest_failures"
# What a failure keeps of its error's words.
GUEST_DETAIL_CHARS = 200


@dataclass(frozen=True)
class ShareGuest:
    """The guest account of one live Web share of a module's page.

    Attributes:
        account: ``guest-`` and 4 characters, the account's name.
        email: ``<account>@share.neutrino``.
        password: The account's password.
        secret: The secret a visitor's token is signed with.
    """

    account: str
    email: str
    password: str
    secret: str

    @classmethod
    def from_dict(cls, data: dict) -> "ShareGuest | None":
        """Read one guest the state carries.

        Args:
            data: ``{account, email, password, secret}``.

        Returns:
            The guest; None when a field is missing or empty.
        """
        fields = {
            name: str(data.get(name, "") or "")
            for name in ("account", "email", "password", "secret")
        }
        if not all(fields.values()):
            return None
        return cls(**fields)

    def to_dict(self) -> dict:
        return {
            "account": self.account,
            "email": self.email,
            "password": self.password,
            "secret": self.secret,
        }


def share_guests(entries) -> tuple:
    """The guests a configuration's ``guests`` names, each account once.

    Args:
        entries: The list the state carries; anything else names none.

    Returns:
        The guests in order; one missing a field, and a second guest of an
        account, is left out.
    """
    guests = []
    accounts = set()
    for entry in entries if isinstance(entries, list) else ():
        guest = ShareGuest.from_dict(entry) if isinstance(entry, dict) else None
        if guest is None or guest.account in accounts:
            continue
        accounts.add(guest.account)
        guests.append(guest)
    return tuple(guests)


class GuestAccountHooks:
    """The three hooks of a module whose Web shares sign visitors in as accounts of the app."""

    def make_guest(self, guest: ShareGuest, record: dict) -> dict:
        """Make one guest's account in the app.

        Args:
            guest: The guest.
            record: The module's record.

        Returns:
            What the record keeps of the account beside the guest, such as
            the app's id for it.

        Raises:
            ModuleApplyError: The module's code and params when a step
                fails; the next start makes the account again.
        """
        raise NotImplementedError

    def remove_guest(self, made: dict, record: dict) -> bool:
        """Remove one guest's account from the app.

        Args:
            made: The guest as the record keeps it.
            record: The module's record.

        Returns:
            True once the account is gone, removed now or one the app no
            longer holds.

        Raises:
            OSError: When the app does not answer; the next start removes
                it again.
        """
        raise NotImplementedError

    def sign_in_guest(self, request, made: dict, record: dict):
        """The forwarder's answer to a visitor whose token verified under a guest's secret.

        Args:
            request: The request.
            made: The guest as the record keeps it.
            record: The module's record.

        Returns:
            The forwarder's decision, as the module's ``admit`` returns it.
        """
        raise NotImplementedError


class ShareGuestAccounts:
    """The guest accounts of one module's Web shares: made, removed, found and reported."""

    def __init__(self, *, name: str, hooks: GuestAccountHooks, log=print):
        """
        Args:
            name: The module's name, for the log.
            hooks: The module's hooks.
            log: Called with each progress line.
        """
        self._name = name
        self._hooks = hooks
        self._log = log
        self._lock = threading.Lock()
        self._made: tuple = ()

    def take_record(self, record: dict) -> None:
        """Take the guests a record holds made as the ones a visitor signs in as.

        Args:
            record: The module's record.
        """
        made = tuple(made_guests(record).values())
        with self._lock:
            self._made = made

    def forget(self) -> None:
        """Hold no guest made."""
        with self._lock:
            self._made = ()

    def is_settled(self, guests: tuple, record: dict) -> bool:
        """Whether the record holds every guest the state names made, and no other.

        Args:
            guests: The guests the state names.
            record: The module's record.
        """
        made = made_guests(record)
        return set(made) == {guest.account for guest in guests}

    def settle(self, guests: tuple, record: dict) -> dict:
        """Make each guest the record does not hold, and remove each one the state no longer names.

        Args:
            guests: The guests the state names.
            record: The module's record.

        Returns:
            The record's ``guests`` and ``guest_failures``: each guest made
            as ``make_guest`` kept it beside the guest, and each failure of
            a guest still owed as ``{code, params}``. The guests made are
            the ones a visitor signs in as from then on.
        """
        wanted = {guest.account: guest for guest in guests}
        made = made_guests(record)
        for account, guest in wanted.items():
            if account in made:
                made[account]["secret"] = guest.secret
        held = record.get(GUEST_FAILURES_FIELD)
        failures = {
            account: dict(failure)
            for account, failure in (held.items() if isinstance(held, dict) else ())
            if account in wanted and account not in made and isinstance(failure, dict)
        }
        for account, guest in wanted.items():
            if account in made:
                continue
            try:
                kept = self._hooks.make_guest(guest, record)
            except ModuleApplyError as error:
                failures[account] = {"code": error.code, "params": dict(error.params)}
                self._log(f"{self._name}: {account}: {error.code} {error.params}")
                continue
            made[account] = {**dict(kept or {}), **guest.to_dict()}
            failures.pop(account, None)
            self._log(f"{self._name}: the guest {account} is made")
        for account in [account for account in made if account not in wanted]:
            try:
                is_gone = self._hooks.remove_guest(made[account], record)
            except OSError as error:
                is_gone = False
                self._log(f"{self._name}: {account} stays: {error}")
            if is_gone:
                del made[account]
                self._log(f"{self._name}: the guest {account} is removed")
        settled = {GUESTS_FIELD: list(made.values()), GUEST_FAILURES_FIELD: failures}
        self.take_record(settled)
        return settled

    def admit(self, request, record: dict):
        """The decision for a token under a made guest's secret, the token spent.

        Args:
            request: The request, its token not yet spent.
            record: The module's record.

        Returns:
            What ``sign_in_guest`` decides for the guest the token verifies
            under; None when it verifies under no made guest's secret.
        """
        with self._lock:
            made = self._made
        for guest in made:
            secret = str(guest.get("secret", "") or "")
            if secret and request.take_token(secret=secret):
                return self._hooks.sign_in_guest(request, guest, record)
        return None

    def details(self, record: dict) -> list:
        """Every guest the record holds, for the report's ``details.guests``.

        Args:
            record: The module's record.

        Returns:
            ``[{account, code, params}]``: each guest made with an empty
            code, then each failure with its code and params.
        """
        guests = [
            {"account": account, "code": "", "params": {}}
            for account in made_guests(record)
        ]
        held = record.get(GUEST_FAILURES_FIELD)
        for account, failure in held.items() if isinstance(held, dict) else ():
            if not isinstance(failure, dict) or not failure.get("code"):
                continue
            params = failure.get("params")
            guests.append(
                {
                    "account": str(account),
                    "code": str(failure["code"]),
                    "params": dict(params) if isinstance(params, dict) else {},
                }
            )
        return guests


def made_guests(record: dict) -> dict:
    """The guests a record holds made, by account, each a copy."""
    made = {}
    for held in record.get(GUESTS_FIELD) or []:
        if isinstance(held, dict) and held.get("account"):
            made[str(held["account"])] = dict(held)
    return made


def guest_failed(code: str, step: str, error: BaseException) -> ModuleApplyError:
    """A guest's failure at one step, ``<code> {step, detail}``, its detail the error's words."""
    return ModuleApplyError(
        code, {"step": step, "detail": str(error)[:GUEST_DETAIL_CHARS]}
    )
