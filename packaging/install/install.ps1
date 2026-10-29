# Install one Neutrino package on Windows: the hub, the agent or the client.
#
#   irm https://github.com/iffiX/neutrino/releases/latest/download/install.ps1 | iex
#   & ([scriptblock]::Create((irm https://github.com/iffiX/neutrino/releases/latest/download/install.ps1))) agent
#   irm https://cnb.cool/iffi-X/neutrino/-/git/raw/main/packaging/install/install.ps1 | iex
#
# Run in any PowerShell. Started without administrator rights, the script
# asks Windows for them once and goes on in the window Windows opens, which
# stays open for the next command. $NeutrinoEdition is the edition whose
# package this script installs, and $NeutrinoReleaseSites the release sites
# its build stamped; a checkout names none. The latest release's tag is read
# from latest.json on the sites, and each file comes from the fastest site,
# the script moving to the next one on a stall. $env:NEUTRINO_VERSION names
# the release, such as v0.5.0; the latest when unset. $env:NEUTRINO_ASSET_DIR
# names a directory holding SHA256SUMS and the packages, which are installed
# from there with nothing downloaded.

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

# The edition this script installs; the mainland source tree stamps it cn.
$script:NeutrinoEdition = 'intl'
# The release sites, each the address of a tag's files, {tag} in it, and the
# address of latest.json.
$script:NeutrinoReleaseSites = @()
# How long a probe or a read of latest.json waits for a site, how long a
# download may receive nothing before its site counts as stalled, in
# seconds, and how many bytes a probe asks for.
$script:NeutrinoProbeWaitSeconds = 5
$script:NeutrinoStallSeconds = 20
$script:NeutrinoProbeBytes = 1048576
# What msiexec answers for a finished install, with and without a reboot owed.
$NeutrinoInstalledCodes = @(0, 3010)
# What the script carries into the window opened as administrator: the
# person's settings, and the roaming folder of the account that ran it, where
# that person's client bindings are.
$NeutrinoCarriedVariables = @('NEUTRINO_VERSION', 'NEUTRINO_ASSET_DIR', 'NEUTRINO_PERSON_APPDATA')

function Test-NeutrinoAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

# Whether this machine's agent holds a binding to a hub: a machine that has
# joined is not told to join again.
function Test-NeutrinoAgentBound {
    $programData = if ($env:ProgramData) { $env:ProgramData } else { 'C:\ProgramData' }
    $binding = Join-Path $programData 'Neutrino\agent\config\agent.json'
    if (-not (Test-Path -LiteralPath $binding)) { return $false }
    $text = Get-Content -Raw -LiteralPath $binding -ErrorAction SilentlyContinue
    return [bool]($text -match '"token"\s*:\s*"[^"]')
}

# Whether this machine's hub has been set up: its panel settings hold a
# password hash, which is any value but the example's placeholder.
function Test-NeutrinoHubSetUp {
    $programData = if ($env:ProgramData) { $env:ProgramData } else { 'C:\ProgramData' }
    $settings = Join-Path $programData 'Neutrino\hub\config\web\settings.json'
    if (-not (Test-Path -LiteralPath $settings)) { return $false }
    $text = Get-Content -Raw -LiteralPath $settings -ErrorAction SilentlyContinue
    return [bool]($text -match '"admin_password_hash"\s*:\s*"(?!PLACEHOLDER)[^"]')
}

# Whether the account that ran the script holds a client binding: a person
# who has joined is not told to join again.
function Test-NeutrinoClientBound {
    $roaming = if ($env:NEUTRINO_PERSON_APPDATA) { $env:NEUTRINO_PERSON_APPDATA } else { $env:APPDATA }
    if (-not $roaming) { return $false }
    $bindings = Join-Path $roaming 'Neutrino\client\client.json'
    if (-not (Test-Path -LiteralPath $bindings)) { return $false }
    $text = Get-Content -Raw -LiteralPath $bindings -ErrorAction SilentlyContinue
    return [bool]($text -match '"token"\s*:\s*"[^"]')
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
    $suffix = if ($script:NeutrinoEdition -eq 'cn') { '-cn' } else { '' }
    $pattern = "^([0-9a-f]{64}) [ *]?(neutrino-$Component-[0-9][^ ]*-windows-$Machine$suffix\.msi)$"
    foreach ($line in Get-Content -LiteralPath $Sums) {
        if ($line -match $pattern) {
            return [pscustomobject]@{ Sha256 = $Matches[1]; Name = $Matches[2] }
        }
    }
    return $null
}

# An HTTP client that follows redirects and waits as long as its caller
# does.
function Get-NeutrinoHttpClient {
    Add-Type -AssemblyName System.Net.Http
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    $handler = New-Object System.Net.Http.HttpClientHandler
    $handler.AllowAutoRedirect = $true
    $client = New-Object System.Net.Http.HttpClient($handler)
    $client.Timeout = [System.Threading.Timeout]::InfiniteTimeSpan
    return $client
}

# The latest release's tag: every site's latest.json read at once, each for
# at most the probe's wait, and the fastest answer naming a tag taken.
function Get-NeutrinoLatestTag {
    $client = Get-NeutrinoHttpClient
    try {
        $reads = @()
        foreach ($site in $script:NeutrinoReleaseSites) {
            $reads += [pscustomobject]@{
                Address = ([Uri]$site.Latest).Authority
                Task = $client.GetAsync([string]$site.Latest)
                Done = -1
            }
        }
        $clock = [Diagnostics.Stopwatch]::StartNew()
        $wait = $script:NeutrinoProbeWaitSeconds * 1000
        while ($clock.ElapsedMilliseconds -lt $wait) {
            $pending = 0
            foreach ($read in $reads) {
                if ($read.Done -ge 0) { continue }
                if ($read.Task.IsCompleted) { $read.Done = $clock.ElapsedMilliseconds } else { $pending += 1 }
            }
            if ($pending -eq 0) { break }
            Start-Sleep -Milliseconds 20
        }
        $found = $null
        $foundDone = 0
        $reasons = @()
        foreach ($read in $reads) {
            if ($read.Done -lt 0) {
                $reasons += "$($read.Address) (timeout)"
                continue
            }
            if ($read.Task.IsFaulted) {
                $reasons += "$($read.Address) (unreachable)"
                continue
            }
            $response = $read.Task.Result
            $code = [int]$response.StatusCode
            if ($code -ge 400) {
                $reasons += "$($read.Address) (http_$code)"
                continue
            }
            $tag = $null
            try {
                $tag = ($response.Content.ReadAsStringAsync().Result | ConvertFrom-Json).tag
            } catch {
                $tag = $null
            }
            if (-not $tag) {
                $reasons += "$($read.Address) (no_tag)"
                continue
            }
            if (-not $found -or $read.Done -lt $foundDone) {
                $found = [string]$tag
                $foundDone = $read.Done
            }
        }
        if (-not $found) {
            throw "No release site named the latest release: $($reasons -join ', ')."
        }
        return $found
    } finally {
        $client.Dispose()
    }
}

# The sites serving one file, fastest first: every site probed at once for
# the file's first bytes, each for at most the probe's wait. A site that
# answered is ranked by its speed from the first byte to the last, two
# speeds within a tenth of each other going to the earlier first byte; a
# site that sent nothing in time comes after them; a site that failed is
# left out, and its reason added to the list given.
function Get-NeutrinoSiteOrder {
    param([string]$Name, [string]$Tag, [System.Collections.Generic.List[string]]$Reasons)
    $client = Get-NeutrinoHttpClient
    try {
        $probes = @()
        foreach ($site in $script:NeutrinoReleaseSites) {
            $base = ([string]$site.Files).Replace('{tag}', $Tag)
            $request = New-Object System.Net.Http.HttpRequestMessage([System.Net.Http.HttpMethod]::Get, "$base$Name")
            $request.Headers.Range = New-Object System.Net.Http.Headers.RangeHeaderValue([long]0, [long]($script:NeutrinoProbeBytes - 1))
            $probes += [pscustomobject]@{
                Base = $base
                Address = ([Uri]$base).Authority
                Send = $client.SendAsync($request, [System.Net.Http.HttpCompletionOption]::ResponseHeadersRead)
                Stream = $null
                Buffer = New-Object byte[] 65536
                Read = $null
                Size = 0
                First = -1
                Last = -1
                Failed = ''
            }
        }
        $clock = [Diagnostics.Stopwatch]::StartNew()
        $wait = $script:NeutrinoProbeWaitSeconds * 1000
        while ($clock.ElapsedMilliseconds -lt $wait) {
            $pending = 0
            foreach ($probe in $probes) {
                if ($probe.Failed -or $probe.Last -ge 0) { continue }
                $pending += 1
                if ($probe.First -lt 0) {
                    if (-not $probe.Send.IsCompleted) { continue }
                    if ($probe.Send.IsFaulted) {
                        $probe.Failed = 'unreachable'
                        continue
                    }
                    $code = [int]$probe.Send.Result.StatusCode
                    if ($code -ne 200 -and $code -ne 206) {
                        $probe.Failed = "http_$code"
                        continue
                    }
                    $probe.First = $clock.ElapsedMilliseconds
                    $probe.Stream = $probe.Send.Result.Content.ReadAsStreamAsync().Result
                    $probe.Read = $probe.Stream.ReadAsync($probe.Buffer, 0, $probe.Buffer.Length)
                    continue
                }
                if (-not $probe.Read.IsCompleted) { continue }
                if ($probe.Read.IsFaulted) {
                    $probe.Failed = 'unreachable'
                    continue
                }
                $probe.Size += $probe.Read.Result
                if ($probe.Read.Result -eq 0 -or $probe.Size -ge $script:NeutrinoProbeBytes) {
                    $probe.Last = $clock.ElapsedMilliseconds
                    continue
                }
                $probe.Read = $probe.Stream.ReadAsync($probe.Buffer, 0, $probe.Buffer.Length)
            }
            if ($pending -eq 0) { break }
            Start-Sleep -Milliseconds 10
        }
        $answered = @()
        $late = @()
        foreach ($probe in $probes) {
            if ($probe.Failed) {
                $Reasons.Add("$($probe.Address) ($($probe.Failed))")
            } elseif ($probe.First -lt 0) {
                $late += $probe.Base
            } else {
                $last = if ($probe.Last -ge 0) { $probe.Last } else { $clock.ElapsedMilliseconds }
                $span = [math]::Max($last - $probe.First, 1)
                $answered += [pscustomobject]@{ Base = $probe.Base; Speed = $probe.Size / $span; First = $probe.First }
            }
        }
        for ($i = 1; $i -lt $answered.Count; $i++) {
            for ($j = $i; $j -gt 0; $j--) {
                $current = $answered[$j]
                $before = $answered[$j - 1]
                $isFaster = $current.Speed -gt $before.Speed * 1.1
                $isTie = -not $isFaster -and $before.Speed -le $current.Speed * 1.1
                if (-not ($isFaster -or ($isTie -and $current.First -lt $before.First))) { break }
                $answered[$j] = $before
                $answered[$j - 1] = $current
            }
        }
        return @($answered | ForEach-Object { $_.Base }) + $late
    } finally {
        $client.Dispose()
    }
}

# Download one file from one address into a file, from where an earlier
# site stopped. Returns nothing when the file is whole, else why it stopped.
function Receive-NeutrinoFile {
    param([string]$Address, [string]$Target)
    $stallMs = $script:NeutrinoStallSeconds * 1000
    $client = Get-NeutrinoHttpClient
    try {
        $offset = 0
        if (Test-Path -LiteralPath $Target) { $offset = (Get-Item -LiteralPath $Target).Length }
        $request = New-Object System.Net.Http.HttpRequestMessage([System.Net.Http.HttpMethod]::Get, $Address)
        if ($offset -gt 0) {
            $request.Headers.Range = New-Object System.Net.Http.Headers.RangeHeaderValue([long]$offset, $null)
        }
        $send = $client.SendAsync($request, [System.Net.Http.HttpCompletionOption]::ResponseHeadersRead)
        if (-not $send.Wait($stallMs)) { return 'stalled' }
        $code = [int]$send.Result.StatusCode
        if ($code -ge 400) { return "http_$code" }
        if ($offset -gt 0 -and $code -ne 206) { return "http_$code" }
        $stream = $send.Result.Content.ReadAsStreamAsync().Result
        $mode = if ($offset -gt 0) { [IO.FileMode]::Append } else { [IO.FileMode]::Create }
        $file = New-Object IO.FileStream($Target, $mode, [IO.FileAccess]::Write)
        try {
            $buffer = New-Object byte[] 65536
            while ($true) {
                $read = $stream.ReadAsync($buffer, 0, $buffer.Length)
                if (-not $read.Wait($stallMs)) { return 'stalled' }
                if ($read.Result -eq 0) { break }
                $file.Write($buffer, 0, $read.Result)
            }
        } finally {
            $file.Dispose()
        }
        return ''
    } catch {
        return 'unreachable'
    } finally {
        $client.Dispose()
    }
}

# Download one file into a directory from the fastest site, moving to the
# next site on a stall or an error and resuming where the last one stopped.
# Given a digest, a file that does not match it drops that site and is
# fetched again from the next one. Stops, naming each site and why it
# failed, when no site serves the file.
function Save-NeutrinoFile {
    param([string]$Name, [string]$Tag, [string]$Directory, [string]$Sha256)
    $reasons = New-Object System.Collections.Generic.List[string]
    $target = Join-Path $Directory $Name
    Remove-Item -Force -LiteralPath $target -ErrorAction SilentlyContinue
    foreach ($base in (Get-NeutrinoSiteOrder -Name $Name -Tag $Tag -Reasons $reasons)) {
        $siteAddress = ([Uri]$base).Authority
        $failure = Receive-NeutrinoFile -Address "$base$Name" -Target $target
        if ($failure) {
            $reasons.Add("$siteAddress ($failure)")
            continue
        }
        if ($Sha256) {
            $digest = (Get-FileHash -Algorithm SHA256 -LiteralPath $target).Hash.ToLowerInvariant()
            if ($digest -ne $Sha256) {
                $reasons.Add("$siteAddress (digest_mismatch)")
                Remove-Item -Force -LiteralPath $target
                continue
            }
        }
        Write-Output "Downloaded $Name from $siteAddress"
        return
    }
    throw "No release site served ${Name}: $($reasons -join ', ')."
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
function Invoke-NeutrinoElevated {
    param([string]$Component)
    if (-not $env:NEUTRINO_PERSON_APPDATA) { $env:NEUTRINO_PERSON_APPDATA = $env:APPDATA }
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
function Import-NeutrinoPath {
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
    if (-not $env:NEUTRINO_ASSET_DIR -and @($script:NeutrinoReleaseSites).Count -eq 0) {
        throw 'This script names no release site; take it from a release, or set NEUTRINO_ASSET_DIR.'
    }
    if (-not (Test-NeutrinoAdministrator)) {
        Invoke-NeutrinoElevated -Component $Component
        return
    }

    $work = Join-Path ([IO.Path]::GetTempPath()) ('neutrino_' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $work | Out-Null
    try {
        $tag = $env:NEUTRINO_VERSION
        if ($env:NEUTRINO_ASSET_DIR) {
            $source = (Resolve-Path -LiteralPath $env:NEUTRINO_ASSET_DIR).Path
            if (-not (Test-Path -LiteralPath (Join-Path $source 'SHA256SUMS'))) {
                throw "There is no SHA256SUMS in $source."
            }
        } else {
            if (-not $tag) { $tag = Get-NeutrinoLatestTag }
            $source = $work
            Save-NeutrinoFile -Name 'SHA256SUMS' -Tag $tag -Directory $work
        }

        $sums = Join-Path $source 'SHA256SUMS'
        $asset = Find-NeutrinoAsset -Sums $sums -Component $Component -Machine $machine
        if (-not $asset) {
            throw "The release publishes no Neutrino $Component package for Windows on $machine."
        }
        $package = Join-Path $source $asset.Name
        if (-not $env:NEUTRINO_ASSET_DIR) {
            Save-NeutrinoFile -Name $asset.Name -Tag $tag -Directory $work -Sha256 $asset.Sha256
        }
        if (-not (Test-Path -LiteralPath $package)) {
            throw "There is no $($asset.Name) in $source."
        }
        if ($env:NEUTRINO_ASSET_DIR) {
            Write-Output "Found $($asset.Name) in $source"
        }
        $digest = (Get-FileHash -Algorithm SHA256 -LiteralPath $package).Hash.ToLowerInvariant()
        if ($digest -ne $asset.Sha256) {
            throw "$($asset.Name) does not match its SHA256SUMS line; nothing was installed."
        }
        Write-Output "$($asset.Name) matches its SHA256SUMS line"

        Write-Output "Installing $($asset.Name)"
        $msiexec = Start-Process -FilePath msiexec.exe -Wait -PassThru `
            -ArgumentList '/i', "`"$package`"", '/qn', '/norestart'
        if ($msiexec.ExitCode -notin $NeutrinoInstalledCodes) {
            throw "msiexec exited $($msiexec.ExitCode) installing $($asset.Name)."
        }
        Write-Output "Installed $($asset.Name)"
        if ($msiexec.ExitCode -eq 3010) {
            Write-Output "Windows needs a restart to finish installing $($asset.Name)."
        }
    } finally {
        Remove-Item -Recurse -Force -LiteralPath $work -ErrorAction SilentlyContinue
    }
    Import-NeutrinoPath

    if ($Component -eq 'agent') {
        if (-not (Test-NeutrinoAgentBound)) {
            Write-Output "Next, in this window: nagent join '<enrollment link from the hub's Agents page>'"
        }
        return
    }
    if ($Component -eq 'client') {
        if (-not (Test-NeutrinoClientBound)) {
            Write-Output "Next, in a PowerShell of your own: nclient hub join '<client link from the hub's Clients page>'"
        }
        return
    }
    $nhub = Join-Path $env:ProgramFiles 'Neutrino\hub\nhub.exe'
    if (Test-NeutrinoHubSetUp) {
        try {
            $address = & $nhub open --print 2>$null
        } catch {
            $address = $null
        }
        if ($address) {
            Write-Output "The hub was upgraded; its panel is at: $address"
        } else {
            Write-Output "The hub was upgraded; in this window, & '$nhub' open opens its panel."
        }
        return
    }
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
