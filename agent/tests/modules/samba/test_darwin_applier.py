"""The file share on macOS's own SMB server, with every system tool faked.

What these pin: smbd enabled through launchd and started only when launchd
does not hold it; share points made with ``sharing`` under the module's
prefix, SMB only, no guest, read-only by ``-R 1`` and never encrypted;
accounts made without a shell or a home, each with a full name of its
own, read back after sysadminctl since it can refuse and exit 0, a bare
record a failed attempt left made again, hidden and put in the SMB group,
the account enabled and the NT hash turned on before ``dscl -passwd``, and
an account the password reaches first made by it; one share point per
share, kept across applies, the module's duplicates removed and all of a
name's points withdrawn; folders granted with ``chmod +a``; the fence a pf
sub-anchor loaded from a kept file and loaded again at start; foreign names
refused before anything is touched; and the status read from launchctl,
the share list and lsof, a password counted only once the record says one
was set.
"""

import json

import pytest

import neutrino_agent.modules.samba.darwin_applier as applier_module
from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.samba.config import SambaConfig
from neutrino_agent.modules.samba.darwin_applier import (
    SambaDarwinApplier,
    parse_share_points,
    render_pf_rules,
)
from neutrino_agent.modules.subprocess_run import CommandResult

CONFIG = SambaConfig.from_dict(
    {
        "shares": [
            {"name": "media", "path": "/Volumes/data/media"},
            {
                "name": "docs",
                "path": "/Volumes/data/docs",
                "is_read_only": True,
                "valid_users": ["ann"],
            },
        ],
        "users": ["ann", "bob"],
        "allowed_subnets": ["192.168.1.0/24", "fd00::/8"],
    }
)

LSOF_OUTPUT = (
    "COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME\n"
    "smbd 812 root 5u IPv4 0x1 0t0 TCP 192.168.1.5:445->192.168.1.20:52344 "
    "(ESTABLISHED)\n"
    "smbd 813 root 5u IPv6 0x2 0t0 TCP [fd00::5]:445->[fd00::20]:52345 "
    "(ESTABLISHED)\n"
)


class FakeTools:
    """Every command the applier runs, recorded, answered by its first words.

    ``dscl`` on ``/Users`` and ``sysadminctl`` act on a directory of
    records, where sysadminctl refuses a full name a record holds and still
    exits 0, as macOS 15 does.

    Attributes:
        calls: Each argument vector, in order.
        answers: Output by the leading words of a command; a command no
            entry names succeeds and prints nothing.
        failing: Leading words of the commands that exit 1.
        users: The directory: each record's keys by its short name.
    """

    def __init__(self):
        self.calls: list = []
        self.answers: dict = {}
        self.failing: set = set()
        self.users: dict = {}

    def __call__(self, command, *, is_checked=True, input_text=None, timeout_s=0):
        command = list(command)
        self.calls.append(command)
        for size in (5, 4, 3, 2, 1):
            key = tuple(command[:size])
            if key in self.failing:
                if is_checked:
                    raise OSError(f"{command[0]} refused")
                return CommandResult(command, 1, "", "refused")
            if key in self.answers:
                return CommandResult(command, 0, self.answers[key], "")
        if command[0] == "sysadminctl" and command[1] == "-addUser":
            return self._add_user(command)
        if command[0] == "dscl" and command[3:4] and command[3].startswith("/Users/"):
            return self._dscl(command)
        return CommandResult(command, 0, "", "")

    def _add_user(self, command):
        name = command[2]
        full_name = command[command.index("-fullName") + 1]
        if any(user.get("RealName") == full_name for user in self.users.values()):
            line = f"User with full name '{full_name}' already exists."
            return CommandResult(
                command, 0, "", f"2026-10-04 21:26:48.632 sysadminctl[1:2] {line}\n"
            )
        self.users[name] = account(full_name)
        return CommandResult(command, 0, "", "")

    def _dscl(self, command):
        name = command[3][len("/Users/") :]
        held = self.users.get(name)
        verb = command[2]
        if verb == "-create":
            self.users.setdefault(name, {})[command[4]] = command[5]
            return CommandResult(command, 0, "", "")
        if held is None:
            return CommandResult(
                command, 56, "", "<dscl_cmd> DS Error: -14136 (eDSRecordNotFound)\n"
            )
        if verb == "-delete":
            del self.users[name]
        if verb == "-read":
            keys = command[4:] or ["RecordName"]
            printed = [
                f"{key}: {held[key]}" if key in held else f"No such key: {key}"
                for key in keys
            ]
            missing = any(key not in held for key in keys)
            return CommandResult(command, int(missing), "\n".join(printed) + "\n", "")
        return CommandResult(command, 0, "", "")

    def ran(self, *words) -> list:
        """The recorded commands that start with these words."""
        return [call for call in self.calls if tuple(call[: len(words)]) == words]


def account(full_name="neutrino file share ann") -> dict:
    """A usable account's record, as sysadminctl makes one."""
    return {
        "RecordName": "x",
        "RealName": full_name,
        "UniqueID": "502",
        "PrimaryGroupID": "20",
        "UserShell": "/usr/bin/false",
        "NFSHomeDirectory": "/var/empty",
    }


def share_list(*points) -> str:
    """What ``sharing -l -f json`` prints: an object keyed by record name."""
    return json.dumps(
        {
            record: {
                "path": path,
                "smb_name": name,
                "smb_read_only": read_only,
                "smb_guest_access": 0,
                "smb_sealed": 0,
                "smb_shared": 1,
            }
            for record, path, name, read_only in points
        }
    )


@pytest.fixture
def tools(monkeypatch, tmp_path):
    plist = tmp_path / "com.apple.smbd.plist"
    plist.write_text("")
    monkeypatch.setattr(applier_module, "SAMBA_DARWIN_SMBD_PLIST", str(plist))
    return FakeTools()


@pytest.fixture
def applier(tools, tmp_path):
    return SambaDarwinApplier(rules_path=str(tmp_path / "samba_pf.conf"), run=tools)


def test_the_fence_passes_the_allowed_subnets_and_blocks_the_rest():
    assert render_pf_rules(["192.168.1.7/24", "bogus", "fd00::/8"]) == (
        "pass in quick proto tcp from { 127.0.0.0/8, ::1/128 } to any port 445\n"
        "table <neutrino_smb_allowed> const { 192.168.1.0/24, fd00::/8 }\n"
        "pass in quick proto tcp from <neutrino_smb_allowed> to any port 445\n"
        "block drop in quick proto tcp from any to any port 445\n"
    )
    assert render_pf_rules([]) == (
        "pass in quick proto tcp from { 127.0.0.0/8, ::1/128 } to any port 445\n"
        "block drop in quick proto tcp from any to any port 445\n"
    )


def test_the_share_list_is_read_in_either_shape():
    keyed = share_list(("neutrino_media", "/m", "media", 1))
    listed = json.dumps([{"name": "Public", "path": "/Users/a/Public"}])
    nested = json.dumps(
        {"neutrino_media": {"path": "/m", "smb": {"name": "media", "read-only": 1}}}
    )

    assert parse_share_points(keyed) == [
        {
            "record": "neutrino_media",
            "path": "/m",
            "smb_name": "media",
            "is_read_only": True,
        }
    ]
    assert parse_share_points(nested) == parse_share_points(keyed)
    assert parse_share_points(listed)[0]["smb_name"] == "Public"
    assert parse_share_points("List of Share Points") == []


def test_an_apply_makes_the_server_the_fence_the_accounts_and_the_shares(
    applier, tools, tmp_path
):
    tools.failing.add(("launchctl", "print"))

    notes = applier.apply(CONFIG, {})

    assert tools.ran("launchctl", "enable") == [
        ["launchctl", "enable", "system/com.apple.smbd"]
    ]
    assert tools.ran("launchctl", "kickstart") == [
        ["launchctl", "kickstart", "system/com.apple.smbd"]
    ]
    rules = tmp_path / "samba_pf.conf"
    assert rules.read_text() == render_pf_rules(CONFIG.allowed_subnets)
    assert tools.ran("pfctl", "-a") == [
        ["pfctl", "-a", "com.apple/neutrino_smb", "-f", str(rules)]
    ]
    assert tools.ran("pfctl", "-E") == [["pfctl", "-E"]]
    (add_ann,) = tools.ran("sysadminctl", "-addUser", "ann")
    assert add_ann[3:9] == [
        "-fullName",
        "neutrino file share ann",
        "-shell",
        "/usr/bin/false",
        "-home",
        "/var/empty",
    ]
    assert tools.ran("dscl", ".", "-create", "/Users/bob") == [
        ["dscl", ".", "-create", "/Users/bob", "IsHidden", "1"]
    ]
    assert tools.ran("dseditgroup")[0][-1] == "com.apple.access_smb"
    assert tools.ran("sharing", "-a") == [
        [
            "sharing",
            "-a",
            "/Volumes/data/media",
            "-S",
            "media",
            "-n",
            "neutrino_media",
            "-s",
            "001",
            "-g",
            "000",
        ],
        [
            "sharing",
            "-a",
            "/Volumes/data/docs",
            "-S",
            "docs",
            "-n",
            "neutrino_docs",
            "-s",
            "001",
            "-g",
            "000",
            "-R",
            "1",
        ],
    ]
    assert all("-E" not in call for call in tools.ran("sharing"))
    granted = [call[2] for call in tools.ran("chmod", "+a")]
    assert granted[0].startswith("user:ann allow list,add_file")
    assert granted[2].startswith("user:ann allow list,search,readattr")
    assert len(granted) == 3
    assert "created share media" in notes
    assert "started the server" in notes


def test_an_enabled_pf_and_a_loaded_smbd_are_left_as_they_are(applier, tools):
    tools.answers[("pfctl", "-s", "info")] = "Status: Enabled for 3 days\n"

    applier.apply(CONFIG, {})

    assert tools.ran("pfctl", "-E") == []
    assert tools.ran("launchctl", "kickstart") == []
    assert tools.ran("launchctl", "bootstrap") == []


def test_a_share_point_the_module_did_not_make_is_refused_untouched(applier, tools):
    tools.answers[("sharing", "-l")] = share_list(("media", "/Users/a/m", "media", 0))

    with pytest.raises(ModuleApplyError) as refused:
        applier.apply(CONFIG, {"shares": {"media": "/Users/a/m"}})

    assert refused.value.code == "share_name_taken"
    assert tools.ran("launchctl", "enable") == []
    assert tools.ran("sharing", "-r") == []


def test_an_account_the_module_did_not_make_is_refused_untouched(applier, tools):
    tools.users["ann"] = account("Ann Example")

    with pytest.raises(ModuleApplyError) as refused:
        applier.apply(CONFIG, {})

    assert refused.value.code == "user_name_taken"
    assert refused.value.params == {"user": "ann"}
    assert tools.ran("sysadminctl") == []


def test_an_account_named_as_the_module_names_its_own_is_its_own(applier, tools):
    """An earlier build gave every account the words alone."""
    tools.users["ann"] = account("neutrino file share")

    applier.apply(CONFIG, {})

    assert [call[2] for call in tools.ran("sysadminctl", "-addUser")] == ["bob"]


def test_two_accounts_in_one_apply_each_get_a_full_name_of_their_own(applier, tools):
    applier.apply(CONFIG, {})

    assert [call[4] for call in tools.ran("sysadminctl", "-addUser")] == [
        "neutrino file share ann",
        "neutrino file share bob",
    ]
    assert tools.users["ann"]["UniqueID"] and tools.users["bob"]["UniqueID"]


def test_a_refusal_the_tool_exits_0_on_is_a_refusal_with_its_own_words(applier, tools):
    tools.users["other"] = account("neutrino file share ann")

    with pytest.raises(ModuleApplyError) as refused:
        applier.apply(CONFIG, {})

    assert refused.value.code == "user_create_failed"
    assert refused.value.params == {
        "user": "ann",
        "detail": "User with full name 'neutrino file share ann' already exists.",
    }
    assert tools.ran("dscl", ".", "-create", "/Users/ann") == []


def test_a_bare_record_a_failed_attempt_left_is_made_again(applier, tools):
    tools.users["ann"] = {"RecordName": "ann", "IsHidden": "1"}

    notes = applier.apply(CONFIG, {"accounts": ["ann"]})

    deleted = ["dscl", ".", "-delete", "/Users/ann"]
    (made,) = tools.ran("sysadminctl", "-addUser", "ann")
    assert tools.calls.index(deleted) < tools.calls.index(made)
    assert tools.users["ann"]["UniqueID"] == "502"
    assert tools.users["ann"]["IsHidden"] == "1"
    assert "made account ann again" in notes


def test_a_bare_record_the_module_did_not_list_is_refused_untouched(applier, tools):
    tools.users["ann"] = {"RecordName": "ann"}

    with pytest.raises(ModuleApplyError) as refused:
        applier.apply(CONFIG, {})

    assert refused.value.code == "user_name_taken"
    assert tools.ran("dscl", ".", "-delete") == []
    assert tools.ran("sysadminctl") == []


def test_a_password_for_a_bare_record_makes_the_account_first(applier, tools):
    tools.users["ann"] = {"RecordName": "ann", "IsHidden": "1"}

    applier.set_password("ann", "s3cret")

    assert tools.ran("dscl", ".", "-delete", "/Users/ann")
    assert tools.users["ann"]["UniqueID"] == "502"
    assert tools.calls[-1] == ["dscl", ".", "-passwd", "/Users/ann", "s3cret"]


def test_a_share_point_that_moved_is_made_again_and_a_dropped_one_removed(
    applier, tools
):
    tools.answers[("sharing", "-l")] = share_list(
        ("neutrino_media", "/old/media", "media", 0),
        ("neutrino_docs", "/Volumes/data/docs", "docs", 1),
        ("neutrino_gone", "/gone", "gone", 0),
    )
    record = {
        "shares": {"media": "/old/media", "docs": "/x", "gone": "/gone"},
        "accounts": ["ann", "bob", "eve"],
    }

    notes = applier.apply(CONFIG, record)

    assert tools.ran("sharing", "-r") == [
        ["sharing", "-r", "neutrino_gone"],
        ["sharing", "-r", "neutrino_media"],
    ]
    assert [call[2] for call in tools.ran("sharing", "-a")] == ["/Volumes/data/media"]
    assert tools.ran("pwpolicy", "-u", "eve") == [
        ["pwpolicy", "-u", "eve", "-disableuser"]
    ]
    assert "retired eve" in notes
    assert "removed share gone" in notes


def test_the_account_is_enabled_and_its_nt_hash_on_before_the_password(applier, tools):
    tools.users["ann"] = account()
    tools.failing.add(("dscl", ".", "-read", "/Groups/com.apple.access_smb"))

    applier.set_password("ann", "s3cret")

    assert tools.calls == [
        ["dscl", ".", "-read", "/Groups/com.apple.access_smb"],
        [
            "dscl",
            ".",
            "-read",
            "/Users/ann",
            "UniqueID",
            "PrimaryGroupID",
            "UserShell",
            "NFSHomeDirectory",
        ],
        ["dscl", ".", "-create", "/Users/ann", "IsHidden", "1"],
        ["pwpolicy", "-u", "ann", "-enableuser"],
        ["pwpolicy", "-u", "ann", "-sethashtypes", "SMB-NT", "on"],
        ["dscl", ".", "-passwd", "/Users/ann", "s3cret"],
    ]


def test_a_password_that_arrives_before_the_account_makes_it_first(applier, tools):
    applier.set_password("ann", "s3cret")

    (made,) = tools.ran("sysadminctl", "-addUser", "ann")
    commands = [call[:3] for call in tools.calls]
    assert commands.index(made[:3]) < commands.index(["dscl", ".", "-passwd"])
    assert tools.ran("dscl", ".", "-create", "/Users/ann") == [
        ["dscl", ".", "-create", "/Users/ann", "IsHidden", "1"]
    ]
    assert tools.calls[-1] == ["dscl", ".", "-passwd", "/Users/ann", "s3cret"]


def test_a_second_apply_adds_no_share_point(applier, tools):
    applier.apply(CONFIG, {})
    tools.answers[("sharing", "-l")] = share_list(
        ("neutrino_media", "/Volumes/data/media", "media", 0),
        ("neutrino_docs", "/Volumes/data/docs", "docs", 1),
    )
    tools.calls.clear()

    notes = applier.apply(CONFIG, {"shares": {"media": "/x", "docs": "/y"}})

    assert tools.ran("sharing", "-a") == []
    assert tools.ran("sharing", "-r") == []
    assert not any("share" in note for note in notes)


def test_duplicate_points_of_a_share_heal_to_one(applier, tools):
    tools.answers[("sharing", "-l")] = share_list(
        ("neutrino_media-2", "/Volumes/data/media", "media", 0),
        ("neutrino_media", "/Volumes/data/media", "media", 0),
        ("neutrino_media-1", "/Volumes/data/media", "media", 0),
        ("neutrino_docs", "/Volumes/data/docs", "docs", 1),
    )

    notes = applier.apply(CONFIG, {"shares": {"media": "/x", "docs": "/y"}})

    assert tools.ran("sharing", "-r") == [
        ["sharing", "-r", "neutrino_media-2"],
        ["sharing", "-r", "neutrino_media-1"],
    ]
    assert tools.ran("sharing", "-a") == []
    assert "removed share point neutrino_media-1" in notes


def test_duplicates_none_of_which_match_are_replaced_by_one(applier, tools):
    tools.answers[("sharing", "-l")] = share_list(
        ("neutrino_media", "/old/media", "media", 0),
        ("neutrino_media-1", "/old/media", "media", 0),
    )

    applier.apply(CONFIG, {"shares": {"media": "/old/media"}})

    assert tools.ran("sharing", "-r") == [
        ["sharing", "-r", "neutrino_media"],
        ["sharing", "-r", "neutrino_media-1"],
    ]
    assert [call[2] for call in tools.ran("sharing", "-a")] == [
        "/Volumes/data/media",
        "/Volumes/data/docs",
    ]


def test_withdrawing_removes_every_point_of_the_module_s_share(applier, tools):
    tools.answers[("sharing", "-l")] = share_list(
        ("neutrino_media", "/m", "media", 0),
        ("neutrino_media-1", "/m", "media", 0),
        ("neutrino_media-2", "/m", "media", 0),
    )

    applier.withdraw({"shares": {"media": "/m"}}, is_removed=False)

    assert [call[2] for call in tools.ran("sharing", "-r")] == [
        "neutrino_media",
        "neutrino_media-1",
        "neutrino_media-2",
    ]


def test_withdrawing_removes_only_the_module_s_points(applier, tools):
    tools.answers[("sharing", "-l")] = share_list(
        ("neutrino_media", "/m", "media", 0), ("Public", "/p", "Public", 0)
    )
    record = {"shares": {"media": "/m", "Public": "/p"}, "accounts": ["ann"]}

    applier.withdraw(record, is_removed=False)

    assert tools.ran("sharing", "-r") == [["sharing", "-r", "neutrino_media"]]
    assert tools.ran("pwpolicy") == []
    assert tools.ran("pfctl") == []


def test_a_removal_also_disables_the_accounts_and_empties_the_fence(
    applier, tools, tmp_path
):
    rules = tmp_path / "samba_pf.conf"
    rules.write_text("block drop in quick proto tcp from any to any port 445\n")

    applier.withdraw({"accounts": ["ann"]}, is_removed=True)

    assert tools.ran("pwpolicy") == [["pwpolicy", "-u", "ann", "-disableuser"]]
    assert tools.ran("pfctl") == [
        ["pfctl", "-a", "com.apple/neutrino_smb", "-F", "all"]
    ]
    assert not rules.exists()


def test_the_kept_fence_is_loaded_again_at_start(applier, tools, tmp_path):
    applier.reload_fence()
    assert tools.calls == []

    rules = tmp_path / "samba_pf.conf"
    rules.write_text(render_pf_rules(["10.0.0.0/8"]))
    applier.reload_fence()

    assert tools.ran("pfctl", "-a") == [
        ["pfctl", "-a", "com.apple/neutrino_smb", "-f", str(rules)]
    ]
    assert tools.ran("pfctl", "-E") == [["pfctl", "-E"]]


def test_the_status_reads_launchd_the_share_list_and_lsof(applier, tools):
    tools.answers[("sharing", "-l")] = share_list(
        ("neutrino_media", "/m", "media", 1), ("Public", "/p", "Public", 0)
    )
    tools.answers[("lsof",)] = LSOF_OUTPUT
    tools.users["ann"] = account()
    tools.answers[("dscl", ".", "-read", "/Users/ann", "AuthenticationAuthority")] = (
        "AuthenticationAuthority: ;ShadowHash;HASHLIST:<SALTED-SHA512-PBKDF2,SMB-NT>\n"
    )
    tools.answers[("pfctl", "-a", "com.apple/neutrino_smb", "-s", "rules")] = (
        "block drop in quick proto tcp from any to any port = 445\n"
    )
    tools.answers[("pfctl", "-s", "info")] = "Status: Enabled\n"

    status = applier.read_status(
        {"shares": {"media": "/m"}, "accounts": ["ann"], "passworded": ["ann"]}
    )

    assert status["is_present"] and status["is_running"]
    assert status["shares"] == [
        {
            "name": "media",
            "path": "/m",
            "params": {"comment": "", "read only": "Yes", "valid users": ""},
        }
    ]
    assert [session["remote_address"] for session in status["sessions"]] == [
        "192.168.1.20",
        "fd00::20",
    ]
    assert status["users"] == [
        {"name": "ann", "is_present": True, "has_password": True}
    ]
    assert status["fence"] == {"is_present": True, "is_enabled": True, "blocked": []}


def test_a_mac_without_smbd_has_no_server(applier, monkeypatch, tmp_path):
    monkeypatch.setattr(
        applier_module, "SAMBA_DARWIN_SMBD_PLIST", str(tmp_path / "missing")
    )

    assert applier.read_status({}) == {"is_present": False, "is_running": False}


def test_a_status_the_tools_cannot_give_reads_as_no_server(tmp_path, monkeypatch):
    plist = tmp_path / "com.apple.smbd.plist"
    plist.write_text("")
    monkeypatch.setattr(applier_module, "SAMBA_DARWIN_SMBD_PLIST", str(plist))

    def missing(command, **kwargs):
        raise FileNotFoundError(command[0])

    applier = SambaDarwinApplier(rules_path=str(tmp_path / "rules"), run=missing)

    assert applier.read_status({}) == {"is_present": False, "is_running": False}


LOG_SHOW_OUTPUT = (
    "Timestamp               Ty Process[PID:TID]\n"
    "2026-10-02 10:00:00.1 Df smbd[812:1] connection from 192.168.1.20\n"
    "2026-10-02 10:00:05.2 Df smbd[812:1] session closed\n"
)


def test_the_server_log_is_what_the_unified_log_holds_of_smbd(applier, tools):
    tools.answers[("log", "show")] = LOG_SHOW_OUTPUT

    assert applier.read_server_log(1) == [
        "2026-10-02 10:00:05.2 Df smbd[812:1] session closed"
    ]
    assert applier.read_server_log(10)[0].endswith("connection from 192.168.1.20")
    assert tools.ran("log", "show")[0] == [
        "log",
        "show",
        "--predicate",
        'process == "smbd"',
        "--last",
        "15m",
        "--style",
        "compact",
    ]


def test_a_log_that_cannot_answer_is_an_os_error(applier, tools):
    tools.failing.add(("log", "show"))

    with pytest.raises(OSError):
        applier.read_server_log(10)


def test_a_user_whose_password_was_never_set_has_none(applier, tools):
    tools.users["ann"] = account()
    tools.answers[("dscl", ".", "-read", "/Users/ann", "AuthenticationAuthority")] = (
        "AuthenticationAuthority: ;ShadowHash;HASHLIST:<SALTED-SHA512-PBKDF2,SMB-NT>\n"
    )

    status = applier.read_status({"accounts": ["ann"], "passworded": []})

    assert status["users"] == [
        {"name": "ann", "is_present": True, "has_password": False}
    ]


def test_duplicate_points_are_one_share_in_the_status(applier, tools):
    tools.answers[("sharing", "-l")] = share_list(
        ("neutrino_media", "/m", "media", 0), ("neutrino_media-1", "/m", "media", 0)
    )

    status = applier.read_status({"shares": {"media": "/m"}})

    assert [share["name"] for share in status["shares"]] == ["media"]


def test_a_bare_record_macos_will_not_delete_is_refused_and_the_rest_applied(
    applier, tools
):
    """macOS 15 refuses the deletion even to root; that one user is refused
    with the system's words, and bob and both shares are applied without it."""
    tools.users["ann"] = {"RecordName": "ann", "IsHidden": "1"}
    tools.failing.add(("dscl", ".", "-delete", "/Users/ann"))

    with pytest.raises(ModuleApplyError) as refused:
        applier.apply(CONFIG, {"accounts": ["ann"]})

    assert refused.value.code == "user_record_unusable"
    assert refused.value.params == {"user": "ann", "detail": "refused"}
    assert tools.users["ann"] == {"RecordName": "ann", "IsHidden": "1"}
    assert [call[2] for call in tools.ran("sysadminctl", "-addUser")] == ["bob"]
    assert [call[2] for call in tools.ran("sharing", "-a")] == [
        "/Volumes/data/media",
        "/Volumes/data/docs",
    ]
    named = " ".join(" ".join(call) for call in tools.ran("chmod"))
    assert "user:ann" not in named
    assert "user:bob" in named


def test_a_password_for_a_bare_record_macos_keeps_is_refused_with_its_words(
    applier, tools
):
    tools.users["ann"] = {"RecordName": "ann"}
    tools.failing.add(("dscl", ".", "-delete", "/Users/ann"))

    with pytest.raises(ModuleApplyError) as refused:
        applier.set_password("ann", "s3cret")

    assert refused.value.code == "user_record_unusable"
    assert tools.ran("dscl", ".", "-passwd") == []
