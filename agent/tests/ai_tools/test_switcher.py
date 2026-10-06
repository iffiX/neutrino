"""The client's steps, for one account of a managed machine.

What these pin: the order of the adoption and the switch is the client's
(list, MCP import, the common snippet extracted and set, add, use); a
snippet already set is never replaced; the provider current before is
recorded once and the record never holds the key; an account whose records
carry the wanted settings is not run; Codex's effort is settled after the
switch; Claude Code's file must name the hub; activation is all or nothing;
switching back returns to the provider before, deletes the hub's entry on a
terminal with the client's answer and takes away a file cc-switch made; a
delete that did not take is a refusal carrying the console's words; the
records are kept under the state root and never in the account's home.
A tool with no directory gets one made as the account, its files written,
and both taken away again on the switch back; every file a switch may write
comes back byte for byte; Codex's and Gemini's files must name the hub; a
switch back that cannot run cc-switch is a refusal that keeps the records
and the files.
"""

import json
import os
import stat

import pytest

from neutrino_agent.ai_tools.switcher import (
    AiToolsAccountSwitcher,
    merge_toml_top_level,
    without_own_keys,
)
from neutrino_agent.exceptions import ToolSwitchError
from tests.ai_tools.fake_cc_switch import FakeCcSwitch, FakeSession

HUB = "http://192.168.10.1:8317"
KEY = "device-key"  # scan: allow
CONFIGS = {
    "claude": {"default": "m1", "opus": "mo"},
    "codex": {"model": "m2", "model_reasoning_effort": "high"},
    "gemini": {"model": "m3"},
}
SETTINGS = "/home/ann/.claude/settings.json"


def switcher_for(tmp_path, cc_switch, files=None):
    session = FakeSession(cc_switch, files=files)
    switcher = AiToolsAccountSwitcher(
        session=session, record_dir=str(tmp_path / "ai_tools" / "ann")
    )
    return switcher, session


def activate(switcher, configs=CONFIGS, key=KEY):
    return switcher.activate(base_url=HUB, api_key=key, tool_configs=configs)


def test_a_tool_is_adopted_once_and_the_hub_added_with_its_snippet(tmp_path):
    cc_switch = FakeCcSwitch(extracted='{"hooks": {"x": 1}, "model": "own"}')
    switcher, session = switcher_for(
        tmp_path, cc_switch, {SETTINGS: '{"env": {}, "hooks": {"x": 1}}'}
    )

    assert activate(switcher) == ["claude", "codex", "gemini"]

    assert cc_switch.made("claude") == [
        "provider list",
        "mcp import",
        "config common show",
        "config common extract",
        "config common set",
        "provider current",
        "provider list",
        "config common show",
        "provider add",
        "use neutrino",
    ]
    assert cc_switch.snippet["claude"] == '{\n  "hooks": {\n    "x": 1\n  }\n}'
    added = cc_switch.added["claude"]
    assert added[:6] == (
        "provider",
        "add",
        "--id",
        "neutrino",
        "--name",
        "Neutrino Hub",
    )
    assert "--base-url=" + HUB in added and "--api-key=" + KEY in added
    assert "--model=m1" in added and "--opus-model=mo" in added
    assert "--common-config" in added
    assert session.payload_path() not in session.files


def test_codex_is_given_the_versioned_path_and_its_effort_after_the_switch(tmp_path):
    cc_switch = FakeCcSwitch()
    switcher, session = switcher_for(tmp_path, cc_switch)

    activate(switcher)

    assert "--base-url=" + HUB + "/v1" in cc_switch.added["codex"]
    toml = session.files["/home/ann/.codex/config.toml"]
    assert toml.startswith('model_reasoning_effort = "high"\n')


def test_a_snippet_already_set_is_never_replaced(tmp_path):
    cc_switch = FakeCcSwitch(extracted='{"hooks": {}}')
    cc_switch.snippet["claude"] = '{"own": true}'
    switcher, _session = switcher_for(tmp_path, cc_switch, {SETTINGS: "{}"})

    activate(switcher)

    assert cc_switch.snippet["claude"] == '{"own": true}'
    assert "config common extract" not in cc_switch.made("claude")


def test_the_record_keeps_what_was_before_and_never_the_key(tmp_path):
    cc_switch = FakeCcSwitch(current="mine")
    switcher, _session = switcher_for(tmp_path, cc_switch, {SETTINGS: "{}"})

    activate(switcher)

    path = tmp_path / "ai_tools" / "ann" / "claude.json"
    record = json.loads(path.read_text())
    assert record["is_present"] is True
    assert record["previous"] == "mine"
    assert KEY not in path.read_text()
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert (
        json.loads((tmp_path / "ai_tools" / "ann" / "codex.json").read_text())[
            "is_present"
        ]
        is False
    )


def test_an_account_whose_records_carry_the_settings_runs_nothing(tmp_path):
    cc_switch = FakeCcSwitch()
    switcher, _session = switcher_for(tmp_path, cc_switch)
    activate(switcher)
    cc_switch.calls.clear()

    assert switcher.is_current(base_url=HUB, api_key=KEY, tool_configs=CONFIGS)
    assert not switcher.is_current(
        base_url=HUB, api_key="another", tool_configs=CONFIGS
    )
    assert cc_switch.calls == []


def test_a_changed_model_is_switched_again_without_a_new_adoption(tmp_path):
    cc_switch = FakeCcSwitch()
    switcher, _session = switcher_for(tmp_path, cc_switch)
    activate(switcher)
    cc_switch.calls.clear()

    activate(switcher, {**CONFIGS, "claude": {"default": "m9"}})

    assert "mcp import" not in cc_switch.made("claude")
    assert "provider add" in cc_switch.made("claude")
    assert "--model=m9" in cc_switch.added["claude"]


def test_claude_must_end_up_naming_the_hub(tmp_path):
    cc_switch = FakeCcSwitch()
    switcher, session = switcher_for(tmp_path, cc_switch)
    original = cc_switch.answer

    def no_write(session_, arguments, app):
        answered = original(session_, arguments, app)
        if tuple(arguments)[:1] == ("use",):
            session.files.pop(SETTINGS, None)
        return answered

    cc_switch.answer = no_write

    with pytest.raises(ToolSwitchError) as caught:
        activate(switcher)

    assert caught.value.code == "switch_failed"
    assert "did not take the hub's endpoint" in caught.value.params["detail"]


def test_activation_is_all_or_nothing(tmp_path):
    cc_switch = FakeCcSwitch()
    switcher, _session = switcher_for(tmp_path, cc_switch)
    original = cc_switch.answer

    def refuse_gemini(session_, arguments, app):
        if app == "gemini" and tuple(arguments)[:2] == ("provider", "add"):
            return 1, "", "gemini store is locked"
        return original(session_, arguments, app)

    cc_switch.answer = refuse_gemini

    with pytest.raises(ToolSwitchError) as caught:
        activate(switcher)

    assert caught.value.code == "switch_failed"
    assert caught.value.params == {
        "account": "ann",
        "detail": "gemini: gemini store is locked",
    }
    assert cc_switch.current["claude"] == "default"
    assert cc_switch.current["codex"] == "default"
    assert "neutrino" not in cc_switch.providers["claude"]
    assert not (tmp_path / "ai_tools" / "ann" / "claude.json").exists()


def test_switching_back_returns_to_the_provider_before_and_deletes_the_hub(tmp_path):
    cc_switch = FakeCcSwitch(current="mine")
    switcher, session = switcher_for(tmp_path, cc_switch, {SETTINGS: "{}"})
    activate(switcher)

    notes = switcher.deactivate()

    assert notes[0] == "claude → mine"
    assert cc_switch.current["claude"] == "mine"
    assert "neutrino" not in cc_switch.providers["claude"]
    assert session.answered[0] == (
        ("provider", "delete", "neutrino"),
        "(y/N)",
        "y\n",
    )
    assert not switcher.has_records()


def test_a_file_cc_switch_made_is_taken_away_again(tmp_path):
    cc_switch = FakeCcSwitch()
    switcher, session = switcher_for(tmp_path, cc_switch)
    activate(switcher)
    assert "/home/ann/.codex/config.toml" in session.files

    switcher.deactivate()

    assert "/home/ann/.codex/config.toml" not in session.files
    assert SETTINGS not in session.files


def test_a_hub_with_nothing_before_it_goes_to_the_seeded_provider(tmp_path):
    cc_switch = FakeCcSwitch(current="")
    switcher, _session = switcher_for(tmp_path, cc_switch)
    activate(switcher)

    assert switcher.deactivate()[1] == "codex → codex-official"


def test_a_delete_that_did_not_take_carries_the_console_s_words(tmp_path):
    cc_switch = FakeCcSwitch()
    switcher, _session = switcher_for(tmp_path, cc_switch)
    activate(switcher)
    cc_switch.is_delete_kept = True

    with pytest.raises(ToolSwitchError) as caught:
        switcher.deactivate()

    assert caught.value.params["detail"].startswith(
        "cc-switch kept the hub's provider:"
    )
    assert "Deleted" in caught.value.params["detail"]


def test_every_file_of_the_account_s_is_reached_through_the_session(tmp_path):
    cc_switch = FakeCcSwitch(extracted='{"hooks": {}}')
    switcher, session = switcher_for(tmp_path, cc_switch, {SETTINGS: "{}"})

    activate(switcher)
    switcher.deactivate()

    touched = {path for _verb, path in session.file_calls}
    assert all(path.startswith("/home/ann/") for path in touched)
    assert not any(
        str(tmp_path) in path for _verb, path in session.file_calls
    ), "the records are the agent's own, never in the home"


def test_the_snippet_loses_the_provider_s_own_keys():
    assert without_own_keys("claude", '{"model": "x", "hooks": {}}') == (
        '{\n  "hooks": {}\n}'
    )
    assert without_own_keys("codex", 'model = "x"\napproval_policy = "never"') == (
        'approval_policy = "never"'
    )
    assert without_own_keys("gemini", '{"GEMINI_MODEL": "x"}') == ""


def test_codex_toml_merge_replaces_top_level_keys_only():
    text = (
        'model_reasoning_effort = "low"\nmodel = "a"\n[x]\nmodel_reasoning_effort = 1\n'
    )

    merged = merge_toml_top_level(text, {"model_reasoning_effort": "high"})

    assert merged == (
        'model_reasoning_effort = "high"\nmodel = "a"\n[x]\n'
        "model_reasoning_effort = 1\n"
    )


def test_a_tool_with_no_directory_gets_one_and_loses_it_again(tmp_path):
    cc_switch = FakeCcSwitch(current="")
    switcher, session = switcher_for(tmp_path, cc_switch)

    assert activate(switcher) == ["claude", "codex", "gemini"]

    assert ("make_dir", "/home/ann/.claude") in session.file_calls
    assert json.loads(session.files[SETTINGS])["env"]["ANTHROPIC_BASE_URL"] == HUB
    assert HUB + "/v1" in session.files["/home/ann/.codex/config.toml"]
    assert KEY in session.files["/home/ann/.codex/auth.json"]
    assert HUB in session.files["/home/ann/.gemini/.env"]

    switcher.deactivate()

    assert session.files == {}
    assert session.dirs == set()
    assert not switcher.has_records()


def test_every_file_a_switch_writes_comes_back_byte_for_byte(tmp_path):
    own = '{\n  "permissions": {\n    "allow": ["Bash(ls:*)"]\n  }\n}\n'
    toml = 'model = "mine"\n\n[tui]\nnotifications = true'
    cc_switch = FakeCcSwitch()
    switcher, session = switcher_for(
        tmp_path,
        cc_switch,
        {SETTINGS: own, "/home/ann/.codex/config.toml": toml},
    )
    activate(switcher)
    assert session.files[SETTINGS] != own

    switcher.deactivate()

    assert session.files[SETTINGS] == own
    assert session.files["/home/ann/.codex/config.toml"] == toml
    assert "/home/ann/.codex/auth.json" not in session.files
    assert "/home/ann/.gemini/.env" not in session.files
    assert session.has_dir("/home/ann/.claude")
    assert session.has_dir("/home/ann/.codex")
    assert not session.has_dir("/home/ann/.gemini")


def test_codex_and_gemini_must_end_up_naming_the_hub(tmp_path):
    cc_switch = FakeCcSwitch()
    switcher, session = switcher_for(tmp_path, cc_switch)
    original = session.make_dir

    def made_elsewhere(path):
        if not path.endswith(".codex"):
            original(path)

    session.make_dir = made_elsewhere

    with pytest.raises(ToolSwitchError) as refused:
        activate(switcher)

    assert refused.value.params["detail"].startswith(
        "codex: the settings file did not take the hub's endpoint"
    )


def test_a_switch_back_that_cannot_run_cc_switch_keeps_the_records(tmp_path):
    cc_switch = FakeCcSwitch()
    own = '{"permissions": {}}\n'
    switcher, session = switcher_for(tmp_path, cc_switch, {SETTINGS: own})
    activate(switcher)
    switched = session.files[SETTINGS]
    cc_switch.refusals[("provider", "list")] = "Permission denied"

    with pytest.raises(ToolSwitchError) as refused:
        switcher.deactivate()

    assert refused.value.code == "switch_failed"
    assert "Permission denied" in refused.value.params["detail"]
    assert switcher.has_records()
    assert switcher.read_record("claude")["kept"]["settings.json"] == own
    assert session.files[SETTINGS] == switched

    del cc_switch.refusals[("provider", "list")]
    switcher.deactivate()

    assert session.files[SETTINGS] == own


def test_a_tool_that_refuses_is_put_back_itself(tmp_path):
    own = '{"permissions": {}}\n'
    cc_switch = FakeCcSwitch()
    switcher, session = switcher_for(tmp_path, cc_switch, {SETTINGS: own})
    original = cc_switch.answer

    def wrong_key(session_, arguments, app):
        answered = original(session_, arguments, app)
        if tuple(arguments) == ("use", "neutrino") and app == "claude":
            session.files[SETTINGS] = json.dumps({"env": {"ANTHROPIC_BASE_URL": HUB}})
        return answered

    cc_switch.answer = wrong_key

    with pytest.raises(ToolSwitchError) as caught:
        activate(switcher)

    assert "did not take the hub's endpoint" in caught.value.params["detail"]
    assert session.files[SETTINGS] == own
    assert not switcher.has_records()
    assert "neutrino" not in cc_switch.providers["claude"]
