"""VS Code's servers on macOS, with launchd and the account database faked.

What these pin: each instance is a LaunchDaemon whose plist names the
account in ``UserName`` and runs the CLI with its host, port and token
file, its output in the account's log file; the token and the log belong to
the account, mode 0600; a changed plist or a job launchd does not hold is
loaded again; an instance no longer named is unloaded and its files
deleted; and a state reads launchd's own word.
"""

import os
import plistlib
import stat

import pytest

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.subprocess_run import CommandResult
from neutrino_agent.modules.vscode.config import VscodeConfig
from neutrino_agent.modules.vscode.darwin_applier import VscodeDarwinApplier

CONFIG = VscodeConfig.from_dict(
    {
        "address": "",
        "instances": [{"account": "ann", "port": 8000, "token": "t-ann"}],
    }
)
LABEL = "com.neutrino.vscode.ann"


class Launchd:
    """launchctl, recorded; a label in ``loaded`` prints as running."""

    def __init__(self):
        self.calls: list = []
        self.loaded: set = set()

    def __call__(self, command, *, is_checked=True, input_text=None, timeout_s=0):
        command = list(command)
        self.calls.append(command)
        if command[:2] == ["launchctl", "print"]:
            label = command[2].split("/", 1)[1]
            if label not in self.loaded:
                return CommandResult(command, 113, "", "")
            return CommandResult(command, 0, "\tstate = running\n", "")
        if command[:2] == ["launchctl", "bootstrap"]:
            self.loaded.add(os.path.basename(command[3])[: -len(".plist")])
        return CommandResult(command, 0, "", "")


@pytest.fixture
def launchd():
    return Launchd()


@pytest.fixture
def applier(launchd, tmp_path):
    owners = []
    (tmp_path / "LaunchDaemons").mkdir()

    def lookup(account):
        if account != "ann":
            raise KeyError(account)
        return 501, 20

    held = VscodeDarwinApplier(
        root=str(tmp_path / "Neutrino"),
        run=launchd,
        lookup_account=lookup,
        chown=lambda path, uid, gid: owners.append((uid, gid)),
        launchd_dir=str(tmp_path / "LaunchDaemons"),
        log_dir=str(tmp_path / "Logs"),
    )
    held.owners = owners
    return held


def test_an_instance_is_a_launch_daemon_of_its_account(applier, launchd, tmp_path):
    notes = applier.apply(CONFIG)

    plist_path = tmp_path / "LaunchDaemons" / f"{LABEL}.plist"
    plist = plistlib.loads(plist_path.read_bytes())
    token = tmp_path / "Neutrino" / "vscode" / "tokens" / "ann.token"
    assert plist["Label"] == LABEL
    assert plist["UserName"] == "ann"
    assert plist["ProgramArguments"] == [
        str(tmp_path / "Neutrino" / "vscode" / "code"),
        "serve-web",
        "--accept-server-license-terms",
        "--host",
        "127.0.0.1",
        "--port",
        "8000",
        "--connection-token-file",
        str(token),
    ]
    assert plist["RunAtLoad"] is True and plist["KeepAlive"] is True
    log = tmp_path / "Logs" / "vscode_ann.log"
    assert plist["StandardOutPath"] == str(log)
    assert plist["StandardErrorPath"] == str(log)
    assert token.read_text() == "t-ann"
    assert stat.S_IMODE(os.stat(token).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(log).st_mode) == 0o600
    assert applier.owners == [(501, 20), (501, 20)]
    assert ["launchctl", "bootstrap", "system", str(plist_path)] in launchd.calls
    assert notes == ["started the server of ann"]


def test_an_unchanged_loaded_instance_is_left_running(applier, launchd):
    applier.apply(CONFIG)
    launchd.calls.clear()

    assert applier.apply(CONFIG) == []

    assert [call for call in launchd.calls if call[1] != "print"] == []


def test_an_account_the_mac_lacks_is_refused(applier, launchd):
    config = VscodeConfig.from_dict(
        {"instances": [{"account": "ghost", "port": 8000, "token": "t"}]}
    )

    with pytest.raises(ModuleApplyError) as refused:
        applier.apply(config)

    assert refused.value.code == "account_unknown"
    assert launchd.calls == []


def test_an_instance_no_longer_named_is_unloaded_and_forgotten(
    applier, launchd, tmp_path
):
    applier.apply(CONFIG)

    applier.apply(VscodeConfig())

    assert ["launchctl", "bootout", f"system/{LABEL}"] in launchd.calls
    assert os.listdir(tmp_path / "LaunchDaemons") == []
    assert os.listdir(tmp_path / "Logs") == []


def test_an_apply_keeps_what_the_log_holds(applier, tmp_path):
    applier.apply(CONFIG)
    log = tmp_path / "Logs" / "vscode_ann.log"
    log.write_text("listening\n")

    applier.apply(CONFIG)

    assert log.read_text() == "listening\n"


def test_the_log_paths_name_each_instance_with_or_without_a_config(applier, tmp_path):
    applier.apply(CONFIG)
    expected = [("ann", str(tmp_path / "Logs" / "vscode_ann.log"))]

    assert applier.log_paths(CONFIG) == expected
    assert applier.log_paths(None) == expected


def test_the_states_read_launchd_and_the_plists_without_a_config(applier, launchd):
    applier.apply(CONFIG)

    (state,) = applier.states(CONFIG)
    assert state == {
        "account": "ann",
        "port": 8000,
        "url": "http://127.0.0.1:8000/",
        "is_running": True,
        "code": "",
    }
    assert applier.states(None)[0]["port"] == 8000
    launchd.loaded.clear()
    assert applier.states(CONFIG)[0]["is_running"] is False


def test_stop_unloads_and_remove_deletes(applier, launchd, tmp_path):
    applier.apply(CONFIG)
    launchd.calls.clear()

    applier.stop()
    assert launchd.calls == [["launchctl", "bootout", f"system/{LABEL}"]]

    applier.remove()
    assert os.listdir(tmp_path / "LaunchDaemons") == []
