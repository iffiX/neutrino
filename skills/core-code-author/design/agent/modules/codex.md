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
and the module installs nothing for it. `user_copy_min_version` is 0.166.0,
the tested version. An older one keeps running in the account's own shell,
and the account uses the module's copy, its row reading
`copy_version_unsupported {account, version, min}`.

**The module's copy is OpenAI's npm build for the platform.**
`data/manifests/codex.json` names one artifact per platform, of kind
`tar_gz`: the tarball of `@openai/codex@{version}-<platform>`, its `file`
`@openai/codex/-/codex-{version}-<platform>.tgz`, `<platform>` being
`linux-x64`, `linux-arm64`, `darwin-x64`, `darwin-arm64`, `win32-x64` or
`win32-arm64`, with the `npm` set as its `source_set` and npm's integrity
as its digest ([../module_install.md](../module_install.md), "Sources").
The tarball holds the program in `package/vendor/<target>/bin/codex`,
`codex.exe` on Windows, `<target>` being `x86_64-unknown-linux-musl`,
`aarch64-unknown-linux-musl`, `x86_64-apple-darwin`,
`aarch64-apple-darwin`, `x86_64-pc-windows-msvc` or
`aarch64-pc-windows-msvc`. Beside `bin/` in `vendor/<target>/` are
`codex-path/rg`, `codex-resources/` and `codex-package.json`, and
`package.json` and `README.md` sit at the top of `package/`. The agent
unpacks it without `package/` into `codex/package/` under the state root,
so the program is `codex/package/vendor/<target>/bin/codex`.

| Rule | Reason |
| --- | --- |
| The module's installer fetches the platform's npm build from the `npm` set, never from Codex's GitHub release or `releases.openai.com`. | One source set serves both tool modules, its three registries serve each tarball under the one integrity npm's upload fixed, and two of them, npmmirror and Tencent's mirror, serve mainland China. |
| The artifact is the tarball of `{version}-<platform>`, never of `{version}` itself. | `@openai/codex@0.166.0` holds only npm's wrapper `bin/codex.js`, 13.5 KB unpacked, which names the six platform builds as optional dependencies and starts `vendor/<target>/bin/codex` of the machine's one. |
| The unpack keeps `vendor/<target>/` whole. | Codex finds `rg` and its helpers through `codex-package.json` beside its `bin/`. |

The tarball is 164 MiB for linux-x64, and 140 to 172 MiB on the other
platforms. Unpacked it takes about 456 MB for linux-x64, npm's
`unpackedSize` of 456,152,362 bytes: `codex` 319 MB,
`codex-code-mode-host` 78 MB, the voice host and its libraries 53 MB and
`rg` 5 MB. The other platforms take 363 to 503 MB. That is the disk the
module's copy takes under the state root, once per machine whatever the
number of accounts, and a version switch holds a second copy beside it
until the new one passes `verify` ([../module_install.md](../module_install.md),
"Module versions").

**The version moves in the hub.** The tested version, 0.166.0, was the
newest release of `openai/codex` on GitHub that is not a pre-release on
2026-11-04, when 0.168.0-alpha.1 was the newest pre-release. The versions
come from the `npm` feed of `@openai/codex`, read from registry.npmjs.org:
its versions that are dotted numbers, which leaves the alpha versions and
the platform builds out. Each
platform's artifact takes the integrity of the build `{version}-<platform>`
([../module_install.md](../module_install.md), "Module versions"), so a
version is listed for a platform once that build is published:
0.166.0-win32-arm64 came 19 minutes after 0.166.0. `verify` is
`package/vendor/<target>/bin/codex` with `--version`, which prints
`codex-cli 0.166.0`.

**The launcher starts the copy and sets nothing.** `codex/bin/codex`,
`codex.cmd` on Windows, starts `package/vendor/<target>/bin/codex` with its
arguments. Codex's own updater runs a command only for a copy under
`~/.codex/packages/standalone/releases/`, one under `/opt/homebrew` or
`/usr/local` on macOS, or one started with `CODEX_MANAGED_BY_NPM` or another
package manager's variable, which npm's wrapper sets. The module's copy is
none of these and is root's, so nothing writes it. Codex reads
`check_for_update_on_startup` from the account's `~/.codex/config.toml`,
which the module does not write, and the update notice it can show names
the newest release on GitHub, which the hub's list of tested and untested
versions does not always hold.

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

`details` is `{has_module_copy, version, accounts: [{account, copy, path,
version, code, params}]}`, the first `version` being the module's copy's,
empty while it has none, and `copy` being `user` or `module`. An apply refuses what
Claude Code's refuses ([claude_code.md](claude_code.md)). Its journal is the
agent's lines that name the module ([../../agent.md](../../agent.md), "Which
modules each system runs").
