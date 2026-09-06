"""The cc_switch module: unpack the handed archive, remove the CLI, verify.

Nothing here fetches: the hub's cache resolved the release and handed the
archive down. Verify asks the service layer's detection for the CLI alone —
the desktop app cannot be driven, so it is not what the module manages.
"""

import os

import pytest

from neutrino_agent.modules.installers import InstallError
from neutrino_agent.modules import switcher as switcher_module
from neutrino_agent.modules.switcher import (
    SwitcherModuleRunner,
    install_cli,
    uninstall_cli,
)
from neutrino_agent.platforms.base import AgentPlatform
from neutrino_agent.services import switcher as switcher_service
from tests.conftest import discard


def _staged(workdir: str, binary_name: str) -> str:
    """A binary already unpacked, standing in for a real archive."""
    staged = os.path.join(workdir, binary_name)
    with open(staged, "wb") as stream:
        stream.write(b"#!/bin/sh\n")
    return staged


def test_install_unpacks_an_archive_it_is_handed(monkeypatch, tmp_path):
    entry = {"binary": "cc-switch", "package_kind": "tar_binary"}
    archive = tmp_path / "switcher.archive"
    archive.write_bytes(b"not really a tarball")
    monkeypatch.setattr(switcher_module, "SWITCHER_INSTALL_DIR", str(tmp_path / "bin"))
    monkeypatch.setattr(
        switcher_module,
        "_extract_binary",
        lambda archive_path, workdir, binary_name, kind: _staged(workdir, binary_name),
    )

    destination = install_cli(entry, str(archive))

    assert destination == str(tmp_path / "bin" / "cc-switch")
    assert os.path.isfile(destination)


def test_install_with_no_build_for_this_machine_is_refused(tmp_path):
    with pytest.raises(InstallError):
        install_cli({}, str(tmp_path / "archive"))


def test_switcher_install_dir_is_windows_native_on_windows(monkeypatch):
    import importlib

    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setenv("ProgramData", "C:\\ProgramData")
    try:
        reloaded = importlib.reload(switcher_module)
        # Never the POSIX bin, which lands off any search path on Windows.
        assert reloaded.SWITCHER_INSTALL_DIR != "/usr/local/bin"
        assert reloaded.SWITCHER_INSTALL_DIR == os.path.join(
            "C:\\ProgramData", "Neutrino", "bin"
        )
        # The detection paths follow the install dir, so both sides agree.
        assert reloaded.SWITCHER_CLI_PATHS[1].startswith(reloaded.SWITCHER_INSTALL_DIR)
        assert reloaded.SWITCHER_CLI_PATHS[1].endswith("cc-switch.exe")
    finally:
        monkeypatch.undo()
        importlib.reload(switcher_module)


def test_uninstall_cli_removes_the_agents_binary(tmp_path, monkeypatch):
    binary = tmp_path / "cc-switch"
    binary.write_text("#!/bin/sh\n")
    monkeypatch.setattr(
        switcher_module, "SWITCHER_CLI_PATHS", (str(binary), str(tmp_path / "absent"))
    )

    uninstall_cli()

    assert not binary.exists()
    uninstall_cli()


def test_the_runner_verifies_by_the_cli_alone(monkeypatch):
    runner = SwitcherModuleRunner(platform=AgentPlatform(), log=discard)
    monkeypatch.setattr(switcher_service, "find_cli", lambda: None)
    monkeypatch.setattr(switcher_service, "find_desktop", lambda: True)

    # The desktop app alone cannot be driven, so it does not count.
    assert runner.verify({"entry": {}}) is False

    monkeypatch.setattr(switcher_service, "find_cli", lambda: "/usr/local/bin/x")
    assert runner.verify({"entry": {}}) is True


def test_the_runner_installs_and_uninstalls_through_the_module(monkeypatch, tmp_path):
    runner = SwitcherModuleRunner(platform=AgentPlatform(), log=discard)
    calls = []
    monkeypatch.setattr(
        switcher_module,
        "install_cli",
        lambda entry, archive: calls.append(("install", entry, archive)),
    )
    monkeypatch.setattr(
        switcher_module, "uninstall_cli", lambda: calls.append(("uninstall",))
    )

    entry = {"binary": "cc-switch", "package_kind": "tar_binary"}
    runner.install({"entry": entry}, str(tmp_path / "archive"))
    runner.uninstall({"entry": entry})

    assert calls == [
        ("install", entry, str(tmp_path / "archive")),
        ("uninstall",),
    ]
