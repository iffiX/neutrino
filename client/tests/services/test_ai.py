"""The AI service: one person's apply, converged on the poll's credential.

The staged choices are what each tool is pointed with; the grant's model is
only the prefill default for a slot nobody has chosen. The store never holds
a key, and restore puts the tools back the way activation found them.
"""

import json

import pytest

from neutrino_client.services.ai import (
    AiServiceHandler,
    clean_tool_configs,
    resolved_configs,
)
from neutrino_client.services.store import ClientServiceStore
from neutrino_client.services.switcher import SwitcherError
from tests.conftest import discard

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
CREDENTIAL = {
    "base_url": "http://hub:8080",
    "api_key": "key-1",
    "model": "m1",
}  # scan: allow


class FakeSwitcher:
    def __init__(self):
        self.active = None
        self.has_cli = True
        self.calls = []
        self.activate_error = None
        self.deactivate_error = None

    def is_installed(self):
        return self.has_cli

    def find_cli(self):
        return "/opt/neutrino_client/bin/cc-switch" if self.has_cli else None

    def is_active(self, *, base_url, api_key="", model=""):
        return self.active == (base_url, api_key, model)

    def activate(self, *, base_url, api_key, tool_configs=None):
        if self.activate_error is not None:
            raise self.activate_error
        self.calls.append(("activate", base_url, api_key, tool_configs))
        default = (tool_configs or {}).get("claude", {}).get("default", "")
        self.active = (base_url, api_key, default)
        return "claude"

    def deactivate(self, *, base_url=""):
        if self.deactivate_error is not None:
            raise self.deactivate_error
        self.calls.append(("deactivate", base_url))
        self.active = None
        return "claude → as it was"


@pytest.fixture
def subject(tmp_path):
    store = ClientServiceStore(path=str(tmp_path / "state.json"))
    fake = FakeSwitcher()
    handler = AiServiceHandler(store=store, log=discard, switcher_module=fake)
    return handler, store, fake


def test_apply_with_a_grant_activates_with_the_prefill_default(subject):
    handler, store, fake = subject
    handler.update_credential(CREDENTIAL)

    outcome = handler.act(entries=[ENTRY], body={"is_enabled": True})

    assert outcome == {}
    kind, base_url, api_key, tool_configs = fake.calls[-1]
    assert (kind, base_url, api_key) == ("activate", "http://hub:8080", "key-1")
    assert tool_configs["claude"] == {
        "default": "m1",
        "opus": "m1",
        "sonnet": "m1",
        "haiku": "m1",
    }
    assert store.ai_granted() == {"base_url": "http://hub:8080", "model": "m1"}
    row = handler.state()["ai"]
    assert row["is_enabled"] is True and row["is_active"] is True
    assert row["code"] == ""


def test_staged_choices_beat_the_grants_model(subject):
    handler, store, fake = subject
    handler.update_credential(CREDENTIAL)

    handler.act(
        entries=[ENTRY],
        body={
            "is_enabled": True,
            "tool_configs": {
                "claude": {"default": "m2", "haiku": "m3"},
                "codex": {"model": "m2", "model_reasoning_effort": "high"},
                "gemini": {"model": "m3"},
            },
        },
    )

    tool_configs = fake.calls[-1][3]
    assert tool_configs["claude"] == {
        "default": "m2",
        "opus": "m1",
        "sonnet": "m1",
        "haiku": "m3",
    }
    assert tool_configs["codex"] == {"model": "m2", "model_reasoning_effort": "high"}
    assert tool_configs["gemini"] == {"model": "m3"}
    assert store.ai_granted()["model"] == "m2"
    assert handler.state()["ai_tool_configs"]["codex"]["model"] == "m2"


def test_a_missing_cli_is_a_bundle_refusal_never_an_install(subject):
    handler, store, fake = subject
    fake.has_cli = False
    handler.update_credential(CREDENTIAL)

    handler.act(entries=[ENTRY], body={"is_enabled": True})

    row = handler.state()["ai"]
    assert row["state"] == "absent"
    assert row["code"] == "bundle_missing"
    assert row["params"] == {"binary": "cc-switch"}
    assert not any(call[0] == "activate" for call in fake.calls)
    assert store.ai_granted() == {}


def test_enabling_before_a_grant_waits_then_activates_on_the_credential(subject):
    handler, store, fake = subject

    handler.act(entries=[ENTRY], body={"is_enabled": True})
    assert handler.state()["ai"]["code"] == "no_endpoint"
    assert not any(call[0] == "activate" for call in fake.calls)

    handler.update_credential(CREDENTIAL)

    assert any(call[0] == "activate" for call in fake.calls)
    assert handler.state()["ai"]["is_active"] is True


def test_a_rotated_key_is_applied_again(subject):
    handler, _store, fake = subject
    handler.act(entries=[ENTRY], body={"is_enabled": True})
    handler.update_credential(CREDENTIAL)
    activations = len([call for call in fake.calls if call[0] == "activate"])

    handler.update_credential(dict(CREDENTIAL, api_key="key-2"))

    assert fake.calls[-1][2] == "key-2"
    assert (
        len([call for call in fake.calls if call[0] == "activate"]) == activations + 1
    )


def test_an_already_pointed_person_is_left_alone(subject):
    handler, _store, fake = subject
    fake.active = ("http://hub:8080", "key-1", "m1")
    handler.update_credential(CREDENTIAL)

    handler.act(entries=[ENTRY], body={"is_enabled": True})

    assert not any(call[0] == "activate" for call in fake.calls)
    assert handler.state()["ai"]["is_active"] is True


def test_disabling_uses_the_last_granted_endpoint_and_clears_it(subject):
    handler, store, fake = subject
    store.set_ai_granted({"base_url": "http://old:8080", "model": "m0"})

    outcome = handler.act(entries=[ENTRY], body={"is_enabled": False})

    assert outcome == {}
    assert ("deactivate", "http://old:8080") in fake.calls
    assert store.ai_granted() == {}
    assert handler.state()["ai"]["is_active"] is False


def test_a_failed_activation_is_a_typed_failed_state(subject):
    handler, store, fake = subject
    fake.activate_error = SwitcherError("cc-switch refused")
    handler.update_credential(CREDENTIAL)

    handler.act(entries=[ENTRY], body={"is_enabled": True})

    row = handler.state()["ai"]
    assert row["state"] == "failed"
    assert row["code"] == "switch_failed"
    assert row["params"] == {"detail": "cc-switch refused"}
    assert store.ai_granted() == {}


def test_restore_puts_the_tools_back_and_keeps_the_choice(subject):
    handler, store, fake = subject
    handler.update_credential(CREDENTIAL)
    handler.act(entries=[ENTRY], body={"is_enabled": True})

    handler.restore()
    handler.restore()

    assert [call for call in fake.calls if call[0] == "deactivate"] == [
        ("deactivate", "http://hub:8080")
    ]
    assert store.ai_granted() == {}
    assert store.is_ai_enabled() is True
    assert handler.state()["ai"]["is_active"] is False


def test_restore_after_shutdown_reactivates_on_the_next_credential(subject):
    handler, _store, fake = subject
    handler.update_credential(CREDENTIAL)
    handler.act(entries=[ENTRY], body={"is_enabled": True})
    handler.release()

    handler.update_credential(CREDENTIAL)

    assert fake.calls[-1][0] == "activate"


def test_an_apply_without_the_toggle_is_refused(subject):
    handler, store, fake = subject

    refused = handler.act(entries=[ENTRY], body={"tool_configs": {}})

    assert refused == {"code": "unknown_request", "params": {}}
    assert fake.calls == []


def test_the_key_never_reaches_the_store(subject, tmp_path):
    handler, _store, _fake = subject
    handler.update_credential(CREDENTIAL)
    handler.act(entries=[ENTRY], body={"is_enabled": True})

    raw = (tmp_path / "state.json").read_text()
    assert "key-1" not in raw
    assert "api_key" not in raw
    assert "key-1" not in json.dumps(handler.state())


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


def test_resolved_configs_fill_every_claude_slot():
    resolved = resolved_configs({"model": "m1"}, {"claude": {"opus": "m2"}})

    assert resolved["claude"] == {
        "default": "m1",
        "opus": "m2",
        "sonnet": "m1",
        "haiku": "m1",
    }
    assert resolved["codex"] == {"model": "", "model_reasoning_effort": ""}
    assert resolved["gemini"] == {"model": ""}
