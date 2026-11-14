"""The PowerShell host's library, read as text: it cannot run here.

What these pin: the library holds no ``exit`` and no prompt, so a request
never ends the process or waits on a person; every operation the agent
sends names a function the library defines, and its dispatch table is the
agent's own; the loop answers one compressed line per request with arrays
kept, refusals as values, errors caught; the task, the one-shot task, the
file share, the thermal zones and the removal keep what the scripts they
replace did, the task settings, the login refusal, the fence before any
share or account, the share accounts' sign-in denial and hiding; the file
share under ``stopped`` starting no server and making no share, and a share
named like one of the person's left off while the others are made; a read of the
server naming its dependents, a stop disabling it first, and a put back as it was; the
folders' access read listing each folder's own allow rules by SID and
whether it inherits, and changing nothing; a relay's
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


def test_a_task_of_system_s_is_registered_at_boot_with_no_login():
    register = body("task_write_system")

    assert "New-ScheduledTaskTrigger -AtStartup" in register
    assert "-ExecutionTimeLimit ([TimeSpan]::Zero)" in register
    assert "-RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)" in register
    assert "-Priority 4" in register
    assert "New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount" in (
        register
    )
    assert "-Principal $principal" in register
    assert "-Description $Request.description" in register
    assert "-Password" not in register


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

    assert 'Get-NeutrinoScheduledTask "$($Request.prefix)*"' in states
    assert "last_result = [int64]$info.LastTaskResult" in states
    assert "Stop-ScheduledTask -TaskName $Request.task" in body("task_stop")
    assert "Unregister-ScheduledTask -TaskName $Request.task -Confirm:$false" in body(
        "task_remove"
    )
    assert 'Remove-NetFirewallRule -Name "$($Request.prefix)*"' in body("rules_forget")
    assert "Win32_Process" not in LIBRARY
    assert "Get-NetTCPConnection" not in LIBRARY
    assert "icacls" not in LIBRARY.lower()


def test_every_task_read_goes_through_the_read_that_tells_a_failure_from_no_task():
    defined = functions()
    readers = [name for name, text in defined.items() if "Get-ScheduledTask " in text]

    assert readers == ["Get-NeutrinoScheduledTask"]
    assert "Get-NeutrinoScheduledTask" in body("task_read")
    assert "Get-NeutrinoScheduledTask" in body("task_states")
    assert "Get-NeutrinoScheduledTask" in body("added_list")


def test_a_stopped_task_is_disabled_and_a_started_one_enabled_first():
    """A stopped instance stays stopped across a reboot."""
    stop = body("task_stop")
    start = body("task_start")

    assert stop.index("Stop-ScheduledTask") < stop.index("Disable-ScheduledTask")
    assert start.index("Enable-ScheduledTask") < start.index("Start-ScheduledTask")


def test_the_file_share_leaves_a_foreign_share_name_off_and_never_grants_everyone():
    apply = body("share_apply")

    assert "$refused += @{name = $s.name; code = 'share_name_taken'}" in apply
    assert "$taken -contains $s.name" in apply
    assert "refusal = @{code = 'share_name_taken'" not in apply
    assert "code = 'user_name_taken'" in apply
    assert "Everyone" not in apply
    assert "-NoPassword -Disabled" in apply
    assert "Add-LocalGroupMember" not in LIBRARY
    assert "SpecialAccounts\\UserList" in apply
    assert "New-NetFirewallRule" not in apply
    assert "Set-NetFirewallRule" not in apply
    assert "Remove-NetFirewallRule -Name $Request.retired_rule_name" in apply
    assert apply.index("share_name_taken") < apply.index("Start-Service")


def test_the_file_share_sweep_takes_an_account_of_0_5_by_the_record_and_the_marker():
    """A description an administrator gave a person's account makes it the
    module's only when a record lists it too."""
    sweep = body("share_sweep")
    users = sweep[sweep.index("Get-LocalUser -ErrorAction") :]
    users = users[: users.index("Remove-LocalUser")]

    assert '(@($Request.earlier_accounts) -contains "$($user.Name)")' in users
    assert "Remove-LocalUser" not in body("share_apply")


def test_the_file_share_sweep_takes_a_hidden_entry_under_a_prefix_whose_account_is_gone():
    """The R167 lab machine kept the hidden entries of accounts an earlier
    round deleted, ``neutrino-lab`` and ``neutrino-lab2``; a live
    ``neutrino_transport`` keeps its own."""
    sweep = body("share_sweep")
    hidden = sweep[sweep.index("(Get-Item -Path $hidden") :]

    assert '"$name".StartsWith($_)' in hidden
    assert "-not (Get-LocalUser -Name $name -ErrorAction SilentlyContinue)" in hidden
    assert "Remove-ItemProperty -Path $hidden -Name $name" in hidden


def test_the_file_share_sweep_takes_an_account_by_its_marker_never_its_start_alone():
    """``neutrino_transport`` starts as the file share's accounts do."""
    sweep = body("share_sweep")
    users = sweep[sweep.index("Get-LocalUser -ErrorAction") :]
    users = users[: users.index("Remove-LocalUser")]

    assert '$is_marked = "$($user.Description)" -eq $Request.marker' in users
    assert "$is_ours = $is_marked -and ($is_named -or" in users


def test_the_file_share_apply_closes_the_sessions_of_a_name_it_makes_again():
    """An account deleted by hand left its sessions holding its old token."""
    apply = body("share_apply")
    made = apply[apply.index("foreach ($u in @($Request.users))") :]
    closed = made.index("Close-SmbSession -SessionId $session.SessionId -Force")

    assert closed < made.index("New-LocalUser -Name $u")
    assert 'EndsWith("\\$u")' in made
    assert "if ($is_readable) { Get-SmbSession" in made


def test_the_file_share_apply_answers_the_accounts_it_made():
    apply = body("share_apply")

    assert "$accounts_made += $u" in apply
    assert "made = $accounts_made}" in apply


def test_the_file_share_apply_answers_each_account_s_sid():
    apply = body("share_apply")

    assert '$sids[$u] = "$($held.SID.Value)"' in apply
    assert "sids = $sids" in apply


def test_the_file_share_sweep_closes_a_deleted_account_s_sessions_first():
    """On the R167 lab machine a sweep under live mounts left each session
    holding the deleted account's token, and its reads were denied on the
    folder granted to the account made again."""
    sweep = body("share_sweep")
    closed = sweep.index("Close-SmbSession -SessionId $session.SessionId -Force")

    assert closed < sweep.index("Remove-LocalUser -SID $user.SID")
    assert 'EndsWith("\\$($user.Name)")' in sweep
    assert "if ($is_readable) { Get-SmbSession" in sweep


def test_the_file_share_under_stopped_starts_no_server_and_makes_no_share():
    apply = body("share_apply")
    served = apply.index("if ($Request.is_served) {")
    unserved = apply.index("if (-not $Request.is_served) {")

    assert served < apply.index("Set-Service -Name LanmanServer")
    assert served < apply.index("Start-Service -Name LanmanServer")
    assert "New-Item -ItemType Directory" not in apply
    assert unserved < apply.index("New-SmbShare")
    assert unserved < apply.index("Grant-SmbShareAccess")


def test_the_server_stop_disables_it_and_then_stops_it():
    """A read of an enabled server starts it during a stop, and the stop fails."""
    stop = body("share_server_stop")
    disabled = stop.index("Set-Service -Name LanmanServer -StartupType Disabled")
    read = stop.index("(Get-Service -Name LanmanServer).Status -ne 'Stopped'")

    assert disabled < read
    assert read < stop.index("Stop-Service -Name LanmanServer -Force")


def test_the_server_read_names_the_services_that_depend_on_it_and_run():
    read = body("share_server_read")

    assert "DependentServices" in read
    assert "$dependent.Status -eq 'Running'" in read
    assert "dependents = $dependents" in read


def test_the_server_put_back_sets_its_start_type_and_runs_it_as_it_was():
    put_back = body("share_server_set")

    assert "Set-Service -Name LanmanServer -StartupType $Request.start_type" in put_back
    assert "if ($Request.is_running) {" in put_back
    assert "foreach ($name in @($Request.dependents))" in put_back
    assert "Stop-Service -Name LanmanServer -Force" in put_back


def test_a_start_starts_again_the_services_a_stop_took_down():
    apply = body("share_apply")

    assert apply.index("Start-Service -Name LanmanServer") < apply.index(
        "foreach ($name in @($Request.server_dependents))"
    )


def test_the_folder_access_read_lists_each_folder_s_own_allow_rules():
    read = body("folder_access")

    assert (
        "GetAccessRules($true, $false, [Security.Principal.SecurityIdentifier])" in read
    )
    assert "-ne 'Allow'" in read
    assert "AreAccessRulesProtected" in read
    assert "Get-Acl -LiteralPath $path" in read
    assert "Set-Acl" not in LIBRARY


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
        "Get-NeutrinoScheduledTask",
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
