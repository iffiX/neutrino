Remove-Item C:\out\switcher_win.txt -ErrorAction SilentlyContinue
Start-Process 'C:\Program Files\Neutrino Client\python\pythonw.exe' -ArgumentList 'C:\switcher_win.py' -Wait
Get-Content C:\out\switcher_win.txt
