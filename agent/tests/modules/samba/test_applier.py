"""The share applier's effects, with Samba and the system replaced."""

import os
import stat

import pytest

from neutrino_agent.modules.base import ModuleApplyError
from neutrino_agent.modules.samba import applier as applier_module
from neutrino_agent.modules.samba.applier import (
    SambaConfigApplier,
    SambaStatusReader,
    SambaUserManager,
    testparm as samba_testparm,
)
from neutrino_agent.modules.samba.config import SambaConfig
from neutrino_agent.modules.subprocess_run import CommandResult


class FakeCommands:
    """Answers scripted commands and records every call."""

    def __init__(self, answers=None):
        self.calls: list = []
        self.answers = dict(answers or {})

    def __call__(self, command, *, is_checked=True, input_text=None, timeout_s=120):
        self.calls.append((list(command), input_text))
        exit_code, stdout = self.answers.get(tuple(command[:2]), (0, ""))
        if callable(exit_code):
            exit_code, stdout = exit_code(command)
        return CommandResult(list(command), exit_code, stdout, "refused")

    def ran(self, *prefix) -> list:
        return [call for call in self.calls if call[0][: len(prefix)] == list(prefix)]


@pytest.fixture
def box(monkeypatch, tmp_path):
    commands = FakeCommands()
    monkeypatch.setattr(applier_module, "run", commands)
    monkeypatch.setattr(
        applier_module, "SAMBA_CONF_PATH", str(tmp_path / "etc/smb.conf")
    )
    monkeypatch.setattr(
        applier_module.shutil, "which", lambda name: "/usr/bin/testparm"
    )
    monkeypatch.setattr(applier_module.shutil, "chown", lambda path, **kw: None)
    monkeypatch.setattr(applier_module, "unit_state", lambda unit: "inactive")
    return commands, tmp_path


def test_testparm_refuses_typed_with_sambas_own_words(box):
    commands, _ = box
    commands.answers[("testparm", "-s")] = (1, "")

    with pytest.raises(ModuleApplyError) as refused:
        samba_testparm("[global]\n")

    assert refused.value.code == "samba_config_rejected"
    assert refused.value.params["detail"] == "refused"


def test_a_missing_testparm_is_samba_missing(box, monkeypatch):
    monkeypatch.setattr(applier_module.shutil, "which", lambda name: None)

    with pytest.raises(ModuleApplyError) as refused:
        samba_testparm("[global]\n")

    assert refused.value.code == "samba_missing"


def test_apply_validates_writes_the_file_and_starts_the_unit(box):
    commands, tmp_path = box
    config = SambaConfig.from_dict(
        {"shares": [{"name": "s", "path": str(tmp_path / "srv/s")}], "users": []}
    )

    note = SambaConfigApplier(unit="smbd.service").apply("[global]\n", config=config)

    assert note == "started"
    assert (tmp_path / "etc/smb.conf").read_text() == "[global]\n"
    assert stat.S_IMODE(os.stat(tmp_path / "srv/s").st_mode) == 0o2775
    assert commands.ran("systemctl", "enable") == [
        (["systemctl", "enable", "--now", "smbd.service"], None)
    ]


def test_apply_reloads_a_running_unit_rather_than_restarting(box, monkeypatch):
    commands, _ = box
    monkeypatch.setattr(applier_module, "unit_state", lambda unit: "active")

    note = SambaConfigApplier(unit="smb.service").apply(
        "[global]\n", config=SambaConfig()
    )

    assert note == "reloaded"
    assert commands.ran("systemctl") == [(["systemctl", "reload", "smb.service"], None)]


def test_a_rejected_render_never_reaches_the_live_file(box):
    commands, tmp_path = box
    commands.answers[("testparm", "-s")] = (1, "")

    with pytest.raises(ModuleApplyError):
        SambaConfigApplier(unit="smbd.service").apply("bad", config=SambaConfig())

    assert not (tmp_path / "etc/smb.conf").exists()


def test_stop_disables_the_unit(box):
    commands, _ = box

    SambaConfigApplier(unit="smbd.service").stop()

    assert commands.ran("systemctl") == [
        (["systemctl", "disable", "--now", "smbd.service"], None)
    ]


def test_converge_creates_missing_accounts_and_retires_dropped_ones(box):
    commands, _ = box
    commands.answers[("id", "-u")] = (
        lambda command: (0, "") if command[2] == "ann" else (1, ""),
        "",
    )
    commands.answers[("id", "-nG")] = (0, "ann\n")
    commands.answers[("pdbedit", "-L")] = (0, "ann:1000:\nold:1001:\n")

    changes = SambaUserManager().converge(["ann", "bob"])

    assert commands.ran("useradd") == [
        (["useradd", "--no-create-home", "--shell", "/usr/sbin/nologin", "bob"], None)
    ]
    assert commands.ran("usermod") == [
        (["usermod", "-aG", "sambashare", "ann"], None),
        (["usermod", "-aG", "sambashare", "bob"], None),
    ]
    assert commands.ran("smbpasswd", "-x") == [(["smbpasswd", "-x", "old"], None)]
    assert "retired old" in changes


def test_set_password_feeds_smbpasswd_on_stdin_and_enables(box):
    commands, _ = box

    SambaUserManager().set_password("ann", "s3cret")

    assert commands.ran("smbpasswd", "-s") == [
        (["smbpasswd", "-s", "-a", "ann"], "s3cret\ns3cret\n")
    ]
    assert commands.ran("smbpasswd", "-e") == [(["smbpasswd", "-e", "ann"], None)]


def test_survey_reads_presence_and_credentials(box):
    commands, _ = box
    commands.answers[("id", "-u")] = (
        lambda command: (0, "") if command[2] == "ann" else (1, ""),
        "",
    )
    commands.answers[("pdbedit", "-L")] = (0, "ann:1000:\n")

    states = SambaUserManager().survey(["ann", "bob"])

    assert [(s.name, s.is_present, s.has_password) for s in states] == [
        ("ann", True, True),
        ("bob", False, False),
    ]


def test_sessions_come_from_smbstatus_json(box):
    commands, _ = box
    commands.answers[("smbstatus", "--json")] = (
        0,
        '{"sessions": {"1": {"username": "ann", "hostname": "pc", '
        '"remote_machine": "ipv4:192.168.100.7:5000"}}, '
        '"tcons": {"a": {"session_id": 1, "service": "share"}}}',
    )

    assert SambaStatusReader().sessions() == [
        {
            "username": "ann",
            "hostname": "pc",
            "remote_address": "192.168.100.7",
            "shares": ["share"],
        }
    ]


def test_a_down_server_has_no_sessions(box):
    commands, _ = box
    commands.answers[("smbstatus", "--json")] = (1, "")

    assert SambaStatusReader().sessions() == []
