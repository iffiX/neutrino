"""The file share on Windows' own SMB server, with the PowerShell host and icacls faked.

What these pin: the request an apply sends the host names only what the
module made, each share's right, the accounts to retire and the block rule
an earlier version made for the host to delete; once the host has converged
the server each share's folder is granted to its accounts and taken from
the module's others through icacls, a grant icacls refuses failing the
apply, and the ``.ssh`` folder under a share stops inheriting and loses
every module account; each
configured account is denied the console and RDP through the local policy;
an apply under ``stopped`` names every share of the module's to remove and
still grants the folders; a refusal stops before any folder or policy; the
withdrawal, the server's log and a password are one request each, the
password in the request alone;
and the status reading is shaped the way the Linux module reports.
"""

import ctypes

import pytest

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.samba.config import SambaConfig
from neutrino_agent.modules.samba.windows_applier import (
    SambaWindowsApplier,
    deny_interactive_logon,
)
from neutrino_agent.modules.shared.subprocess_run import CommandResult
from tests.conftest import RecordingHost

CONFIG = SambaConfig.from_dict(
    {
        "shares": [
            {
                "name": "media",
                "path": "D:\\media",
                "comment": "films",
                "valid_users": ["ann", "bob"],
            },
            {
                "name": "docs",
                "path": "D:\\docs",
                "is_read_only": True,
                "valid_users": ["ann"],
            },
        ],
        "users": ["ann", "bob"],
    }
)


class Icacls:
    """icacls, recording each argument vector and refusing the ones asked."""

    def __init__(self, refused=()):
        self.calls: list = []
        self._refused = set(refused)

    def __call__(self, argv, **_):
        self.calls.append(list(argv))
        code = 5 if tuple(argv[2:]) in self._refused else 0
        return CommandResult(command=list(argv), exit_code=code, stdout="", stderr="")


def applier_with(host, *, run=None, denied=None) -> SambaWindowsApplier:
    return SambaWindowsApplier(
        powershell=host,
        deny_logon=denied.append if denied is not None else None,
        run=run if run is not None else Icacls(),
    )


def test_an_apply_names_only_what_the_module_made():
    host = RecordingHost({"share_apply": {"notes": ["created share media"]}})
    denied = []
    icacls = Icacls()
    applier = applier_with(host, run=icacls, denied=denied)
    record = {"shares": {"old": "D:\\old", "media": "D:\\media"}, "accounts": ["eve"]}

    notes = applier.apply(CONFIG, record)

    assert notes == ["created share media"]
    assert host.calls == [
        (
            "share_apply",
            {
                "marker": "neutrino:",
                "owned_shares": ["media", "old"],
                "owned_accounts": ["eve"],
                "users": ["ann", "bob"],
                "retired_accounts": ["eve"],
                "removed_shares": ["old"],
                "shares": [
                    {
                        "name": "media",
                        "path": "D:\\media",
                        "description": "neutrino: films",
                        "accounts": ["ann", "bob"],
                        "share_right": "Change",
                    },
                    {
                        "name": "docs",
                        "path": "D:\\docs",
                        "description": "neutrino:",
                        "accounts": ["ann"],
                        "share_right": "Read",
                    },
                ],
                "retired_rule_name": "neutrino_smb_fence",
                "share_owner": "BUILTIN\\Administrators",
                "is_sweep": False,
                "user_prefix": "neutrino-",
                "is_served": True,
            },
        )
    ]
    assert icacls.calls == [
        ["icacls.exe", "D:\\old", "/remove:g", "eve"],
        ["icacls.exe", "D:\\old", "/remove:g", "ann"],
        ["icacls.exe", "D:\\old", "/remove:g", "bob"],
        ["icacls.exe", "D:\\media", "/remove:g", "eve"],
        ["icacls.exe", "D:\\media", "/grant", "ann:(OI)(CI)M"],
        ["icacls.exe", "D:\\media", "/grant", "bob:(OI)(CI)M"],
        ["icacls.exe", "D:\\docs", "/remove:g", "eve"],
        ["icacls.exe", "D:\\docs", "/remove:g", "bob"],
        ["icacls.exe", "D:\\docs", "/grant", "ann:(OI)(CI)RX"],
    ]
    assert denied == ["ann", "bob"]


def test_the_ssh_folder_under_a_share_is_taken_from_every_module_account(
    tmp_path,
):
    (tmp_path / ".ssh").mkdir()
    config = SambaConfig.from_dict(
        {
            "shares": [
                {"name": "ann", "path": str(tmp_path), "valid_users": ["ann", "bob"]}
            ],
            "users": ["ann", "bob"],
        }
    )
    icacls = Icacls()
    applier = applier_with(RecordingHost(), run=icacls, denied=[])

    applier.apply(config, {"shares": {}, "accounts": ["eve"]})

    ssh_dir = str(tmp_path / ".ssh")
    assert icacls.calls == [
        ["icacls.exe", str(tmp_path), "/remove:g", "eve"],
        ["icacls.exe", str(tmp_path), "/grant", "ann:(OI)(CI)M"],
        ["icacls.exe", str(tmp_path), "/grant", "bob:(OI)(CI)M"],
        ["icacls.exe", ssh_dir, "/inheritance:d"],
        ["icacls.exe", ssh_dir, "/remove:g", "eve"],
        ["icacls.exe", ssh_dir, "/remove:g", "ann"],
        ["icacls.exe", ssh_dir, "/remove:g", "bob"],
    ]


def test_an_ssh_folder_icacls_cannot_keep_fails_the_apply(tmp_path):
    (tmp_path / ".ssh").mkdir()
    config = SambaConfig.from_dict(
        {
            "shares": [{"name": "ann", "path": str(tmp_path), "valid_users": ["ann"]}],
            "users": ["ann"],
        }
    )
    icacls = Icacls(refused=[("/inheritance:d",)])
    applier = applier_with(RecordingHost(), run=icacls, denied=[])

    with pytest.raises(OSError, match="could not keep"):
        applier.apply(config, {})


def test_a_folder_icacls_refuses_fails_the_apply_and_denies_nobody():
    denied = []
    icacls = Icacls(refused=[("/grant", "bob:(OI)(CI)M")])
    applier = applier_with(RecordingHost(), run=icacls, denied=denied)

    with pytest.raises(OSError, match="icacls refused bob on D:\\\\media"):
        applier.apply(CONFIG, {})

    assert denied == []


def test_a_refused_apply_grants_and_denies_nobody_anything():
    host = RecordingHost({"share_apply": ModuleApplyError("user_name_taken", {})})
    denied = []
    icacls = Icacls()
    applier = applier_with(host, run=icacls, denied=denied)

    with pytest.raises(ModuleApplyError):
        applier.apply(CONFIG, {})

    assert icacls.calls == []
    assert denied == []


def test_withdrawing_names_the_shares_and_says_whether_it_is_a_removal():
    host = RecordingHost()
    record = {"shares": {"media": "D:\\media"}, "accounts": ["ann"]}

    applier_with(host).withdraw(record, is_removed=True)

    assert host.calls == [
        (
            "share_withdraw",
            {
                "marker": "neutrino:",
                "owned_shares": ["media"],
                "owned_accounts": ["ann"],
                "is_removed": True,
            },
        )
    ]


def test_a_password_goes_in_the_request_only():
    host = RecordingHost()

    applier_with(host).set_password("ann", "pw")

    assert host.calls == [("share_password", {"name": "ann", "password": "pw"})]


def test_the_status_is_shaped_the_way_the_linux_module_reports():
    read = {
        "is_present": True,
        "is_running": True,
        "shares": [
            {
                "name": "media",
                "path": "D:\\media",
                "description": "neutrino: films",
                "access": [
                    {"account": "XENON\\ann", "right": "Change"},
                    {"account": "XENON\\bob", "right": "Read"},
                ],
            }
        ],
        "sessions": [{"user": "XENON\\ann", "address": "192.168.1.20"}],
        "users": [{"name": "ann", "is_present": True, "is_enabled": False}],
    }
    host = RecordingHost({"share_status": read})

    status = applier_with(host).read_status({"accounts": ["ann"]})

    assert host.calls == [
        (
            "share_status",
            {"marker": "neutrino:", "accounts": ["ann"]},
        )
    ]
    assert status["is_present"] and status["is_running"]
    assert status["shares"] == [
        {
            "name": "media",
            "path": "D:\\media",
            "params": {
                "comment": "films",
                "read only": "No",
                "valid users": "ann bob",
            },
        }
    ]
    assert status["sessions"] == [
        {
            "username": "ann",
            "hostname": "192.168.1.20",
            "remote_address": "192.168.1.20",
            "shares": [],
        }
    ]
    assert status["users"] == [
        {"name": "ann", "is_present": True, "has_password": False}
    ]
    assert "fence" not in status


def test_a_share_granted_to_the_owner_alone_lists_no_user():
    read = {
        "shares": [
            {
                "name": "empty",
                "path": "D:\\empty",
                "description": "neutrino:",
                "access": [{"account": "BUILTIN\\Administrators", "right": "Full"}],
            }
        ]
    }

    (share,) = applier_with(RecordingHost({"share_status": read})).read_status({})[
        "shares"
    ]

    assert share["params"]["valid users"] == ""


@pytest.mark.parametrize(
    "error", [OSError("gone"), TimeoutError("busy"), ModuleApplyError("x", {})]
)
def test_a_status_the_host_cannot_give_reads_as_no_server(error):
    applier = applier_with(RecordingHost({"share_status": error}))

    assert applier.read_status({}) == {"is_present": False, "is_running": False}


class FakeAdvapi32:
    """The four local-policy calls, recorded; a SID of eight bytes."""

    def __init__(self, *, open_status=0, add_status=0):
        self.calls: list = []
        self.rights: list = []
        self._open_status = open_status
        self._add_status = add_status

    def LookupAccountNameW(self, system, account, sid, sid_size, domain, *sizes):
        self.calls.append(("lookup", account, sid is None))
        sid_size._obj.value = 8
        sizes[0]._obj.value = 6
        return 0 if sid is None else 1

    def LsaOpenPolicy(self, system, attributes, access, handle):
        self.calls.append(("open", access))
        return self._open_status

    def LsaAddAccountRights(self, policy, sid, rights, count):
        self.calls.append(("add", count))
        self.rights = [
            ctypes.wstring_at(rights[index].Buffer, rights[index].Length // 2)
            for index in range(count)
        ]
        return self._add_status

    def LsaClose(self, policy):
        self.calls.append(("close",))
        return 0

    def LsaNtStatusToWinError(self, status):
        return 5


def test_an_account_is_denied_the_console_and_rdp():
    advapi32 = FakeAdvapi32()

    deny_interactive_logon("ann", advapi32=advapi32)

    assert advapi32.rights == [
        "SeDenyInteractiveLogonRight",
        "SeDenyRemoteInteractiveLogonRight",
    ]
    assert [call[0] for call in advapi32.calls] == [
        "lookup",
        "lookup",
        "open",
        "add",
        "close",
    ]
    assert advapi32.calls[2] == ("open", 0x10 | 0x800)


@pytest.mark.parametrize(
    "advapi32, closes",
    [(FakeAdvapi32(open_status=0xC0000022), 0), (FakeAdvapi32(add_status=1), 1)],
)
def test_a_policy_that_refuses_is_an_os_error_and_the_handle_is_closed(
    advapi32, closes
):
    with pytest.raises(OSError):
        deny_interactive_logon("ann", advapi32=advapi32)

    assert [call for call in advapi32.calls if call == ("close",)] == [
        ("close",)
    ] * closes


def test_the_server_log_is_the_smb_server_s_latest_events():
    answer = {"lines": ["2026-10-02T10:00:00 1001 A client connected.", " "]}
    host = RecordingHost({"share_log": answer})

    lines = applier_with(host).read_server_log(50)

    assert lines == ["2026-10-02T10:00:00 1001 A client connected."]
    assert host.calls == [
        (
            "share_log",
            {"log_name": "Microsoft-Windows-SMBServer/Operational", "lines": 50},
        )
    ]


def test_a_server_log_the_host_cannot_give_is_an_os_error():
    host = RecordingHost({"share_log": OSError("gone")})

    with pytest.raises(OSError):
        applier_with(host).read_server_log(50)


def test_an_apply_under_stopped_takes_every_share_off_and_grants_the_folders():
    host = RecordingHost({"share_apply": {"notes": ["removed share media"]}})
    denied = []
    icacls = Icacls()
    applier = applier_with(host, run=icacls, denied=denied)
    record = {"shares": {"old": "D:\\old", "media": "D:\\media"}, "accounts": ["eve"]}

    notes = applier.apply(CONFIG, record, is_served=False)

    assert notes == ["removed share media"]
    ((verb, request),) = host.calls
    assert verb == "share_apply"
    assert request["is_served"] is False
    assert request["removed_shares"] == ["media", "old"]
    assert [share["name"] for share in request["shares"]] == ["media", "docs"]
    assert ["icacls.exe", "D:\\media", "/grant", "ann:(OI)(CI)M"] in icacls.calls
    assert ["icacls.exe", "D:\\docs", "/grant", "ann:(OI)(CI)RX"] in icacls.calls
    assert denied == ["ann", "bob"]


def test_the_first_apply_asks_the_host_to_sweep_what_the_marker_names():
    host = RecordingHost({"share_apply": {"notes": ["swept share old"]}})

    notes = applier_with(host, denied=[]).apply(CONFIG, {}, is_sweep=True)
    applier_with(host, denied=[]).apply(CONFIG, {})

    first, second = [call for call in host.calls if call[0] == "share_apply"]
    assert first[1]["is_sweep"] is True
    assert first[1]["user_prefix"] == "neutrino-"
    assert second[1]["is_sweep"] is False
    assert notes == ["swept share old"]


def test_a_folder_share_with_no_account_stays_off_and_its_folder_loses_the_grants():
    """A share whose users are none is no request of the host's, the host
    removes it as the module's, and its folder loses every module account."""
    host = RecordingHost()
    icacls = Icacls()
    applier = applier_with(host, run=icacls, denied=[])
    config = SambaConfig.from_dict(
        {
            "shares": [
                {"name": "lab", "path": "D:\\lab", "valid_users": []},
                {"name": "ann", "path": "C:\\Users\\ann", "valid_users": ["ann"]},
            ],
            "users": ["ann"],
        }
    )

    applier.apply(config, {"shares": {"lab": "D:\\lab"}, "accounts": ["ann", "bob"]})

    request = host.calls[0][1]
    assert [share["name"] for share in request["shares"]] == ["ann"]
    assert request["removed_shares"] == ["lab"]
    assert icacls.calls[:2] == [
        ["icacls.exe", "D:\\lab", "/remove:g", "ann"],
        ["icacls.exe", "D:\\lab", "/remove:g", "bob"],
    ]


def test_a_folder_two_shares_name_is_granted_each_of_their_accounts_once():
    """A folder share at an account's home keeps the Home share's account
    and adds its own; the change right wins over the read right, and an
    account taken out of both loses its grant."""
    icacls = Icacls()
    applier = applier_with(RecordingHost(), run=icacls, denied=[])
    config = SambaConfig.from_dict(
        {
            "shares": [
                {"name": "ann", "path": "C:\\Users\\ann", "valid_users": ["ann"]},
                {
                    "name": "lab",
                    "path": "c:\\users\\ann\\",
                    "is_read_only": True,
                    "valid_users": ["ann", "bob"],
                },
            ],
            "users": ["ann", "bob"],
        }
    )

    applier.apply(config, {"shares": {}, "accounts": ["carol"]})

    assert icacls.calls == [
        ["icacls.exe", "C:\\Users\\ann", "/remove:g", "carol"],
        ["icacls.exe", "C:\\Users\\ann", "/grant", "ann:(OI)(CI)M"],
        ["icacls.exe", "C:\\Users\\ann", "/grant", "bob:(OI)(CI)RX"],
    ]


def test_a_folder_share_that_moved_takes_its_grants_off_the_old_folder():
    icacls = Icacls()
    applier = applier_with(RecordingHost(), run=icacls, denied=[])
    config = SambaConfig.from_dict(
        {
            "shares": [{"name": "lab", "path": "E:\\lab", "valid_users": ["ann"]}],
            "users": ["ann"],
        }
    )

    applier.apply(config, {"shares": {"lab": "D:\\lab"}, "accounts": ["ann"]})

    assert icacls.calls == [
        ["icacls.exe", "D:\\lab", "/remove:g", "ann"],
        ["icacls.exe", "E:\\lab", "/grant", "ann:(OI)(CI)M"],
    ]
