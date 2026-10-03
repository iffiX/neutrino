Get-Content "$env:LOCALAPPDATA\Neutrino\client\client.log" -Tail 12
Write-Output "socket read failed lines: $((Select-String -Path "$env:LOCALAPPDATA\Neutrino\client\client.log" -Pattern 'socket read failed|10038' | Measure-Object).Count)"
