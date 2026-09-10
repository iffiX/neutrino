"""Finding cc-switch and handing it what the person already had.

The carried CLI wins over one on the path; every file operation is the
standard library's own on this person's home, with no step-down anywhere.
cc-switch itself is scripted below as a small store: what it answers, and
every call the switcher made, in order.
"""

import json
import os
import subprocess

import pytest

import neutrino_client.bundled as bundled
from neutrino_client.services import switcher


@pytest.fixture(autouse=True)
def _own_platform(monkeypatch):
    from tests.conftest import FakeClientPlatform

    monkeypatch.setattr(switcher, "_PLATFORM", FakeClientPlatform())


def wire(monkeypatch, cli):
    """Script cc-switch, and let the platform's answered delete take effect."""
    monkeypatch.setattr(switcher, "_run", cli)

    def delete(argv):
        cli.providers[argv[2]].discard(argv[-1])

    switcher._PLATFORM.on_answer = delete
    return switcher._PLATFORM


def test_the_carried_cli_wins_over_the_path(monkeypatch):
    monkeypatch.setattr(
        bundled, "cc_switch_path", lambda: "/opt/neutrino_client/bin/cc-switch"
    )
    monkeypatch.setattr(switcher.shutil, "which", lambda name: "/usr/bin/cc-switch")

    assert switcher.find_cli() == "/opt/neutrino_client/bin/cc-switch"


def test_the_path_answers_when_the_bundle_is_absent(monkeypatch):
    monkeypatch.setattr(bundled, "cc_switch_path", lambda: "")
    monkeypatch.setattr(switcher.shutil, "which", lambda name: "/usr/bin/cc-switch")

    assert switcher.find_cli() == "/usr/bin/cc-switch"
    assert switcher.is_installed() is True


def test_no_cli_when_nothing_is_installed(monkeypatch):
    monkeypatch.setattr(bundled, "cc_switch_path", lambda: "")
    monkeypatch.setattr(switcher.shutil, "which", lambda name: None)

    assert switcher.find_cli() is None
    assert switcher.is_installed() is False


def test_the_cli_runs_as_this_person_with_no_step_down(monkeypatch):
    monkeypatch.setattr(bundled, "cc_switch_path", lambda: "/opt/cc-switch")
    recorded = []

    def record(command, **kwargs):
        recorded.append(list(command))
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    monkeypatch.setattr(switcher.subprocess, "run", record)

    assert switcher._run(["provider", "current"], "claude") == "ok"

    assert recorded == [["/opt/cc-switch", "--app", "claude", "provider", "current"]]
    assert not any("runuser" in command for command in recorded)


def test_the_cli_runs_quietly_and_is_read_as_utf8(monkeypatch):
    """Its tables are UTF-8 whatever the console's code page is."""
    monkeypatch.setattr(bundled, "cc_switch_path", lambda: "/opt/cc-switch")
    seen = {}

    def record(command, **kwargs):
        seen.update(kwargs)
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    monkeypatch.setattr(switcher, "run_quietly", record)

    switcher._run(["provider", "list"], "claude")

    assert seen == {"timeout_s": switcher.COMMAND_TIMEOUT_S, "encoding": "utf-8"}


def test_a_refusing_cli_is_the_commands_own_error(monkeypatch):
    monkeypatch.setattr(bundled, "cc_switch_path", lambda: "/opt/cc-switch")
    monkeypatch.setattr(
        switcher.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command, 1, stdout="", stderr="no store"
        ),
    )

    with pytest.raises(subprocess.CalledProcessError) as caught:
        switcher._run(["use", "x"], "claude")
    assert caught.value.returncode == 1
    assert caught.value.stderr == "no store"
    assert switcher._run(["use", "x"], "claude", is_checked=False) == ""


def test_a_refusing_cli_reaches_the_page_as_its_words(tmp_path, monkeypatch):
    home_file(tmp_path, ".claude/settings.json", "{}")

    def refuse(arguments, app, *, is_checked=True):
        if is_checked:
            raise subprocess.CalledProcessError(1, ["cc-switch"], stderr="no store")
        return ""

    monkeypatch.setattr(switcher, "_run", refuse)

    with pytest.raises(switcher.ToolSwitchError) as caught:
        switcher._point_at_hub("claude", "http://hub", "k", {"default": "m1"})
    assert str(caught.value) == "no store"


class Cli:
    """cc-switch, scripted: a store per app, and every call made."""

    HEADER = "Common Config Snippet\n=====\nApp: {app}\n"

    def __init__(self, *, current="default", extracted="", writes_claude=True):
        self.calls = []
        self.current = {app: current for app in switcher.SWITCHER_APPS}
        self.snippet = {app: "" for app in switcher.SWITCHER_APPS}
        self.providers = {
            app: {current} if current else set() for app in switcher.SWITCHER_APPS
        }
        self.extracted = extracted
        self.writes_claude = writes_claude
        self.added = {}
        self.refusals = {}

    def __call__(self, arguments, app, *, is_checked=True):
        key = tuple(arguments)
        self.calls.append((app, key))
        for prefix, error in self.refusals.items():
            if key[: len(prefix)] == prefix:
                if is_checked:
                    raise error
                return ""
        if key[:2] == ("provider", "list"):
            rows = ["│   ┆ ID ┆ Name ┆ API URL │"]
            for identifier in sorted(self.providers[app]):
                mark = "✓" if identifier == self.current[app] else " "
                rows.append(f"│ {mark} ┆ {identifier} ┆ {identifier} ┆ N/A │")
            return "\n".join(rows) + "\n"
        if key[:2] == ("provider", "current"):
            if self.current[app]:
                return f"Current Provider\n  ID:       {self.current[app]}\n  App:     {app}\n"
            return "Error: Current provider '' not found\n"
        if key[:2] == ("provider", "add"):
            self.providers[app].add(key[key.index("--id") + 1])
            self.added[app] = key
            return "added"
        if key[:1] == ("use",):
            self.current[app] = key[1]
            if (
                app == "claude"
                and key[1] == switcher.SWITCHER_PROVIDER_ID
                and self.writes_claude
            ):
                arguments_added = self.added.get("claude", ())
                env = {
                    "ANTHROPIC_BASE_URL": arguments_added[
                        arguments_added.index("--base-url") + 1
                    ],
                    "ANTHROPIC_AUTH_TOKEN": arguments_added[
                        arguments_added.index("--api-key") + 1
                    ],
                }
                if "--model" in arguments_added:
                    env["ANTHROPIC_MODEL"] = arguments_added[
                        arguments_added.index("--model") + 1
                    ]
                switcher._write_text(".claude/settings.json", json.dumps({"env": env}))
            return ""
        if key[:2] == ("provider", "delete"):
            self.providers[app].discard(key[2])
            return ""
        if key[:3] == ("config", "common", "show"):
            return self.HEADER.format(app=app) + self.snippet[app]
        if key[:3] == ("config", "common", "extract"):
            return self.extracted
        if key[:3] == ("config", "common", "set"):
            self.snippet[app] = open(key[4], encoding="utf-8").read()
            return ""
        return ""

    def made(self, app):
        """The verbs called for one app, in order."""
        return [
            " ".join(key[:3] if key[:1] == ("config",) else key[:2])
            for made_app, key in self.calls
            if made_app == app
        ]


def home_file(tmp_path, relative, text):
    path = tmp_path / "home" / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_a_tool_is_adopted_once_and_the_hub_added_with_its_snippet(
    tmp_path, monkeypatch
):
    home_file(tmp_path, ".claude/settings.json", '{"env": {}, "hooks": {"x": 1}}')
    cli = Cli(extracted='{"hooks": {"x": 1}}')
    wire(monkeypatch, cli)

    switcher._point_at_hub("claude", "http://hub", "k", {"default": "m1", "opus": "mo"})

    assert cli.made("claude") == [
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
    assert cli.snippet["claude"] == '{\n  "hooks": {\n    "x": 1\n  }\n}'
    added = cli.added["claude"]
    assert added[:6] == (
        "provider",
        "add",
        "--id",
        "neutrino",
        "--name",
        "Neutrino Hub",
    )
    assert ("--base-url", "http://hub") == added[6:8]
    assert ("--api-key", "k") == added[8:10]
    assert ("--model", "m1", "--opus-model", "mo") == added[10:14]
    assert added[-1] == "--common-config"
    assert cli.current["claude"] == "neutrino"


def test_codex_is_pointed_at_the_versioned_path_the_responses_api_lives_under(
    monkeypatch, tmp_path
):
    """Codex appends /responses itself; only /v1/responses exists on the hub."""
    home_file(tmp_path, ".claude/settings.json", '{"env": {}}')
    cli = Cli()
    wire(monkeypatch, cli)

    switcher.activate(base_url="http://hub:8317", api_key="k", tool_configs={})

    for app, added in cli.added.items():
        endpoint = added[added.index("--base-url") + 1]
        assert endpoint == (
            "http://hub:8317/v1" if app == "codex" else "http://hub:8317"
        ), app


def test_a_snippet_the_person_set_is_never_replaced(tmp_path, monkeypatch):
    home_file(tmp_path, ".claude/settings.json", "{}")
    cli = Cli(extracted='{"hooks": {"theirs": 1}}')
    cli.snippet["claude"] = '{"permissions": {"allow": ["Bash"]}}'
    monkeypatch.setattr(switcher, "_run", cli)

    switcher._point_at_hub("claude", "http://hub", "k", {})

    verbs = cli.made("claude")
    assert "config common extract" not in verbs
    assert "config common set" not in verbs
    assert cli.snippet["claude"] == '{"permissions": {"allow": ["Bash"]}}'
    assert cli.added["claude"][-1] == "--common-config"


def test_a_tool_with_no_snippet_and_nothing_to_extract_gets_no_flag(
    tmp_path, monkeypatch
):
    home_file(tmp_path, ".gemini/.env", "GEMINI_MODEL=old\n")
    cli = Cli(extracted='{"GEMINI_MODEL": "old"}')
    monkeypatch.setattr(switcher, "_run", cli)

    switcher._point_at_hub("gemini", "http://hub", "k", {"model": "g1"})

    assert cli.snippet["gemini"] == ""
    assert "--common-config" not in cli.added["gemini"]
    assert ("--model", "g1") == cli.added["gemini"][-2:]


def test_a_tool_without_a_file_is_not_adopted_and_is_remembered_as_such(
    tmp_path, monkeypatch
):
    cli = Cli(current="")
    monkeypatch.setattr(switcher, "_run", cli)

    switcher._point_at_hub("codex", "http://hub", "secret-key-value", {"model": "c1"})

    assert "mcp import" not in cli.made("codex")
    record = switcher._read_record("codex")
    assert (record["is_present"], record["previous"]) == (False, "")
    assert record["added"]["flags"] == ["--model", "c1"]
    assert "secret-key-value" not in json.dumps(record)


def test_the_provider_that_was_current_is_recorded_once(tmp_path, monkeypatch):
    home_file(tmp_path, ".claude/settings.json", "{}")
    cli = Cli(current="deepseek")
    platform = wire(monkeypatch, cli)

    switcher._point_at_hub("claude", "http://hub", "k", {"default": "m1"})
    record = switcher._read_record("claude")
    assert (record["is_present"], record["previous"]) == (True, "deepseek")
    assert platform.answered == []

    # Applied again with nothing changed: cc-switch is asked what is
    # current and nothing else; nothing is adopted twice.
    cli.calls.clear()
    switcher._point_at_hub("claude", "http://hub", "k", {"default": "m1"})
    assert cli.made("claude") == ["provider current"]
    assert platform.answered == []

    # Applied again with a change: the record stands, and the hub's entry
    # is switched away from and deleted before being added afresh.
    switcher._point_at_hub("claude", "http://hub", "k", {"default": "m2"})
    assert switcher._read_record("claude")["previous"] == "deepseek"
    assert ("claude", ("use", "deepseek")) in cli.calls
    argv, prompt, answer = platform.answered[0]
    assert argv[1:] == ["--app", "claude", "provider", "delete", "neutrino"]
    assert (prompt, answer) == ("(y/N)", "y\n")
    assert cli.current["claude"] == "neutrino"


def test_codex_effort_is_settled_after_the_switch_only_when_chosen(
    tmp_path, monkeypatch
):
    config = home_file(
        tmp_path, ".codex/config.toml", 'model = "c1"\n[mcp_servers.m]\ncommand = "c"\n'
    )
    wire(monkeypatch, Cli())

    switcher._point_at_hub(
        "codex", "http://hub", "k", {"model": "c1", "model_reasoning_effort": "low"}
    )
    assert config.read_text().splitlines()[0] == 'model_reasoning_effort = "low"'
    assert 'command = "c"' in config.read_text()

    config.write_text('model = "c1"\n')
    switcher._point_at_hub("codex", "http://hub", "k", {"model": "c1"})
    assert config.read_text() == 'model = "c1"\n'


def test_claude_must_end_up_naming_the_hub(tmp_path, monkeypatch):
    home_file(tmp_path, ".claude/settings.json", "{}")
    monkeypatch.setattr(switcher, "_run", Cli(writes_claude=False))

    with pytest.raises(switcher.ToolSwitchError) as caught:
        switcher._point_at_hub("claude", "http://hub", "k", {"default": "m1"})
    assert "did not take" in str(caught.value)


def test_deactivation_switches_back_and_deletes_the_hubs_entry(tmp_path, monkeypatch):
    home_file(tmp_path, ".claude/settings.json", "{}")
    cli = Cli(current="deepseek")
    platform = wire(monkeypatch, cli)
    switcher._point_at_hub("claude", "http://hub", "k", {"default": "m1"})
    cli.calls.clear()

    previous = switcher._point_away("claude")

    assert previous == "deepseek"
    assert cli.made("claude") == [
        "provider list",
        "provider current",
        "use deepseek",
        "provider list",
    ]
    assert platform.answered[-1][0][-2:] == ["delete", "neutrino"]
    assert "neutrino" not in cli.providers["claude"]
    assert switcher._read_record("claude") is None
    assert (tmp_path / "home" / ".claude" / "settings.json").is_file()


def test_a_file_cc_switch_made_is_taken_away_again(tmp_path, monkeypatch):
    cli = Cli(current="")
    platform = wire(monkeypatch, cli)
    switcher._point_at_hub("gemini", "http://hub", "k", {})
    made = home_file(tmp_path, ".gemini/.env", "GEMINI_API_KEY=k\n")
    cli.calls.clear()

    assert switcher._point_away("gemini") == "gemini-official"
    assert not made.exists()
    assert platform.answered[-1][0][-2:] == ["delete", "neutrino"]
    assert ("gemini", ("use", "gemini-official")) in cli.calls


def test_deactivation_with_no_record_still_takes_the_entry_out(monkeypatch):
    cli = Cli()
    cli.providers["codex"].add("neutrino")
    platform = wire(monkeypatch, cli)

    assert switcher._point_away("codex") == ""
    # Not current, so nothing to switch away from: straight to the delete.
    assert cli.made("codex") == ["provider list", "provider current", "provider list"]
    assert platform.answered[-1][0][-2:] == ["delete", "neutrino"]


def test_a_current_hub_with_nothing_before_it_goes_to_the_seeded_provider(
    monkeypatch,
):
    cli = Cli(current="neutrino")
    cli.providers["codex"].add("neutrino")
    wire(monkeypatch, cli)

    assert switcher._drop_provider("codex", "") == "codex-official"
    assert cli.current["codex"] == "codex-official"
    assert "neutrino" not in cli.providers["codex"]


def test_a_hub_entry_that_is_not_there_is_not_deleted(monkeypatch):
    cli = Cli()
    platform = wire(monkeypatch, cli)

    switcher._drop_provider("codex", "default")

    assert cli.made("codex") == ["provider list"]
    assert platform.answered == []


def test_a_delete_that_did_not_take_is_an_error(monkeypatch):
    cli = Cli()
    cli.providers["codex"].add("neutrino")
    monkeypatch.setattr(switcher, "_run", cli)
    switcher._PLATFORM.on_answer = None

    with pytest.raises(switcher.ToolSwitchError) as caught:
        switcher._drop_provider("codex", "default")
    assert "kept" in str(caught.value)


def test_a_platform_without_a_terminal_is_a_typed_error(monkeypatch):
    from neutrino_client.exceptions import PlatformUnsupportedError

    cli = Cli()
    cli.providers["codex"].add("neutrino")
    monkeypatch.setattr(switcher, "_run", cli)
    switcher._PLATFORM.answer_error = PlatformUnsupportedError("no terminal")

    with pytest.raises(switcher.ToolSwitchError) as caught:
        switcher._drop_provider("codex", "default")
    assert "could not answer" in str(caught.value)


def test_the_hubs_row_is_found_by_its_id_cell_alone(monkeypatch):
    cli = Cli()
    cli.providers["claude"] = {"default", "neutrino-mirror"}
    monkeypatch.setattr(switcher, "_run", cli)
    assert switcher._has_provider("claude") is False

    cli.providers["claude"].add("neutrino")
    assert switcher._has_provider("claude") is True


def test_the_snippet_loses_the_providers_own_keys():
    assert switcher._without_own_keys(
        "gemini", '{"GEMINI_MODEL": "old", "MY_OWN": "keep"}'
    ) == ('{\n  "MY_OWN": "keep"\n}')
    assert switcher._without_own_keys("gemini", '{"GEMINI_MODEL": "old"}') == ""
    assert (
        switcher._without_own_keys(
            "codex",
            'model = "old"\napproval_policy = "on-request"\n[mcp_servers.m]\nmodel = "in-section"',
        )
        == 'approval_policy = "on-request"\n[mcp_servers.m]\nmodel = "in-section"'
    )
    assert (
        switcher._without_own_keys("claude", '{"hooks": {"x": 1}}')
        == '{\n  "hooks": {\n    "x": 1\n  }\n}'
    )
    assert switcher._without_own_keys("claude", "") == ""
    assert switcher._without_own_keys("claude", "not json") == ""
    assert switcher._without_own_keys("claude", "[1, 2]") == ""


def test_the_live_payload_takes_each_tools_shape(tmp_path):
    home_file(tmp_path, ".claude/settings.json", '{"hooks": {"x": 1}}')
    home_file(tmp_path, ".codex/config.toml", 'model = "c"\n')
    home_file(tmp_path, ".gemini/.env", "GEMINI_API_KEY=k\nMY_OWN = keep\nbad line\n")

    assert switcher._live_payload("claude") == '{"hooks": {"x": 1}}'
    assert json.loads(switcher._live_payload("codex")) == {
        "config": 'model = "c"\n',
        "auth": {},
    }
    assert json.loads(switcher._live_payload("gemini")) == {
        "env": {"GEMINI_API_KEY": "k", "MY_OWN": "keep"}
    }


def test_an_absent_claude_file_is_an_empty_object():
    assert switcher._live_payload("claude") == "{}"


def test_the_current_provider_is_read_off_its_id_line(monkeypatch):
    monkeypatch.setattr(switcher, "_run", Cli(current="deepseek"))
    assert switcher._current_provider("claude") == "deepseek"
    assert switcher.is_active_for("claude") is False

    monkeypatch.setattr(switcher, "_run", Cli(current=""))
    assert switcher._current_provider("claude") == ""

    monkeypatch.setattr(switcher, "_run", Cli(current="neutrino"))
    assert switcher.is_active_for("claude") is True


def test_the_common_snippet_is_what_stands_past_the_header(monkeypatch):
    cli = Cli()
    cli.snippet["codex"] = 'approval_policy = "on-request"\n'
    monkeypatch.setattr(switcher, "_run", cli)

    assert switcher._common_snippet("codex") == 'approval_policy = "on-request"'
    assert switcher._common_snippet("claude") == ""


def test_the_payload_file_is_gone_afterwards():
    with switcher._payload_file("hello") as path:
        assert open(path, encoding="utf-8").read() == "hello"
    assert not os.path.exists(path)


def test_is_active_is_read_from_the_tools_own_file(tmp_path):
    home_file(
        tmp_path,
        ".claude/settings.json",
        json.dumps(
            {
                "env": {
                    "ANTHROPIC_BASE_URL": "http://hub",
                    "ANTHROPIC_AUTH_TOKEN": "key-1",  # scan: allow
                    "ANTHROPIC_MODEL": "m1",
                }
            }
        ),
    )

    assert switcher.is_active(base_url="http://hub", api_key="key-1", model="m1")
    assert not switcher.is_active(base_url="http://other", api_key="key-1", model="m1")
    assert not switcher.is_active(base_url="http://hub", api_key="rotated", model="m1")
    assert not switcher.is_active(base_url="http://hub", api_key="key-1", model="m2")
    assert not switcher.is_active(base_url="", api_key="", model="")


def test_activation_is_all_or_nothing(monkeypatch):
    """A tool that refuses has every tool switched before it put back."""
    switched = []
    put_back = []

    def refuse_codex(app, base_url, api_key, config):
        if app == "codex":
            raise switcher.ToolSwitchError("no store")
        switched.append(app)

    monkeypatch.setattr(switcher, "_point_at_hub", refuse_codex)
    monkeypatch.setattr(switcher, "_point_away", lambda app: put_back.append(app))

    with pytest.raises(switcher.ToolSwitchError) as caught:
        switcher.activate(base_url="http://hub", api_key="k")

    assert str(caught.value) == "codex: no store"
    assert switched == ["claude"]
    assert put_back == ["claude"]


def test_a_rollback_that_fails_is_named_in_the_refusal(monkeypatch):
    def refuse_codex(app, base_url, api_key, config):
        if app == "codex":
            raise switcher.ToolSwitchError("no store")

    def cannot(app):
        raise switcher.ToolSwitchError("kept")

    monkeypatch.setattr(switcher, "_point_at_hub", refuse_codex)
    monkeypatch.setattr(switcher, "_point_away", cannot)

    with pytest.raises(switcher.ToolSwitchError) as caught:
        switcher.activate(base_url="http://hub", api_key="k")
    assert str(caught.value) == "codex: no store; not put back: claude: kept"


def test_the_note_names_only_the_tools_switched_this_time(monkeypatch):
    monkeypatch.setattr(switcher, "_point_at_hub", lambda *args: True)
    assert switcher.activate(base_url="http://hub", api_key="k") == (
        "claude, codex, gemini"
    )

    monkeypatch.setattr(switcher, "_point_at_hub", lambda app, *args: app == "codex")
    assert switcher.activate(base_url="http://hub", api_key="k") == "codex"

    monkeypatch.setattr(switcher, "_point_at_hub", lambda *args: False)
    assert switcher.activate(base_url="http://hub", api_key="k") == ""


def test_deactivation_names_where_each_tool_went(monkeypatch):
    monkeypatch.setattr(
        switcher, "_point_away", lambda app: {"claude": "deepseek"}.get(app, "")
    )

    assert switcher.deactivate(base_url="http://hub") == (
        "claude → deepseek, codex → unset, gemini → unset"
    )


def test_codex_toml_merge_replaces_top_level_keys_only():
    text = (
        'model = "old"\n'
        "approval = true\n"
        "[model_providers.neutrino]\n"
        'model = "kept-in-section"\n'
    )

    merged = switcher._merge_toml_top_level(
        text, {"model": "m2", "model_reasoning_effort": "high"}
    )

    lines = merged.splitlines()
    assert 'model = "m2"' in lines[:2]
    assert 'model_reasoning_effort = "high"' in lines[:2]
    assert "approval = true" in merged
    assert 'model = "kept-in-section"' in merged
    assert 'model = "old"' not in merged


def test_the_switcher_steps_down_to_nobody():
    import inspect

    source = inspect.getsource(switcher)
    assert "run_as" not in source
    assert "runuser" not in source
    assert "account" not in source.replace("Account", "")
