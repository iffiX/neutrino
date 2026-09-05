"""The AI service reconcile: grant activates, deactivation uses what was
granted, and the store never holds a key."""

import pytest

from neutrino_agent.services.ai import AiServiceReconciler
from neutrino_agent.services.store import MachineServiceStore
from neutrino_agent.switcher import NoTargetUserError

PLATFORM_TUPLE = {"os": "linux", "family": "debian", "arch": "amd64"}
SWITCHER_BLOCK = {"github_repo": "x/y", "binary": "cc-switch"}
OFFER = {
    "kind": "ai",
    "title": "AI tools",
    "platforms": {"linux-amd64": {"switcher": SWITCHER_BLOCK}},
}
CREDS = {
    "base_url": "http://hub:8080",
    "api_key": "key-1",
    "model": "m1",
}  # scan: allow


class FakeSwitcher:
    def __init__(self):
        self.active = {}
        self.has_cli = True
        self.calls = []
        self.activate_error = None

    def is_installed(self):
        return self.has_cli

    def find_cli(self):
        return "/usr/local/bin/cc-switch" if self.has_cli else None

    def install_cli(self, entry):
        self.calls.append(("install", entry))
        self.has_cli = True

    def is_active(self, *, run_as, base_url, api_key="", model=""):
        return self.active.get(run_as) == (base_url, api_key, model)

    def activate(self, *, base_url, api_key, run_as, model=""):
        if self.activate_error is not None:
            raise self.activate_error
        self.calls.append(("activate", run_as, base_url, api_key, model))
        self.active[run_as] = (base_url, api_key, model)
        return "claude"

    def deactivate(self, *, run_as, base_url=""):
        self.calls.append(("deactivate", run_as, base_url))
        self.active.pop(run_as, None)
        return "claude → as it was"


def discard(message: str) -> None:
    """Swallow the log lines."""


@pytest.fixture
def subject(tmp_path):
    store = MachineServiceStore(path=str(tmp_path / "services.json"))
    fake = FakeSwitcher()
    reconciler = AiServiceReconciler(
        store=store,
        platform_tuple=PLATFORM_TUPLE,
        log=discard,
        switcher_module=fake,
    )
    return reconciler, store, fake


def feed(reconciler, *, offer=OFFER, accounts=("alice",), credentials=None):
    """Seed the inputs and reconcile synchronously."""
    with reconciler._lock:
        reconciler._offer = dict(offer)
        reconciler._accounts = list(accounts)
        reconciler._credentials = dict(credentials or {})
    reconciler._reconcile()


def test_a_grant_activates_and_records_the_endpoint(subject):
    reconciler, store, fake = subject
    store.set_ai_target("alice", is_activated=True)

    feed(reconciler, credentials={"alice": CREDS})

    assert ("activate", "alice", "http://hub:8080", "key-1", "m1") in fake.calls
    assert store.ai_granted() == {
        "alice": {"base_url": "http://hub:8080", "model": "m1"}
    }
    row = reconciler.report()["alice"]
    assert row["is_active"] is True and row["code"] == ""


def test_a_missing_cli_is_installed_from_the_offer(subject):
    reconciler, store, fake = subject
    fake.has_cli = False
    store.set_ai_target("alice", is_activated=True)

    feed(reconciler, credentials={"alice": CREDS})

    assert ("install", SWITCHER_BLOCK) in fake.calls
    assert reconciler.report()["alice"]["is_active"] is True


def test_deactivation_uses_the_last_granted_endpoint_and_clears_it(subject):
    reconciler, store, fake = subject
    store.set_ai_target("alice", is_activated=False)
    store.set_ai_granted("alice", {"base_url": "http://old:8080", "model": "m0"})

    feed(reconciler, credentials={})

    assert ("deactivate", "alice", "http://old:8080") in fake.calls
    assert store.ai_granted() == {}
    assert reconciler.report()["alice"]["is_active"] is False


def test_a_target_without_a_grant_reports_no_endpoint(subject):
    reconciler, store, fake = subject
    store.set_ai_target("alice", is_activated=True)

    feed(reconciler, credentials={})

    assert reconciler.report()["alice"]["code"] == "no_endpoint"
    assert not any(call[0] == "activate" for call in fake.calls)


def test_an_account_the_platform_does_not_report_fails_typed(subject):
    reconciler, store, fake = subject
    store.set_ai_target("ghost", is_activated=True)
    fake.activate_error = NoTargetUserError("no target account 'ghost'")

    feed(reconciler, accounts=("alice",), credentials={"ghost": CREDS})

    assert reconciler.report()["ghost"]["code"] == "no_target_user"


def test_no_offer_reconciles_nothing(subject):
    reconciler, store, fake = subject
    store.set_ai_target("alice", is_activated=True)

    feed(reconciler, offer={}, credentials={"alice": CREDS})

    assert fake.calls == []
    assert reconciler.report() == {}


def test_an_already_pointed_account_is_left_alone(subject):
    reconciler, store, fake = subject
    store.set_ai_target("alice", is_activated=True)
    fake.active["alice"] = ("http://hub:8080", "key-1", "m1")

    feed(reconciler, credentials={"alice": CREDS})

    assert not any(call[0] == "activate" for call in fake.calls)
    assert reconciler.report()["alice"]["is_active"] is True
