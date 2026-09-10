# Runs on the Windows box. Everything build_msi.py needs and nothing else:
# a Python to run it, the .NET SDK that hosts WiX, and WiX itself at the
# version the release workflow pins. Each step is skipped when its result is
# already there, so a rerun after a failure costs seconds.

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$env:DOTNET_CLI_TELEMETRY_OPTOUT = '1'

$root = 'C:\neutrino'
$tools = "$root\tools"
New-Item -Force -ItemType Directory -Path $tools | Out-Null

$pythonVersion = '3.12.10'
$pythonHome = 'C:\Program Files\Python312'
$dotnetHome = 'C:\dotnet'
$wixVersion = '6.0.2'
$toolsHome = "$env:USERPROFILE\.dotnet\tools"

$env:PATH = "$pythonHome;$pythonHome\Scripts;$dotnetHome;$toolsHome;$env:PATH"
# A global tool's launcher looks for the runtime under Program Files unless
# told where a non-default install went.
$env:DOTNET_ROOT = $dotnetHome

if (-not (Test-Path "$pythonHome\python.exe")) {
    Write-Host "== python $pythonVersion"
    $installer = "$tools\python-$pythonVersion-amd64.exe"
    Invoke-WebRequest "https://www.python.org/ftp/python/$pythonVersion/python-$pythonVersion-amd64.exe" -OutFile $installer
    Start-Process $installer -Wait -ArgumentList '/quiet', 'InstallAllUsers=1', 'PrependPath=1', 'Include_test=0'
}
python --version

if (-not (Test-Path "$dotnetHome\dotnet.exe")) {
    Write-Host "== .NET SDK"
    Invoke-WebRequest 'https://dot.net/v1/dotnet-install.ps1' -OutFile "$tools\dotnet-install.ps1"
    & "$tools\dotnet-install.ps1" -Channel 8.0 -InstallDir $dotnetHome
}
dotnet --version

if (-not (Test-Path "$toolsHome\wix.exe")) {
    Write-Host "== WiX $wixVersion"
    dotnet tool install --global wix --version $wixVersion
}
wix --version

# CloseApplication comes from the Util extension, whose own 7 does not load
# in WiX 6.
Write-Host "== WiX Util extension $wixVersion"
wix extension add -g "WixToolset.Util.wixext/$wixVersion"

# The next SSH session must find all of it too.
$machinePath = [Environment]::GetEnvironmentVariable('PATH', 'Machine')
foreach ($dir in @($pythonHome, "$pythonHome\Scripts", $dotnetHome, $toolsHome)) {
    if ($machinePath -notlike "*$dir*") { $machinePath = "$dir;$machinePath" }
}
[Environment]::SetEnvironmentVariable('PATH', $machinePath, 'Machine')
[Environment]::SetEnvironmentVariable('DOTNET_ROOT', $dotnetHome, 'Machine')
Write-Host "toolchain ready"
