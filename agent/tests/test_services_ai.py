"""The AI service: staged apply through the handler, reconcile on the grant.

The staged choices are what each tool is pointed with; the grant's model is
only the prefill default for a slot nobody has chosen. The no_target_user
guard is symmetric, and the store never holds a key.
"""

import pytest

from neutrino_agent.services.ai import (
    AiServiceHandler,
    AiServiceReconciler,
    clean_tool_configs,
)
from neutrino_agent.services.store import MachineServiceStore
from neutrino_agent.services.switcher import NoTargetUserError

PLATFORM_TUPLE = {"os": "linux", "family": "debian", "arch": "amd64"}
ENTRY = {
    "id": "ai",
    "type": "ai",
    "title": "AI tools",
    "payload": {
        "endpoint": "http://hub:8080",
        "protocol": "anthropic",
        "models": ["m1", "m2", "m3"],
    },
    "is_healthy": True,
    "source": "module",
    "description": "",
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

    def activate(self, *, base_url, api_key, run_as, tool_configs=None):
        if self.activate_error is not None:
            raise self.activate_error
        self.calls.append(("activate", run_as, base_url, api_key, tool_configs))
        default = (tool_configs or {}).get("claude", {}).get("default", "")
        self.active[run_as] = (base_url, api_key, default)
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


def feed(reconciler, *, entry=ENTRY, accounts=("alice",), credentials=None):
    """Seed the inputs and reconcile synchronously."""
    with reconciler._lock:
        reconciler._entry = dict(entry)
        reconciler._accounts = list(accounts)
        reconciler._credentials = dict(credentials or {})
    reconciler._reconcile()


def test_a_grant_activates_with_the_prefill_default(subject):
    reconciler, store, fake = subject
    store.set_ai_target("alice", is_activated=True)

    feed(reconciler, credentials={"alice": CREDS})

    kind, run_as, base_url, api_key, tool_configs = fake.calls[-1]
    assert (kind, run_as, base_url, api_key) == (
        "activate",
        "alice",
        "http://hub:8080",
        "key-1",
    )
    # Every unchosen Claude slot falls back to the grant's model.
    assert tool_configs["claude"] == {
        "default": "m1",
        "opus": "m1",
        "sonnet": "m1",
        "haiku": "m1",
    }
    assert store.ai_granted() == {
        "alice": {"base_url": "http://hub:8080", "model": "m1"}
    }
    row = reconciler.report()["alice"]
    assert row["is_active"] is True and row["code"] == ""


def test_staged_choices_beat_the_grants_model(subject):
    reconciler, store, fake = subject
    store.set_ai_target("alice", is_activated=True)
    store.set_ai_tool_configs(
        {
            "claude": {"default": "m2", "haiku": "m3"},
            "codex": {"model": "m2", "model_reasoning_effort": "high"},
            "gemini": {"model": "m3"},
        }
    )

    feed(reconciler, credentials={"alice": CREDS})

    tool_configs = fake.calls[-1][4]
    assert tool_configs["claude"] == {
        "default": "m2",
        "opus": "m1",
        "sonnet": "m1",
        "haiku": "m3",
    }
    assert tool_configs["codex"] == {"model": "m2", "model_reasoning_effort": "high"}
    assert tool_configs["gemini"] == {"model": "m3"}
    assert store.ai_granted()["alice"]["model"] == "m2"


def test_a_missing_cli_is_installed_from_the_release_table(subject):
    reconciler, store, fake = subject
    fake.has_cli = False
    store.set_ai_target("alice", is_activated=True)

    feed(reconciler, credentials={"alice": CREDS})

    installs = [call for call in fake.calls if call[0] == "install"]
    assert len(installs) == 1
    assert installs[0][1].get("binary") == "cc-switch"
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


def test_no_entry_reconciles_nothing(subject):
    reconciler, store, fake = subject
    store.set_ai_target("alice", is_activated=True)

    feed(reconciler, entry={}, credentials={"alice": CREDS})

    assert fake.calls == []
    assert reconciler.report() == {}


def test_an_already_pointed_account_is_left_alone(subject):
    reconciler, store, fake = subject
    store.set_ai_target("alice", is_activated=True)
    fake.active["alice"] = ("http://hub:8080", "key-1", "m1")

    feed(reconciler, credentials={"alice": CREDS})

    assert not any(call[0] == "activate" for call in fake.calls)
    assert reconciler.report()["alice"]["is_active"] is True


def test_a_changed_choice_re_applies(subject):
    reconciler, store, fake = subject
    store.set_ai_target("alice", is_activated=True)
    fake.active["alice"] = ("http://hub:8080", "key-1", "m1")
    store.set_ai_tool_configs({"claude": {"default": "m2"}})

    feed(reconciler, credentials={"alice": CREDS})

    assert any(call[0] == "activate" for call in fake.calls)


# --- the handler: one staged apply committed as one step ---


def handler_for(store, accounts=("alice", "bob")):
    beats = []
    handler = AiServiceHandler(
        store=store, accounts=lambda: list(accounts), on_change=lambda: beats.append(1)
    )
    return handler, beats


def test_apply_commits_targets_and_tool_configs(tmp_path):
    store = MachineServiceStore(path=str(tmp_path / "services.json"))
    handler, beats = handler_for(store)

    outcome = handler.act(
        entries=[ENTRY],
        account="root",
        is_privileged=True,
        body={
            "targets": {"alice": True, "bob": False},
            "tool_configs": {"claude": {"default": "m2"}},
        },
    )

    assert outcome == {}
    assert store.ai_targets() == {"alice": True, "bob": False}
    assert store.ai_tool_configs() == {
        "claude": {"default": "m2"},
        "codex": {},
        "gemini": {},
    }
    assert beats == [1]


def test_an_ordinary_caller_may_name_only_itself(tmp_path):
    store = MachineServiceStore(path=str(tmp_path / "services.json"))
    handler, _beats = handler_for(store)

    refused = handler.act(
        entries=[ENTRY],
        account="alice",
        is_privileged=False,
        body={"targets": {"bob": True}},
    )
    assert refused == {"code": "control_scope_refused", "params": {}}

    assert (
        handler.act(
            entries=[ENTRY],
            account="alice",
            is_privileged=False,
            body={"targets": {"alice": True}},
        )
        == {}
    )


def test_the_no_target_guard_covers_both_directions(tmp_path):
    store = MachineServiceStore(path=str(tmp_path / "services.json"))
    handler, _beats = handler_for(store)

    for wish in (True, False):
        refused = handler.act(
            entries=[ENTRY],
            account="root",
            is_privileged=True,
            body={"targets": {"mallory": wish}},
        )
        assert refused == {"code": "no_target_user", "params": {}}
    assert store.ai_targets() == {}


def test_tool_configs_are_cleaned_of_unknown_knobs():
    cleaned = clean_tool_configs(
        {
            "claude": {"default": "m1", "bogus": "x"},
            "codex": {"model": "m2", "model_reasoning_effort": "extreme"},
            "vim": {"model": "m9"},
        }
    )

    assert cleaned == {
        "claude": {"default": "m1"},
        "codex": {"model": "m2"},
        "gemini": {},
    }
