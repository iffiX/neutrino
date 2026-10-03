# Install one Neutrino package on Windows: the hub, the agent or the client.
#
#   irm https://github.com/iffiX/neutrino/releases/latest/download/install.ps1 | iex
#   & ([scriptblock]::Create((irm https://github.com/iffiX/neutrino/releases/latest/download/install.ps1))) agent
#
# Run in a PowerShell opened as administrator. $env:NEUTRINO_VERSION names the
# release, such as v0.5.0; the latest when unset. $env:NEUTRINO_ASSET_DIR
# names a directory holding SHA256SUMS and the packages, which are installed
# from there with nothing downloaded.

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$NeutrinoReleases = 'https://github.com/iffiX/neutrino/releases'
# What msiexec answers for a finished install, with and without a reboot owed.
$NeutrinoInstalledCodes = @(0, 3010)

function Test-NeutrinoAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-NeutrinoMachine {
    param([string]$Architecture)
    switch ($Architecture.ToUpperInvariant()) {
        'AMD64' { return 'amd64' }
        'X86_64' { return 'amd64' }
        default { return $null }
    }
}

function Find-NeutrinoAsset {
    param([string]$Sums, [string]$Component, [string]$Machine)
    $pattern = "^([0-9a-f]{64}) [ *]?(neutrino-$Component-[0-9][^ ]*-windows-$Machine\.msi)$"
    foreach ($line in Get-Content -LiteralPath $Sums) {
        if ($line -match $pattern) {
            return [pscustomobject]@{ Sha256 = $Matches[1]; Name = $Matches[2] }
        }
    }
    return $null
}

function Install-Neutrino {
    param([string]$Component = 'hub')

    if (-not (Test-NeutrinoAdministrator)) {
        throw 'Run this in a PowerShell opened as administrator.'
    }
    if ($Component -notin @('hub', 'agent', 'client')) {
        throw "Name hub, agent or client to install, not $Component."
    }
    $machine = Get-NeutrinoMachine -Architecture $env:PROCESSOR_ARCHITECTURE
    if (-not $machine) {
        throw "No Neutrino package is published for Windows on $env:PROCESSOR_ARCHITECTURE."
    }

    $work = Join-Path ([IO.Path]::GetTempPath()) ('neutrino_' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $work | Out-Null
    try {
        if ($env:NEUTRINO_ASSET_DIR) {
            $source = (Resolve-Path -LiteralPath $env:NEUTRINO_ASSET_DIR).Path
            if (-not (Test-Path -LiteralPath (Join-Path $source 'SHA256SUMS'))) {
                throw "There is no SHA256SUMS in $source."
            }
        } else {
            if ($env:NEUTRINO_VERSION) {
                $base = "$NeutrinoReleases/download/$env:NEUTRINO_VERSION"
            } else {
                $base = "$NeutrinoReleases/latest/download"
            }
            $source = $work
            Invoke-WebRequest -UseBasicParsing -Uri "$base/SHA256SUMS" -OutFile (Join-Path $work 'SHA256SUMS')
        }

        $sums = Join-Path $source 'SHA256SUMS'
        $asset = Find-NeutrinoAsset -Sums $sums -Component $Component -Machine $machine
        if (-not $asset) {
            throw "The release publishes no Neutrino $Component package for Windows on $machine."
        }
        $package = Join-Path $source $asset.Name
        if (-not $env:NEUTRINO_ASSET_DIR) {
            Invoke-WebRequest -UseBasicParsing -Uri "$base/$($asset.Name)" -OutFile $package
        }
        if (-not (Test-Path -LiteralPath $package)) {
            throw "There is no $($asset.Name) in $source."
        }
        $digest = (Get-FileHash -Algorithm SHA256 -LiteralPath $package).Hash.ToLowerInvariant()
        if ($digest -ne $asset.Sha256) {
            throw "$($asset.Name) does not match its SHA256SUMS line; nothing was installed."
        }

        Write-Output "Installing $($asset.Name)"
        $msiexec = Start-Process -FilePath msiexec.exe -Wait -PassThru `
            -ArgumentList '/i', "`"$package`"", '/qn', '/norestart'
        if ($msiexec.ExitCode -notin $NeutrinoInstalledCodes) {
            throw "msiexec exited $($msiexec.ExitCode) installing $($asset.Name)."
        }
    } finally {
        Remove-Item -Recurse -Force -LiteralPath $work -ErrorAction SilentlyContinue
    }

    if ($Component -ne 'hub') { return }
    $nhub = Join-Path $env:ProgramFiles 'Neutrino\hub\nhub.exe'
    if (-not [Console]::IsInputRedirected) {
        & $nhub setup
        return
    }
    try {
        $address = & $nhub open --print 2>$null
    } catch {
        $address = $null
    }
    if ($address) {
        Write-Output "Set the hub up in a browser at: $address"
    } else {
        Write-Output "Set the hub up with: & '$nhub' open"
    }
}

Install-Neutrino @args
