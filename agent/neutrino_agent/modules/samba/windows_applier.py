"""The file share on Windows' own SMB server.

Each operation is one PowerShell script, handed a JSON document on its
standard input and answering one JSON document on its standard output
(:mod:`neutrino_agent.modules.powershell_run`), so a password never appears
on a command line. The module changes only the shares
and accounts it made: a share whose description starts with the marker and
that the module's record lists, an account the record lists. Accounts are
local, in no group, hidden from the sign-in screen and denied the console
and RDP. One inbound block rule for TCP 445, covering every address outside
the allowed subnets, fences the server; it also covers shares the person
made themselves.

Not pure: runs PowerShell and calls the local security policy.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import ctypes
import ipaddress
import subprocess

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.powershell_run import listed, run_powershell
from neutrino_agent.modules.samba.config import SambaConfig
from neutrino_agent.modules.samba.constants import (
    SAMBA_WINDOWS_DENIED_RIGHTS,
    SAMBA_WINDOWS_FENCE_RULE,
    SAMBA_WINDOWS_FENCE_TITLE,
    SAMBA_WINDOWS_FOLDER_CHANGE,
    SAMBA_WINDOWS_FOLDER_READ,
    SAMBA_WINDOWS_MARKER,
    SAMBA_WINDOWS_SHARE_CHANGE,
    SAMBA_WINDOWS_SHARE_OWNER,
    SAMBA_WINDOWS_SHARE_READ,
)
from neutrino_agent.platforms import win32

# The server's state, the marked shares, the listed accounts, the sessions
# and the fence.
STATUS_SCRIPT = """
$svc = Get-Service -Name LanmanServer -ErrorAction SilentlyContinue
$shares = @()
foreach ($share in @(Get-SmbShare -ErrorAction SilentlyContinue)) {
  if (-not "$($share.Description)".StartsWith($d.marker)) { continue }
  $access = @()
  foreach ($entry in @(Get-SmbShareAccess -Name $share.Name)) {
    $access += @{account = "$($entry.AccountName)"; right = "$($entry.AccessRight)"}
  }
  $shares += @{name = $share.Name; path = $share.Path;
    description = "$($share.Description)"; access = $access}
}
$sessions = @()
foreach ($session in @(Get-SmbSession -ErrorAction SilentlyContinue)) {
  $sessions += @{user = "$($session.ClientUserName)";
    address = "$($session.ClientComputerName)"}
}
$users = @()
foreach ($name in @($d.accounts)) {
  $held = Get-LocalUser -Name $name -ErrorAction SilentlyContinue
  $users += @{name = $name; is_present = [bool]$held;
    is_enabled = [bool]($held -and $held.Enabled)}
}
$fence = @{is_present = $false; is_enabled = $false; blocked = @()}
$rule = Get-NetFirewallRule -Name $d.rule_name -ErrorAction SilentlyContinue
if ($rule) {
  $fence.is_present = $true
  $fence.is_enabled = "$($rule.Enabled)" -eq 'True'
  $fence.blocked = @(($rule | Get-NetFirewallAddressFilter).RemoteAddress)
}
@{is_present = [bool]$svc; is_running = [bool]($svc -and $svc.Status -eq 'Running');
  shares = $shares; sessions = $sessions; users = $users; fence = $fence} |
  ConvertTo-Json -Compress -Depth 6
"""

# Refuses names the module did not make, then converges the server, the
# fence, the accounts and the shares.
APPLY_SCRIPT = """
$computer = $env:COMPUTERNAME
foreach ($s in @($d.shares)) {
  $held = Get-SmbShare -Name $s.name -ErrorAction SilentlyContinue
  $is_ours = (@($d.owned_shares) -contains $s.name) -and
    "$($held.Description)".StartsWith($d.marker)
  if ($held -and -not $is_ours) { Send-Refusal 'share_name_taken' @{name = $s.name} }
}
foreach ($u in @($d.users)) {
  $held = Get-LocalUser -Name $u -ErrorAction SilentlyContinue
  $is_ours = (@($d.owned_accounts) -contains $u) -or
    ("$($held.Description)" -eq $d.marker)
  if ($held -and -not $is_ours) {
    Send-Refusal 'user_name_taken' @{user = $u}
  }
}
$notes = @()
$svc = Get-Service -Name LanmanServer
if ("$($svc.StartType)" -eq 'Disabled') {
  Set-Service -Name LanmanServer -StartupType Automatic
}
if ($svc.Status -ne 'Running') {
  Start-Service -Name LanmanServer
  $notes += 'started the server'
}
$blocked = @($d.blocked_addresses)
$rule = Get-NetFirewallRule -Name $d.rule_name -ErrorAction SilentlyContinue
if ($blocked.Count -eq 0) {
  if ($rule) { Set-NetFirewallRule -Name $d.rule_name -Enabled False }
} elseif (-not $rule) {
  New-NetFirewallRule -Name $d.rule_name -DisplayName $d.rule_title `
    -Direction Inbound -Action Block -Protocol TCP -LocalPort 445 `
    -RemoteAddress $blocked -Profile Any | Out-Null
  $notes += 'fenced the server'
} else {
  Set-NetFirewallRule -Name $d.rule_name -RemoteAddress $blocked -Enabled True
}
$hidden = 'HKLM:\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Winlogon\\SpecialAccounts\\UserList'
if (-not (Test-Path -Path $hidden)) { New-Item -Path $hidden -Force | Out-Null }
foreach ($u in @($d.users)) {
  if (-not (Get-LocalUser -Name $u -ErrorAction SilentlyContinue)) {
    New-LocalUser -Name $u -NoPassword -Disabled -AccountNeverExpires `
      -UserMayNotChangePassword -Description $d.marker | Out-Null
    Set-LocalUser -Name $u -PasswordNeverExpires $true
    $notes += "created account $u"
  }
  New-ItemProperty -Path $hidden -Name $u -Value 0 -PropertyType DWord -Force | Out-Null
}
foreach ($u in @($d.retired_accounts)) {
  $held = Get-LocalUser -Name $u -ErrorAction SilentlyContinue
  if ($held -and $held.Enabled) {
    Disable-LocalUser -Name $u
    $notes += "retired $u"
  }
}
foreach ($name in @($d.removed_shares)) {
  $held = Get-SmbShare -Name $name -ErrorAction SilentlyContinue
  if ($held -and "$($held.Description)".StartsWith($d.marker)) {
    Remove-SmbShare -Name $name -Force
    $notes += "removed share $name"
  }
}
foreach ($s in @($d.shares)) {
  if (-not (Test-Path -LiteralPath $s.path)) {
    New-Item -ItemType Directory -Path $s.path -Force | Out-Null
  }
  foreach ($u in @($s.revoked)) { Invoke-Icacls $s.path /remove:g $u | Out-Null }
  foreach ($u in @($s.accounts)) {
    $code = Invoke-Icacls $s.path /grant "${u}:$($s.folder_right)"
    if ($code -ne 0) { throw "icacls refused $u on $($s.path)" }
  }
  $wanted = @()
  foreach ($u in @($s.accounts)) { $wanted += "$computer\\$u" }
  $held = Get-SmbShare -Name $s.name -ErrorAction SilentlyContinue
  if ($held -and $held.Path -ne $s.path) {
    Remove-SmbShare -Name $s.name -Force
    $held = $null
  }
  if (-not $held) {
    $made = @{Name = $s.name; Path = $s.path; Description = $s.description}
    if ($wanted.Count -eq 0) { $made.FullAccess = $d.share_owner }
    elseif ($s.share_right -eq 'Change') { $made.ChangeAccess = $wanted }
    else { $made.ReadAccess = $wanted }
    New-SmbShare @made | Out-Null
    $notes += "created share $($s.name)"
    continue
  }
  Set-SmbShare -Name $s.name -Description $s.description -Force
  foreach ($entry in @(Get-SmbShareAccess -Name $s.name)) {
    $account = "$($entry.AccountName)"
    $is_kept = ($wanted -contains $account) -and ("$($entry.AccessRight)" -eq $s.share_right)
    if ($wanted.Count -eq 0) { $is_kept = $account -eq $d.share_owner }
    if (-not $is_kept) {
      Revoke-SmbShareAccess -Name $s.name -AccountName $account -Force | Out-Null
    }
  }
  foreach ($account in $wanted) {
    Grant-SmbShareAccess -Name $s.name -AccountName $account `
      -AccessRight $s.share_right -Force | Out-Null
  }
  if ($wanted.Count -eq 0) {
    Grant-SmbShareAccess -Name $s.name -AccountName $d.share_owner `
      -AccessRight Full -Force | Out-Null
  }
}
@{notes = $notes} | ConvertTo-Json -Compress -Depth 4
"""

# Takes down the marked shares the record lists; with ``is_removed`` also
# disables the listed accounts and deletes the fence.
WITHDRAW_SCRIPT = """
foreach ($name in @($d.owned_shares)) {
  $held = Get-SmbShare -Name $name -ErrorAction SilentlyContinue
  if ($held -and "$($held.Description)".StartsWith($d.marker)) {
    Remove-SmbShare -Name $name -Force
  }
}
if ($d.is_removed) {
  foreach ($u in @($d.owned_accounts)) {
    $held = Get-LocalUser -Name $u -ErrorAction SilentlyContinue
    if ($held -and $held.Enabled) { Disable-LocalUser -Name $u }
  }
  Remove-NetFirewallRule -Name $d.rule_name -ErrorAction SilentlyContinue
}
'{}'
"""

# Sets one listed account's password and lets it sign in over the network.
PASSWORD_SCRIPT = """
$secret = ConvertTo-SecureString -String $d.password -AsPlainText -Force
Set-LocalUser -Name $d.name -Password $secret -PasswordNeverExpires $true
Enable-LocalUser -Name $d.name
'{}'
"""


def blocked_ranges(allowed_subnets: list) -> list:
    """Every address outside the allowed subnets, as firewall ranges.

    Args:
        allowed_subnets: The networks the shares answer, IPv4 or IPv6; an
            entry that is no network is left out, which blocks more.

    Returns:
        ``first-last`` ranges, IPv4 before IPv6, empty when the subnets
        cover every address of both families.
    """
    allowed: dict = {4: [], 6: []}
    for subnet in allowed_subnets:
        try:
            network = ipaddress.ip_network(str(subnet).strip(), strict=False)
        except ValueError:
            continue
        allowed[network.version].append(
            (int(network.network_address), int(network.broadcast_address))
        )
    ranges = []
    for version, highest in ((4, 2**32 - 1), (6, 2**128 - 1)):
        cursor = 0
        for first, last in sorted(allowed[version]):
            if first > cursor:
                ranges.append(_address_range(version, cursor, first - 1))
            cursor = max(cursor, last + 1)
        if cursor <= highest:
            ranges.append(_address_range(version, cursor, highest))
    return ranges


def deny_interactive_logon(account: str, *, advapi32=None) -> None:
    """Deny one local account the console and RDP in the local policy.

    Args:
        account: The local account's name.
        advapi32: The bound advapi32; None binds the real one.

    Raises:
        OSError: When the account has no SID or the policy refuses.
    """
    if advapi32 is None:
        advapi32 = win32.libraries().advapi32
    sid = _account_sid(advapi32, account)
    attributes = win32.LsaObjectAttributes()
    attributes.Length = ctypes.sizeof(win32.LsaObjectAttributes)
    policy = ctypes.c_void_p()
    status = advapi32.LsaOpenPolicy(
        None,
        ctypes.byref(attributes),
        win32.POLICY_CREATE_ACCOUNT | win32.POLICY_LOOKUP_NAMES,
        ctypes.byref(policy),
    )
    if status:
        code = advapi32.LsaNtStatusToWinError(status)
        raise OSError(code, f"LsaOpenPolicy refused: error {code}")
    try:
        buffers = [
            ctypes.create_unicode_buffer(name) for name in SAMBA_WINDOWS_DENIED_RIGHTS
        ]
        rights = (win32.LsaUnicodeString * len(buffers))()
        for index, (name, buffer) in enumerate(
            zip(SAMBA_WINDOWS_DENIED_RIGHTS, buffers)
        ):
            rights[index].Length = len(name) * 2
            rights[index].MaximumLength = (len(name) + 1) * 2
            rights[index].Buffer = ctypes.cast(buffer, ctypes.c_void_p)
        status = advapi32.LsaAddAccountRights(policy, sid, rights, len(buffers))
        if status:
            code = advapi32.LsaNtStatusToWinError(status)
            raise OSError(code, f"LsaAddAccountRights refused {account}: error {code}")
    finally:
        advapi32.LsaClose(policy)


def _account_sid(advapi32, account: str):
    """One account's SID, in a buffer the caller keeps alive."""
    sid_size = win32.DWORD(0)
    domain_size = win32.DWORD(0)
    use = win32.DWORD(0)
    advapi32.LookupAccountNameW(
        None,
        account,
        None,
        ctypes.byref(sid_size),
        None,
        ctypes.byref(domain_size),
        ctypes.byref(use),
    )
    if not sid_size.value:
        raise OSError(f"no SID for the account {account}")
    sid = ctypes.create_string_buffer(sid_size.value)
    domain = ctypes.create_unicode_buffer(max(domain_size.value, 1))
    if not advapi32.LookupAccountNameW(
        None,
        account,
        sid,
        ctypes.byref(sid_size),
        domain,
        ctypes.byref(domain_size),
        ctypes.byref(use),
    ):
        raise OSError(f"no SID for the account {account}")
    return sid


def _address_range(version: int, first: int, last: int) -> str:
    """One range as the firewall reads it, a lone address bare."""
    make = ipaddress.IPv4Address if version == 4 else ipaddress.IPv6Address
    if first == last:
        return str(make(first))
    return f"{make(first)}-{make(last)}"


class SambaWindowsApplier:
    """Converges Windows' SMB server with the module's configuration."""

    def __init__(self, *, powershell=None, deny_logon=None):
        """
        Args:
            powershell: Called with ``(script, document)``; returns the JSON
                object the script printed. None runs PowerShell.
            deny_logon: Called with an account name to deny it the console
                and RDP. None calls the local security policy.
        """
        self._powershell = powershell if powershell is not None else run_powershell
        self._deny_logon = (
            deny_logon if deny_logon is not None else deny_interactive_logon
        )

    def read_status(self, record: dict) -> dict:
        """What the server holds of the module's, read now.

        Args:
            record: The module's record: ``{"shares", "accounts"}``.

        Returns:
            ``{"is_present", "is_running", "shares", "sessions", "users",
            "fence"}``; ``is_present`` false when PowerShell cannot answer.
        """
        try:
            read = self._powershell(
                STATUS_SCRIPT,
                {
                    "marker": SAMBA_WINDOWS_MARKER,
                    "accounts": list(record.get("accounts") or []),
                    "rule_name": SAMBA_WINDOWS_FENCE_RULE,
                },
            )
        except (OSError, subprocess.SubprocessError, ModuleApplyError):
            return {"is_present": False, "is_running": False}
        return {
            "is_present": bool(read.get("is_present")),
            "is_running": bool(read.get("is_running")),
            "shares": [_share_detail(entry) for entry in listed(read.get("shares"))],
            "sessions": [
                _session_detail(entry) for entry in listed(read.get("sessions"))
            ],
            "users": [
                {
                    "name": str(entry.get("name", "")),
                    "is_present": bool(entry.get("is_present")),
                    "has_password": bool(entry.get("is_enabled")),
                }
                for entry in listed(read.get("users"))
                if isinstance(entry, dict)
            ],
            "fence": _fence_detail(read.get("fence")),
        }

    def apply(self, config: SambaConfig, record: dict) -> list:
        """Make the server serve the configuration, and nothing else of ours.

        An account is the module's when the record lists it or its
        description is the marker; a share is the module's when the record
        lists it and its description starts with the marker.

        Args:
            config: The validated configuration.
            record: The module's record: ``{"shares", "accounts"}``.

        Returns:
            What changed, one note each.

        Raises:
            ModuleApplyError: ``share_name_taken`` or ``user_name_taken`` for
                a name the module did not make.
            OSError: When PowerShell or the local policy fails.
        """
        owned_shares = dict(record.get("shares") or {})
        owned_accounts = list(record.get("accounts") or [])
        wanted_shares = {share.name for share in config.shares}
        known_accounts = owned_accounts + [
            name for name in config.users if name not in owned_accounts
        ]
        answer = self._powershell(
            APPLY_SCRIPT,
            {
                "marker": SAMBA_WINDOWS_MARKER,
                "owned_shares": sorted(owned_shares),
                "owned_accounts": owned_accounts,
                "users": list(config.users),
                "retired_accounts": [
                    name for name in owned_accounts if name not in config.users
                ],
                "removed_shares": sorted(set(owned_shares) - wanted_shares),
                "shares": [
                    _share_document(share, config, known_accounts)
                    for share in config.shares
                ],
                "blocked_addresses": blocked_ranges(config.allowed_subnets),
                "rule_name": SAMBA_WINDOWS_FENCE_RULE,
                "rule_title": SAMBA_WINDOWS_FENCE_TITLE,
                "share_owner": SAMBA_WINDOWS_SHARE_OWNER,
            },
        )
        for name in config.users:
            self._deny_logon(name)
        return [str(note) for note in listed(answer.get("notes"))]

    def withdraw(self, record: dict, *, is_removed: bool) -> None:
        """Take the module's shares off the server.

        Args:
            record: The module's record: ``{"shares", "accounts"}``.
            is_removed: Also disable the module's accounts and delete the
                fence, as an uninstall does.

        Raises:
            OSError: When PowerShell fails.
        """
        self._powershell(
            WITHDRAW_SCRIPT,
            {
                "marker": SAMBA_WINDOWS_MARKER,
                "owned_shares": sorted(record.get("shares") or {}),
                "owned_accounts": list(record.get("accounts") or []),
                "is_removed": is_removed,
                "rule_name": SAMBA_WINDOWS_FENCE_RULE,
            },
        )

    def reload_fence(self) -> None:
        """Nothing to load: the firewall keeps the rule across a restart."""

    def set_password(self, name: str, password: str) -> None:
        """Set one of the module's accounts' password and enable it.

        Args:
            name: An account the record lists.
            password: The new password; it reaches PowerShell on standard
                input.

        Raises:
            OSError: When PowerShell fails.
        """
        self._powershell(PASSWORD_SCRIPT, {"name": name, "password": password})


def _share_document(share, config: SambaConfig, known_accounts: list) -> dict:
    """One share as the apply script converges it."""
    accounts = list(share.valid_users or config.users)
    is_writable = not share.is_read_only
    return {
        "name": share.name,
        "path": share.path,
        "description": f"{SAMBA_WINDOWS_MARKER} {share.comment}".strip(),
        "accounts": accounts,
        "revoked": [name for name in known_accounts if name not in accounts],
        "share_right": (
            SAMBA_WINDOWS_SHARE_CHANGE if is_writable else SAMBA_WINDOWS_SHARE_READ
        ),
        "folder_right": (
            SAMBA_WINDOWS_FOLDER_CHANGE if is_writable else SAMBA_WINDOWS_FOLDER_READ
        ),
    }


def _share_detail(entry) -> dict:
    """One marked share in the shape the Linux module reports."""
    entry = entry if isinstance(entry, dict) else {}
    description = str(entry.get("description", ""))
    comment = description[len(SAMBA_WINDOWS_MARKER) :].strip()
    access = [
        item
        for item in listed(entry.get("access"))
        if isinstance(item, dict)
        and str(item.get("account", "")) != SAMBA_WINDOWS_SHARE_OWNER
    ]
    users = [str(item.get("account", "")).rsplit("\\", 1)[-1] for item in access]
    is_read_only = all(
        str(item.get("right", "")) == SAMBA_WINDOWS_SHARE_READ for item in access
    )
    return {
        "name": str(entry.get("name", "")),
        "path": str(entry.get("path", "")),
        "params": {
            "comment": comment,
            "read only": "Yes" if is_read_only else "No",
            "valid users": " ".join(users),
        },
    }


def _session_detail(entry) -> dict:
    """One SMB session in the shape the Linux module reports."""
    entry = entry if isinstance(entry, dict) else {}
    address = str(entry.get("address", ""))
    return {
        "username": str(entry.get("user", "")).rsplit("\\", 1)[-1],
        "hostname": address,
        "remote_address": address,
        "shares": [],
    }


def _fence_detail(entry) -> dict:
    """The block rule as the details report it."""
    entry = entry if isinstance(entry, dict) else {}
    return {
        "is_present": bool(entry.get("is_present")),
        "is_enabled": bool(entry.get("is_enabled")),
        "blocked": [str(item) for item in listed(entry.get("blocked"))],
    }
