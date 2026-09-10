Remove-Item C:\out\unmount_win.txt -ErrorAction SilentlyContinue
net use W: /delete /y 2>&1 | Out-String
Start-Process 'C:\Program Files\Neutrino Client\python\pythonw.exe' -ArgumentList 'C:\unmount_win.py' -Wait
Get-Content C:\out\unmount_win.txt
net use 2>&1 | Out-String
