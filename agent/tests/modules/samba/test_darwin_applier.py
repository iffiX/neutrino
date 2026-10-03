"""The file share on macOS's own SMB server, with every system tool faked.

What these pin: smbd enabled through launchd and started only when launchd
does not hold it; share points made with ``sharing`` under the module's
prefix, SMB only, no guest, read-only by ``-R 1`` and never encrypted;
accounts made without a shell or a home, hidden and put in the SMB group,
the NT hash turned on before ``dscl -passwd``; folders granted with
``chmod +a``; the fence a pf sub-anchor loaded from a kept file and loaded
again at start; foreign names refused before anything is touched; and the
status read from launchctl, the share list and lsof.
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

    Attributes:
        calls: Each argument vector, in order.
        answers: Output by the leading words of a command; a command no
            entry names succeeds and prints nothing.
        failing: Leading words of the commands that exit 1.
    """

    def __init__(self):
        self.calls: list = []
        self.answers: dict = {}
        self.failing: set = set()

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
        return CommandResult(command, 0, "", "")

    def ran(self, *words) -> list:
        """The recorded commands that start with these words."""
        return [call for call in self.calls if tuple(call[: len(words)]) == words]


def share_list(*points) -> str:
    return json.dumps(
        {
            record: {"path": path, "smb": {"name": name, "read-only": read_only}}
            for record, path, name, read_only in points
        }
    )


@pytest.fixture
def tools(monkeypatch, tmp_path):
    plist = tmp_path / "com.apple.smbd.plist"
    plist.write_text("")
    monkeypatch.setattr(applier_module, "SAMBA_DARWIN_SMBD_PLIST", str(plist))
    held = FakeTools()
    # Nobody exists yet but what a test adds.
    held.failing.add(("dscl", ".", "-read", "/Users/ann", "UniqueID"))
    held.failing.add(("dscl", ".", "-read", "/Users/bob", "UniqueID"))
    return held


@pytest.fixture
def applier(tools, tmp_path):
    return SambaDarwinApplier(rules_path=str(tmp_path / "samba_pf.conf"), run=tools)


def test_the_fence_passes_the_allowed_subnets_and_blocks_the_rest():
    assert render_pf_rules(["192.168.1.7/24", "bogus", "fd00::/8"]) == (
        "table <neutrino_smb_allowed> const { 192.168.1.0/24, fd00::/8 }\n"
        "pass in quick proto tcp from <neutrino_smb_allowed> to any port 445\n"
        "block drop in quick proto tcp from any to any port 445\n"
    )
    assert render_pf_rules([]) == (
        "block drop in quick proto tcp from any to any port 445\n"
    )


def test_the_share_list_is_read_in_either_shape():
    keyed = share_list(("neutrino_media", "/m", "media", 1))
    listed = json.dumps([{"name": "Public", "path": "/Users/a/Public"}])

    assert parse_share_points(keyed) == [
        {
            "record": "neutrino_media",
            "path": "/m",
            "smb_name": "media",
            "is_read_only": True,
        }
    ]
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
        "neutrino file share",
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
    tools.failing.discard(("dscl", ".", "-read", "/Users/ann", "UniqueID"))
    tools.answers[("dscl", ".", "-read", "/Users/ann", "RealName")] = (
        "RealName:\n Ann Example\n"
    )

    with pytest.raises(ModuleApplyError) as refused:
        applier.apply(CONFIG, {})

    assert refused.value.code == "user_name_taken"
    assert refused.value.params == {"user": "ann"}
    assert tools.ran("sysadminctl") == []


def test_an_account_named_as_the_module_names_its_own_is_its_own(applier, tools):
    tools.failing.discard(("dscl", ".", "-read", "/Users/ann", "UniqueID"))
    tools.answers[("dscl", ".", "-read", "/Users/ann", "RealName")] = (
        "RealName: neutrino file share\n"
    )

    applier.apply(CONFIG, {})

    assert [call[2] for call in tools.ran("sysadminctl", "-addUser")] == ["bob"]


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


def test_the_nt_hash_goes_on_before_the_password_is_set(applier, tools):
    applier.set_password("ann", "s3cret")

    assert tools.calls == [
        ["pwpolicy", "-u", "ann", "-sethashtypes", "SMB-NT", "on"],
        ["dscl", ".", "-passwd", "/Users/ann", "s3cret"],
        ["pwpolicy", "-u", "ann", "-enableuser"],
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
    tools.failing.discard(("dscl", ".", "-read", "/Users/ann", "UniqueID"))
    tools.answers[("dscl", ".", "-read", "/Users/ann", "AuthenticationAuthority")] = (
        "AuthenticationAuthority: ;ShadowHash;HASHLIST:<SALTED-SHA512-PBKDF2,SMB-NT>\n"
    )
    tools.answers[("pfctl", "-a", "com.apple/neutrino_smb", "-s", "rules")] = (
        "block drop in quick proto tcp from any to any port = 445\n"
    )
    tools.answers[("pfctl", "-s", "info")] = "Status: Enabled\n"

    status = applier.read_status({"shares": {"media": "/m"}, "accounts": ["ann"]})

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
