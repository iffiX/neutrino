# The msi walk, run as SYSTEM: remove any earlier install, install the fresh
# msi, then check what the package promises.
$ErrorActionPreference = "Continue"
function Step($t) { Write-Output "=== $t" }
$msi = (Get-ChildItem C:\out\*.msi | Select-Object -First 1).FullName
Write-Output "msi: $msi"
Step "remove an earlier install"
$products = Get-ChildItem HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall | Where-Object { $_.GetValue("DisplayName") -eq "Neutrino Client" }
foreach ($p in $products) {
  $r = Start-Process msiexec -Wait -PassThru -ArgumentList '/x', $p.PSChildName, '/quiet', '/norestart', '/l*v', 'C:\out\uninstall.log'
  Write-Output "uninstall $($p.PSChildName): exit $($r.ExitCode)"
}
Step "install"
$r = Start-Process msiexec -Wait -PassThru -ArgumentList '/i', $msi, '/quiet', '/norestart', '/l*v', 'C:\out\install.log'
Write-Output "msiexec exit $($r.ExitCode)"
Step "what landed"
Get-ChildItem "$env:ProgramFiles\Neutrino Client" | Select-Object Name, Length | Format-Table -AutoSize | Out-String -Width 120
Get-ChildItem "$env:ProgramFiles\Neutrino Client\bin" | Select-Object Name, Length | Format-Table -AutoSize | Out-String -Width 120
Step "run entry"
Get-ItemProperty HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run | Select-Object NeutrinoClient | Format-List | Out-String
Step "path"
(Get-ItemProperty "HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Environment").Path
Step "start menu"
Get-ChildItem "C:\ProgramData\Microsoft\Windows\Start Menu\Programs" | Where-Object Name -like "Neutrino*" | Select-Object Name | Out-String
Step "webview2"
Get-ItemProperty "HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}" -ErrorAction SilentlyContinue | Select-Object pv | Out-String
Step "nclient --version"
& "$env:ProgramFiles\Neutrino Client\nclient.exe" --version
Write-Output "exit $LASTEXITCODE"
Step "nclient status (unbound, no resident)"
& "$env:ProgramFiles\Neutrino Client\nclient.exe" status
Write-Output "exit $LASTEXITCODE"
