# Open the window in the signed-in person's session, not SYSTEM's.
Unregister-ScheduledTask -TaskName nclient_gui -Confirm:$false -ErrorAction SilentlyContinue
$action = New-ScheduledTaskAction -Execute 'C:\Program Files\Neutrino Client\python\pythonw.exe' -Argument '-m neutrino_client.cli.entry gui'
$principal = New-ScheduledTaskPrincipal -UserId 'neutrino' -LogonType Interactive
Register-ScheduledTask -TaskName nclient_gui -Action $action -Principal $principal -Force | Out-Null
Start-ScheduledTask -TaskName nclient_gui
Start-Sleep -Seconds 12
$info = Get-ScheduledTaskInfo -TaskName nclient_gui
Write-Output "task result $($info.LastTaskResult) at $($info.LastRunTime)"
tasklist | Select-String -Pattern "python|rustdesk|cc-switch" | Out-String
