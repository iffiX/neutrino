$nc = "$env:ProgramFiles\Neutrino Client\nclient.exe"
function Show { (& $nc service ai show 2>&1 | Out-String) -split "`n" | Select-Object -Skip 1 -First 1 }
function WaitFor($needle, $t0) {
  for ($i = 0; $i -lt 300; $i++) {
    $line = Show
    if ($line -match [regex]::Escape($needle)) { return "$needle after $([math]::Round(((Get-Date) - $t0).TotalSeconds, 2))s :: $line" }
    Start-Sleep -Milliseconds 100
  }
  return "TIMEOUT waiting for '$needle' :: $line"
}
Write-Output "== page: toggle off, Apply"
& powershell -NoProfile -ExecutionPolicy Bypass -File C:\ui.ps1 maximize | Out-Null
Start-Sleep -Seconds 1
& powershell -NoProfile -ExecutionPolicy Bypass -File C:\ui.ps1 click 230 390 | Out-Null
Start-Sleep -Milliseconds 600
$t0 = Get-Date
& powershell -NoProfile -ExecutionPolicy Bypass -File C:\ui.ps1 click 791 324 | Out-Null
Write-Output (WaitFor "as they were" $t0)
Write-Output "== files after page deactivation"
Get-Content "$env:USERPROFILE\.claude\settings.json"
Get-Content "$env:USERPROFILE\.codex\config.toml"
Get-Content "$env:USERPROFILE\.gemini\.env"
Write-Output "== cli: apply hub (timed)"
$t0 = Get-Date
& $nc service ai apply hub 2>&1 | Out-String
Write-Output (WaitFor "point at the hub" $t0)
Write-Output "== cli: apply off then apply hub at once (busy expected)"
$t0 = Get-Date
& $nc service ai apply off 2>&1 | Out-String
& $nc service ai apply hub 2>&1 | Out-String
Write-Output "second call returned exit $LASTEXITCODE"
Write-Output (WaitFor "as they were" $t0)
Start-Sleep -Seconds 1
Show
Write-Output "== cli: apply hub again (timed, adopt records already there)"
$t0 = Get-Date
& $nc service ai apply hub 2>&1 | Out-Null
Write-Output (WaitFor "point at the hub" $t0)
Write-Output "== cli: apply off (timed)"
$t0 = Get-Date
& $nc service ai apply off 2>&1 | Out-Null
Write-Output (WaitFor "as they were" $t0)
Write-Output "== files at the end"
Get-Content "$env:USERPROFILE\.claude\settings.json"
Get-Content "$env:USERPROFILE\.codex\config.toml"
Get-Content "$env:USERPROFILE\.gemini\.env"
Get-Content "$env:APPDATA\Neutrino Client\client.log" -Tail 8
