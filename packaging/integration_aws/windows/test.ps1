# Runs on the Windows box. The installer is what ships, so it is what is
# tested: install it, see the service register and run, see the agent answer
# as unenrolled, join the hub the link names, see it heartbeat.
#
# Exit codes of the agent are values here, not errors: unenrolled is 1.

param(
    [Parameter(Mandatory = $true)][string]$Msi,
    [Parameter(Mandatory = $true)][string]$Link
)

$ErrorActionPreference = 'Continue'
$PSNativeCommandUseErrorActionPreference = $false
$ProgressPreference = 'SilentlyContinue'

function Step($name) { Write-Host ""; Write-Host "== $name" }
function Fail($why) { Write-Host "FAILED: $why"; exit 1 }

# A console `nagent` left waiting by an earlier walk holds the interpreter
# open, and the uninstaller's restart manager cannot close a process in
# another session: it answers 1601 and removes nothing.
Get-Process python -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -like "$env:ProgramFiles\Neutrino Agent\*" } |
    Stop-Process -Force -ErrorAction SilentlyContinue

# Every build carries its own product code, so the previous install is
# removed by the code the registry holds for it, never by the new file.
$installed = Get-ChildItem 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall' |
    Where-Object { (Get-ItemProperty $_.PSPath).DisplayName -eq 'Neutrino Agent' }
foreach ($product in $installed) {
    Step "remove the previous install $($product.PSChildName)"
    $remove = Start-Process msiexec -Wait -PassThru -ArgumentList '/x', $product.PSChildName, '/quiet', '/norestart', '/l*v', 'C:\neutrino\uninstall.log'
    if ($remove.ExitCode -ne 0) { Fail "msiexec /x exited $($remove.ExitCode); see C:\neutrino\uninstall.log" }
}
if (Get-Service -Name 'NeutrinoAgent' -ErrorAction SilentlyContinue) { Fail "the service outlived the uninstaller" }

Step "install $Msi"
$install = Start-Process msiexec -Wait -PassThru -ArgumentList '/i', $Msi, '/quiet', '/norestart', '/l*v', 'C:\neutrino\install.log'
if ($install.ExitCode -ne 0) { Fail "msiexec exited $($install.ExitCode); see C:\neutrino\install.log" }

Step "the service"
$service = Get-CimInstance Win32_Service -Filter "Name='NeutrinoAgent'"
if ($null -eq $service) { Fail "no NeutrinoAgent service registered" }
$service | Format-List Name, State, StartMode, PathName
if ($service.State -ne 'Running') { Fail "the service is $($service.State)" }
if ($service.PathName -notlike '*run --windows-service*') { Fail "the service runs $($service.PathName)" }

$nagent = "$env:ProgramFiles\Neutrino Agent\nagent.cmd"
# Uninstalling keeps the binding under ProgramData, the way a deb's remove
# keeps /etc: a box from an earlier walk comes back already joined, and the
# walk starts from unenrolled by leaving first.
& $nagent status | Out-Null
if ($LASTEXITCODE -eq 0) {
    Step "leave the hub a previous walk joined"
    & $nagent disconnect
    if ($LASTEXITCODE -ne 0) { Fail "nagent disconnect exited $LASTEXITCODE" }
}

Step "status before joining (expects exit 1: unenrolled)"
& $nagent status
if ($LASTEXITCODE -ne 1) { Fail "nagent status exited $LASTEXITCODE, expected 1" }

Step "join the hub"
& $nagent connect $Link --yes
if ($LASTEXITCODE -ne 0) { Fail "nagent connect exited $LASTEXITCODE" }

Step "status after joining (expects exit 0: heartbeat ok)"
$ok = $false
foreach ($try in 1..12) {
    & $nagent status
    if ($LASTEXITCODE -eq 0) { $ok = $true; break }
    Start-Sleep -Seconds 5
}
if (-not $ok) { Fail "the agent never reported a good heartbeat" }

Step "the service, after joining"
Get-CimInstance Win32_Service -Filter "Name='NeutrinoAgent'" | Format-List Name, State
Write-Host "windows side passed"
