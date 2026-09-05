"""Finding cc-switch without running it, and giving a machine back what it had.

The desktop app is a GUI with no argument parsing, so probing it by asking
for its version would open a window on someone's screen. What these check is
that detection stays a matter of looking at paths, that the copy taken at
activation puts a person's own configuration back exactly, and that acting
on an account nobody reported is refused in both directions alike.
"""

import pytest

from neutrino_agent.services import switcher
from neutrino_agent.platforms.base import AgentPlatform


class ReportingPlatform(AgentPlatform):
    """Reports a fixed set of human accounts."""

    def __init__(self, accounts):
        self._accounts = accounts

    def human_accounts(self):
        return list(self._accounts)


def test_cli_found_at_the_agent_install_path(tmp_path, monkeypatch):
    binary = tmp_path / "cc-switch"
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)
    monkeypatch.setattr(switcher, "SWITCHER_CLI_PATHS", (str(binary),))
    assert switcher.find_cli() == str(binary)


def test_no_cli_when_nothing_is_installed(tmp_path, monkeypatch):
    monkeypatch.setattr(switcher, "SWITCHER_CLI_PATHS", (str(tmp_path / "absent"),))
    monkeypatch.setattr(switcher.shutil, "which", lambda name: None)
    assert switcher.find_cli() is None


def test_a_path_binary_owned_by_the_desktop_package_is_not_the_cli(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(switcher, "SWITCHER_CLI_PATHS", (str(tmp_path / "absent"),))
    monkeypatch.setattr(switcher.shutil, "which", lambda name: "/usr/bin/cc-switch")
    monkeypatch.setattr(switcher, "_is_desktop_owned", lambda path: True)
    assert switcher.find_cli() is None


def test_desktop_install_is_detected_by_its_directory(tmp_path, monkeypatch):
    marker = tmp_path / "cc-switch"
    marker.mkdir()
    monkeypatch.setattr(switcher, "SWITCHER_DESKTOP_MARKERS", (str(marker),))
    assert switcher.find_desktop() is True


def test_installed_means_either_form(tmp_path, monkeypatch):
    monkeypatch.setattr(switcher, "SWITCHER_CLI_PATHS", (str(tmp_path / "absent"),))
    monkeypatch.setattr(switcher.shutil, "which", lambda name: None)
    monkeypatch.setattr(switcher, "SWITCHER_DESKTOP_MARKERS", ())
    assert switcher.is_installed() is False

    marker = tmp_path / "desktop"
    marker.mkdir()
    monkeypatch.setattr(switcher, "SWITCHER_DESKTOP_MARKERS", (str(marker),))
    assert switcher.is_installed() is True


def test_the_original_configuration_comes_back_exactly(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir()
    settings.write_text('{"model": "opus", "permissions": {"allow": ["Bash(ls:*)"]}}')
    settings.chmod(0o600)

    switcher._capture_original("claude", "")
    settings.write_text('{"env": {"ANTHROPIC_BASE_URL": "http://hub"}}')
    settings.chmod(0o644)

    assert switcher._restore_original("claude", "") is True
    assert settings.read_text() == (
        '{"model": "opus", "permissions": {"allow": ["Bash(ls:*)"]}}'
    )
    assert settings.stat().st_mode & 0o777 == 0o600
    assert not (tmp_path / switcher.SWITCHER_ORIGINAL_DIR / "claude.json").exists()


def test_a_machine_that_had_no_configuration_is_left_with_none(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    settings = tmp_path / ".claude" / "settings.json"

    switcher._capture_original("claude", "")
    settings.parent.mkdir()
    settings.write_text('{"env": {"ANTHROPIC_BASE_URL": "http://hub"}}')

    assert switcher._restore_original("claude", "") is True
    assert not settings.exists()


def test_the_copy_is_taken_once_so_reapplying_does_not_overwrite_it(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("HOME", str(tmp_path))
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir()
    settings.write_text('{"model": "opus"}')

    switcher._capture_original("claude", "")
    settings.write_text('{"env": {"ANTHROPIC_MODEL": "deepseek"}}')
    switcher._capture_original("claude", "")

    switcher._restore_original("claude", "")
    assert settings.read_text() == '{"model": "opus"}'


def test_without_a_copy_there_is_nothing_to_put_back(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert switcher._restore_original("claude", "") is False


def test_the_no_target_user_guard_is_symmetric(monkeypatch):
    """Activation and deactivation refuse alike, so a cleanup can never be
    skipped by the same gap that let the setup mis-target."""
    monkeypatch.setattr(switcher, "_PLATFORM", ReportingPlatform(["alice"]))

    for run_as in ("", "ghost"):
        with pytest.raises(switcher.NoTargetUserError) as caught:
            switcher.activate(base_url="http://hub", api_key="k", run_as=run_as)
        assert caught.value.code == "no_target_user"
        with pytest.raises(switcher.NoTargetUserError) as caught:
            switcher.deactivate(run_as=run_as, base_url="http://hub")
        assert caught.value.code == "no_target_user"


def test_a_reported_account_passes_the_guard_both_ways(monkeypatch):
    monkeypatch.setattr(switcher, "_PLATFORM", ReportingPlatform(["alice"]))
    monkeypatch.setattr(switcher, "_add_provider", lambda *a, **k: None)
    monkeypatch.setattr(switcher, "_drop_provider", lambda app, run_as: "")
    monkeypatch.setattr(switcher, "_restore_original", lambda app, run_as: True)
    monkeypatch.setattr(switcher, "_points_at_hub", lambda app, run_as, base_url: False)

    activated = switcher.activate(base_url="http://hub", api_key="k", run_as="alice")
    deactivated = switcher.deactivate(run_as="alice", base_url="http://hub")

    assert "claude" in activated
    assert "as it was" in deactivated


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


def test_the_release_table_answers_by_platform_key():
    entry = switcher.release_entry(["linux-debian-amd64", "linux-amd64", "linux"])
    assert entry["binary"] == "cc-switch"

    assert switcher.release_entry(["linux-armhf", "linux"]) == {}
