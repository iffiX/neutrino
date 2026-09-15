"""The AI service: one person's apply, converged on the exit hub's grant.

The credential comes from the exit hub's ``ai`` entry over its ``service``
stream, opened on every reconcile; the staged choices are what each tool is
pointed with, and the grant's model is only the prefill default for a slot
nobody has chosen. The store never holds a key and never holds the toggle:
a handler starts with the tools pointed nowhere, restore puts them back the
way activation found them, and letting go of the hub the tools point at
restores them too.
"""

import json

import pytest

from neutrino_client.exceptions import (
    GatewayRefusedDetail,
    GatewayUnreachable,
    GatewayUntrusted,
    ToolSwitchError,
)
from neutrino_client.services.ai import (
    AiServiceHandler,
    ai_entry_id,
    clean_tool_configs,
    resolved_configs,
)
from neutrino_client.services.store import ClientServiceStore
from tests.conftest import SERVICES, discard


def run_inline(target):
    """The lane's thread starter, running the job right here."""
    target()


ENTRY = {
    "hub_id": "h1",
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


class FakeHub:
    """The close a hub answers the ai entry's service stream with, scripted.

    Attributes:
        exit_hub_id: What the resident names as the exit hub.
        opened: ``(hub_id, entry_id)`` for every stream opened, in order.
    """

    def __init__(self, reply=None, error=None):
        self.reply = dict(CREDENTIAL) if reply is None else reply
        self.error = error
        self.exit_hub_id = "h1"
        self.opened = []

    def open_service(self, hub_id, entry_id):
        self.opened.append((hub_id, entry_id))
        if self.error is not None:
            raise self.error
        return dict(self.reply)

    def exit(self) -> str:
        return self.exit_hub_id


class FakeSwitcher:
    def __init__(self):
        self.active = None
        self.has_cli = True
        self.calls = []
        self.activate_error = None
        self.deactivate_error = None
        self.active_apps = set()

    def is_active_for(self, app):
        return app in self.active_apps

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
        if self.active == (base_url, api_key, default):
            return ""
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
    hub = FakeHub()
    handler = AiServiceHandler(
        store=store,
        original_dir=str(tmp_path / "original"),
        open_service=hub.open_service,
        exit_hub_id=hub.exit,
        log=discard,
        switcher_module=fake,
        start_thread=run_inline,
    )
    return handler, store, fake, hub


def activations(fake) -> list:
    return [call for call in fake.calls if call[0] == "activate"]


def test_apply_opens_the_entrys_stream_and_activates_with_the_prefill_default(
    subject,
):
    handler, store, fake, hub = subject

    outcome = handler.act(entries=[ENTRY], body={"is_enabled": True})

    assert outcome == {}
    assert hub.opened == [("h1", "ai")]
    kind, base_url, api_key, tool_configs = fake.calls[-1]
    assert (kind, base_url, api_key) == ("activate", "http://hub:8080", "key-1")
    assert tool_configs["claude"] == {
        "default": "m1",
        "opus": "m1",
        "sonnet": "m1",
        "haiku": "m1",
    }
    row = handler.state()["ai"]
    assert row["is_enabled"] is True and row["is_active"] is True
    assert row["code"] == ""


def test_staged_choices_beat_the_grants_model(subject):
    handler, store, fake, _hub = subject

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
    assert handler.state()["ai_tool_configs"]["codex"]["model"] == "m2"


def test_a_missing_cli_is_a_bundle_refusal_never_an_install(subject):
    handler, store, fake, _hub = subject
    fake.has_cli = False

    handler.act(entries=[ENTRY], body={"is_enabled": True})

    row = handler.state()["ai"]
    assert row["state"] == "absent"
    assert row["code"] == "bundle_missing"
    assert row["params"] == {"binary": "cc-switch"}
    assert activations(fake) == []


def test_enabling_with_no_ai_entry_published_waits_for_one(subject):
    handler, store, fake, hub = subject

    handler.act(entries=[], body={"is_enabled": True})
    assert handler.state()["ai"]["code"] == "no_endpoint"
    assert hub.opened == []
    assert activations(fake) == []

    handler.refresh(entries=[ENTRY])

    assert hub.opened == [("h1", "ai")]
    assert handler.state()["ai"]["is_active"] is True


def test_only_the_exit_hubs_entry_is_asked(subject):
    """Another hub's gateway, even one with the same entry id, is not it."""
    handler, _store, fake, hub = subject
    office = dict(ENTRY, hub_id="h2", payload=dict(ENTRY["payload"], endpoint="o"))
    hub.exit_hub_id = "h2"

    handler.act(entries=[ENTRY], body={"is_enabled": True})
    assert handler.state()["ai"]["code"] == "no_endpoint"
    assert hub.opened == []

    handler.refresh(entries=[ENTRY, office])

    assert hub.opened == [("h2", "ai")]
    assert handler.state()["ai"]["is_active"] is True
    assert handler._granted["hub_id"] == "h2"


def test_moving_the_exit_is_one_activation_at_the_new_hub(subject):
    handler, _store, fake, hub = subject
    office = dict(ENTRY, hub_id="h2")
    handler.act(entries=[ENTRY, office], body={"is_enabled": True})
    hub.exit_hub_id = "h2"
    hub.reply = dict(CREDENTIAL, base_url="http://office:8080")

    handler.refresh(entries=[ENTRY, office])

    assert hub.opened == [("h1", "ai"), ("h2", "ai")]
    assert [call[0] for call in fake.calls] == ["activate", "activate"]
    assert fake.calls[-1][1] == "http://office:8080"
    assert handler._granted["hub_id"] == "h2"


def test_letting_go_of_the_hub_the_tools_point_at_restores_them(subject):
    handler, _store, fake, _hub = subject
    handler.act(entries=[ENTRY], body={"is_enabled": True})

    assert handler.release_hub("h2") == 0
    assert [call for call in fake.calls if call[0] == "deactivate"] == []

    assert handler.release_hub("h1") == 0
    assert handler.release_hub("h1") == 0

    assert [call for call in fake.calls if call[0] == "deactivate"] == [
        ("deactivate", "http://hub:8080")
    ]
    assert handler.state()["ai"]["is_enabled"] is True
    assert handler.state()["ai"]["is_active"] is False


def test_a_grant_with_no_endpoint_is_no_endpoint(subject):
    handler, _store, fake, hub = subject
    hub.reply = {"base_url": "", "api_key": "", "model": "m1"}

    handler.act(entries=[ENTRY], body={"is_enabled": True})

    row = handler.state()["ai"]
    assert (row["code"], row["is_active"], row["state"]) == (
        "no_endpoint",
        False,
        "installed",
    )
    assert activations(fake) == []


@pytest.mark.parametrize(
    "error, code",
    [
        (GatewayUnreachable("down"), "hub_unreachable"),
        (GatewayUntrusted("pin"), "hub_untrusted"),
        (GatewayRefusedDetail(code="client_disabled", params={}), "client_disabled"),
    ],
)
def test_a_hub_that_does_not_grant_is_typed_and_the_tools_stay(subject, error, code):
    handler, _store, fake, hub = subject
    hub.error = error

    handler.act(entries=[ENTRY], body={"is_enabled": True})

    row = handler.state()["ai"]
    assert row["code"] == code
    assert row["is_active"] is False
    assert row["state"] == "installed"
    assert row["is_enabled"] is True
    assert activations(fake) == []


def test_a_refresh_activates_once_the_hub_grants(subject):
    handler, _store, fake, hub = subject
    hub.error = GatewayUnreachable("down")
    handler.act(entries=[ENTRY], body={"is_enabled": True})

    hub.error = None
    handler.refresh(entries=SERVICES)

    assert hub.opened == [("h1", "ai"), ("h1", "ai")]
    assert handler.state()["ai"]["is_active"] is True


def test_a_rotated_key_is_applied_on_the_next_refresh(subject):
    handler, _store, fake, hub = subject
    handler.act(entries=[ENTRY], body={"is_enabled": True})
    before = len(activations(fake))

    hub.reply = dict(CREDENTIAL, api_key="key-2")
    handler.refresh(entries=[ENTRY])

    assert fake.calls[-1][2] == "key-2"
    assert len(activations(fake)) == before + 1


def test_a_refresh_while_the_tools_are_off_opens_no_stream(subject):
    handler, _store, fake, hub = subject

    handler.refresh(entries=[ENTRY])

    assert hub.opened == []
    assert fake.calls == []
    assert handler.state()["ai"]["is_enabled"] is False


def test_an_already_pointed_person_is_looked_at_and_left_as_they_stand(subject):
    """Every tool is asked each time, so an upgrade that changes one tool's
    endpoint reaches a person whose Claude Code already stood on the hub."""
    handler, _store, fake, _hub = subject
    fake.active = ("http://hub:8080", "key-1", "m1")

    handler.act(entries=[ENTRY], body={"is_enabled": True})

    assert activations(fake)
    assert fake.active == ("http://hub:8080", "key-1", "m1")
    assert handler.state()["ai"]["is_active"] is True


def test_disabling_uses_the_endpoint_the_activation_granted(subject):
    handler, _store, fake, hub = subject
    handler.act(entries=[ENTRY], body={"is_enabled": True})

    outcome = handler.act(entries=[ENTRY], body={"is_enabled": False})

    assert outcome == {}
    assert ("deactivate", "http://hub:8080") in fake.calls
    assert handler.state()["ai"]["is_active"] is False
    assert hub.opened == [("h1", "ai")]

    handler.act(entries=[ENTRY], body={"is_enabled": False})
    assert len([call for call in fake.calls if call[0] == "deactivate"]) == 1


def test_a_failed_activation_is_a_typed_failed_state(subject):
    handler, store, fake, _hub = subject
    fake.activate_error = ToolSwitchError("cc-switch refused")

    handler.act(entries=[ENTRY], body={"is_enabled": True})

    row = handler.state()["ai"]
    assert row["state"] == "failed"
    assert row["code"] == "switch_failed"
    assert row["params"] == {"detail": "cc-switch refused"}


def test_restore_puts_the_tools_back_and_keeps_the_choice(subject):
    handler, _store, fake, _hub = subject
    handler.act(entries=[ENTRY], body={"is_enabled": True})

    handler.restore()
    handler.restore()

    assert [call for call in fake.calls if call[0] == "deactivate"] == [
        ("deactivate", "http://hub:8080")
    ]
    assert handler.state()["ai"]["is_enabled"] is True
    assert handler.state()["ai"]["is_active"] is False


def test_restore_after_shutdown_reactivates_on_the_next_refresh(subject):
    handler, _store, fake, _hub = subject
    handler.act(entries=[ENTRY], body={"is_enabled": True})
    handler.release()

    handler.refresh(entries=[ENTRY])

    assert fake.calls[-1][0] == "activate"


def test_an_apply_without_the_toggle_is_refused(subject):
    handler, _store, fake, hub = subject

    refused = handler.act(entries=[ENTRY], body={"tool_configs": {}})

    assert refused == {"code": "unknown_request", "params": {}}
    assert fake.calls == []
    assert hub.opened == []


def test_a_fresh_handler_points_the_tools_nowhere(subject):
    handler, _store, fake, hub = subject

    row = handler.state()["ai"]

    assert row["is_enabled"] is False
    assert row["is_active"] is False
    assert fake.calls == []

    handler.refresh(entries=[ENTRY])

    assert activations(fake) == []
    assert hub.opened == []


def test_the_toggle_of_a_previous_run_is_not_kept(subject, tmp_path):
    handler, store, fake, hub = subject
    handler.act(entries=[ENTRY], body={"is_enabled": True})

    fresh = AiServiceHandler(
        store=store,
        original_dir=str(tmp_path / "original"),
        open_service=hub.open_service,
        exit_hub_id=hub.exit,
        log=discard,
        switcher_module=fake,
        start_thread=run_inline,
    )
    fresh.refresh(entries=[ENTRY])

    assert fresh.state()["ai"]["is_enabled"] is False
    assert fresh.state()["ai"]["is_active"] is False


def test_leftovers_of_an_unclean_exit_are_put_back(subject):
    handler, _store, fake, _hub = subject
    fake.active_apps = {"codex"}

    handler.clear_leftovers()

    assert [call for call in fake.calls if call[0] == "deactivate"] == [
        ("deactivate", "")
    ]


def test_an_adopt_record_alone_is_a_leftover(subject, tmp_path):
    handler, _store, fake, _hub = subject
    original = tmp_path / "original"
    original.mkdir()
    (original / "claude.json").write_text("{}")

    handler.clear_leftovers()

    assert [call for call in fake.calls if call[0] == "deactivate"] == [
        ("deactivate", "")
    ]


def test_a_clean_machine_has_nothing_to_put_back(subject):
    handler, _store, fake, _hub = subject

    handler.clear_leftovers()

    assert fake.calls == []


def test_a_machine_without_the_cli_is_not_asked(subject):
    handler, _store, fake, _hub = subject
    fake.has_cli = False
    fake.active_apps = {"claude"}

    handler.clear_leftovers()

    assert fake.calls == []


def test_the_key_never_reaches_the_store_or_the_state(subject, tmp_path):
    handler, _store, _fake, _hub = subject
    handler.act(
        entries=[ENTRY],
        body={"is_enabled": True, "tool_configs": {"claude": {"default": "m1"}}},
    )

    raw = (tmp_path / "state.json").read_text()
    assert "key-1" not in raw
    assert "api_key" not in raw
    assert "key-1" not in json.dumps(handler.state())


def test_the_ai_entry_is_found_by_hub_and_type_whatever_its_id():
    assert ai_entry_id(SERVICES, "h1") == "ai"
    assert ai_entry_id(SERVICES, "h2") == "ai"
    assert ai_entry_id(SERVICES, "h9") == ""
    assert ai_entry_id([dict(ENTRY, id="gateway")], "h1") == "gateway"
    assert ai_entry_id([SERVICES[1]], "h1") == ""
    assert ai_entry_id([], "h1") == ""
    assert ai_entry_id(None, "h1") == ""


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
