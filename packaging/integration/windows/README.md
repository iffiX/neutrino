# Windows client verification

The walk a client msi takes on the lab's Windows VM before it is handed over:
install over a running resident, open, close to the tray, reopen, mount and
unmount a share, switch the AI tools on and off from the page, quit. The
harness under `../../integration_aws/windows/` builds the msi on a rented
box; this one exercises it where a screenshot can be taken.

## What is here

| File | What it does |
| --- | --- |
| `vm.py` | The one driver: run a line as SYSTEM, write a file in, run a script as the signed-in person, screenshot, serve the msi over the NAT bridge. |
| `user_run.ps1` | Runs one script inside the signed-in person's session through a scheduled task and reads its output back. Copied to `C:\\user_run.ps1` first. One task name, so never two at once. |
| `ui.ps1`, `ui_run.ps1` | Maximize the window, click, type, scroll, from a command list in `C:\\ui_cmds.txt`. The window is found by title through EnumWindows. |
| `install_over_running.ps1` | Fetches `new_client.msi` from the share and installs it while a resident runs; the installer must close it. |
| `test_client_install.ps1` | The install walk as SYSTEM: remove, install, what landed, `nclient.cmd --version`. |
| `launch_gui.ps1` | Starts the resident in the person's session. |
| `close_reopen.ps1`, `quit_timed.ps1`, `enum_win.ps1` | Close to the tray and reopen; Quit from the tray with the time it took; list the client's windows. |
| `mount_win.*`, `unmount_win.*`, `explorer_shot.ps1` | Map and unmap a share through the platform layer under `pythonw`, with Explorer open for the screenshot. |
| `switcher_win.*`, `ai_cycle.ps1` | The switcher on the real profile under `pythonw`, with the profile stashed and put back; the page and CLI switch on and off with timings and the busy refusal. |
| `log_tail.ps1` | The resident's log, and whether it carries a socket error. |

## Running it

```bash
cd packaging/integration/windows
./vm.py serve                                   # once; then copy the msi to ~/win_share/new_client.msi on the host
for f in *.ps1 *.py; do ./vm.py put "$f" "C:\\$f"; done
./vm.py exec "powershell -NoProfile -ExecutionPolicy Bypass -File C:\\launch_gui.ps1"
./vm.py exec "powershell -NoProfile -ExecutionPolicy Bypass -File C:\\install_over_running.ps1"
./vm.py user C:\\close_reopen.ps1
./vm.py user C:\\mount_win.ps1 && ./vm.py shot mounted
./vm.py user C:\\quit_timed.ps1
```

The VM signs the person in automatically, so the session the scripts run in
is the one on screen. Any run that opens a window must not use
`-WindowStyle Hidden`.
