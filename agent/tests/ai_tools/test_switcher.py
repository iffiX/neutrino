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
and the files. OpenCode's provider goes in whole as ``--config`` beside the
account's own, with no adoption step but the list, and its ``~/.config``
made for the switch is taken away again. OpenCode's top-level ``model``
names the hub's model when the file names none, follows a changed model
while it is the one written, and a ``model`` of the account's own stays; a
record without the wanted ``model`` is switched once more, and the switch
back takes away OpenCode's migration backup holding the hub's provider.
Codex is given its model's one number as ``model_context_window`` and Claude
Code the smallest one number of its slots that name no ``claude-`` model as
``CLAUDE_CODE_MAX_CONTEXT_TOKENS``, none while every slot names one, and
OpenCode its model's ``limit`` ``{context, output}`` inside ``--config``
with no ``input``, ``output`` never more than half of ``context`` and the
smaller of 32000 and half of ``context`` where the model states none, each read back from its file; a changed length switches the tool again, a record
whose ``added`` lacks the lengths is switched once more, and no length is
left after the switch back.
"""

import json
import os
import stat

import pytest

from neutrino_agent.ai_tools import switcher as switcher_module
from neutrino_agent.ai_tools.switcher import (
    AiToolsAccountSwitcher,
    merge_toml_top_level,
    opencode_limit,
    tool_window,
    with_opencode_model,
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
    "opencode": {"model": "m4"},
}
SETTINGS = "/home/ann/.claude/settings.json"
OPENCODE = "/home/ann/.config/opencode/opencode.json"


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

    assert activate(switcher) == ["claude", "codex", "gemini", "opencode"]

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

    touched = {call[1] for call in session.file_calls}
    assert all(path.startswith("/home/ann/") for path in touched)
    assert not any(
        str(tmp_path) in call[1] for call in session.file_calls
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

    assert activate(switcher) == ["claude", "codex", "gemini", "opencode"]

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


KEY_FILES = (
    SETTINGS,
    "/home/ann/.codex/auth.json",
    "/home/ann/.gemini/.env",
    OPENCODE,
)


def test_every_file_holding_the_key_is_the_account_s_alone_while_switched(tmp_path):
    cc_switch = FakeCcSwitch()
    switcher, session = switcher_for(tmp_path, cc_switch)

    activate(switcher)

    assert {path: session.modes.get(path) for path in KEY_FILES} == {
        path: 0o600 for path in KEY_FILES
    }
    assert "/home/ann/.codex/config.toml" not in session.modes


def test_the_switch_back_puts_each_file_s_own_mode_back(tmp_path):
    own = '{"permissions": {}}\n'
    cc_switch = FakeCcSwitch()
    switcher, session = switcher_for(tmp_path, cc_switch, {SETTINGS: own})
    session.modes[SETTINGS] = 0o640

    activate(switcher)
    assert session.modes[SETTINGS] == 0o600
    switcher.deactivate()

    assert session.files[SETTINGS] == own
    assert session.modes[SETTINGS] == 0o640


def test_every_cc_switch_run_uses_the_agent_s_own_store_and_the_switch_back_removes_it(
    tmp_path,
):
    cc_switch = FakeCcSwitch()
    switcher, session = switcher_for(tmp_path, cc_switch, {SETTINGS: "{}"})

    activate(switcher)
    switcher.deactivate()

    assert cc_switch.stores and all(cc_switch.stores)
    assert session.store_calls[0] == "prepare"
    assert session.store_calls[-1] == "remove"
    assert switcher.read_record("claude") is None


def test_a_tool_switched_before_the_store_existed_goes_back_in_the_person_s_own(
    tmp_path,
):
    import json as json_module

    cc_switch = FakeCcSwitch()
    switcher, session = switcher_for(tmp_path, cc_switch, {SETTINGS: "{}"})
    activate(switcher)
    for app in ("claude", "codex", "gemini", "opencode"):
        record = switcher.read_record(app)
        del record["is_own_store"]
        with open(switcher._record_path(app), "w", encoding="utf-8") as stream:
            json_module.dump(record, stream)
    cc_switch.stores.clear()

    switcher.deactivate()

    assert cc_switch.stores and not any(cc_switch.stores)


def failing_store(session):
    """A store that is made, then refuses its mode, as macOS chmod once did."""

    def prepare():
        session.store_calls.append("prepare")
        session.dirs.add(session.store_path())
        raise session.failure("could not make the store: chmod refused")

    session.prepare_store = prepare


def test_a_store_that_could_not_be_made_is_taken_away_when_no_record_was_kept(
    tmp_path,
):
    cc_switch = FakeCcSwitch()
    switcher, session = switcher_for(tmp_path, cc_switch, {SETTINGS: "{}"})
    failing_store(session)

    with pytest.raises(ToolSwitchError):
        activate(switcher)

    assert session.store_calls == ["prepare", "remove"]
    assert not session.has_dir(session.store_path())
    assert cc_switch.calls == []


def test_a_store_that_could_not_be_made_stays_while_a_record_stands(tmp_path):
    cc_switch = FakeCcSwitch()
    switcher, session = switcher_for(tmp_path, cc_switch, {SETTINGS: "{}"})
    activate(switcher)
    session.store_calls.clear()
    failing_store(session)

    with pytest.raises(ToolSwitchError):
        activate(switcher, key="another-key")

    assert session.store_calls == ["prepare"]
    assert switcher.has_records()


def test_opencode_gets_the_hub_s_provider_whole_beside_the_account_s_own(tmp_path):
    own = json.dumps(
        {
            "model": "mine/x",
            "provider": {"mine": {"options": {"baseURL": "https://mine"}}},
            "mcp": {"fs": {"type": "local"}},
        }
    )
    cc_switch = FakeCcSwitch()
    switcher, session = switcher_for(tmp_path, cc_switch, {OPENCODE: own})

    activate(switcher)

    assert cc_switch.made("opencode") == [
        "provider list",
        "provider list",
        "provider add",
        "use neutrino",
    ]
    added = cc_switch.added["opencode"]
    assert not [flag for flag in added if flag.startswith(("--base-url", "--api-key"))]
    (given,) = [flag for flag in added if flag.startswith("--config=")]
    assert json.loads(given[len("--config=") :]) == {
        "npm": "@ai-sdk/openai-compatible",
        "name": "Neutrino Hub",
        "options": {"baseURL": HUB + "/v1", "apiKey": KEY},
        "models": {"m4": {"name": "m4"}},
    }
    live = json.loads(session.files[OPENCODE])
    assert sorted(live["provider"]) == ["mine", "neutrino"]
    assert live["model"] == "mine/x" and live["mcp"] == {"fs": {"type": "local"}}
    assert switcher.read_record("opencode")["previous"] == ""
    assert switcher.read_record("opencode")["written_model"] == ""

    switcher.deactivate()

    assert session.files[OPENCODE] == own
    assert "provider delete" in cc_switch.made("opencode")
    assert not [
        key for _a, app, key in cc_switch.calls if app == "opencode" and key[0] == "use"
    ][1:]


def test_opencode_s_config_folder_made_for_the_switch_is_taken_away_again(tmp_path):
    cc_switch = FakeCcSwitch(current="")
    switcher, session = switcher_for(tmp_path, cc_switch)

    activate(switcher)

    assert ("make_dir", "/home/ann/.config/opencode") in session.file_calls
    assert switcher.read_record("opencode")["is_parent_present"] is False
    assert HUB + "/v1" in session.files[OPENCODE]

    switcher.deactivate()

    assert ("remove_empty_dir", "/home/ann/.config/opencode") in session.file_calls
    assert ("remove_empty_dir", "/home/ann/.config") in session.file_calls
    assert OPENCODE not in session.files


def test_a_config_folder_that_was_there_stays(tmp_path):
    cc_switch = FakeCcSwitch()
    switcher, session = switcher_for(tmp_path, cc_switch)
    session.dirs.add("/home/ann/.config")

    activate(switcher)
    record = switcher.read_record("opencode")
    switcher.deactivate()

    assert record["is_dir_present"] is False
    assert record["is_parent_present"] is True
    assert ("remove_empty_dir", "/home/ann/.config") not in session.file_calls
    assert session.has_dir("/home/ann/.config")


def test_a_changed_opencode_model_replaces_the_hub_s_provider(tmp_path):
    cc_switch = FakeCcSwitch()
    switcher, session = switcher_for(tmp_path, cc_switch)
    activate(switcher)
    cc_switch.calls.clear()

    activate(switcher, {**CONFIGS, "opencode": {"model": "m5"}})

    assert cc_switch.made("opencode") == [
        "provider list",
        "provider delete",
        "provider list",
        "provider add",
        "use neutrino",
    ]
    live = json.loads(session.files[OPENCODE])
    assert live["provider"]["neutrino"]["models"] == {"m5": {"name": "m5"}}
    assert live["model"] == "neutrino/m5"
    assert switcher.read_record("opencode")["written_model"] == "neutrino/m5"


def test_an_opencode_file_cc_switch_cannot_read_fails_the_switch(tmp_path):
    cc_switch = FakeCcSwitch()
    switcher, session = switcher_for(
        tmp_path, cc_switch, {OPENCODE: '{\n  // mine\n  "model": "a/b"\n}\n'}
    )

    with pytest.raises(ToolSwitchError) as refused:
        activate(switcher)

    assert refused.value.params["detail"].startswith("opencode: Error: JSON")
    assert not switcher.has_records()


def test_opencode_with_no_model_of_its_own_starts_on_the_hub_s_model(tmp_path):
    cc_switch = FakeCcSwitch()
    switcher, session = switcher_for(tmp_path, cc_switch)

    activate(switcher)

    live = json.loads(session.files[OPENCODE])
    assert live["model"] == "neutrino/m4"
    assert live["provider"]["neutrino"]["models"] == {"m4": {"name": "m4"}}
    assert switcher.read_record("opencode")["written_model"] == "neutrino/m4"
    written = session.file_calls.index(("write", OPENCODE))
    assert session.file_calls.index(("set_mode", OPENCODE, 0o600)) > written
    assert session.modes[OPENCODE] == 0o600

    switcher.deactivate()

    assert OPENCODE not in session.files


def test_a_model_of_the_account_s_own_stays_when_the_model_changes(tmp_path):
    own = json.dumps({"model": "mine/x", "provider": {"mine": {}}})
    cc_switch = FakeCcSwitch()
    switcher, session = switcher_for(tmp_path, cc_switch, {OPENCODE: own})
    activate(switcher)

    activate(switcher, {**CONFIGS, "opencode": {"model": "m5"}})

    live = json.loads(session.files[OPENCODE])
    assert live["model"] == "mine/x"
    assert live["provider"]["neutrino"]["models"] == {"m5": {"name": "m5"}}
    assert switcher.read_record("opencode")["written_model"] == ""
    switcher.deactivate()
    assert session.files[OPENCODE] == own


def test_a_model_the_account_set_after_the_switch_is_its_own(tmp_path):
    cc_switch = FakeCcSwitch()
    switcher, session = switcher_for(tmp_path, cc_switch)
    activate(switcher)
    live = json.loads(session.files[OPENCODE])
    live["model"] = "neutrino/m4-large"
    session.files[OPENCODE] = json.dumps(live, indent=2)

    activate(switcher, {**CONFIGS, "opencode": {"model": "m5"}})

    assert json.loads(session.files[OPENCODE])["model"] == "neutrino/m4-large"
    assert switcher.read_record("opencode")["written_model"] == ""


def test_the_switch_back_takes_the_written_model_away_byte_for_byte(tmp_path):
    own = '{\n  "$schema": "https://opencode.ai/config.json",\n  "theme": "é"\n}\n'
    cc_switch = FakeCcSwitch()
    switcher, session = switcher_for(tmp_path, cc_switch, {OPENCODE: own})
    session.modes[OPENCODE] = 0o644

    activate(switcher)
    activate(switcher, {**CONFIGS, "opencode": {"model": "m5"}})
    live = json.loads(session.files[OPENCODE])
    assert live["model"] == "neutrino/m5" and live["theme"] == "é"
    switcher.deactivate()

    assert session.files[OPENCODE] == own
    assert session.modes[OPENCODE] == 0o644


def test_the_opencode_model_is_written_as_json_in_cc_switch_s_layout():
    text = '{\n  "$schema": "s",\n  "provider": {\n    "neutrino": {}\n  }\n}'

    merged, written = with_opencode_model(text, "neutrino/m4", "")

    assert merged == (
        '{\n  "$schema": "s",\n  "provider": {\n    "neutrino": {}\n  },\n'
        '  "model": "neutrino/m4"\n}'
    )
    assert written == "neutrino/m4"
    assert with_opencode_model(text + "\n", "neutrino/m4", "")[0] == merged + "\n"
    assert with_opencode_model(merged, "neutrino/m4", "neutrino/m4") == (
        merged,
        "neutrino/m4",
    )


def test_the_written_opencode_model_goes_when_the_tool_has_no_model():
    text = '{\n  "model": "neutrino/m4"\n}'

    assert with_opencode_model(text, "", "neutrino/m4") == ("{}", "")
    assert with_opencode_model(text, "", "") == (text, "")
    assert with_opencode_model("{}", "", "") == ("{}", "")


BACKUP = "/home/ann/.config/opencode/opencode.json.tui-migration.bak"


def test_an_opencode_record_without_the_wanted_model_is_switched_once_more(tmp_path):
    cc_switch = FakeCcSwitch()
    switcher, session = switcher_for(tmp_path, cc_switch)
    activate(switcher)
    path = tmp_path / "ai_tools" / "ann" / "opencode.json"
    record = json.loads(path.read_text())
    del record["added"]["model"]
    del record["written_model"]
    path.write_text(json.dumps(record))
    live = json.loads(session.files[OPENCODE])
    del live["model"]
    session.files[OPENCODE] = json.dumps(live, indent=2)
    cc_switch.calls.clear()

    assert not switcher.is_current(base_url=HUB, api_key=KEY, tool_configs=CONFIGS)
    assert activate(switcher) == ["opencode"]

    assert cc_switch.made("opencode") == [
        "provider list",
        "provider delete",
        "provider list",
        "provider add",
        "use neutrino",
    ]
    assert json.loads(session.files[OPENCODE])["model"] == "neutrino/m4"
    assert switcher.read_record("opencode")["added"]["model"] == "neutrino/m4"
    assert switcher.is_current(base_url=HUB, api_key=KEY, tool_configs=CONFIGS)
    assert activate(switcher) == []


def test_the_switch_back_takes_away_the_migration_backup_holding_the_hub(tmp_path):
    cc_switch = FakeCcSwitch(current="")
    switcher, session = switcher_for(tmp_path, cc_switch)
    activate(switcher)
    session.files[BACKUP] = session.files[OPENCODE]

    switcher.deactivate()

    assert ("remove", BACKUP) in session.file_calls
    assert BACKUP not in session.files
    assert not session.has_dir("/home/ann/.config")


def test_a_migration_backup_without_the_hub_s_provider_stays(tmp_path):
    own = '{\n  "theme": "tokyonight",\n  "provider": {"mine": {}}\n}'
    cc_switch = FakeCcSwitch()
    switcher, session = switcher_for(tmp_path, cc_switch, {BACKUP: own})
    activate(switcher)

    switcher.deactivate()

    assert session.files[BACKUP] == own
    assert ("remove", BACKUP) not in session.file_calls


# --- each tool's context length ---

CODEX_FILE = "/home/ann/.codex/config.toml"
WIDE = {"context_length": 400000, "input_limit": 272000, "output_limit": 128000}
SMALL = {"context_length": 16384, "input_limit": 0, "output_limit": 0}
LENGTH_CONFIGS = {
    "claude": {"default": "lab-mini", "opus": "claude-opus-4-6", "haiku": "qwen"},
    "codex": {"model": "lab-mini", "model_reasoning_effort": "high"},
    "gemini": {"model": "qwen"},
    "opencode": {"model": "qwen"},
}
LENGTHS = {"lab-mini": WIDE, "qwen": SMALL, "claude-opus-4-6": dict(SMALL)}


def activate_with(switcher, lengths, configs=LENGTH_CONFIGS):
    return switcher.activate(
        base_url=HUB, api_key=KEY, tool_configs=configs, context_lengths=lengths
    )


def claude_env(session) -> dict:
    return json.loads(session.files[SETTINGS]).get("env", {})


def test_codex_and_claude_code_get_their_one_number_after_the_switch(tmp_path):
    cc_switch = FakeCcSwitch()
    switcher, session = switcher_for(tmp_path, cc_switch)

    activate_with(switcher, LENGTHS)

    toml = session.files[CODEX_FILE]
    assert "model_context_window = 272000\n" in toml
    assert 'model_reasoning_effort = "high"\n' in toml
    assert claude_env(session)["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] == "16384"
    assert switcher.read_record("codex")["added"]["model_context_window"] == 272000
    assert switcher.read_record("claude")["added"]["max_context_tokens"] == 16384
    assert "model_context_window" not in switcher.read_record("gemini")["added"]
    assert switcher.is_current(
        base_url=HUB,
        api_key=KEY,
        tool_configs=LENGTH_CONFIGS,
        context_lengths=LENGTHS,
    )


def test_claude_code_gets_no_variable_while_every_slot_names_a_claude_model(tmp_path):
    cc_switch = FakeCcSwitch()
    switcher, session = switcher_for(tmp_path, cc_switch)
    configs = {**LENGTH_CONFIGS, "claude": {"default": "claude-opus-4-6"}}

    activate_with(switcher, LENGTHS, configs)

    assert "CLAUDE_CODE_MAX_CONTEXT_TOKENS" not in claude_env(session)
    assert switcher.read_record("claude")["added"]["max_context_tokens"] == 0


def test_the_variable_is_the_smallest_of_the_slots_that_name_no_claude_model():
    lengths = {"a": {"context_length": 100000}, "b": WIDE, "claude-x": SMALL}
    config = {"default": "a", "opus": "claude-x", "sonnet": "b", "haiku": "none"}

    assert tool_window("claude", config, lengths) == 100000
    assert tool_window("codex", {"model": "b"}, lengths) == 272000
    assert tool_window("codex", {"model": "none"}, lengths) == 0
    assert tool_window("gemini", {"model": "a"}, lengths) == 0


def test_a_changed_length_switches_the_tool_again(tmp_path):
    cc_switch = FakeCcSwitch()
    switcher, session = switcher_for(tmp_path, cc_switch)
    activate_with(switcher, LENGTHS)
    changed = {**LENGTHS, "lab-mini": {"context_length": 100000}}

    assert not switcher.is_current(
        base_url=HUB, api_key=KEY, tool_configs=LENGTH_CONFIGS, context_lengths=changed
    )
    assert activate_with(switcher, changed) == ["codex"]
    assert "model_context_window = 100000\n" in session.files[CODEX_FILE]

    smaller = {**changed, "qwen": {"context_length": 8192}}
    assert activate_with(switcher, smaller) == ["claude", "opencode"]
    assert claude_env(session)["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] == "8192"


def test_a_record_whose_added_lacks_the_lengths_is_switched_once_more(tmp_path):
    cc_switch = FakeCcSwitch()
    switcher, session = switcher_for(tmp_path, cc_switch)
    activate_with(switcher, LENGTHS)
    for app, key in (
        ("codex", "model_context_window"),
        ("claude", "max_context_tokens"),
    ):
        path = tmp_path / "ai_tools" / "ann" / f"{app}.json"
        record = json.loads(path.read_text())
        del record["added"][key]
        path.write_text(json.dumps(record))

    assert activate_with(switcher, LENGTHS) == ["claude", "codex"]
    assert activate_with(switcher, LENGTHS) == []


def test_a_length_the_file_did_not_take_fails_the_switch(tmp_path, monkeypatch):
    cc_switch = FakeCcSwitch()
    switcher, _session = switcher_for(tmp_path, cc_switch)
    monkeypatch.setattr(switcher_module, "with_claude_window", lambda text, n: text)

    with pytest.raises(ToolSwitchError) as caught:
        activate_with(switcher, LENGTHS)

    assert "did not take the context length" in caught.value.params["detail"]


def test_no_length_is_left_after_the_switch_back(tmp_path):
    cc_switch = FakeCcSwitch()
    own_toml = 'model = "own"\n'
    switcher, session = switcher_for(
        tmp_path, cc_switch, {CODEX_FILE: own_toml, SETTINGS: '{"env": {}}'}
    )
    activate_with(switcher, LENGTHS)

    switcher.deactivate()

    assert session.files[CODEX_FILE] == own_toml
    assert session.files[SETTINGS] == '{"env": {}}'


def opencode_provider(session) -> dict:
    return json.loads(session.files[OPENCODE])["provider"]["neutrino"]


def test_opencode_gets_its_model_s_limit_of_context_and_output_and_no_input(tmp_path):
    cc_switch = FakeCcSwitch()
    switcher, session = switcher_for(tmp_path, cc_switch)
    configs = {**LENGTH_CONFIGS, "opencode": {"model": "lab-mini"}}

    activate_with(switcher, LENGTHS, configs)

    given = json.loads(
        next(a for a in cc_switch.added["opencode"] if a.startswith("--config="))[9:]
    )
    assert given["models"]["lab-mini"]["limit"] == {"context": 272000, "output": 128000}
    assert opencode_provider(session)["models"]["lab-mini"] == {
        "name": "lab-mini",
        "limit": {"context": 272000, "output": 128000},
    }
    assert switcher.read_record("opencode")["added"]["limit"] == {
        "context": 272000,
        "output": 128000,
    }


def test_a_model_stating_no_longest_answer_gets_32000_or_half_its_window():
    small = {"context_length": 16384, "input_limit": 0, "output_limit": 0}
    large = {"context_length": 131072, "input_limit": 0, "output_limit": 0}

    assert opencode_limit({"model": "s"}, {"s": small}) == {
        "context": 16384,
        "output": 8192,
    }
    assert opencode_limit({"model": "l"}, {"l": large}) == {
        "context": 131072,
        "output": 32000,
    }
    assert opencode_limit({"model": "none"}, {"s": small}) == {}
    assert opencode_limit({}, None) == {}


def test_an_opencode_model_with_no_length_gets_no_limit(tmp_path):
    cc_switch = FakeCcSwitch()
    switcher, session = switcher_for(tmp_path, cc_switch)

    activate_with(switcher, {}, LENGTH_CONFIGS)

    assert opencode_provider(session)["models"]["qwen"] == {"name": "qwen"}
    assert switcher.read_record("opencode")["added"]["limit"] == {}


def test_a_limit_the_file_did_not_keep_fails_the_switch(tmp_path):
    cc_switch = FakeCcSwitch()
    cc_switch.dropped_limit_keys = ("input", "output")
    switcher, _session = switcher_for(tmp_path, cc_switch)

    with pytest.raises(ToolSwitchError) as caught:
        activate_with(switcher, LENGTHS)

    assert "did not take the context length" in caught.value.params["detail"]


def test_opencode_s_limit_goes_with_its_provider_at_the_switch_back(tmp_path):
    cc_switch = FakeCcSwitch()
    own = '{"provider": {"mine": {"name": "Mine"}}}'
    switcher, session = switcher_for(tmp_path, cc_switch, {OPENCODE: own})
    activate_with(switcher, LENGTHS)

    switcher.deactivate()

    assert session.files[OPENCODE] == own


def test_opencode_s_output_is_never_more_than_half_its_context():
    vendor = {"output_limit": 128000, "input_limit": 0}

    assert opencode_limit(
        {"model": "m"}, {"m": dict(vendor, context_length=100000)}
    ) == {"context": 100000, "output": 50000}
    assert opencode_limit(
        {"model": "m"}, {"m": dict(vendor, context_length=1000000)}
    ) == {"context": 1000000, "output": 128000}
