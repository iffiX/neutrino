# The VS Code module

The `vscode` module runs Microsoft's standalone CLI, `code serve-web`, once
per account on Linux, Windows and macOS ([protocol.md](../../protocol.md),
"The modules section, one entry per module"). A VS Code instance listens on
`127.0.0.1` alone, on every system. A client reaches it through a `connect`
stream ([agent.md](../../agent.md), "The connect stream"), and its token is
what admits a browser.

It is a program run as a person's account ([module_template.md](../module_template.md)):
`agent/neutrino_agent/modules/vscode/` holds `config.py`, `constants.py`
and `hooks.py`, and `modules/shared/` does the rest. The account service
layer, `modules/shared/account_service/`, runs each instance as its account:
the unit `neutrino_vscode@<account>.service` with `User=` on Linux, the
LaunchDaemon `com.neutrino.vscode.<account>` with `UserName` on macOS, and
the task `neutrino_vscode_<account>` registered with the account's login on
Windows. The paths each system uses are the "VS Code" row of the platform
table ([agent.md](../../agent.md), "The platform layer"). Its token is the
instance's connection token, which `code serve-web` checks itself, so the
module names no forwarder rule.

Its journal on Windows reads the end of `<account>.log` beside the CLI,
which the task's `cmd.exe` appends to; on macOS the LaunchDaemon's
`StandardOutPath` and `StandardErrorPath` name
`/Library/Logs/Neutrino/agent/vscode_<account>.log`.
