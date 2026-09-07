<powershell>
# First boot of the Windows box: an SSH door for the harness, and nothing
# else. OpenSSH is a Windows capability pulled from Windows Update, which is
# the minutes `up.sh` spends waiting; the key it trusts is the harness's own,
# generated into state/ and never anybody's personal one.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0 | Out-Null
Set-Service -Name sshd -StartupType Automatic
Start-Service sshd

$sshDir = Join-Path $env:ProgramData 'ssh'
New-Item -Force -ItemType Directory -Path $sshDir | Out-Null
$keys = Join-Path $sshDir 'administrators_authorized_keys'
Set-Content -Path $keys -Value '@AUTHORIZED_KEY@' -Encoding ascii
# sshd refuses the file unless only administrators and SYSTEM can touch it.
icacls $keys /inheritance:r /grant 'Administrators:F' /grant 'SYSTEM:F' | Out-Null

# Land in PowerShell rather than cmd: every script the harness runs is one.
New-ItemProperty -Path 'HKLM:\SOFTWARE\OpenSSH' -Name DefaultShell `
    -Value 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe' `
    -PropertyType String -Force | Out-Null

if (-not (Get-NetFirewallRule -Name 'neutrino-sshd' -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -Name 'neutrino-sshd' -DisplayName 'OpenSSH Server (neutrino)' `
        -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22 | Out-Null
}
Restart-Service sshd
</powershell>
