# The find of a command line program's copy, run as one account.
#
# Standard input holds one JSON object. {name, skip, places} looks for the
# account's own copy: each folder of the system's PATH and then the
# account's user PATH, expanded as Windows joins them for a new process,
# <name>.exe then <name>.cmd in each, the folder skip passed over; then each
# of places, its variables expanded. The first copy whose --version prints a
# dotted number within 10 seconds is the account's. {version_of} reads the
# version of one copy. The answer is one JSON line, {path, version}, both
# empty when no copy is found.

$ErrorActionPreference = 'Stop'

function Write-Answer([string]$Path, [string]$Version) {
    $text = (@{ path = $Path; version = $Version } | ConvertTo-Json -Compress)
    $writer = New-Object System.IO.StreamWriter([Console]::OpenStandardOutput(), (New-Object System.Text.UTF8Encoding($false)))
    $writer.WriteLine($text)
    $writer.Flush()
}

function Read-Version([string]$Path) {
    $info = New-Object System.Diagnostics.ProcessStartInfo
    if ($Path.EndsWith('.cmd', [StringComparison]::OrdinalIgnoreCase)) {
        $info.FileName = $env:ComSpec
        $info.Arguments = '/d /c ""' + $Path + '" --version"'
    } else {
        $info.FileName = $Path
        $info.Arguments = '--version'
    }
    $info.UseShellExecute = $false
    $info.RedirectStandardInput = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $info.CreateNoWindow = $true
    try {
        $process = [System.Diagnostics.Process]::Start($info)
    } catch {
        return ''
    }
    $process.StandardInput.Close()
    $out = $process.StandardOutput.ReadToEndAsync()
    $err = $process.StandardError.ReadToEndAsync()
    if (-not $process.WaitForExit(10000)) {
        try { $process.Kill() } catch { }
        return ''
    }
    if ($process.ExitCode -ne 0) {
        return ''
    }
    $found = [regex]::Match($out.Result + "`n" + $err.Result, '\d+(\.\d+)+')
    if ($found.Success) {
        return $found.Value
    }
    return ''
}

function Test-File([string]$Path) {
    try {
        return (Test-Path -LiteralPath $Path -PathType Leaf)
    } catch {
        return $false
    }
}

$reader = New-Object System.IO.StreamReader([Console]::OpenStandardInput(), [System.Text.Encoding]::UTF8)
$request = $reader.ReadToEnd() | ConvertFrom-Json

if ($request.version_of) {
    $path = [string]$request.version_of
    if (Test-File $path) {
        Write-Answer $path (Read-Version $path)
    } else {
        Write-Answer $path ''
    }
    return
}

$name = [string]$request.name
$skip = ([string]$request.skip).TrimEnd('\')
$machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
$user = [Environment]::GetEnvironmentVariable('Path', 'User')
$candidates = New-Object System.Collections.Generic.List[string]
foreach ($part in ((@($machine, $user) | Where-Object { $_ }) -join ';').Split(';')) {
    $folder = [Environment]::ExpandEnvironmentVariables($part.Trim()).TrimEnd('\')
    if (-not $folder -or $folder -ieq $skip) {
        continue
    }
    foreach ($suffix in @('.exe', '.cmd')) {
        $candidates.Add($folder + '\' + $name + $suffix)
    }
}
foreach ($place in @($request.places)) {
    if ($place) {
        $candidates.Add([Environment]::ExpandEnvironmentVariables([string]$place))
    }
}
$seen = @{}
foreach ($candidate in $candidates) {
    $key = $candidate.ToLowerInvariant()
    if ($seen.ContainsKey($key)) {
        continue
    }
    $seen[$key] = $true
    if (-not (Test-File $candidate)) {
        continue
    }
    $version = Read-Version $candidate
    if ($version) {
        Write-Answer $candidate $version
        return
    }
}
Write-Answer '' ''
