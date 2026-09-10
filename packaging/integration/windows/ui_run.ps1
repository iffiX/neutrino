# Run a list of ui.ps1 commands (one per line in C:\ui_cmds.txt) in the person's session.
foreach ($line in Get-Content C:\ui_cmds.txt) {
  if ($line.Trim() -eq '') { continue }
  $parts = $line -split ' ', 3
  if ($parts[0] -eq 'sleep') { Start-Sleep -Seconds ([double]$parts[1]); continue }
  if ($parts[0] -eq 'cli') { & "$env:ProgramFiles\Neutrino Client\nclient.cmd" ($parts[1] -split ' ') 2>&1 | Out-String; Write-Output "exit $LASTEXITCODE"; continue }
  if ($parts[0] -eq 'clibg') { Start-Process -FilePath "$env:ProgramFiles\Neutrino Client\nclient.cmd" -ArgumentList ($parts[1] -split ' ') -WindowStyle Hidden -RedirectStandardOutput C:\out\clibg.txt; continue }
  if ($parts[0] -eq 'ps') { Invoke-Expression $parts[1] | Out-String; continue }
  & powershell -NoProfile -ExecutionPolicy Bypass -File C:\ui.ps1 @($parts) | Out-String
}
