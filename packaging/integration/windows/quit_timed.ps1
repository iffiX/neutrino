Add-Type @"
using System; using System.Text; using System.Runtime.InteropServices;
public class Q {
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr l);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassName(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool PostMessageW(IntPtr h, uint m, IntPtr w, IntPtr l);
  public static IntPtr Tray = IntPtr.Zero; public static uint Pid = 0;
  public static bool Cb(IntPtr h, IntPtr l) { uint pid; GetWindowThreadProcessId(h, out pid); if (pid != Pid) return true;
    var c = new StringBuilder(128); GetClassName(h, c, 128); if (c.ToString() == "NeutrinoClientTray") Tray = h; return true; }
}
"@
$p = Get-Process nclient | Select-Object -First 1
[Q]::Pid = $p.Id
[Q]::EnumWindows([Q+EnumProc]{ param($h, $l) [Q]::Cb($h, $l) }, [IntPtr]::Zero) | Out-Null
$t0 = Get-Date
[Q]::PostMessageW([Q]::Tray, 0x0111, [IntPtr]2, [IntPtr]::Zero) | Out-Null
Write-Output "posted quit at $($t0.ToString('HH:mm:ss.fff'))"
for ($i = 0; $i -lt 400; $i++) { Start-Sleep -Milliseconds 50; if ($p.HasExited) { break } }
Write-Output "exited after $([math]::Round(((Get-Date) - $t0).TotalSeconds, 2))s"
Get-Content "$env:APPDATA\Neutrino Client\client.log" -Tail 2
