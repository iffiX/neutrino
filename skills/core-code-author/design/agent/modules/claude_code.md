# The Claude Code module

The `claude_code` module makes Claude Code, Anthropic's coding agent for the
terminal, ready for each enabled account on Linux (amd64 and arm64), macOS
(arm64 and amd64, macOS 13 or later) and Windows (amd64 and arm64, Windows
10 1809 or later), tested at 2.1.311. Claude Code is proprietary, and
Anthropic's legal agreements govern its use. It is a command line program
([../module_template.md](../module_template.md), "A command line
program"): `agent/neutrino_agent/modules/claude_code/` holds `config.py`,
`constants.py` and `hooks.py`, and `modules/shared/programs.py` does the
rest. Its configuration is `{accounts: [{account, password}]}`, `password`
being the account's login, sent to a Windows machine alone
([../../protocol.md](../../protocol.md), "The account layer in the state").

**An account's own Claude Code comes first.** `find` reads the account's
`PATH`, then these places, as the account ([../../agent.md](../../agent.md),
"Parallel, never take over"):

| System | The places after `PATH` |
| --- | --- |
| Linux | `~/.local/bin/claude`, the native installer's; `/usr/local/bin/claude`; `/usr/bin/claude`, the apt, dnf and apk packages' |
| macOS | `~/.local/bin/claude`, the native installer's; `/opt/homebrew/bin/claude` and `/usr/local/bin/claude`, Homebrew's casks |
| Windows | `%USERPROFILE%\.local\bin\claude.exe`, the native installer's; `%LOCALAPPDATA%\Microsoft\WinGet\Links\claude.exe`, WinGet's; `%APPDATA%\npm\claude.cmd`, npm's |

A copy at the manifest's `user_copy_min_version` or newer is the account's,
and the module installs nothing for it. An older one keeps running in the
account's own shell, and the account uses the module's copy, its row
reading `copy_version_unsupported {account, version, min}`. The person's
copy keeps its own updater: the native installer and npm update it in the
background, and Homebrew, WinGet, apt, dnf and apk when the person
upgrades.

**The module's copy is Anthropic's npm package for the platform.**
`data/manifests/claude_code.json` names one artifact per platform, of kind
`tar_gz`: the tarball of `@anthropic-ai/claude-code-<platform>`, the
`linux-x64`, `linux-arm64`, `darwin-x64`, `darwin-arm64`, `win32-x64` or
`win32-arm64` package, with the `npm` set as its `source_set` and npm's
integrity as its digest ([../module_install.md](../module_install.md),
"Sources"). The tarball holds `claude`, `claude.exe` on Windows, with
`package.json`, `LICENSE.md` and `README.md`, all under `package/`, and the
agent unpacks it without that directory into `claude_code/package/` under
the state root, where the program keeps the publisher's mode 755.

| Rule | Reason |
| --- | --- |
| The module's installer fetches the npm package, never `downloads.claude.ai`. | The npm set holds npmmirror and Tencent's mirror, which serve mainland China. The tarball is 127 MiB for linux-x64, where the bucket's binary is 280 MiB uncompressed. The `npm` feed already lists the versions and gives each its integrity, and the bucket lists no versions. |
| The npm package's program is the one Anthropic signs. | For 2.1.311 the sha256 of `claude` in the linux-x64, darwin-arm64 and win32-x64 packages equals the `checksum` that release's `manifest.json` names, and that manifest's signature verifies under Anthropic's release key, fingerprint `31DD DE24 DDFA B679 F42D 7BD2 BAA9 29FF 1A7E CACE`. |
| No release of Neutrino's carries Claude Code, and its manifest names no `{release}` source. | Claude Code is Anthropic's proprietary software, and the module's installer fetches the package Anthropic publishes, from the registries that serve it. |

**The version moves in the hub.** The tested version, 2.1.311, is a
version of Anthropic's `stable` channel. The versions and their digests come
from the `npm` feed of each platform's own package,
`@anthropic-ai/claude-code-<platform>`, read from registry.npmjs.org
([../module_install.md](../module_install.md), "Module versions").
`verify` is the unpacked program's path with `--version`.

**The launcher keeps the copy's updater off.** `claude_code/bin/claude`,
`claude.cmd` on Windows, sets `DISABLE_UPDATES=1` and starts the copy with
its arguments:

```sh
#!/bin/sh
DISABLE_UPDATES=1
export DISABLE_UPDATES
exec "/var/lib/neutrino/agent/claude_code/package/claude" "$@"
```

```bat
@echo off
setlocal
set "DISABLE_UPDATES=1"
"%ProgramData%\Neutrino\agent\state\claude_code\package\claude.exe" %*
exit /b %ERRORLEVEL%
```

Anthropic's documentation says `DISABLE_UPDATES` blocks "all updates
including manual `claude update` and `claude install`", for Claude Code
distributed "through your own channels". Without the variable, the same
documentation says, a copy behind a launcher the native installer did not
make goes on installing new versions under `~/.local/share/claude/versions/`
in the account's home, and "keeps every installed version on disk". With
it the module's copy writes nothing there, so whatever that directory holds
is the person's, and an uninstall leaves it. The variable is the launcher's
alone: a person's own copy goes on updating itself, and the unpacked
program is reached by its full path only.

**The gateway is the machine's AI tools setting.** The module writes no
settings file: every copy of Claude Code an account runs, the person's, the
module's and the Agent SDK's, reads the account's `~/.claude/settings.json`,
which the setting writes when the account's switch is on
([../ai_tools.md](../ai_tools.md)).

**CloudCLI and Codeg run their own Claude Code.** The Agent SDK in each
one's npm packages holds a Claude Code of the version that SDK was built
with, and each runs that copy, so neither requires this module
([cloudcli.md](cloudcli.md), [codeg.md](codeg.md)). This module's floor and
launcher do not reach that copy.

**An uninstall keeps every account's own files.** It removes
`claude_code/` under the state root, every link and `PATH` entry that still
carries the module's mark, and the record. Its line in the uninstall dialog
is "Each account's settings in ~/.claude stay, and so does a copy of Claude
Code installed outside this module."

`details` is `{has_module_copy, accounts: [{account, copy, path, version,
code, params}]}`, `copy` being `user` or `module`. An apply refuses
`account_unknown {account}` for an account the machine does not have, and
on Windows `account_no_profile {account}`, `credential_missing {account}`
and `credential_invalid {account}`, as Codeg's does. Its journal is the
agent's lines that name the module ([../../agent.md](../../agent.md), "Which
modules each system runs").
