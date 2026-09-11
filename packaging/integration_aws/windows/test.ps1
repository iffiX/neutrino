# Runs on the Windows box. The installer is what ships, so it is what is
# tested: install it, see the compiled client answer as unbound, join the hub
# the link names, run the resident, see it connected.
#
# Exit codes of the client are values here, not errors: unbound is 1.

param(
    [Parameter(Mandatory = $true)][string]$Msi,
    [Parameter(Mandatory = $true)][string]$Link
)

$ErrorActionPreference = 'Continue'
$PSNativeCommandUseErrorActionPreference = $false
$ProgressPreference = 'SilentlyContinue'

function Step($name) { Write-Host ""; Write-Host "== $name" }
function Fail($why) { Write-Host "FAILED: $why"; exit 1 }

$nclient = "$env:ProgramFiles\Neutrino Client\nclient.exe"

# A resident left by an earlier walk holds the prefix open, and the
# installer's own quit cannot reach one in another session.
Get-Process nclient -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

# Every build carries its own product code, so the previous install is
# removed by the code the registry holds for it, never by the new file.
$installed = Get-ChildItem 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall' |
    Where-Object { (Get-ItemProperty $_.PSPath).DisplayName -eq 'Neutrino Client' }
foreach ($product in $installed) {
    Step "remove the previous install $($product.PSChildName)"
    $remove = Start-Process msiexec -Wait -PassThru -ArgumentList '/x', $product.PSChildName, '/quiet', '/norestart', '/l*v', 'C:\neutrino\uninstall.log'
    if ($remove.ExitCode -ne 0) { Fail "msiexec /x exited $($remove.ExitCode); see C:\neutrino\uninstall.log" }
}
if (Test-Path "$env:ProgramFiles\Neutrino Client") { Fail "the prefix outlived the uninstaller" }

Step "install $Msi"
$install = Start-Process msiexec -Wait -PassThru -ArgumentList '/i', $Msi, '/quiet', '/norestart', '/l*v', 'C:\neutrino\install.log'
if ($install.ExitCode -ne 0) { Fail "msiexec exited $($install.ExitCode); see C:\neutrino\install.log" }
if (-not (Test-Path $nclient)) { Fail "no nclient.exe under Program Files" }

Step "what landed"
$all = Get-ChildItem -Recurse -File "$env:ProgramFiles\Neutrino Client"
Write-Host "files $($all.Count), .py $(($all | Where-Object Extension -eq '.py').Count), .pyc $(($all | Where-Object Extension -eq '.pyc').Count)"
if (($all | Where-Object { $_.Extension -in '.py', '.pyc' }).Count -ne 0) { Fail "the payload carries Python source or bytecode" }

# A removal keeps the binding, so a box from an earlier walk comes back
# already joined; the walk starts from unbound by leaving first.
& $nclient status | Out-Null
if ($LASTEXITCODE -ne 1) {
    Step "leave the hub a previous walk joined"
    & $nclient quit | Out-Null
    & $nclient disconnect
}

Step "status before joining (expects exit 1: unbound)"
& $nclient status
if ($LASTEXITCODE -ne 1) { Fail "nclient status exited $LASTEXITCODE, expected 1" }

Step "join the hub"
& $nclient connect $Link --yes
if ($LASTEXITCODE -ne 0) { Fail "nclient connect exited $LASTEXITCODE" }

Step "run the resident"
Start-Process -FilePath $nclient -ArgumentList 'gui', '--hidden'

Step "status after joining (expects exit 0: bound, running, connected)"
$ok = $false
foreach ($try in 1..12) {
    & $nclient status
    if ($LASTEXITCODE -eq 0) { $ok = $true; break }
    Start-Sleep -Seconds 5
}
if (-not $ok) { Fail "the client never reported itself connected" }
Write-Host "windows side passed"
