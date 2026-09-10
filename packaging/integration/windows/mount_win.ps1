Remove-Item C:\out\mount_win.txt -ErrorAction SilentlyContinue
Get-Process explorer -ErrorAction SilentlyContinue | Where-Object MainWindowTitle -ne '' | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Process 'C:\Program Files\Neutrino Client\python\pythonw.exe' -ArgumentList 'C:\mount_win.py' -Wait
Get-Content C:\out\mount_win.txt
