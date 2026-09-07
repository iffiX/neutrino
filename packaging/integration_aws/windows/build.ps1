# Runs on the Windows box. Builds the installer from the tree pushed to
# C:\neutrino\src, exactly as the release workflow does: both architectures,
# the arm64 one built but never installed here.

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$env:DOTNET_CLI_TELEMETRY_OPTOUT = '1'
$env:PATH = "C:\Program Files\Python312;C:\Program Files\Python312\Scripts;C:\dotnet;$env:USERPROFILE\.dotnet\tools;$env:PATH"
$env:DOTNET_ROOT = 'C:\dotnet'

$src = 'C:\neutrino\src'
$dist = 'C:\neutrino\dist'
New-Item -Force -ItemType Directory -Path $dist | Out-Null
Remove-Item "$dist\*.msi" -ErrorAction SilentlyContinue

Set-Location $src
foreach ($arch in @('x64', 'arm64')) {
    Write-Host "== building $arch"
    python agent\packaging\build_msi.py --output-dir $dist --architecture $arch
    if ($LASTEXITCODE -ne 0) { throw "build_msi.py failed for $arch" }
}
Get-ChildItem $dist | Format-Table Name, Length
