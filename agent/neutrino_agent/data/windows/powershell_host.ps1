# The agent's PowerShell host on Windows: one function per operation the
# agent asks for, and a loop that reads one JSON request per line on standard
# input and writes one JSON answer per line on standard output.
#
# A request is {"id": n, "op": "...", "args": {...}}. An answer is
# {"id": n, "ok": true, "value": {...}, "private_bytes": n}; a function that
# refuses returns @{refusal = @{code = ...; params = ...}}, answered as
# {"id": n, "ok": false, "kind": "refusal", "code": ..., "params": ...}; an
# exception is {"id": n, "ok": false, "kind": "error", "message": ...}.
# The end of standard input ends the loop and the process.

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$WarningPreference = 'SilentlyContinue'
$InformationPreference = 'SilentlyContinue'
# Both streams carry ASCII alone, whichever encoding the console takes.
try {
    [Console]::InputEncoding = New-Object -TypeName Text.UTF8Encoding -ArgumentList $false
    [Console]::OutputEncoding = New-Object -TypeName Text.UTF8Encoding -ArgumentList $false
} catch {
    $Error.Clear()
}

# Whether an error is Windows refusing a login (0x8007052E), in the error's
# message or only in its id and HResult.
function Test-NeutrinoLogonRefused($Failure) {
    $said = "$($Failure.Exception.Message) $($Failure.FullyQualifiedErrorId)"
    $hresult = '{0:X8}' -f $Failure.Exception.HResult
    return ($said -match '0x8007052E') -or ($hresult -eq '8007052E')
}

# The refusal a login Windows rejects at registration answers.
function Get-NeutrinoLogonRefusal($Account) {
    return @{refusal = @{code = 'credential_invalid'; params = @{account = $Account}}}
}

# One task: whether it is there, its description and its state.
function Get-NeutrinoTask($Request) {
    $task = Get-ScheduledTask -TaskName $Request.task -ErrorAction SilentlyContinue
    if ($null -eq $task) {
        return @{is_present = $false; description = ''; state = ''}
    }
    return @{is_present = $true; description = "$($task.Description)"; state = "$($task.State)"}
}

# Each task whose name starts with the prefix: its state and its last result.
function Get-NeutrinoTaskState($Request) {
    $tasks = @()
    foreach ($task in @(Get-ScheduledTask -TaskName "$($Request.prefix)*" -ErrorAction SilentlyContinue)) {
        $info = Get-ScheduledTaskInfo -TaskName $task.TaskName
        $tasks += @{
            name = "$($task.TaskName)"
            state = "$($task.State)"
            last_result = [int64]$info.LastTaskResult
        }
    }
    return @{tasks = $tasks}
}

# Registers an instance's task under the account's login: at startup, no time
# limit, started again a minute after it stops, a limited token.
function Register-NeutrinoTask($Request) {
    $action = New-ScheduledTaskAction -Execute $Request.program -Argument $Request.arguments
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) `
        -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
    try {
        Register-ScheduledTask -TaskName $Request.task -Description $Request.description `
            -Action $action -Trigger $trigger -Settings $settings `
            -User $Request.account -Password $Request.password -RunLevel Limited -Force | Out-Null
    } catch {
        if (Test-NeutrinoLogonRefused $_) {
            return Get-NeutrinoLogonRefusal $Request.account
        }
        throw
    }
    return @{}
}

# Registers a one-shot task under the account's login with a time limit and a
# limited token, and starts it.
function Invoke-NeutrinoOneShotTask($Request) {
    $action = New-ScheduledTaskAction -Execute $Request.program -Argument $Request.arguments
    $settings = New-ScheduledTaskSettingsSet `
        -ExecutionTimeLimit (New-TimeSpan -Seconds $Request.timeout_s) `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    try {
        Register-ScheduledTask -TaskName $Request.task -Action $action -Settings $settings `
            -User $Request.account -Password $Request.password -RunLevel Limited -Force | Out-Null
    } catch {
        if (Test-NeutrinoLogonRefused $_) {
            return Get-NeutrinoLogonRefusal $Request.account
        }
        throw
    }
    Start-ScheduledTask -TaskName $Request.task | Out-Null
    return @{}
}

# Starts a task.
function Start-NeutrinoTask {
    [CmdletBinding(SupportsShouldProcess = $true)]
    [OutputType([hashtable])]
    param($Request)
    if ($PSCmdlet.ShouldProcess($Request.task)) {
        Start-ScheduledTask -TaskName $Request.task | Out-Null
    }
    return @{}
}

# Stops a task's run; a task that is not there or not running is left.
function Stop-NeutrinoTask {
    [CmdletBinding(SupportsShouldProcess = $true)]
    [OutputType([hashtable])]
    param($Request)
    if ($PSCmdlet.ShouldProcess($Request.task)) {
        Stop-ScheduledTask -TaskName $Request.task -ErrorAction SilentlyContinue | Out-Null
    }
    return @{}
}

# Stops a task's run and unregisters it; a task that is not there is left.
function Unregister-NeutrinoTask($Request) {
    Stop-ScheduledTask -TaskName $Request.task -ErrorAction SilentlyContinue | Out-Null
    Unregister-ScheduledTask -TaskName $Request.task -Confirm:$false `
        -ErrorAction SilentlyContinue | Out-Null
    return @{}
}

# Removes every firewall rule whose name starts with the prefix.
function Remove-NeutrinoFirewallRule {
    [CmdletBinding(SupportsShouldProcess = $true)]
    [OutputType([hashtable])]
    param($Request)
    if ($PSCmdlet.ShouldProcess($Request.prefix)) {
        Remove-NetFirewallRule -Name "$($Request.prefix)*" -ErrorAction SilentlyContinue | Out-Null
    }
    return @{}
}

# The services, the scheduled tasks and the firewall rules whose names start
# with the prefix.
function Get-NeutrinoAddition($Request) {
    $services = @(Get-Service -Name "$($Request.prefix)*" -ErrorAction SilentlyContinue |
        ForEach-Object { [string]$_.Name })
    $tasks = @(Get-ScheduledTask -TaskName "$($Request.prefix)*" -ErrorAction SilentlyContinue |
        ForEach-Object { [string]$_.TaskName })
    $rules = @(Get-NetFirewallRule -Name "$($Request.prefix)*" -ErrorAction SilentlyContinue |
        ForEach-Object { [string]$_.Name })
    return @{services = $services; tasks = $tasks; rules = $rules}
}

# Stops and deletes the services named, stops and unregisters the tasks
# named, and removes the firewall rules named.
function Remove-NeutrinoAddition {
    [CmdletBinding(SupportsShouldProcess = $true)]
    [OutputType([hashtable])]
    param($Request)
    if (-not $PSCmdlet.ShouldProcess('the agent''s additions')) {
        return @{}
    }
    foreach ($name in @($Request.services)) {
        Stop-Service -Name $name -Force -ErrorAction SilentlyContinue | Out-Null
        & sc.exe delete $name | Out-Null
    }
    foreach ($name in @($Request.tasks)) {
        Stop-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue | Out-Null
        Unregister-ScheduledTask -TaskName $name -Confirm:$false `
            -ErrorAction SilentlyContinue | Out-Null
    }
    foreach ($name in @($Request.rules)) {
        Remove-NetFirewallRule -Name $name -ErrorAction SilentlyContinue | Out-Null
    }
    return @{}
}

# The thermal zones the firmware exposes, in tenths of a kelvin; none on most
# machines.
function Get-NeutrinoThermalZone {
    $readings = @()
    try {
        $zones = @(Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature)
        foreach ($zone in $zones) {
            $readings += [double]$zone.CurrentTemperature
        }
    } catch {
        $readings = @()
    }
    return @{readings = $readings}
}

# The SMB server's state, the shares whose description starts with the
# marker, the sessions, the listed accounts and the fence rule.
function Get-NeutrinoShare($Request) {
    $svc = Get-Service -Name LanmanServer -ErrorAction SilentlyContinue
    $shares = @()
    foreach ($share in @(Get-SmbShare -ErrorAction SilentlyContinue)) {
        if (-not "$($share.Description)".StartsWith($Request.marker)) {
            continue
        }
        $access = @()
        foreach ($entry in @(Get-SmbShareAccess -Name $share.Name)) {
            $access += @{account = "$($entry.AccountName)"; right = "$($entry.AccessRight)"}
        }
        $shares += @{
            name = $share.Name
            path = $share.Path
            description = "$($share.Description)"
            access = $access
        }
    }
    $sessions = @()
    foreach ($session in @(Get-SmbSession -ErrorAction SilentlyContinue)) {
        $sessions += @{
            user = "$($session.ClientUserName)"
            address = "$($session.ClientComputerName)"
        }
    }
    $users = @()
    foreach ($name in @($Request.accounts)) {
        $held = Get-LocalUser -Name $name -ErrorAction SilentlyContinue
        $users += @{
            name = $name
            is_present = [bool]$held
            is_enabled = [bool]($held -and $held.Enabled)
        }
    }
    $fence = @{is_present = $false; is_enabled = $false; blocked = @()}
    $rule = Get-NetFirewallRule -Name $Request.rule_name -ErrorAction SilentlyContinue
    if ($rule) {
        $fence.is_present = $true
        $fence.is_enabled = "$($rule.Enabled)" -eq 'True'
        $fence.blocked = @(($rule | Get-NetFirewallAddressFilter).RemoteAddress)
    }
    return @{
        is_present = [bool]$svc
        is_running = [bool]($svc -and $svc.Status -eq 'Running')
        shares = $shares
        sessions = $sessions
        users = $users
        fence = $fence
    }
}

# Refuses a share or an account name the module did not make, then
# converges the server, the fence, the accounts and the shares; the shares'
# folders are made here and granted by the agent afterwards.
function Set-NeutrinoShare {
    [CmdletBinding(SupportsShouldProcess = $true)]
    [OutputType([hashtable])]
    param($Request)
    if (-not $PSCmdlet.ShouldProcess('the file share')) {
        return @{notes = @()}
    }
    $computer = $env:COMPUTERNAME
    foreach ($s in @($Request.shares)) {
        $held = Get-SmbShare -Name $s.name -ErrorAction SilentlyContinue
        $is_ours = (@($Request.owned_shares) -contains $s.name) -and
            "$($held.Description)".StartsWith($Request.marker)
        if ($held -and -not $is_ours) {
            return @{refusal = @{code = 'share_name_taken'; params = @{name = $s.name}}}
        }
    }
    foreach ($u in @($Request.users)) {
        $held = Get-LocalUser -Name $u -ErrorAction SilentlyContinue
        $is_ours = (@($Request.owned_accounts) -contains $u) -or
            ("$($held.Description)" -eq $Request.marker)
        if ($held -and -not $is_ours) {
            return @{refusal = @{code = 'user_name_taken'; params = @{user = $u}}}
        }
    }
    $notes = @()
    $svc = Get-Service -Name LanmanServer
    if ("$($svc.StartType)" -eq 'Disabled') {
        Set-Service -Name LanmanServer -StartupType Automatic | Out-Null
    }
    if ($svc.Status -ne 'Running') {
        Start-Service -Name LanmanServer | Out-Null
        $notes += 'started the server'
    }
    $blocked = @($Request.blocked_addresses)
    $rule = Get-NetFirewallRule -Name $Request.rule_name -ErrorAction SilentlyContinue
    if ($blocked.Count -eq 0) {
        if ($rule) {
            Set-NetFirewallRule -Name $Request.rule_name -Enabled False | Out-Null
        }
    } elseif (-not $rule) {
        New-NetFirewallRule -Name $Request.rule_name -DisplayName $Request.rule_title `
            -Direction Inbound -Action Block -Protocol TCP -LocalPort 445 `
            -RemoteAddress $blocked -Profile Any | Out-Null
        $notes += 'fenced the server'
    } else {
        Set-NetFirewallRule -Name $Request.rule_name -RemoteAddress $blocked -Enabled True | Out-Null
    }
    $hidden = 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon\SpecialAccounts\UserList'
    if (-not (Test-Path -Path $hidden)) {
        New-Item -Path $hidden -Force | Out-Null
    }
    foreach ($u in @($Request.users)) {
        if (-not (Get-LocalUser -Name $u -ErrorAction SilentlyContinue)) {
            New-LocalUser -Name $u -NoPassword -Disabled -AccountNeverExpires `
                -UserMayNotChangePassword -Description $Request.marker | Out-Null
            Set-LocalUser -Name $u -PasswordNeverExpires $true | Out-Null
            $notes += "created account $u"
        }
        New-ItemProperty -Path $hidden -Name $u -Value 0 -PropertyType DWord -Force | Out-Null
    }
    foreach ($u in @($Request.retired_accounts)) {
        $held = Get-LocalUser -Name $u -ErrorAction SilentlyContinue
        if ($held -and $held.Enabled) {
            Disable-LocalUser -Name $u | Out-Null
            $notes += "retired $u"
        }
    }
    foreach ($name in @($Request.removed_shares)) {
        $held = Get-SmbShare -Name $name -ErrorAction SilentlyContinue
        if ($held -and "$($held.Description)".StartsWith($Request.marker)) {
            Remove-SmbShare -Name $name -Force | Out-Null
            $notes += "removed share $name"
        }
    }
    foreach ($s in @($Request.shares)) {
        if (-not (Test-Path -LiteralPath $s.path)) {
            New-Item -ItemType Directory -Path $s.path -Force | Out-Null
        }
        $wanted = @()
        foreach ($u in @($s.accounts)) {
            $wanted += "$computer\$u"
        }
        $held = Get-SmbShare -Name $s.name -ErrorAction SilentlyContinue
        if ($held -and $held.Path -ne $s.path) {
            Remove-SmbShare -Name $s.name -Force | Out-Null
            $held = $null
        }
        if (-not $held) {
            $made = @{Name = $s.name; Path = $s.path; Description = $s.description}
            if ($wanted.Count -eq 0) {
                $made.FullAccess = $Request.share_owner
            } elseif ($s.share_right -eq 'Change') {
                $made.ChangeAccess = $wanted
            } else {
                $made.ReadAccess = $wanted
            }
            New-SmbShare @made | Out-Null
            $notes += "created share $($s.name)"
            continue
        }
        Set-SmbShare -Name $s.name -Description $s.description -Force | Out-Null
        foreach ($entry in @(Get-SmbShareAccess -Name $s.name)) {
            $account = "$($entry.AccountName)"
            $is_kept = ($wanted -contains $account) -and ("$($entry.AccessRight)" -eq $s.share_right)
            if ($wanted.Count -eq 0) {
                $is_kept = $account -eq $Request.share_owner
            }
            if (-not $is_kept) {
                Revoke-SmbShareAccess -Name $s.name -AccountName $account -Force | Out-Null
            }
        }
        foreach ($account in $wanted) {
            Grant-SmbShareAccess -Name $s.name -AccountName $account `
                -AccessRight $s.share_right -Force | Out-Null
        }
        if ($wanted.Count -eq 0) {
            Grant-SmbShareAccess -Name $s.name -AccountName $Request.share_owner `
                -AccessRight Full -Force | Out-Null
        }
    }
    return @{notes = $notes}
}

# Takes down the marked shares the record lists; with is_removed also
# disables the listed accounts and deletes the fence.
function Remove-NeutrinoShare {
    [CmdletBinding(SupportsShouldProcess = $true)]
    [OutputType([hashtable])]
    param($Request)
    if (-not $PSCmdlet.ShouldProcess('the file share')) {
        return @{}
    }
    foreach ($name in @($Request.owned_shares)) {
        $held = Get-SmbShare -Name $name -ErrorAction SilentlyContinue
        if ($held -and "$($held.Description)".StartsWith($Request.marker)) {
            Remove-SmbShare -Name $name -Force | Out-Null
        }
    }
    if ($Request.is_removed) {
        foreach ($u in @($Request.owned_accounts)) {
            $held = Get-LocalUser -Name $u -ErrorAction SilentlyContinue
            if ($held -and $held.Enabled) {
                Disable-LocalUser -Name $u | Out-Null
            }
        }
        Remove-NetFirewallRule -Name $Request.rule_name -ErrorAction SilentlyContinue | Out-Null
    }
    return @{}
}

# The SMB server's latest events, oldest first: the time, the event id and
# the first line of the message.
function Get-NeutrinoShareLog($Request) {
    $events = @(Get-WinEvent -LogName $Request.log_name -MaxEvents $Request.lines `
        -ErrorAction SilentlyContinue)
    $lines = @()
    for ($k = $events.Count - 1; $k -ge 0; $k--) {
        $record = $events[$k]
        $first = @("$($record.Message)" -split '\r?\n' | Where-Object { $_.Trim() })
        $text = if ($first.Count -gt 0) { $first[0].Trim() } else { '' }
        $lines += "$($record.TimeCreated.ToString('s')) $($record.Id) $text".TrimEnd()
    }
    return @{lines = $lines}
}

# Sets one listed account's password and lets it sign in over the network.
function Set-NeutrinoSharePassword {
    [CmdletBinding(SupportsShouldProcess = $true)]
    [OutputType([hashtable])]
    param($Request)
    if (-not $PSCmdlet.ShouldProcess($Request.name)) {
        return @{}
    }
    $secret = New-Object -TypeName Security.SecureString
    foreach ($character in $Request.password.ToCharArray()) {
        $secret.AppendChar($character)
    }
    Set-LocalUser -Name $Request.name -Password $secret -PasswordNeverExpires $true | Out-Null
    Enable-LocalUser -Name $Request.name | Out-Null
    return @{}
}

# Each operation the agent sends, by its name.
$NeutrinoOperations = @{
    'task_read' = 'Get-NeutrinoTask'
    'task_states' = 'Get-NeutrinoTaskState'
    'task_write' = 'Register-NeutrinoTask'
    'task_run_once' = 'Invoke-NeutrinoOneShotTask'
    'task_start' = 'Start-NeutrinoTask'
    'task_stop' = 'Stop-NeutrinoTask'
    'task_remove' = 'Unregister-NeutrinoTask'
    'rules_forget' = 'Remove-NeutrinoFirewallRule'
    'added_list' = 'Get-NeutrinoAddition'
    'added_remove' = 'Remove-NeutrinoAddition'
    'thermal_zones' = 'Get-NeutrinoThermalZone'
    'share_status' = 'Get-NeutrinoShare'
    'share_apply' = 'Set-NeutrinoShare'
    'share_withdraw' = 'Remove-NeutrinoShare'
    'share_log' = 'Get-NeutrinoShareLog'
    'share_password' = 'Set-NeutrinoSharePassword'
}

# The answer to one request line: the function's value, its refusal, or the
# error it raised.
function Get-NeutrinoAnswer($Line) {
    $id = $null
    try {
        $request = ConvertFrom-Json -InputObject $Line
        $id = $request.id
        $name = $NeutrinoOperations["$($request.op)"]
        if (-not $name) {
            throw "no operation named $($request.op)"
        }
        $value = @(& $name $request.args)[-1]
        if ($value -is [hashtable] -and $value.ContainsKey('refusal')) {
            return @{
                id = $id
                ok = $false
                kind = 'refusal'
                code = $value.refusal.code
                params = $value.refusal.params
            }
        }
        return @{id = $id; ok = $true; value = $value}
    } catch {
        return @{id = $id; ok = $false; kind = 'error'; message = "$($_.Exception.Message)"}
    }
}

# One answer as one line of JSON, every character beyond ASCII escaped.
function ConvertTo-NeutrinoLine($Answer) {
    $json = ConvertTo-Json -InputObject $Answer -Compress -Depth 8
    return [regex]::Replace($json, '[^\x00-\x7F]', {
            param($found)
            '\u{0:x4}' -f [int][char]$found.Value
        })
}

while ($true) {
    $line = [Console]::In.ReadLine()
    if ($null -eq $line) {
        break
    }
    $answer = Get-NeutrinoAnswer $line
    $answer.private_bytes = [Diagnostics.Process]::GetCurrentProcess().PrivateMemorySize64
    [Console]::Out.WriteLine((ConvertTo-NeutrinoLine $answer))
    [Console]::Out.Flush()
}
