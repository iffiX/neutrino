"""Finding cc-switch and giving the person back what they had.

The carried CLI wins over one on the path; every file operation is the
standard library's own on this person's home, with no step-down anywhere;
the copy taken at activation puts the configuration back exactly.
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


def test_a_refusing_cli_is_a_switcher_error(monkeypatch):
    monkeypatch.setattr(bundled, "cc_switch_path", lambda: "/opt/cc-switch")
    monkeypatch.setattr(
        switcher.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command, 1, stdout="", stderr="no store"
        ),
    )

    with pytest.raises(switcher.SwitcherError) as caught:
        switcher._run(["use", "x"], "claude")
    assert "no store" in str(caught.value)
    assert switcher._run(["use", "x"], "claude", is_checked=False) == ""


def test_the_original_configuration_comes_back_exactly(tmp_path):
    settings = tmp_path / "home" / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text('{"model": "opus", "permissions": {"allow": ["Bash(ls:*)"]}}')
    settings.chmod(0o600)

    switcher._capture_original("claude")
    settings.write_text('{"env": {"ANTHROPIC_BASE_URL": "http://hub"}}')
    settings.chmod(0o644)

    assert switcher._restore_original("claude") is True
    assert settings.read_text() == (
        '{"model": "opus", "permissions": {"allow": ["Bash(ls:*)"]}}'
    )
    assert settings.stat().st_mode & 0o777 == 0o600
    assert not os.path.exists(switcher._original_path("claude"))


def test_the_copy_lives_under_the_clients_own_configuration(tmp_path):
    settings = tmp_path / "home" / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text("{}")

    switcher._capture_original("claude")

    kept = tmp_path / "config" / "original" / "claude.json"
    assert kept.is_file()
    assert json.loads(kept.read_text())["is_present"] is True


def test_a_person_who_had_no_configuration_is_left_with_none(tmp_path):
    settings = tmp_path / "home" / ".claude" / "settings.json"

    switcher._capture_original("claude")
    settings.parent.mkdir(parents=True)
    settings.write_text('{"env": {"ANTHROPIC_BASE_URL": "http://hub"}}')

    assert switcher._restore_original("claude") is True
    assert not settings.exists()


def test_the_copy_is_taken_once_so_reapplying_does_not_overwrite_it(tmp_path):
    settings = tmp_path / "home" / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text('{"model": "opus"}')

    switcher._capture_original("claude")
    settings.write_text('{"env": {"ANTHROPIC_MODEL": "deepseek"}}')
    switcher._capture_original("claude")

    switcher._restore_original("claude")
    assert settings.read_text() == '{"model": "opus"}'


def test_without_a_copy_there_is_nothing_to_put_back():
    assert switcher._restore_original("claude") is False


def test_stripping_hub_keys_leaves_the_persons_own(tmp_path):
    settings = tmp_path / "home" / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(
        json.dumps(
            {
                "model": "opus",
                "env": {
                    "ANTHROPIC_BASE_URL": "http://hub",
                    "ANTHROPIC_AUTH_TOKEN": "key-1",  # scan: allow
                    "ANTHROPIC_API_KEY": "key-2",  # scan: allow
                    "EDITOR": "vim",
                },
            }
        )
    )

    switcher._strip_hub_keys("claude")

    assert json.loads(settings.read_text()) == {
        "model": "opus",
        "env": {"EDITOR": "vim"},
    }


def test_is_active_is_read_from_the_tools_own_file(tmp_path):
    settings = tmp_path / "home" / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(
        json.dumps(
            {
                "env": {
                    "ANTHROPIC_BASE_URL": "http://hub",
                    "ANTHROPIC_AUTH_TOKEN": "key-1",  # scan: allow
                    "ANTHROPIC_MODEL": "m1",
                }
            }
        )
    )

    assert switcher.is_active(base_url="http://hub", api_key="key-1", model="m1")
    assert not switcher.is_active(base_url="http://other", api_key="key-1", model="m1")
    assert not switcher.is_active(base_url="http://hub", api_key="rotated", model="m1")
    assert not switcher.is_active(base_url="http://hub", api_key="key-1", model="m2")
    assert not switcher.is_active(base_url="", api_key="", model="")


def test_activation_survives_a_tool_that_refuses(monkeypatch):
    def add_except_claude(app, base_url, api_key, config):
        if app == "claude":
            raise switcher.SwitcherError("no store")

    monkeypatch.setattr(switcher, "_add_provider", add_except_claude)
    note = switcher.activate(base_url="http://hub", api_key="k")
    assert note == "codex, gemini (1 not set up here)"

    def refuse(app, base_url, api_key, config):
        raise switcher.SwitcherError(f"{app} refused")

    monkeypatch.setattr(switcher, "_add_provider", refuse)
    with pytest.raises(switcher.SwitcherError) as caught:
        switcher.activate(base_url="http://hub", api_key="k")
    assert "claude" in str(caught.value)


def test_deactivation_ends_with_no_tool_calling_the_hub(monkeypatch):
    monkeypatch.setattr(switcher, "_drop_provider", lambda app: "deepseek")
    monkeypatch.setattr(switcher, "_restore_original", lambda app: True)
    monkeypatch.setattr(
        switcher, "_points_at_hub", lambda app, base_url: app == "claude"
    )
    stripped = []
    monkeypatch.setattr(switcher, "_strip_hub_keys", lambda app: stripped.append(app))

    note = switcher.deactivate(base_url="http://hub")

    assert stripped == ["claude"]
    assert note == "claude → as it was, codex → as it was, gemini → as it was"


def test_the_claude_env_names_every_chosen_slot():
    env = switcher._hub_env(
        {"env": {"KEEP": "1", "ANTHROPIC_API_KEY": "old"}},
        "http://hub",
        "key-1",
        {"default": "m1", "opus": "m2", "sonnet": "", "haiku": "m3"},
    )

    assert env["ANTHROPIC_BASE_URL"] == "http://hub"
    assert env["ANTHROPIC_AUTH_TOKEN"] == "key-1"
    assert env["ANTHROPIC_MODEL"] == "m1"
    assert env["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "m2"
    assert env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "m3"
    assert "ANTHROPIC_DEFAULT_SONNET_MODEL" not in env
    assert env["KEEP"] == "1" and "ANTHROPIC_API_KEY" not in env


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


def test_gemini_env_merge_sets_one_line():
    merged = switcher._merge_env_line(
        "GEMINI_API_KEY=k\nGEMINI_MODEL=old\n", "GEMINI_MODEL", "m3"
    )

    assert merged == "GEMINI_API_KEY=k\nGEMINI_MODEL=m3\n"


def test_the_switcher_steps_down_to_nobody():
    import inspect

    source = inspect.getsource(switcher)
    assert "run_as" not in source
    assert "runuser" not in source
    assert "account" not in source.replace("Account", "")
