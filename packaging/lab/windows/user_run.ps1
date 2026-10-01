# Run one PowerShell script as the signed-in person and read its output back.
$script = $args[0]
Unregister-ScheduledTask -TaskName nclient_run -Confirm:$false -ErrorAction SilentlyContinue
Remove-Item C:\out\run.txt -ErrorAction SilentlyContinue
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -Command `"& '$script' *> C:\out\run.txt; Add-Content C:\out\run.txt '[done]'`""
$principal = New-ScheduledTaskPrincipal -UserId 'neutrino' -LogonType Interactive
Register-ScheduledTask -TaskName nclient_run -Action $action -Principal $principal -Force | Out-Null
Start-ScheduledTask -TaskName nclient_run
$deadline = (Get-Date).AddSeconds(420)
while (-not (Test-Path C:\out\run.txt) -or -not (Select-String -Path C:\out\run.txt -Pattern '\[done\]' -Quiet)) {
  if ((Get-Date) -gt $deadline) { Write-Output "timeout"; break }
  Start-Sleep -Seconds 1
}
Get-Content C:\out\run.txt
