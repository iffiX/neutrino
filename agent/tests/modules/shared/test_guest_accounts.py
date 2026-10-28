"""The guest accounts of a module's Web shares, with the module's three hooks replaced.

What these pin: the guests a configuration names are read whole, each
account once; a settle makes each guest the record does not hold, keeps
what ``make_guest`` returns beside it, and removes each one the state no
longer names, a guest whose removal the app does not answer staying; a
failed make is kept as ``{code, params}``, reported, and made again at the
next settle, and a failure of a guest no longer named is dropped; a token
under a made guest's secret is handed to ``sign_in_guest`` with that guest,
spent, and a token under no made guest's secret is the caller's; and the
report lists each guest made, then each failure.
"""

import pytest

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.shared.guest_accounts import (
    GuestAccountHooks,
    ShareGuest,
    ShareGuestAccounts,
    guest_failed,
    share_guests,
)

FIRST = {
    "account": "guest-k3f9",
    "email": "guest-k3f9@share.neutrino",
    "password": "p1",
    "secret": "s1",
}
SECOND = {
    "account": "guest-a2b7",
    "email": "guest-a2b7@share.neutrino",
    "password": "p2",
    "secret": "s2",
}


class FakeHooks(GuestAccountHooks):
    def __init__(self):
        self.made: list = []
        self.removed: list = []
        self.signed_in: list = []
        self.failing: dict = {}
        self.unanswered: set = set()

    def make_guest(self, guest, record):
        if guest.account in self.failing:
            raise ModuleApplyError("demo_guest_failed", self.failing[guest.account])
        self.made.append(guest.account)
        return {"user_id": f"id-{guest.account}"}

    def remove_guest(self, made, record):
        if made["account"] in self.unanswered:
            raise ConnectionRefusedError("down")
        self.removed.append(made["user_id"])
        return True

    def sign_in_guest(self, request, made, record):
        self.signed_in.append(made["account"])
        return "signed in"


class FakeRequest:
    def __init__(self, secret: str):
        self.secret = secret
        self.tried: list = []

    def take_token(self, *, secret=None):
        self.tried.append(secret)
        return secret == self.secret


@pytest.fixture
def hooks():
    return FakeHooks()


@pytest.fixture
def accounts(hooks):
    return ShareGuestAccounts(name="demo", hooks=hooks, log=lambda line: None)


def test_the_guests_are_read_whole_and_each_account_once():
    guests = share_guests(
        [FIRST, {**FIRST, "password": "other"}, {**SECOND, "secret": ""}, "x"]
    )

    assert guests == (ShareGuest(**FIRST),)
    assert share_guests(None) == ()


def test_a_settle_makes_each_owed_guest_and_keeps_what_the_hook_returns(
    accounts, hooks
):
    guests = share_guests([FIRST, SECOND])

    settled = accounts.settle(guests, {})

    assert hooks.made == ["guest-k3f9", "guest-a2b7"]
    assert settled == {
        "guests": [
            {**FIRST, "user_id": "id-guest-k3f9"},
            {**SECOND, "user_id": "id-guest-a2b7"},
        ],
        "guest_failures": {},
    }
    assert accounts.is_settled(guests, settled)
    assert accounts.details(settled) == [
        {"account": "guest-k3f9", "code": "", "params": {}},
        {"account": "guest-a2b7", "code": "", "params": {}},
    ]


def test_a_guest_the_record_holds_is_not_made_again(accounts, hooks):
    record = accounts.settle(share_guests([FIRST]), {})
    hooks.made.clear()

    again = accounts.settle(share_guests([FIRST]), record)

    assert hooks.made == []
    assert again == record


def test_a_guest_the_state_drops_is_removed_and_one_unanswered_stays(accounts, hooks):
    record = accounts.settle(share_guests([FIRST, SECOND]), {})
    hooks.unanswered.add("guest-a2b7")

    settled = accounts.settle((), record)

    assert hooks.removed == ["id-guest-k3f9"]
    assert [made["account"] for made in settled["guests"]] == ["guest-a2b7"]
    assert not accounts.is_settled((), settled)


def test_a_failed_make_is_reported_and_made_again_at_the_next_settle(accounts, hooks):
    guests = share_guests([FIRST])
    hooks.failing["guest-k3f9"] = {"step": "register", "detail": "500"}

    failed = accounts.settle(guests, {})

    assert failed["guests"] == []
    assert accounts.details(failed) == [
        {
            "account": "guest-k3f9",
            "code": "demo_guest_failed",
            "params": {"step": "register", "detail": "500"},
        }
    ]
    hooks.failing.clear()

    settled = accounts.settle(guests, failed)

    assert settled["guest_failures"] == {}
    assert accounts.details(settled)[0]["code"] == ""


def test_the_failure_of_a_guest_no_longer_named_is_dropped(accounts, hooks):
    hooks.failing["guest-k3f9"] = {"step": "register", "detail": "500"}
    failed = accounts.settle(share_guests([FIRST]), {})

    settled = accounts.settle((), failed)

    assert settled == {"guests": [], "guest_failures": {}}


def test_a_token_under_a_made_guest_s_secret_signs_in_as_that_guest(accounts, hooks):
    accounts.settle(share_guests([FIRST, SECOND]), {})

    decision = accounts.admit(FakeRequest("s2"), {})

    assert decision == "signed in"
    assert hooks.signed_in == ["guest-a2b7"]


def test_a_token_under_no_made_guest_s_secret_is_the_caller_s(accounts, hooks):
    hooks.failing["guest-a2b7"] = {"step": "register", "detail": "500"}
    accounts.settle(share_guests([FIRST, SECOND]), {})

    assert accounts.admit(FakeRequest("s2"), {}) is None
    assert accounts.admit(FakeRequest("other"), {}) is None
    assert hooks.signed_in == []


def test_the_guests_a_record_holds_are_taken_back_and_forgotten(accounts, hooks):
    record = ShareGuestAccounts(name="demo", hooks=hooks, log=lambda line: None).settle(
        share_guests([FIRST]), {}
    )

    accounts.take_record(record)
    assert accounts.admit(FakeRequest("s1"), record) == "signed in"
    accounts.forget()
    assert accounts.admit(FakeRequest("s1"), record) is None


def test_a_guest_failure_is_a_module_apply_error_with_its_step():
    error = guest_failed("demo_guest_failed", "register", ConnectionError("x" * 300))

    assert isinstance(error, ModuleApplyError)
    assert error.code == "demo_guest_failed"
    assert error.params == {"step": "register", "detail": "x" * 200}
