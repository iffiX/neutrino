Get-Content "$env:APPDATA\Neutrino Client\client.log" -Tail 12
Write-Output "socket read failed lines: $((Select-String -Path "$env:APPDATA\Neutrino Client\client.log" -Pattern 'socket read failed|10038' | Measure-Object).Count)"
