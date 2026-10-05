# Install one Neutrino package on Windows: the hub, the agent or the client.
#
#   irm https://github.com/iffiX/neutrino/releases/latest/download/install.ps1 | iex
#   & ([scriptblock]::Create((irm https://github.com/iffiX/neutrino/releases/latest/download/install.ps1))) agent
#   irm https://gitee.com/iffiX/neutrino/raw/main/packaging/install/install.ps1 | iex
#
# Run in any PowerShell. Started without administrator rights, the script
# asks Windows for them once and goes on in the window Windows opens, which
# stays open for the next command. $NeutrinoEdition is the edition this
# script installs: intl from GitHub, cn from Gitee, where the latest
# release's tag is read from the API first. $env:NEUTRINO_VERSION names the
# release, such as v0.5.0; the latest when unset. $env:NEUTRINO_ASSET_DIR
# names a directory holding SHA256SUMS and the packages, which are installed
# from there with nothing downloaded.

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

# The edition this script installs; the mainland source tree stamps it cn.
$script:NeutrinoEdition = 'intl'
$NeutrinoReleases = 'https://github.com/iffiX/neutrino/releases'
$NeutrinoCnReleases = 'https://gitee.com/iffiX/neutrino/releases'
$NeutrinoCnLatestReleaseApi = 'https://gitee.com/api/v5/repos/iffiX/neutrino/releases/latest'
# What msiexec answers for a finished install, with and without a reboot owed.
$NeutrinoInstalledCodes = @(0, 3010)
# What the script carries into the window opened as administrator.
$NeutrinoCarriedVariables = @('NEUTRINO_VERSION', 'NEUTRINO_ASSET_DIR')

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

# Where the release's files are, for this script's edition. A cn release is
# found by its tag, which the API names for the latest one.
function Get-NeutrinoReleaseBase {
    param([string]$Work)
    if ($script:NeutrinoEdition -ne 'cn') {
        if ($env:NEUTRINO_VERSION) {
            return "$NeutrinoReleases/download/$env:NEUTRINO_VERSION"
        }
        return "$NeutrinoReleases/latest/download"
    }
    $tag = $env:NEUTRINO_VERSION
    if (-not $tag) {
        $latest = Join-Path $Work 'latest.json'
        Invoke-WebRequest -UseBasicParsing -Uri $NeutrinoCnLatestReleaseApi -OutFile $latest
        $tag = (Get-Content -Raw -LiteralPath $latest | ConvertFrom-Json).tag_name
        if (-not $tag) {
            throw "The latest release at $NeutrinoCnLatestReleaseApi names no tag."
        }
    }
    return "$NeutrinoCnReleases/download/$tag"
}

# This script's own text, however it was started: from a file, or fetched
# and run with Invoke-Expression.
function Get-NeutrinoScriptText {
    $ast = (Get-Command Install-Neutrino).ScriptBlock.Ast
    while ($ast.Parent) { $ast = $ast.Parent }
    return $ast.Extent.Text
}

# Ask Windows once for administrator rights: the same script, with what it
# was given, runs again in a PowerShell window opened as administrator, which
# stays open afterwards.
function Start-NeutrinoElevated {
    param([string]$Component)
    $copy = Join-Path ([IO.Path]::GetTempPath()) ('neutrino_install_' + [guid]::NewGuid().ToString('N') + '.ps1')
    Set-Content -LiteralPath $copy -Value (Get-NeutrinoScriptText) -Encoding UTF8
    $settings = ''
    foreach ($name in $NeutrinoCarriedVariables) {
        $value = [Environment]::GetEnvironmentVariable($name)
        if ($value) {
            $settings += "`$env:$name = '$($value.Replace("'", "''"))'; "
        }
    }
    $command = "$settings& '$($copy.Replace("'", "''"))' $Component"
    $shell = (Get-Process -Id $PID).Path
    Write-Output 'Neutrino asks Windows for administrator rights once, and goes on in the window it opens.'
    try {
        Start-Process -FilePath $shell -Verb RunAs -ArgumentList @(
            '-NoProfile', '-NoExit', '-ExecutionPolicy', 'Bypass', '-Command', $command
        ) | Out-Null
    } catch {
        throw 'Windows did not grant administrator rights; nothing was installed.'
    }
}

# What the machine's and the person's PATH say now, so a program the install
# put on it answers in this window.
function Update-NeutrinoPath {
    $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user = [Environment]::GetEnvironmentVariable('Path', 'User')
    $found = (@($machine, $user) | Where-Object { $_ }) -join ';'
    if ($found) { $env:Path = $found }
}

function Install-Neutrino {
    param([string]$Component = 'hub')

    if ($Component -notin @('hub', 'agent', 'client')) {
        throw "Name hub, agent or client to install, not $Component."
    }
    $machine = Get-NeutrinoMachine -Architecture $env:PROCESSOR_ARCHITECTURE
    if (-not $machine) {
        throw "No Neutrino package is published for Windows on $env:PROCESSOR_ARCHITECTURE."
    }
    if (-not (Test-NeutrinoAdministrator)) {
        Start-NeutrinoElevated -Component $Component
        return
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
            $base = Get-NeutrinoReleaseBase -Work $work
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
    Update-NeutrinoPath

    if ($Component -eq 'agent') {
        Write-Output "Next, in this window: nagent join '<enrollment link from the hub's Devices page>'"
        return
    }
    if ($Component -eq 'client') {
        Write-Output "Next, in a PowerShell of your own: nclient join '<client link from the hub's Clients page>'"
        return
    }
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
        Write-Output "Next, set the hub up in a browser at: $address"
    } else {
        Write-Output "Next, in this window: & '$nhub' open"
    }
}

Install-Neutrino @args
