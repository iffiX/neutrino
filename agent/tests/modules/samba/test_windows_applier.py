"""The file share on Windows' own SMB server, with PowerShell faked.

What these pin: the document an apply sends names only what the module made, the fence as ranges outside
the allowed subnets, each share's rights, and the accounts to retire; each
configured account is denied the console and RDP through the local policy;
and the status reading is shaped the way the Linux module reports.
"""

import ctypes
import json

import pytest

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.samba.config import SambaConfig
from neutrino_agent.modules.samba.windows_applier import (
    APPLY_SCRIPT,
    PASSWORD_SCRIPT,
    SERVER_LOG_SCRIPT,
    STATUS_SCRIPT,
    WITHDRAW_SCRIPT,
    SambaWindowsApplier,
    blocked_ranges,
    deny_interactive_logon,
)

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


class FakePowerShell:
    """Records each script and document, and answers a canned object."""

    def __init__(self, answers=None, error=None):
        self.runs: list = []
        self._answers = dict(answers or {})
        self._error = error

    def __call__(self, script, document):
        self.runs.append((script, json.loads(json.dumps(document))))
        if self._error is not None:
            raise self._error
        return dict(self._answers.get(script, {}))


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
    powershell = FakePowerShell({APPLY_SCRIPT: {"notes": ["created share media"]}})
    denied = []
    applier = SambaWindowsApplier(powershell=powershell, deny_logon=denied.append)
    record = {"shares": {"old": "D:\\old", "media": "D:\\media"}, "accounts": ["eve"]}

    notes = applier.apply(CONFIG, record)

    assert notes == ["created share media"]
    ((script, document),) = powershell.runs
    assert script == APPLY_SCRIPT
    assert document["marker"] == "neutrino:"
    assert document["owned_shares"] == ["media", "old"]
    assert document["owned_accounts"] == ["eve"]
    assert document["users"] == ["ann", "bob"]
    assert document["retired_accounts"] == ["eve"]
    assert document["removed_shares"] == ["old"]
    assert document["rule_name"] == "neutrino_smb_fence"
    assert document["share_owner"] == "BUILTIN\\Administrators"
    assert document["blocked_addresses"] == blocked_ranges(["192.168.1.0/24"])
    media, docs = document["shares"]
    assert media == {
        "name": "media",
        "path": "D:\\media",
        "description": "neutrino: films",
        "accounts": ["ann", "bob"],
        "revoked": ["eve"],
        "share_right": "Change",
        "folder_right": "(OI)(CI)M",
    }
    assert docs["description"] == "neutrino:"
    assert docs["accounts"] == ["ann"]
    assert docs["revoked"] == ["eve", "bob"]
    assert (docs["share_right"], docs["folder_right"]) == ("Read", "(OI)(CI)RX")
    assert denied == ["ann", "bob"]


def test_a_refused_apply_denies_nobody_anything():
    powershell = FakePowerShell(error=ModuleApplyError("user_name_taken", {}))
    denied = []
    applier = SambaWindowsApplier(powershell=powershell, deny_logon=denied.append)

    with pytest.raises(ModuleApplyError):
        applier.apply(CONFIG, {})

    assert denied == []


def test_the_apply_script_refuses_foreign_names_and_never_grants_everyone():
    assert "Send-Refusal 'share_name_taken'" in APPLY_SCRIPT
    assert "Send-Refusal 'user_name_taken'" in APPLY_SCRIPT
    assert "Everyone" not in APPLY_SCRIPT
    assert "-NoPassword -Disabled" in APPLY_SCRIPT
    assert "Add-LocalGroupMember" not in APPLY_SCRIPT
    assert "SpecialAccounts\\UserList" in APPLY_SCRIPT
    assert "-Action Block -Protocol TCP -LocalPort 445" in APPLY_SCRIPT
    assert "Set-NetFirewallRule -Name $d.rule_name -RemoteAddress" in APPLY_SCRIPT
    # The fence goes up before any share or account is made.
    assert APPLY_SCRIPT.index("New-NetFirewallRule") < APPLY_SCRIPT.index(
        "New-SmbShare"
    )
    assert APPLY_SCRIPT.index("New-NetFirewallRule") < APPLY_SCRIPT.index(
        "New-LocalUser"
    )


def test_withdrawing_names_the_shares_and_says_whether_it_is_a_removal():
    powershell = FakePowerShell()
    applier = SambaWindowsApplier(powershell=powershell, deny_logon=None)
    record = {"shares": {"media": "D:\\media"}, "accounts": ["ann"]}

    applier.withdraw(record, is_removed=True)

    ((script, document),) = powershell.runs
    assert script == WITHDRAW_SCRIPT
    assert document["owned_shares"] == ["media"]
    assert document["owned_accounts"] == ["ann"]
    assert document["is_removed"] is True


def test_a_password_goes_in_the_document_only():
    powershell = FakePowerShell()
    applier = SambaWindowsApplier(powershell=powershell)

    applier.set_password("ann", "pw")

    assert powershell.runs == [(PASSWORD_SCRIPT, {"name": "ann", "password": "pw"})]
    assert "Enable-LocalUser" in PASSWORD_SCRIPT


def test_the_status_is_shaped_the_way_the_linux_module_reports():
    read = {
        "is_present": True,
        "is_running": True,
        "shares": {
            "name": "media",
            "path": "D:\\media",
            "description": "neutrino: films",
            "access": [
                {"account": "XENON\\ann", "right": "Change"},
                {"account": "XENON\\bob", "right": "Read"},
            ],
        },
        "sessions": [{"user": "XENON\\ann", "address": "192.168.1.20"}],
        "users": [{"name": "ann", "is_present": True, "is_enabled": False}],
        "fence": {"is_present": True, "is_enabled": True, "blocked": "0.0.0.0-9.9.9.9"},
    }
    applier = SambaWindowsApplier(powershell=FakePowerShell({STATUS_SCRIPT: read}))

    status = applier.read_status({"accounts": ["ann"]})

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
    applier = SambaWindowsApplier(powershell=FakePowerShell({STATUS_SCRIPT: read}))

    (share,) = applier.read_status({})["shares"]

    assert share["params"]["valid users"] == ""


def test_a_status_powershell_cannot_give_reads_as_no_server():
    applier = SambaWindowsApplier(powershell=FakePowerShell(error=OSError("gone")))

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
    answer = {"lines": ["2026-10-02T10:00:00 1001 A client connected."]}
    powershell = FakePowerShell({SERVER_LOG_SCRIPT: answer})

    lines = SambaWindowsApplier(powershell=powershell).read_server_log(50)

    assert lines == ["2026-10-02T10:00:00 1001 A client connected."]
    ((script, document),) = powershell.runs
    assert document == {
        "log_name": "Microsoft-Windows-SMBServer/Operational",
        "lines": 50,
    }
    assert "Get-WinEvent -LogName $d.log_name -MaxEvents $d.lines" in script


def test_a_server_log_powershell_cannot_give_is_an_os_error():
    powershell = FakePowerShell(error=OSError("gone"))

    with pytest.raises(OSError):
        SambaWindowsApplier(powershell=powershell).read_server_log(50)
