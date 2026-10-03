"""VS Code's servers on Linux, with systemd and the account database faked.

What these pin: the template unit runs the CLI as ``User=%i`` from the
account's environment file; each instance's token belongs to its account,
mode 0600; an unknown account is refused before anything is written; a new
or changed instance is restarted and an unchanged one only kept up; an
instance no longer named is disabled and its files deleted; and each state
is read off its unit.
"""

import os
import stat

import pytest

import neutrino_agent.modules.vscode.linux_applier as applier_module
from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.subprocess_run import CommandResult
from neutrino_agent.modules.vscode.config import VscodeConfig
from neutrino_agent.modules.vscode.linux_applier import (
    VscodeLinuxApplier,
    render_unit,
)

CONFIG = VscodeConfig.from_dict(
    {
        "address": "192.168.1.5",
        "instances": [{"account": "ann", "port": 8000, "token": "t-ann"}],
    }
)


class Systemd:
    """systemctl, recorded; every unit the test names active reads active."""

    def __init__(self):
        self.calls: list = []
        self.active: set = set()

    def __call__(self, command, *, is_checked=True, input_text=None, timeout_s=0):
        self.calls.append(list(command))
        return CommandResult(list(command), 0, "", "")

    def unit_state(self, unit):
        return "active" if unit in self.active else "inactive"


@pytest.fixture
def systemd(monkeypatch):
    held = Systemd()
    monkeypatch.setattr(applier_module, "unit_state", held.unit_state)
    return held


@pytest.fixture
def applier(systemd, tmp_path):
    owners = []
    (tmp_path / "systemd").mkdir()

    def lookup(account):
        if account != "ann":
            raise KeyError(account)
        return 1000, 1000

    def chown(path, uid, gid):
        owners.append((os.path.basename(path), uid, gid))

    held = VscodeLinuxApplier(
        run=systemd,
        lookup_account=lookup,
        chown=chown,
        cli_dir="/usr/local/lib/neutrino_vscode",
        token_dir=str(tmp_path / "vscode"),
        systemd_dir=str(tmp_path / "systemd"),
        sysctl_path=str(tmp_path / "sysctl.d" / "90-neutrino-vscode.conf"),
        proc_dir=str(tmp_path / "proc"),
    )
    held.owners = owners
    return held


def limits(tmp_path, watches, instances):
    """What the kernel reports for the two inotify limits."""
    inotify = tmp_path / "proc" / "fs" / "inotify"
    inotify.mkdir(parents=True, exist_ok=True)
    (inotify / "max_user_watches").write_text(f"{watches}\n")
    (inotify / "max_user_instances").write_text(f"{instances}\n")


def test_the_template_runs_the_cli_as_the_account_from_its_environment():
    unit = render_unit(
        "/var/lib/neutrino/agent/vscode/code", "/var/lib/neutrino/agent/vscode/tokens"
    )

    assert "User=%i\n" in unit
    assert "EnvironmentFile=/var/lib/neutrino/agent/vscode/tokens/%i.env\n" in unit
    assert (
        "ExecStart=/var/lib/neutrino/agent/vscode/code serve-web "
        "--accept-server-license-terms --host ${VSCODE_HOST} --port ${VSCODE_PORT} "
        "--connection-token-file ${VSCODE_TOKEN_FILE}\n"
    ) in unit


def test_an_instance_gets_its_token_its_environment_and_its_unit(
    applier, systemd, tmp_path
):
    notes = applier.apply(CONFIG)

    token = tmp_path / "vscode" / "ann.token"
    assert token.read_text() == "t-ann"
    assert stat.S_IMODE(os.stat(token).st_mode) == 0o600
    assert applier.owners == [("ann.token", 1000, 1000)]
    assert (tmp_path / "vscode" / "ann.env").read_text() == (
        f"VSCODE_HOST=192.168.1.5\nVSCODE_PORT=8000\nVSCODE_TOKEN_FILE={token}\n"
    )
    assert (tmp_path / "systemd" / "neutrino_vscode@.service").is_file()
    assert systemd.calls == [
        ["systemctl", "daemon-reload"],
        ["systemctl", "enable", "neutrino_vscode@ann.service"],
        ["systemctl", "restart", "neutrino_vscode@ann.service"],
    ]
    assert notes == ["started the server of ann"]


def test_an_unchanged_instance_is_only_kept_up(applier, systemd):
    applier.apply(CONFIG)
    systemd.calls.clear()

    assert applier.apply(CONFIG) == []

    assert systemd.calls == [
        ["systemctl", "enable", "--now", "neutrino_vscode@ann.service"]
    ]


def test_an_account_the_machine_lacks_is_refused_before_anything_is_written(
    applier, systemd, tmp_path
):
    config = VscodeConfig.from_dict(
        {"instances": [{"account": "ghost", "port": 8000, "token": "t"}]}
    )

    with pytest.raises(ModuleApplyError) as refused:
        applier.apply(config)

    assert refused.value.code == "account_unknown"
    assert refused.value.params == {"account": "ghost"}
    assert systemd.calls == []
    assert not (tmp_path / "vscode").exists()


def test_an_instance_no_longer_named_is_disabled_and_forgotten(
    applier, systemd, tmp_path
):
    applier.apply(CONFIG)
    systemd.calls.clear()

    applier.apply(VscodeConfig())

    assert ["systemctl", "disable", "--now", "neutrino_vscode@ann.service"] in (
        systemd.calls
    )
    assert os.listdir(tmp_path / "vscode") == []


def test_the_states_read_each_unit_and_the_env_files_without_a_config(applier, systemd):
    applier.apply(CONFIG)
    systemd.active.add("neutrino_vscode@ann.service")

    assert applier.states(CONFIG) == [
        {
            "account": "ann",
            "port": 8000,
            "url": "http://192.168.1.5:8000/",
            "is_running": True,
            "code": "",
        }
    ]
    assert applier.states(None)[0]["port"] == 8000
    assert applier.units() == ["neutrino_vscode@ann.service"]


def test_stop_and_remove_act_on_every_instance(applier, systemd, tmp_path):
    applier.apply(CONFIG)
    systemd.calls.clear()

    applier.stop()
    assert systemd.calls == [["systemctl", "stop", "neutrino_vscode@ann.service"]]

    applier.remove()
    assert not (tmp_path / "systemd" / "neutrino_vscode@.service").exists()
    assert applier.units() == []


def test_low_inotify_limits_are_raised_to_the_floors(applier, systemd, tmp_path):
    limits(tmp_path, 65536, 128)
    (tmp_path / "sysctl.d").mkdir()

    notes = applier.apply(CONFIG)

    drop_in = (tmp_path / "sysctl.d" / "90-neutrino-vscode.conf").read_text()
    assert drop_in == (
        "fs.inotify.max_user_watches = 524288\nfs.inotify.max_user_instances = 512\n"
    )
    assert ["sysctl", "-p", str(tmp_path / "sysctl.d" / "90-neutrino-vscode.conf")] in (
        systemd.calls
    )
    assert "raised the inotify limits" in notes


def test_limits_already_high_enough_are_left_alone(applier, systemd, tmp_path):
    limits(tmp_path, 1048576, 1024)
    (tmp_path / "sysctl.d").mkdir()

    applier.apply(CONFIG)

    assert not (tmp_path / "sysctl.d" / "90-neutrino-vscode.conf").exists()
    assert not any(call[0] == "sysctl" for call in systemd.calls)


def test_only_the_limit_below_its_floor_is_raised(applier, tmp_path):
    limits(tmp_path, 1048576, 128)
    (tmp_path / "sysctl.d").mkdir()

    applier.apply(CONFIG)

    drop_in = (tmp_path / "sysctl.d" / "90-neutrino-vscode.conf").read_text()
    assert drop_in == "fs.inotify.max_user_instances = 512\n"


def test_remove_deletes_the_sysctl_drop_in(applier, tmp_path):
    limits(tmp_path, 65536, 128)
    (tmp_path / "sysctl.d").mkdir()
    applier.apply(CONFIG)

    applier.remove()

    assert not (tmp_path / "sysctl.d" / "90-neutrino-vscode.conf").exists()
