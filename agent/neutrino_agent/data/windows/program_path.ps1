# The entry of a command line program's launcher folder in one account's
# user PATH, run as that account.
#
# Standard input holds one JSON object, {verb, folder}. "add" puts the folder
# at the end of the user PATH unless an entry names it already; "remove"
# takes away every entry that names the folder. The value is read
# unexpanded and written back with its own type, REG_EXPAND_SZ or REG_SZ,
# every other entry as it was, and Windows is told the environment changed.
# The answer is one JSON line, {result}: added, present, removed, absent, or
# unsupported for a value of another type.

$ErrorActionPreference = 'Stop'

# The user PATH after the change, or $null when it stays as it is.
function Get-ChangedPath([string]$Value, [string]$Folder, [string]$Verb) {
    $entries = $Value.Split(';')
    $ours = @($entries | Where-Object { $_.Trim().TrimEnd('\') -ieq $Folder })
    if ($Verb -eq 'add') {
        if ($ours.Count -gt 0) {
            return $null
        }
        if ($Value -eq '') {
            return $Folder
        }
        if ($Value.EndsWith(';')) {
            return $Value + $Folder
        }
        return $Value + ';' + $Folder
    }
    if ($ours.Count -eq 0) {
        return $null
    }
    $kept = @($entries | Where-Object { $_.Trim().TrimEnd('\') -ine $Folder })
    return ($kept -join ';')
}

function Write-Answer([string]$Result) {
    $text = (@{ result = $Result } | ConvertTo-Json -Compress)
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

$key = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey('Environment')
$name = $key.GetValueNames() | Where-Object { $_ -ieq 'Path' } | Select-Object -First 1
if ($name) {
    $kind = $key.GetValueKind($name)
    $value = [string]$key.GetValue($name, '', [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
} else {
    $name = 'Path'
    $kind = [Microsoft.Win32.RegistryValueKind]::ExpandString
    $value = ''
}
if ($kind -ne [Microsoft.Win32.RegistryValueKind]::ExpandString -and $kind -ne [Microsoft.Win32.RegistryValueKind]::String) {
    Write-Answer 'unsupported'
    return
}

$changed = Get-ChangedPath $value $folder $verb
if ($null -eq $changed) {
    if ($verb -eq 'add') {
        Write-Answer 'present'
    } else {
        Write-Answer 'absent'
    }
    return
}
$key.SetValue($name, $changed, $kind)
Send-EnvironmentChange
if ($verb -eq 'add') {
    Write-Answer 'added'
} else {
    Write-Answer 'removed'
}
