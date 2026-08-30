"""Finding cc-switch without running it, and giving a machine back what it had.

The desktop app is a GUI with no argument parsing, so probing it by asking
for its version would open a window on someone's screen. What these check is
that detection stays a matter of looking at paths, and that the copy taken at
activation puts a person's own configuration back exactly.
"""

from neutrino_agent import switcher


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
