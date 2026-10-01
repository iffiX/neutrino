Get-Process explorer -ErrorAction SilentlyContinue | Where-Object MainWindowTitle -ne '' | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Process explorer.exe -ArgumentList 'shell:MyComputerFolder'
Start-Sleep -Seconds 6
net use 2>&1 | Out-String
