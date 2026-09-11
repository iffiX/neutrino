# Runs on the Windows box. Builds the client installer from the tree pushed
# to C:\neutrino\src, exactly as the release workflow does. x64 only: the
# viewer and cc-switch upstream publish no Windows arm64 build.

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$env:DOTNET_CLI_TELEMETRY_OPTOUT = '1'
$env:PATH = "C:\Program Files\Python313;C:\Program Files\Python313\Scripts;C:\dotnet;$env:USERPROFILE\.dotnet\tools;$env:PATH"
$env:DOTNET_ROOT = 'C:\dotnet'

$src = 'C:\neutrino\src'
$dist = 'C:\neutrino\dist'
New-Item -Force -ItemType Directory -Path $dist | Out-Null
Remove-Item "$dist\*.msi" -ErrorAction SilentlyContinue

# A fresh image trusts no GitHub root until Windows has fetched it; one
# request per host through schannel does that, and Python's own client then
# verifies the release assets it downloads.
foreach ($origin in @('https://github.com/', 'https://objects.githubusercontent.com/', 'https://release-assets.githubusercontent.com/')) {
    try { Invoke-WebRequest $origin -Method Head -UseBasicParsing | Out-Null } catch {}
}

Set-Location $src
Write-Host "== building x64"
python client\packaging\build_msi.py --output-dir $dist --architecture x64
if ($LASTEXITCODE -ne 0) { throw "build_msi.py failed" }
Get-ChildItem $dist | Format-Table Name, Length
