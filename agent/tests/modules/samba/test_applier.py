"""The share applier's effects, with Samba and the system replaced.

What these pin beside the reads: a missing share folder is made and an
existing one is left as it is; ``smb.conf`` stays the person's and gets
the module's include line once, after its ``[global]`` header; a missing
``smb.conf`` is the distribution's stock file with the line; a whole
``smb.conf`` an earlier version rendered is the person's and only gets the
line; the module's shares go to its own file; an uninstall deletes that
file and takes the line out; the sweep takes every ``neutrino-`` user and
credential off the machine; the person's own
configuration refuses a taken share name and the global settings that stop
the module's shares; each user's Samba password is set from the hub's map
when it differs from the digest held or Samba holds no credential, never
otherwise, and a user the module set a password for and the configuration
dropped loses its credential, and the account too when the module made it;
a configured user the machine lacks is made as a system account with no
home and no login shell; an account a share writes as that is no account
of the machine's is ``account_unknown``.
"""

import os
import stat

import pytest

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.samba import applier as applier_module
from neutrino_agent.modules.samba.applier import (
    SambaConfigApplier,
    SambaConfigReader,
    SambaStatusReader,
    SambaUserManager,
    check_person_config,
    password_digest,
    plan_smb_conf,
    testparm as samba_testparm,
    without_include_line,
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


STOCK = "[global]\n   workgroup = WORKGROUP\n\n[printers]\n   path = /var/spool/samba\n"


def one_share(tmp_path) -> SambaConfig:
    return SambaConfig.from_dict(
        {
            "shares": [
                {"name": "s", "path": str(tmp_path / "srv/s"), "valid_users": ["u"]}
            ],
            "users": ["u"],
        }
    )


INCLUDE = "   include = "
MARKER = applier_module.SAMBA_CONF_MARKER


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
        applier_module, "SAMBA_MODULE_CONF_PATH", str(tmp_path / "etc/neutrino.conf")
    )
    monkeypatch.setattr(
        applier_module, "SAMBA_STOCK_CONF_PATHS", (str(tmp_path / "stock/smb.conf"),)
    )
    (tmp_path / "stock").mkdir()
    (tmp_path / "stock/smb.conf").write_text(STOCK)
    monkeypatch.setattr(
        applier_module, "SAMBA_USERS_DIR", str(tmp_path / "etc/neutrino_users")
    )
    monkeypatch.setattr(
        applier_module.shutil, "which", lambda name: "/usr/bin/testparm"
    )
    monkeypatch.setattr(applier_module, "unit_state", lambda unit: "inactive")
    monkeypatch.setattr(applier_module, "pwd", None)
    return commands, tmp_path


def test_testparm_refuses_typed_with_sambas_own_words(box):
    commands, _ = box
    commands.answers[("testparm", "-s")] = (1, "")

    with pytest.raises(ModuleApplyError) as refused:
        samba_testparm("[global]\n", "[global]\n")

    assert refused.value.code == "samba_config_rejected"
    assert refused.value.params["detail"] == "refused"


def test_a_missing_testparm_is_samba_missing(box, monkeypatch):
    monkeypatch.setattr(applier_module.shutil, "which", lambda name: None)

    with pytest.raises(ModuleApplyError) as refused:
        samba_testparm("[global]\n", "[global]\n")

    assert refused.value.code == "samba_missing"


def test_apply_writes_the_modules_file_and_gives_a_machine_without_smb_conf_the_stock_one(
    box,
):
    commands, tmp_path = box
    (tmp_path / "home/ann").mkdir(parents=True)
    os.chmod(tmp_path / "home/ann", 0o700)
    config = SambaConfig.from_dict(
        {
            "shares": [
                {"name": "s", "path": str(tmp_path / "srv/s"), "valid_users": ["u"]},
                {
                    "name": "ann",
                    "path": str(tmp_path / "home/ann"),
                    "valid_users": ["u"],
                },
            ],
            "users": ["u"],
        }
    )
    rendered = f"{MARKER}\n[s]\n"

    note = SambaConfigApplier(unit="smbd.service").apply(rendered, config=config)

    module_conf = str(tmp_path / "etc/neutrino.conf")
    assert note == (
        f"wrote the distribution's {tmp_path / 'stock/smb.conf'}; "
        "added the include line; started"
    )
    assert (tmp_path / "etc/neutrino.conf").read_text() == rendered
    assert (tmp_path / "etc/smb.conf").read_text() == (
        f"[global]\n{INCLUDE}{module_conf}\n   workgroup = WORKGROUP\n\n"
        "[printers]\n   path = /var/spool/samba\n"
    )
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
    config = one_share(tmp_path)

    SambaConfigApplier(unit="smbd.service").apply(
        f"{MARKER}\n", config=config, user_files={"ann.conf": "   force user = ann\n"}
    )

    assert sorted(path.name for path in users_dir.iterdir()) == [
        "ann.conf",
        "notes.txt",
    ]
    assert (users_dir / "ann.conf").read_text() == "   force user = ann\n"
    assert stat.S_IMODE(os.stat(users_dir / "ann.conf").st_mode) == 0o644
    assert stat.S_IMODE(os.stat(users_dir).st_mode) == 0o755


def test_a_persons_smb_conf_gets_the_include_line_once_and_nothing_else(box):
    _, tmp_path = box
    (tmp_path / "etc").mkdir()
    persons = "# mine\n[Global]\n   workgroup = HOME\n\n[media]\n   path = /srv/media\n"
    (tmp_path / "etc/smb.conf").write_text(persons)
    applier = SambaConfigApplier(unit="smbd.service")

    first = applier.apply(f"{MARKER}\n", config=one_share(tmp_path))
    second = applier.apply(f"{MARKER}\n", config=one_share(tmp_path))

    module_conf = str(tmp_path / "etc/neutrino.conf")
    assert first == "added the include line; started"
    assert second == "started"
    assert (tmp_path / "etc/smb.conf").read_text() == (
        f"# mine\n[Global]\n{INCLUDE}{module_conf}\n   workgroup = HOME\n\n"
        "[media]\n   path = /srv/media\n"
    )
    assert not (tmp_path / "etc/backup.conf").exists()


def test_an_earlier_versions_whole_file_is_the_persons_and_only_gets_the_line(box):
    _, tmp_path = box
    (tmp_path / "etc").mkdir()
    earlier = (
        f"{MARKER}\n\n[global]\n   hosts deny = 0/0\n\n[lab]\n   path = /home/lab\n"
    )
    (tmp_path / "etc/smb.conf").write_text(earlier)
    (tmp_path / "etc/backup.conf").write_text("[global]\n   workgroup = HOME\n")

    note = SambaConfigApplier(unit="smbd.service").apply(
        f"{MARKER}\n", config=one_share(tmp_path)
    )

    module_conf = str(tmp_path / "etc/neutrino.conf")
    assert note == "added the include line; started"
    assert (tmp_path / "etc/smb.conf").read_text() == (
        f"{MARKER}\n\n[global]\n{INCLUDE}{module_conf}\n   hosts deny = 0/0\n\n"
        "[lab]\n   path = /home/lab\n"
    )
    assert (tmp_path / "etc/backup.conf").exists()


def test_the_sweep_takes_every_neutrino_user_and_credential_and_no_other(box):
    commands, _ = box
    commands.answers[("pdbedit", "-L")] = (0, "neutrino-ann:1001:\nbob:1002:\n")
    commands.answers[("getent", "passwd")] = (
        0,
        "root:x:0:0:root:/root:/bin/bash\n"
        "neutrino-ann:x:997:997:neutrino file share:/home/neutrino-ann:/usr/sbin/nologin\n"
        "neutrino-old:x:996:996:neutrino file share:/nonexistent:/usr/sbin/nologin\n"
        "bob:x:1002:1002::/home/bob:/bin/bash\n",
    )

    notes = SambaUserManager().sweep()

    assert commands.ran("smbpasswd") == [(["smbpasswd", "-x", "neutrino-ann"], None)]
    assert commands.ran("userdel") == [
        (["userdel", "neutrino-ann"], None),
        (["userdel", "neutrino-old"], None),
    ]
    assert notes == [
        "swept the credential of neutrino-ann",
        "swept the account neutrino-ann",
        "swept the account neutrino-old",
    ]


def test_the_plan_is_pure_and_puts_a_global_header_in_front_of_a_file_without_one():
    text, note = plan_smb_conf(
        "[media]\n   path = /srv/media\n",
        stock=("[global]\n", "stock"),
        is_served=True,
    )

    assert text == (
        f"[global]\n{INCLUDE}{applier_module.SAMBA_MODULE_CONF_PATH}\n\n"
        "[media]\n   path = /srv/media\n"
    )
    assert note == "added the include line"
    assert plan_smb_conf(None, stock=("[global]\n", "a stock"), is_served=True) == (
        f"[global]\n{INCLUDE}{applier_module.SAMBA_MODULE_CONF_PATH}\n",
        "wrote a stock; added the include line",
    )
    assert plan_smb_conf(text, stock=("", ""), is_served=True) == (text, "")
    assert plan_smb_conf(text, stock=("", ""), is_served=False) == (
        "[global]\n\n[media]\n   path = /srv/media\n",
        "took the include line out",
    )
    assert plan_smb_conf(None, stock=("x", "s"), is_served=False) == ("", "")
    persons = "[global]\n   workgroup = HOME\n"
    assert plan_smb_conf(persons, stock=("", ""), is_served=False) == (persons, "")
    assert without_include_line(text) == "[global]\n\n[media]\n   path = /srv/media\n"


def test_a_removal_deletes_the_modules_file_and_takes_the_line_out(box):
    _, tmp_path = box
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc/smb.conf").write_text("[global]\n   workgroup = HOME\n")
    applier = SambaConfigApplier(unit="smbd.service")
    applier.apply(f"{MARKER}\n", config=one_share(tmp_path), user_files={"a.conf": "x"})

    applier.remove()
    applier.remove()

    assert (tmp_path / "etc/smb.conf").read_text() == "[global]\n   workgroup = HOME\n"
    assert not (tmp_path / "etc/neutrino.conf").exists()
    assert not (tmp_path / "etc/neutrino_users").exists()


def test_a_configuration_with_no_share_leaves_the_persons_file_byte_for_byte(box):
    commands, tmp_path = box
    (tmp_path / "etc").mkdir()
    persons = "# mine\n[global]\n   workgroup = HOME\n"
    (tmp_path / "etc/smb.conf").write_text(persons)
    applier = SambaConfigApplier(unit="smbd.service")

    note = applier.apply(f"{MARKER}\n", config=SambaConfig())

    assert note == "unchanged"
    assert (tmp_path / "etc/smb.conf").read_text() == persons
    assert not (tmp_path / "etc/neutrino.conf").exists()
    assert commands.ran("systemctl") == []
    assert commands.ran("testparm") == []


def test_the_last_share_going_takes_the_file_and_the_line_away(box, monkeypatch):
    commands, tmp_path = box
    (tmp_path / "etc").mkdir()
    persons = "[global]\n   workgroup = HOME\n"
    (tmp_path / "etc/smb.conf").write_text(persons)
    monkeypatch.setattr(applier_module, "unit_state", lambda unit: "active")
    applier = SambaConfigApplier(unit="smbd.service")
    applier.apply(
        f"{MARKER}\n[s]\n", config=one_share(tmp_path), user_files={"a.conf": "x"}
    )

    note = applier.apply(f"{MARKER}\n", config=SambaConfig())

    assert note == "took the include line out; reloaded"
    assert (tmp_path / "etc/smb.conf").read_text() == persons
    assert not (tmp_path / "etc/neutrino.conf").exists()
    assert not (tmp_path / "etc/neutrino_users").exists()


def test_apply_reloads_a_running_unit_rather_than_restarting(box, monkeypatch):
    commands, tmp_path = box
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc/smb.conf").write_text(
        f"[global]\n{INCLUDE}{tmp_path / 'etc/neutrino.conf'}\n"
    )
    monkeypatch.setattr(applier_module, "unit_state", lambda unit: "active")

    note = SambaConfigApplier(unit="smb.service").apply(
        f"{MARKER}\n", config=one_share(tmp_path)
    )

    assert note == "reloaded"
    assert commands.ran("systemctl") == [(["systemctl", "reload", "smb.service"], None)]


def test_samba_checks_the_merged_configuration_before_anything_is_written(box):
    commands, tmp_path = box
    seen = {}

    def refuse(command):
        seen["smb_conf"] = open(command[2], encoding="utf-8").read()
        return 1, ""

    commands.answers[("testparm", "-s")] = (refuse, "")
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc/smb.conf").write_text("[global]\n   workgroup = HOME\n")

    with pytest.raises(ModuleApplyError) as refused:
        SambaConfigApplier(unit="smbd.service").apply("bad", config=one_share(tmp_path))

    assert refused.value.code == "samba_config_rejected"
    assert seen["smb_conf"].startswith("[global]\n   include = ")
    assert "neutrino.conf" in seen["smb_conf"]
    assert not (tmp_path / "etc/neutrino.conf").exists()
    assert (tmp_path / "etc/smb.conf").read_text() == "[global]\n   workgroup = HOME\n"


def test_the_persons_configuration_is_read_without_the_modules_line(box):
    commands, tmp_path = box
    seen = {}

    def answer(command):
        seen["text"] = open(command[2], encoding="utf-8").read()
        return 0, "[global]\n\thosts allow = 10.0.0.0/8\n[media]\n\tpath = /srv/m\n"

    commands.answers[("testparm", "-s")] = (answer, "")
    planned = (
        f"[global]\n{INCLUDE}{tmp_path / 'etc/neutrino.conf'}\n   workgroup = HOME\n"
    )

    global_section, shares = SambaConfigReader().read_persons(planned)

    assert seen["text"] == "[global]\n   workgroup = HOME\n"
    assert global_section == {"hosts allow": "10.0.0.0/8"}
    assert shares == [{"name": "media", "path": "/srv/m", "params": {}}]


@pytest.mark.parametrize(
    "global_section, shares, code, params",
    [
        (
            {},
            [{"name": "Ann", "path": "/x", "params": {}}],
            "share_name_taken",
            {"name": "Ann"},
        ),
        ({"hosts allow": "192.168.1.0/24"}, [], "samba_hosts_allow_no_loopback", {}),
        (
            {"bind interfaces only": "Yes", "interfaces": "eth0"},
            [],
            "samba_interfaces_no_loopback",
            {},
        ),
        ({"security": "ADS"}, [], "samba_domain_member", {}),
        ({"server role": "member server"}, [], "samba_domain_member", {}),
    ],
)
def test_the_persons_configuration_refuses_what_stops_the_modules_shares(
    global_section, shares, code, params
):
    config = SambaConfig.from_dict({"shares": [{"name": "ann", "path": "/a"}]})

    with pytest.raises(ModuleApplyError) as refused:
        check_person_config(global_section, shares, config)

    assert (refused.value.code, refused.value.params) == (code, params)


def test_the_persons_configuration_that_leaves_the_loopback_open_passes():
    config = SambaConfig.from_dict({"shares": [{"name": "ann", "path": "/a"}]})

    check_person_config(
        {
            "hosts allow": "192.168.1., 127.0.0.1",
            "bind interfaces only": "yes",
            "interfaces": "eth0 lo",
            "security": "user",
            "server role": "standalone server",
        },
        [{"name": "media", "path": "/m", "params": {}}],
        config,
    )


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


def test_a_configuration_whose_only_share_admits_no_user_serves_nothing(box):
    commands, tmp_path = box
    (tmp_path / "etc").mkdir()
    persons = "[global]\n   workgroup = HOME\n"
    (tmp_path / "etc/smb.conf").write_text(persons)
    config = SambaConfig.from_dict(
        {
            "shares": [{"name": "carried", "path": "/srv/c", "valid_users": []}],
            "users": [],
        }
    )

    note = SambaConfigApplier(unit="smbd.service").apply(f"{MARKER}\n", config=config)

    assert note == "unchanged"
    assert (tmp_path / "etc/smb.conf").read_text() == persons
    assert not (tmp_path / "etc/neutrino.conf").exists()
