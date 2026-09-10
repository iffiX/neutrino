Add-Type @"
using System; using System.Text; using System.Runtime.InteropServices; using System.Collections.Generic;
public class Win {
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr l);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassName(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  public static List<string> Rows = new List<string>();
  public static bool Cb(IntPtr h, IntPtr l) {
    uint pid; GetWindowThreadProcessId(h, out pid);
    var c = new StringBuilder(128); GetClassName(h, c, 128);
    var t = new StringBuilder(128); GetWindowText(h, t, 128);
    Rows.Add(pid + "\t" + h + "\t" + (IsWindowVisible(h) ? "vis" : "hid") + "\t" + c + "\t" + t);
    return true; }
}
"@
$procs = Get-Process python, pythonw -ErrorAction SilentlyContinue
Write-Output ("client processes: " + (($procs | ForEach-Object { "$($_.ProcessName):$($_.Id)" }) -join ' '))
[Win]::EnumWindows([Win+EnumProc]{ param($h, $l) [Win]::Cb($h, $l) }, [IntPtr]::Zero) | Out-Null
$ids = $procs | ForEach-Object { $_.Id }
[Win]::Rows | Where-Object { $_.Split("`t")[0] -in $ids } | ForEach-Object { Write-Output $_ }
