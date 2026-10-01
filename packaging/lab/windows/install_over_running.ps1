# Install over a deliberately running resident: the installer must close it.
$ErrorActionPreference = "Continue"
Write-Output ("nclient before: " + ((Get-Process nclient -ErrorAction SilentlyContinue | ForEach-Object { $_.Id }) -join ','))
Invoke-WebRequest http://192.168.122.1:8000/new_client.msi -OutFile C:\out\new_client.msi
$r = Start-Process msiexec -Wait -PassThru -ArgumentList '/i','C:\out\new_client.msi','/quiet','/norestart','/l*v','C:\out\upgrade.log'
Write-Output "msiexec exit $($r.ExitCode)"
Start-Sleep -Seconds 3
Write-Output ("nclient after: " + ((Get-Process nclient -ErrorAction SilentlyContinue | ForEach-Object { $_.Id }) -join ','))
Write-Output "== what the log says about closing"
Select-String -Path C:\out\upgrade.log -Pattern 'CloseApplication|WixCloseApplications|CLIENTWINDOWRUNNING' -ErrorAction SilentlyContinue |
  Select-Object -First 6 | ForEach-Object { $_.Line.Trim() }
Write-Output "== installed app.js carries the drive picker"
$js = Get-Content "$env:ProgramFiles\Neutrino Client\neutrino_client\data\gui\app.js" -Raw -ErrorAction SilentlyContinue
Write-Output ("driveLetterLine present: " + ($js -match 'driveLetterLine'))
