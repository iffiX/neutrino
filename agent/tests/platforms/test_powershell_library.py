"""The PowerShell host's library, read as text: it cannot run here.

What these pin: the library holds no ``exit`` and no prompt, so a request
never ends the process or waits on a person; every operation the agent
sends names a function the library defines, and its dispatch table is the
agent's own; the loop answers one compressed line per request with arrays
kept, refusals as values, errors caught; the task, the one-shot task, the
file share, the thermal zones and the removal keep what the scripts they
replace did, the task settings, the login refusal, the fence before any
share or account, the share accounts' sign-in denial and hiding; a relay's
rule allows inbound TCP to its port on its adapter alone; nothing there
starts icacls or lists processes, which the agent does itself; a
function of a verb that changes the machine asks ``ShouldProcess``; and the
file is ASCII.
"""

import re

import pytest

from neutrino_agent.platforms.powershell_host import (
    WINDOWS_POWERSHELL_HOST_OPS,
    library_path,
)

with open(library_path(), encoding="utf-8") as _stream:
    LIBRARY = _stream.read()

# The verbs PSScriptAnalyzer holds to ask ShouldProcess.
STATE_CHANGING_VERBS = (
    "New",
    "Set",
    "Remove",
    "Start",
    "Stop",
    "Restart",
    "Reset",
    "Update",
)


def functions() -> dict:
    """Each function the library defines, by name, with its body."""
    found = {}
    pieces = re.split(r"^function ", LIBRARY, flags=re.M)
    for piece in pieces[1:]:
        name = re.match(r"[A-Za-z-]+", piece).group(0)
        found[name] = piece[: piece.find("\n}\n") + 2]
    return found


def body(op: str) -> str:
    return functions()[WINDOWS_POWERSHELL_HOST_OPS[op]]


def test_the_library_holds_no_exit_and_no_prompt():
    assert not re.search(r"\bexit\b", LIBRARY, flags=re.I)
    assert "Read-Host" not in LIBRARY
    assert "Write-Host" not in LIBRARY


def test_every_operation_names_a_function_the_library_defines():
    defined = functions()

    for op, name in WINDOWS_POWERSHELL_HOST_OPS.items():
        assert name in defined, op
        assert name.split("-", 1)[1].startswith("Neutrino")


def test_the_library_s_dispatch_table_is_the_agent_s():
    table = LIBRARY[LIBRARY.index("$NeutrinoOperations = @{") :]
    table = table[: table.index("\n}\n")]

    assert (
        dict(re.findall(r"'(\w+)' = '([\w-]+)'", table)) == WINDOWS_POWERSHELL_HOST_OPS
    )


def test_the_loop_answers_one_compressed_line_per_request():
    assert "$ErrorActionPreference = 'Stop'" in LIBRARY
    assert "$ProgressPreference = 'SilentlyContinue'" in LIBRARY
    assert "[Console]::InputEncoding = New-Object" in LIBRARY
    assert "[Console]::OutputEncoding = New-Object" in LIBRARY
    assert "$line = [Console]::In.ReadLine()" in LIBRARY
    assert "if ($null -eq $line) {\n        break" in LIBRARY
    assert "ConvertTo-Json -InputObject $Answer -Compress -Depth 8" in LIBRARY
    assert "PrivateMemorySize64" in LIBRARY
    answer = functions()["Get-NeutrinoAnswer"]
    assert "kind = 'refusal'" in answer and "kind = 'error'" in answer
    assert "$value.ContainsKey('refusal')" in answer
    assert "} catch {" in answer


def test_a_task_is_registered_at_boot_under_the_login_with_no_time_limit():
    register = body("task_write")

    assert "New-ScheduledTaskTrigger -AtStartup" in register
    assert "-ExecutionTimeLimit ([TimeSpan]::Zero)" in register
    assert "-RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)" in register
    assert (
        "-AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable"
        in (register)
    )
    assert "-User $Request.account -Password $Request.password -RunLevel Limited" in (
        register
    )
    assert "-Description $Request.description" in register
    assert "Test-NeutrinoLogonRefused $_" in register
    assert "Get-NeutrinoLogonRefusal $Request.account" in register


def test_a_one_shot_task_has_a_time_limit_and_starts_once_registered():
    once = body("task_run_once")

    assert "-ExecutionTimeLimit (New-TimeSpan -Seconds $Request.timeout_s)" in once
    assert "-RunLevel Limited" in once
    assert "Trigger" not in once
    assert once.index("Register-ScheduledTask") < once.index("Start-ScheduledTask")
    assert "Test-NeutrinoLogonRefused $_" in once


def test_a_login_refused_is_0x8007052e_in_the_message_or_the_hresult():
    refused = functions()["Test-NeutrinoLogonRefused"]
    refusal = functions()["Get-NeutrinoLogonRefusal"]

    assert "-match '0x8007052E'" in refused
    assert "$Failure.Exception.HResult" in refused and "'8007052E'" in refused
    assert "code = 'credential_invalid'" in refusal


def test_the_task_states_and_the_stops_are_the_task_scheduler_s_alone():
    states = body("task_states")

    assert 'Get-ScheduledTask -TaskName "$($Request.prefix)*"' in states
    assert "last_result = [int64]$info.LastTaskResult" in states
    assert "Stop-ScheduledTask -TaskName $Request.task" in body("task_stop")
    assert "Unregister-ScheduledTask -TaskName $Request.task -Confirm:$false" in body(
        "task_remove"
    )
    assert 'Remove-NetFirewallRule -Name "$($Request.prefix)*"' in body("rules_forget")
    assert "Win32_Process" not in LIBRARY
    assert "Get-NetTCPConnection" not in LIBRARY
    assert "icacls" not in LIBRARY.lower()


def test_a_stopped_task_is_disabled_and_a_started_one_enabled_first():
    """A stopped instance stays stopped across a reboot."""
    stop = body("task_stop")
    start = body("task_start")

    assert stop.index("Stop-ScheduledTask") < stop.index("Disable-ScheduledTask")
    assert start.index("Enable-ScheduledTask") < start.index("Start-ScheduledTask")


def test_the_file_share_refuses_foreign_names_and_never_grants_everyone():
    apply = body("share_apply")

    assert "code = 'share_name_taken'" in apply
    assert "code = 'user_name_taken'" in apply
    assert "Everyone" not in apply
    assert "-NoPassword -Disabled" in apply
    assert "Add-LocalGroupMember" not in LIBRARY
    assert "SpecialAccounts\\UserList" in apply
    assert "New-NetFirewallRule" not in apply
    assert "Set-NetFirewallRule" not in apply
    assert "Remove-NetFirewallRule -Name $Request.retired_rule_name" in apply
    assert apply.index("share_name_taken") < apply.index("Start-Service")


def test_the_share_s_other_operations_keep_what_their_scripts_did():
    withdraw = body("share_withdraw")
    password = body("share_password")

    assert "Remove-SmbShare -Name $name -Force" in withdraw
    assert "if ($Request.is_removed)" in withdraw
    assert "NetFirewallRule" not in withdraw
    assert "NetFirewallRule" not in body("share_status")
    assert "$secret.AppendChar($character)" in password
    assert "ConvertTo-SecureString" not in LIBRARY
    assert "Enable-LocalUser -Name $Request.name" in password
    assert "Get-SmbShareAccess" in body("share_status")


def test_the_share_log_takes_its_messages_from_wevtutil_in_utf_16():
    log = body("share_log")

    assert "System32\\wevtutil.exe" in log
    assert "/rd:true /f:RenderedXml /uni:true" in log
    assert "StandardOutputEncoding = [Text.Encoding]::Unicode" in log
    assert "Get-WinEvent" not in log
    assert "FormatDescription" not in log


def test_the_thermal_zones_and_the_removal_keep_what_their_scripts_did():
    assert "MSAcpi_ThermalZoneTemperature" in body("thermal_zones")
    listed = body("added_list")
    removed = body("added_remove")

    for kind in (
        "Get-Service -Name",
        "Get-ScheduledTask -TaskName",
        "Get-NetFirewallRule -Name",
    ):
        assert kind + ' "$($Request.prefix)*"' in listed
    assert "& sc.exe delete $name" in removed
    assert "Unregister-ScheduledTask -TaskName $name -Confirm:$false" in removed
    assert "Remove-NetFirewallRule -Name $name" in removed


def test_a_relay_s_rule_is_an_inbound_tcp_allow_scoped_to_its_adapter():
    listed = body("relay_rules_read")
    written = body("relay_rules_write")

    assert 'Get-NetFirewallRule -Name "$($Request.prefix)*"' in listed
    assert "Get-NetFirewallPortFilter" in listed
    assert "Get-NetFirewallInterfaceFilter" in listed
    assert "Remove-NetFirewallRule -Name $name" in written
    for part in (
        "New-NetFirewallRule -Name $rule.name",
        "-Direction Inbound -Action Allow -Protocol TCP -LocalPort $rule.port",
        "-InterfaceAlias $rule.alias",
    ):
        assert part in written


@pytest.mark.parametrize(
    "name",
    sorted(name for name in functions() if name.split("-")[0] in STATE_CHANGING_VERBS),
)
def test_a_function_that_changes_the_machine_asks_should_process(name):
    defined = functions()[name]

    assert "[CmdletBinding(SupportsShouldProcess = $true)]" in defined
    assert "$PSCmdlet.ShouldProcess(" in defined


def test_the_library_is_ascii():
    LIBRARY.encode("ascii")
