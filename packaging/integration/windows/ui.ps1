# UI driver for the client window in the signed-in session:
#   ui.ps1 maximize | click X Y | dblclick X Y | type TEXT | key VK | wheel N | front
Add-Type @"
using System; using System.Text; using System.Runtime.InteropServices;
public class U {
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr l);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowTextW(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  public static IntPtr Found = IntPtr.Zero;
  public static bool Cb(IntPtr h, IntPtr l) {
    var t = new StringBuilder(256); GetWindowTextW(h, t, 256);
    if (t.ToString().StartsWith("Neutrino client")) { Found = h; return false; } return true; }
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint x, uint y, int d, UIntPtr e);
  [DllImport("user32.dll")] public static extern void keybd_event(byte k, byte s, uint f, UIntPtr e);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  public struct RECT { public int L, T, R, B; }
}
"@
[U]::EnumWindows([U+EnumProc]{ param($h, $l) [U]::Cb($h, $l) }, [IntPtr]::Zero) | Out-Null
$h = [U]::Found
$cmd = $args[0]
switch ($cmd) {
  "front" { [U]::ShowWindow($h, 9) | Out-Null; [U]::SetForegroundWindow($h) | Out-Null; Write-Output "hwnd $h" }
  "maximize" { [U]::ShowWindow($h, 3) | Out-Null; [U]::SetForegroundWindow($h) | Out-Null; Write-Output "hwnd $h maximized" }
  "rect" { $r = New-Object U+RECT; [U]::GetWindowRect($h, [ref]$r) | Out-Null; Write-Output "$($r.L) $($r.T) $($r.R) $($r.B)" }
  "click" { [U]::SetCursorPos([int]$args[1], [int]$args[2]) | Out-Null; Start-Sleep -Milliseconds 150; [U]::mouse_event(2,0,0,0,[UIntPtr]::Zero); [U]::mouse_event(4,0,0,0,[UIntPtr]::Zero); Write-Output "clicked $($args[1]) $($args[2])" }
  "wheel" { [U]::mouse_event(0x0800,0,0,[int]$args[1],[UIntPtr]::Zero); Write-Output "wheel $($args[1])" }
  "type" { Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.SendKeys]::SendWait($args[1]); Write-Output "typed" }
  "sleep" { Start-Sleep -Seconds ([double]$args[1]) }
}
