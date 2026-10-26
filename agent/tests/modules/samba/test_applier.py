"""The share applier's effects, with Samba and the system replaced.

What these pin beside the reads: a missing share folder is made and an
existing one is left as it is; a hand-made ``smb.conf`` is copied to the
backup once, before the first write, and a file the module wrote, or a
second apply, copies nothing; each user's Samba password is set from the
hub's map when it differs from the digest held or Samba holds no
credential, never otherwise, and a user the module set a password for and
the configuration dropped loses its credential, and the account too when the module made it; a configured
user the machine lacks is made as a system account with no home and no
login shell; an account a share writes as that is no account of the
machine's is ``account_unknown``.
"""

import os
import stat

import pytest

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.samba import applier as applier_module
from neutrino_agent.modules.samba.applier import (
    SambaConfigApplier,
    SambaStatusReader,
    SambaUserManager,
    keep_backup,
    password_digest,
    testparm as samba_testparm,
)
from neutrino_agent.modules.samba.config import SambaConfig
from neutrino_agent.modules.shared.subprocess_run import CommandResult

# What Samba 4.15.13 on Ubuntu 22.04 prints; it does not know ``--json``.
SMBSTATUS_4_15_PROCESSES_IDLE = (
    "\nSamba version 4.15.13-Ubuntu\n"
    "PID     Username     Group        Machine                                   Protocol Version  Encryption           Signing              \n"
    "----------------------------------------------------------------------------------------------------------------------------------------\n"
)
SMBSTATUS_4_15_PROCESSES_LIVE = (
    "\nSamba version 4.15.13-Ubuntu\n"
    "PID     Username     Group        Machine                                   Protocol Version  Encryption           Signing              \n"
    "----------------------------------------------------------------------------------------------------------------------------------------\n"
    "190983  ntcap        ntcap        127.0.0.1 (ipv4:127.0.0.1:36814)          SMB3_11           -                    partial(AES-128-GMAC)\n"
    "190982  ntcap        ntcap        127.0.0.1 (ipv4:127.0.0.1:36812)          SMB3_11           -                    partial(AES-128-GMAC)\n"
)
SMBSTATUS_4_15_SHARES_IDLE = (
    "\nService      pid     Machine       Connected at                     Encryption   Signing     \n"
    "---------------------------------------------------------------------------------------------\n"
    "\n"
)
SMBSTATUS_4_15_SHARES_LIVE = (
    "\nService      pid     Machine       Connected at                     Encryption   Signing     \n"
    "---------------------------------------------------------------------------------------------\n"
    "capture      190983  127.0.0.1     Tue Sep 15 12:26:48 AM 2026 CDT  -            -           \n"
    "team space   190982  127.0.0.1     Tue Sep 15 12:26:48 AM 2026 CDT  -            -           \n"
    "\n"
)


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
        applier_module, "SAMBA_CONF_BACKUP_PATH", str(tmp_path / "etc/backup.conf")
    )
    monkeypatch.setattr(
        applier_module, "SAMBA_USERS_DIR", str(tmp_path / "etc/neutrino_users")
    )
    monkeypatch.setattr(
        applier_module.shutil, "which", lambda name: "/usr/bin/testparm"
    )
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
    (tmp_path / "home/ann").mkdir(parents=True)
    os.chmod(tmp_path / "home/ann", 0o700)
    config = SambaConfig.from_dict(
        {
            "shares": [
                {"name": "s", "path": str(tmp_path / "srv/s")},
                {"name": "ann", "path": str(tmp_path / "home/ann")},
            ],
            "users": [],
        }
    )

    note = SambaConfigApplier(unit="smbd.service").apply("[global]\n", config=config)

    assert note == "started"
    assert (tmp_path / "etc/smb.conf").read_text() == "[global]\n"
    assert (tmp_path / "srv/s").is_dir()
    assert stat.S_IMODE(os.stat(tmp_path / "home/ann").st_mode) == 0o700
    assert commands.ran("systemctl", "enable") == [
        (["systemctl", "enable", "--now", "smbd.service"], None)
    ]


def test_apply_writes_each_users_file_and_drops_the_rest(box, monkeypatch):
    commands, tmp_path = box
    users_dir = tmp_path / "etc/neutrino_users"
    users_dir.mkdir(parents=True)
    (users_dir / "old.conf").write_text("   force user = old\n")
    (users_dir / "notes.txt").write_text("kept")
    config = SambaConfig.from_dict({"shares": [], "users": []})

    SambaConfigApplier(unit="smbd.service").apply(
        "[global]\n", config=config, user_files={"ann.conf": "   force user = ann\n"}
    )

    assert sorted(path.name for path in users_dir.iterdir()) == [
        "ann.conf",
        "notes.txt",
    ]
    assert (users_dir / "ann.conf").read_text() == "   force user = ann\n"
    assert stat.S_IMODE(os.stat(users_dir / "ann.conf").st_mode) == 0o644
    assert stat.S_IMODE(os.stat(users_dir).st_mode) == 0o755


def test_a_hand_made_smb_conf_is_kept_aside_once_before_the_first_write(box):
    _, tmp_path = box
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc/smb.conf").write_text("[global]\n   workgroup = HOME\n")
    applier = SambaConfigApplier(unit="smbd.service")

    applier.apply("# Generated by neutrino. x\n", config=SambaConfig())
    (tmp_path / "etc/smb.conf").write_text("[global]\n   by hand again\n")
    applier.apply("# Generated by neutrino. y\n", config=SambaConfig())

    assert (tmp_path / "etc/backup.conf").read_text() == (
        "[global]\n   workgroup = HOME\n"
    )


def test_a_file_the_module_wrote_is_never_kept_aside(box):
    _, tmp_path = box
    (tmp_path / "etc").mkdir()
    marker = applier_module.SAMBA_CONF_MARKER
    (tmp_path / "etc/smb.conf").write_text(f"{marker}\n[global]\n")

    assert keep_backup() is False
    assert not (tmp_path / "etc/backup.conf").exists()


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


def test_stop_stops_the_unit_and_leaves_it_enabled(box):
    commands, _ = box

    SambaConfigApplier(unit="smbd.service").stop()

    assert commands.ran("systemctl") == [(["systemctl", "stop", "smbd.service"], None)]


def users_config(passwords: dict) -> SambaConfig:
    return SambaConfig(users=list(passwords), passwords=dict(passwords))


def test_converge_sets_each_password_that_differs_or_samba_lacks(box):
    commands, _ = box
    commands.answers[("pdbedit", "-L")] = (0, "ann:1000:\nbob:1001:\n")
    held = {
        "ann": password_digest("kept"),
        "bob": password_digest("old"),
    }

    changes, kept = SambaUserManager().converge(
        users_config({"ann": "kept", "bob": "new", "cid": "first"}), held
    )

    assert commands.ran("smbpasswd", "-s") == [
        (["smbpasswd", "-s", "-a", "bob"], "new\nnew\n"),
        (["smbpasswd", "-s", "-a", "cid"], "first\nfirst\n"),
    ]
    assert kept == {
        "ann": password_digest("kept"),
        "bob": password_digest("new"),
        "cid": password_digest("first"),
    }
    assert changes == ["set the password of bob", "set the password of cid"]


def test_a_password_samba_no_longer_holds_is_set_again(box):
    commands, _ = box
    commands.answers[("pdbedit", "-L")] = (0, "")

    SambaUserManager().converge(
        users_config({"ann": "kept"}), {"ann": password_digest("kept")}
    )

    assert [call[0] for call in commands.ran("smbpasswd", "-s")] == [
        ["smbpasswd", "-s", "-a", "ann"]
    ]


def test_a_dropped_user_the_module_set_loses_its_credential_and_no_other(box):
    commands, _ = box
    commands.answers[("pdbedit", "-L")] = (0, "ann:1000:\nold:1001:\nown:1002:\n")

    changes, kept = SambaUserManager().converge(
        users_config({"ann": "pw"}),
        {"ann": password_digest("pw"), "old": password_digest("x")},
    )

    assert commands.ran("smbpasswd", "-x") == [(["smbpasswd", "-x", "old"], None)]
    assert kept == {"ann": password_digest("pw")}
    assert changes == ["retired old"]


def test_a_dropped_user_the_module_made_is_deleted_and_a_persons_is_not(box):
    commands, _ = box
    commands.answers[("pdbedit", "-L")] = (0, "ann:1000:\nold:1001:\nown:1002:\n")
    commands.answers[("getent", "passwd")] = (
        lambda command: (
            (0, f"{command[2]}:x:999:999:neutrino file share:/:/usr/sbin/nologin\n")
            if command[2] == "old"
            else (0, f"{command[2]}:x:1002:1002:A Person:/home/own:/bin/bash\n")
        ),
        "",
    )

    SambaUserManager().converge(
        users_config({"ann": "pw"}),
        {
            "ann": password_digest("pw"),
            "old": password_digest("x"),
            "own": password_digest("y"),
        },
    )

    assert commands.ran("userdel") == [(["userdel", "old"], None)]


def test_a_configured_user_the_machine_lacks_is_made_with_no_home_or_shell(
    box, monkeypatch
):
    commands, _ = box
    commands.answers[("id", "-u")] = (
        lambda command: (0, "") if command[2] == "neutrino-ann" else (1, ""),
        "",
    )
    monkeypatch.setattr(
        applier_module.os.path, "exists", lambda path: path == "/sbin/nologin"
    )

    changes = SambaUserManager().converge_accounts(
        users_config({"neutrino-ann": "pw", "neutrino-bob": "pw"})
    )

    assert commands.ran("useradd") == [
        (
            [
                "useradd",
                "--system",
                "--no-create-home",
                "--shell",
                "/sbin/nologin",
                "--comment",
                "neutrino file share",
                "neutrino-bob",
            ],
            None,
        )
    ]
    assert changes == ["made the user neutrino-bob"]


def test_an_account_a_share_writes_as_that_is_no_account_is_unknown(box):
    commands, _ = box
    commands.answers[("id", "-u")] = (
        lambda command: (0, "") if command[2] == "ann" else (1, ""),
        "",
    )

    SambaUserManager().check_accounts(["ann"])
    with pytest.raises(ModuleApplyError) as refused:
        SambaUserManager().check_accounts(["ann", "ghost"])

    assert (refused.value.code, refused.value.params) == (
        "account_unknown",
        {"account": "ghost"},
    )


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
        '{"sessions": {"1": {"username": "ann", "remote_machine": "pc", '
        '"hostname": "ipv4:192.168.100.7:5000"}}, '
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
    assert commands.ran("smbstatus") == [(["smbstatus", "--json"], None)]


def test_a_smbstatus_without_json_is_read_from_its_tables(box):
    commands, _ = box
    commands.answers[("smbstatus", "--json")] = (1, "")
    commands.answers[("smbstatus", "-p")] = (0, SMBSTATUS_4_15_PROCESSES_LIVE)
    commands.answers[("smbstatus", "-S")] = (0, SMBSTATUS_4_15_SHARES_LIVE)

    assert SambaStatusReader().sessions() == [
        {
            "username": "ntcap",
            "hostname": "127.0.0.1",
            "remote_address": "127.0.0.1",
            "shares": ["capture"],
        },
        {
            "username": "ntcap",
            "hostname": "127.0.0.1",
            "remote_address": "127.0.0.1",
            "shares": ["team space"],
        },
    ]


def test_a_smbstatus_without_json_and_no_visitor_lists_nothing(box):
    commands, _ = box
    commands.answers[("smbstatus", "--json")] = (1, "")
    commands.answers[("smbstatus", "-p")] = (0, SMBSTATUS_4_15_PROCESSES_IDLE)
    commands.answers[("smbstatus", "-S")] = (0, SMBSTATUS_4_15_SHARES_IDLE)

    assert SambaStatusReader().sessions() == []
    assert commands.ran("smbstatus", "-S") == []


def test_output_that_is_neither_json_nor_a_table_lists_nothing(box):
    commands, _ = box
    commands.answers[("smbstatus", "--json")] = (0, "Samba version 4.15.13-Ubuntu\n")
    commands.answers[("smbstatus", "-p")] = (
        0,
        "PID Username\n-----\n(ipv4:127.0.0.1:5000)\n190983 ntcap\n",
    )

    assert SambaStatusReader().sessions() == []
    assert commands.ran("smbstatus", "-S") == []


def test_a_share_table_that_cannot_be_read_leaves_the_sessions_without_shares(box):
    commands, _ = box
    commands.answers[("smbstatus", "--json")] = (1, "")
    commands.answers[("smbstatus", "-p")] = (0, SMBSTATUS_4_15_PROCESSES_LIVE)
    commands.answers[("smbstatus", "-S")] = (0, "-----\ncapture\n\n")

    assert [entry["shares"] for entry in SambaStatusReader().sessions()] == [[], []]


def test_a_down_server_has_no_sessions(box):
    commands, _ = box
    commands.answers[("smbstatus", "--json")] = (1, "")
    commands.answers[("smbstatus", "-p")] = (1, "")

    assert SambaStatusReader().sessions() == []
    assert commands.ran("smbstatus", "-S") == []
