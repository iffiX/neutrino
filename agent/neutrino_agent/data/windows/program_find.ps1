# The find of a command line program's copies, run as one account.
#
# Standard input holds one JSON object, {name, module_folder, places}. Each
# folder of the system's PATH and then of the account's user PATH, expanded
# as Windows joins them for a new process, is read in order for <name>.exe
# then <name>.cmd. The module's own folder is passed over, and is_module_first
# says whether it comes before every other copy. The first other copy is the
# answer, else the first of places, its variables expanded. The answer is
# one JSON line, {path, version, is_on_path, is_system_path,
# is_module_first}: version the first dotted number the copy's --version
# prints within 10 seconds, empty when it prints none; path empty when no
# copy is found.

$ErrorActionPreference = 'Stop'

function Write-Answer([string]$Path, [string]$Version, [bool]$IsOnPath, [bool]$IsSystemPath, [bool]$IsModuleFirst) {
    $text = (@{
        path = $Path
        version = $Version
        is_on_path = $IsOnPath
        is_system_path = $IsSystemPath
        is_module_first = $IsModuleFirst
    } | ConvertTo-Json -Compress)
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
$name = [string]$request.name
$moduleFolder = ([string]$request.module_folder).TrimEnd('\')
$folders = New-Object System.Collections.Generic.List[object]
foreach ($scope in @('Machine', 'User')) {
    $value = [Environment]::GetEnvironmentVariable('Path', $scope)
    if (-not $value) {
        continue
    }
    foreach ($part in $value.Split(';')) {
        $folder = [Environment]::ExpandEnvironmentVariables($part.Trim()).TrimEnd('\')
        if ($folder) {
            $folders.Add(@{ folder = $folder; is_system = ($scope -eq 'Machine') })
        }
    }
}

$isModuleFirst = $false
foreach ($each in $folders) {
    if ($each.folder -ieq $moduleFolder) {
        if (Test-File ($each.folder + '\' + $name + '.cmd')) {
            $isModuleFirst = $true
        }
        continue
    }
    foreach ($suffix in @('.exe', '.cmd')) {
        $candidate = $each.folder + '\' + $name + $suffix
        if (Test-File $candidate) {
            Write-Answer $candidate (Read-Version $candidate) $true ([bool]$each.is_system) $isModuleFirst
            return
        }
    }
}
foreach ($place in @($request.places)) {
    if (-not $place) {
        continue
    }
    $candidate = [Environment]::ExpandEnvironmentVariables([string]$place)
    if (Test-File $candidate) {
        Write-Answer $candidate (Read-Version $candidate) $false $false $isModuleFirst
        return
    }
}
Write-Answer '' '' $false $false $isModuleFirst
