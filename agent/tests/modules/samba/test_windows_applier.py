"""The file share on Windows' own SMB server, with the PowerShell host and icacls faked.

What these pin: the request an apply sends the host names only what the
module made, the fence as ranges outside the allowed subnets, each share's
right, and the accounts to retire; once the host has converged the server
each share's folder is granted to its accounts and taken from the module's
others through icacls, a grant icacls refuses failing the apply; each
configured account is denied the console and RDP through the local policy;
a refusal stops before any folder or policy; the withdrawal, the server's
log and a password are one request each, the password in the request alone;
and the status reading is shaped the way the Linux module reports.
"""

import ctypes

import pytest

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.samba.config import SambaConfig
from neutrino_agent.modules.samba.windows_applier import (
    SambaWindowsApplier,
    blocked_ranges,
    deny_interactive_logon,
)
from neutrino_agent.modules.shared.subprocess_run import CommandResult
from tests.conftest import RecordingHost

ALL_IPV6 = "::-ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff"

CONFIG = SambaConfig.from_dict(
    {
        "shares": [
            {"name": "media", "path": "D:\\media", "comment": "films"},
            {
                "name": "docs",
                "path": "D:\\docs",
                "is_read_only": True,
                "valid_users": ["ann"],
            },
        ],
        "users": ["ann", "bob"],
        "allowed_subnets": ["192.168.1.0/24"],
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


def test_the_fence_blocks_every_address_outside_the_allowed_subnets():
    assert blocked_ranges(["192.168.1.0/24"]) == [
        "0.0.0.0-192.168.0.255",
        "192.168.2.0-255.255.255.255",
        ALL_IPV6,
    ]
    assert blocked_ranges(["10.0.0.0/8", "10.1.0.0/16", "fd00::/8"]) == [
        "0.0.0.0-9.255.255.255",  # scan: allow
        "11.0.0.0-255.255.255.255",
        "::-fcff:ffff:ffff:ffff:ffff:ffff:ffff:ffff",
        "fe00::-ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff",
    ]


def test_no_subnet_blocks_everything_and_every_address_blocks_nothing():
    assert blocked_ranges([]) == ["0.0.0.0-255.255.255.255", ALL_IPV6]
    assert blocked_ranges(["not a network"]) == blocked_ranges([])
    assert blocked_ranges(["0.0.0.0/0", "::/0"]) == []
    assert blocked_ranges(["192.168.1.7/32", "0.0.0.0/1"]) == [
        "128.0.0.0-192.168.1.6",  # scan: allow
        "192.168.1.8-255.255.255.255",
        ALL_IPV6,
    ]


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
                "blocked_addresses": [
                    "0.0.0.0-126.255.255.255",  # scan: allow
                    "128.0.0.0-192.168.0.255",  # scan: allow
                    "192.168.2.0-255.255.255.255",
                    "::",
                    "::2-ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff",
                ],
                "rule_name": "neutrino_smb_fence",
                "rule_title": "Neutrino file share fence",
                "share_owner": "BUILTIN\\Administrators",
            },
        )
    ]
    assert icacls.calls == [
        ["icacls.exe", "D:\\media", "/remove:g", "eve"],
        ["icacls.exe", "D:\\media", "/grant", "ann:(OI)(CI)M"],
        ["icacls.exe", "D:\\media", "/grant", "bob:(OI)(CI)M"],
        ["icacls.exe", "D:\\docs", "/remove:g", "eve"],
        ["icacls.exe", "D:\\docs", "/remove:g", "bob"],
        ["icacls.exe", "D:\\docs", "/grant", "ann:(OI)(CI)RX"],
    ]
    assert denied == ["ann", "bob"]


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
                "rule_name": "neutrino_smb_fence",
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
        "fence": {
            "is_present": True,
            "is_enabled": True,
            "blocked": ["0.0.0.0-9.9.9.9"],
        },
    }
    host = RecordingHost({"share_status": read})

    status = applier_with(host).read_status({"accounts": ["ann"]})

    assert host.calls == [
        (
            "share_status",
            {
                "marker": "neutrino:",
                "accounts": ["ann"],
                "rule_name": "neutrino_smb_fence",
            },
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
    assert status["fence"] == {
        "is_present": True,
        "is_enabled": True,
        "blocked": ["0.0.0.0-9.9.9.9"],
    }


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
