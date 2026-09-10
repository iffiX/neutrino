# Close the window (to the tray), check the resident lives on, open it again from a second launch.
Add-Type @"
using System; using System.Text; using System.Runtime.InteropServices;
public class W {
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr l);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowTextW(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern bool PostMessageW(IntPtr h, uint m, IntPtr w, IntPtr l);
  public static IntPtr Found = IntPtr.Zero; public static bool Visible = false;
  public static bool Cb(IntPtr h, IntPtr l) {
    var t = new StringBuilder(256); GetWindowTextW(h, t, 256);
    if (t.ToString().StartsWith("Neutrino client")) { Found = h; Visible = IsWindowVisible(h); return false; } return true; }
}
"@
function Find { [W]::Found = [IntPtr]::Zero; [W]::Visible = $false; [W]::EnumWindows([W+EnumProc]{ param($h, $l) [W]::Cb($h, $l) }, [IntPtr]::Zero) | Out-Null; "window $([W]::Found) visible $([W]::Visible)" }
$p = Get-Process pythonw | Select-Object -First 1
Write-Output "resident $($p.Id); before: $(Find)"
[W]::PostMessageW([W]::Found, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null
Start-Sleep -Seconds 2
Write-Output "after close: $(Find); resident alive $(-not $p.HasExited)"
Start-Process "$env:ProgramFiles\Neutrino Client\python\pythonw.exe" -ArgumentList '-m neutrino_client.cli.entry gui'
Start-Sleep -Seconds 4
Write-Output "after second launch: $(Find); pythonw count $((Get-Process pythonw).Count)"
