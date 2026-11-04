# The entry of a command line program's launcher folder in one account's
# user PATH, run as that account.
#
# Standard input holds one JSON object, {verb, folder, is_made}. "first"
# takes every entry that names the folder out and puts one at the front;
# "remove" takes every entry that names the folder out, and deletes the
# value when that leaves it empty and is_made says the module made it. The
# value is read unexpanded and written back with its own type, REG_EXPAND_SZ
# or REG_SZ, every other entry as it was, and Windows is told the
# environment changed. The answer is one JSON line, {result, is_made}:
# result added, moved, present, removed or absent, or unsupported for a
# value of another type; is_made true when "first" made the value.

$ErrorActionPreference = 'Stop'

# Whether one entry names the folder.
function Test-Ours([string]$Entry, [string]$Folder) {
    return ($Entry.Trim().TrimEnd('\') -ieq $Folder)
}

# The user PATH after the change, or $null when it stays as it is.
function Get-ChangedPath([string]$Value, [string]$Folder, [string]$Verb) {
    $entries = @()
    if ($Value -ne '') {
        $entries = @($Value.Split(';'))
    }
    $ours = @($entries | Where-Object { Test-Ours $_ $Folder })
    $others = @($entries | Where-Object { -not (Test-Ours $_ $Folder) })
    if ($Verb -eq 'first') {
        if ($ours.Count -eq 1 -and (Test-Ours $entries[0] $Folder)) {
            return $null
        }
        return ((@($Folder) + $others) -join ';')
    }
    if ($ours.Count -eq 0) {
        return $null
    }
    return ($others -join ';')
}

function Write-Answer([string]$Result, [bool]$IsMade) {
    $text = (@{ result = $Result; is_made = $IsMade } | ConvertTo-Json -Compress)
    $writer = New-Object System.IO.StreamWriter([Console]::OpenStandardOutput(), (New-Object System.Text.UTF8Encoding($false)))
    $writer.WriteLine($text)
    $writer.Flush()
}

function Send-EnvironmentChange {
    Add-Type -Namespace Neutrino -Name UserEnvironment -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("user32.dll", CharSet = System.Runtime.InteropServices.CharSet.Unicode)]
public static extern System.IntPtr SendMessageTimeout(System.IntPtr window, uint message, System.UIntPtr wParam, string lParam, uint flags, uint timeout, out System.UIntPtr result);
'@
    $result = [UIntPtr]::Zero
    [void][Neutrino.UserEnvironment]::SendMessageTimeout([IntPtr]0xffff, 0x1A, [UIntPtr]::Zero, 'Environment', 2, 5000, [ref]$result)
}

$reader = New-Object System.IO.StreamReader([Console]::OpenStandardInput(), [System.Text.Encoding]::UTF8)
$request = $reader.ReadToEnd() | ConvertFrom-Json
$verb = [string]$request.verb
$folder = ([string]$request.folder).TrimEnd('\')
$isMade = [bool]$request.is_made

$key = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey('Environment')
$name = $key.GetValueNames() | Where-Object { $_ -ieq 'Path' } | Select-Object -First 1
$isPresent = [bool]$name
if ($isPresent) {
    $kind = $key.GetValueKind($name)
    $value = [string]$key.GetValue($name, '', [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
} else {
    $name = 'Path'
    $kind = [Microsoft.Win32.RegistryValueKind]::ExpandString
    $value = ''
}
if ($kind -ne [Microsoft.Win32.RegistryValueKind]::ExpandString -and $kind -ne [Microsoft.Win32.RegistryValueKind]::String) {
    Write-Answer 'unsupported' $false
    return
}

$isNamed = @($value.Split(';') | Where-Object { $value -ne '' -and (Test-Ours $_ $folder) }).Count -gt 0
$changed = Get-ChangedPath $value $folder $verb
if ($null -eq $changed) {
    if ($verb -eq 'first') {
        Write-Answer 'present' $false
    } else {
        Write-Answer 'absent' $false
    }
    return
}
if ($verb -ne 'first' -and $changed -eq '' -and $isMade) {
    $key.DeleteValue($name)
} else {
    $key.SetValue($name, $changed, $kind)
}
Send-EnvironmentChange
if ($verb -ne 'first') {
    Write-Answer 'removed' $false
} elseif ($isNamed) {
    Write-Answer 'moved' $false
} else {
    Write-Answer 'added' (-not $isPresent)
}
