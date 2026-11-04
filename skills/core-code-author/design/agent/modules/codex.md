# The Codex module

The `codex` module makes Codex, OpenAI's coding agent for the terminal
(Apache-2.0), ready for each enabled account on Linux, macOS and Windows,
each on amd64 and arm64, tested at 0.166.0. It is a command line program
([../module_template.md](../module_template.md), "A command line
program"): `agent/neutrino_agent/modules/codex/` holds `config.py`,
`constants.py` and `hooks.py`, and `modules/shared/programs.py` does the
rest. Its configuration is `{accounts: [{account, password}]}`, `password`
being the account's login, sent to a Windows machine alone
([../../protocol.md](../../protocol.md), "The account layer in the state").

**An account's own Codex comes first.** `find` reads the account's `PATH`,
then these places, as the account ([../../agent.md](../../agent.md),
"Parallel, never take over"):

| System | The places after `PATH` |
| --- | --- |
| Linux | `~/.local/bin/codex`, the publisher's `install.sh`; `/usr/local/bin/codex` |
| macOS | `~/.local/bin/codex`; `/opt/homebrew/bin/codex` and `/usr/local/bin/codex`, Homebrew's cask |
| Windows | `%LOCALAPPDATA%\Programs\OpenAI\Codex\bin\codex.exe`, the publisher's `install.ps1`; `%APPDATA%\npm\codex.cmd`, npm's |

A copy at the manifest's `user_copy_min_version` or newer is the account's,
and the module installs nothing for it. An older one keeps running in the
account's own shell, and the account uses the module's copy, its row
reading `copy_version_unsupported {account, version, min}`.

**The module's copy is the publisher's package archive.**
`data/manifests/codex.json` names one artifact per platform, of kind
`tar_gz`: `codex-package-<target>.tar.gz` of the GitHub release
`rust-v{version}`, `<target>` being `x86_64-unknown-linux-musl`,
`aarch64-unknown-linux-musl`, `x86_64-apple-darwin`,
`aarch64-apple-darwin`, `x86_64-pc-windows-msvc` or
`aarch64-pc-windows-msvc`. Its digest is the one GitHub's API gives the
asset, which equals the release's own `codex-package_SHA256SUMS`, and its
sources are the GitHub release, then
`https://releases.openai.com/codex/releases/{version}/{file}`, which serves
the same files ([../module_install.md](../module_install.md), "Sources").
The agent unpacks it into `codex/package/` under the state root: `bin/codex`
with `bin/codex-code-mode-host`, `codex-path/rg`, `codex-resources/` and
`codex-package.json`, all at the archive's top.

| Rule | Reason |
| --- | --- |
| The artifact is the package archive, never the release's `codex-<target>.tar.gz`. | The publisher's own installer installs the package. Codex finds `rg` and its helpers through `codex-package.json` beside `bin/`, and the archive of one program holds none of them. |
| The npm registries are no source of it. | They serve `@openai/codex@<version>-<platform>`, another archive of the same program, whose bytes differ from the release's. |

**The version moves in the hub.** The versions and their digests come from
the `github` feed of `openai/codex` with the tag `rust-v{version}`, which
leaves the alpha prereleases out ([../module_install.md](../module_install.md),
"Module versions"). `verify` is `package/bin/codex` with `--version`, which
prints `codex-cli 0.166.0`.

**The launcher starts the copy and sets nothing.** `codex/bin/codex`,
`codex.cmd` on Windows, starts `package/bin/codex` with its arguments.
Codex's own updater runs a command only for a copy under
`~/.codex/packages/standalone/releases/` or one that a JavaScript package
manager or Homebrew installed, and the module's copy is none of these and is root's,
so nothing writes it. Codex reads `check_for_update_on_startup` from the
account's `~/.codex/config.toml`, which the module does not write, and the
update notice it can show names the newest release on GitHub, which the
hub's list of tested and untested versions does not always hold.

**The gateway is the machine's AI tools setting.** The module writes no
settings file: both copies read the account's `~/.codex/config.toml` and
`auth.json`, which the setting writes when the account's switch is on
([../ai_tools.md](../ai_tools.md)).

**CloudCLI and Codeg run their own Codex.** CloudCLI's npm package depends
on `@openai/codex` and runs that copy, and Codeg runs the `codex-acp`
adapter it installs, so neither requires this module
([cloudcli.md](cloudcli.md), [codeg.md](codeg.md)).

**An uninstall keeps every account's own files.** It removes `codex/` under
the state root, every link and `PATH` entry that still carries the module's
mark, and the record. Its line in the uninstall dialog is "Each account's
settings in ~/.codex stay, and so does a copy of Codex installed outside
this module."

`details` is `{has_module_copy, accounts: [{account, copy, path, version,
code, params}]}`, `copy` being `user` or `module`. An apply refuses what
Claude Code's refuses ([claude_code.md](claude_code.md)). Its journal is the
agent's lines that name the module ([../../agent.md](../../agent.md), "Which
modules each system runs").
