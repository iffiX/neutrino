# The OpenCode module

The `opencode` module makes OpenCode, Anomaly's open source coding agent for
the terminal (MIT), ready for each enabled account on Linux, macOS and
Windows, each on amd64 and arm64, tested at 1.19.5. It is a command line
program ([../module_template.md](../module_template.md), "A command line
program"): `agent/neutrino_agent/modules/opencode/` holds `config.py`,
`constants.py` and `hooks.py`, and `modules/shared/programs.py` does the
rest. Its configuration is `{accounts: [{account, password}]}`, `password`
being the account's login, sent to a Windows machine alone
([../../protocol.md](../../protocol.md), "The account layer in the state").

**The module's copy runs first for each enabled account.** Before an
account is checked, `find` reads the account's `PATH`, then these places, as
the account, and a copy found is named in the panel's dialog
([../../agent.md](../../agent.md), "Parallel, never take over"):

| System | The places after `PATH` |
| --- | --- |
| Linux | `~/.opencode/bin/opencode`, the publisher's install script; `/usr/local/bin/opencode`; `/usr/bin/opencode`, the AUR package's |
| macOS | `~/.opencode/bin/opencode`; `/opt/homebrew/bin/opencode` and `/usr/local/bin/opencode`, Homebrew's |
| Windows | `%USERPROFILE%\scoop\shims\opencode.exe`, Scoop's; `%ProgramData%\chocolatey\bin\opencode.exe`, Chocolatey's; `%APPDATA%\npm\opencode.cmd`, npm's |

On the person's yes the account's `PATH` names the module's launcher
folder first, and the person's copy stays where it is, for its own
installer to update or remove.

**The module's copy is the publisher's npm package for the platform.**
`data/manifests/opencode.json` names one artifact per platform, of kind
`tar_gz`: the tarball of `opencode-<platform>`, the `linux-x64-baseline`,
`linux-arm64`, `darwin-x64-baseline`, `darwin-arm64`,
`windows-x64-baseline` or `windows-arm64` package, with the `npm` set as its
`source_set` and npm's integrity as its digest
([../module_install.md](../module_install.md), "Sources"). The tarball holds
`bin/opencode`, `bin/opencode.exe` on Windows, and `package.json`, both
under `package/`, and the agent unpacks it without that directory into
`opencode/package/` under the state root, so the program is
`opencode/package/bin/opencode`.

| Rule | Reason |
| --- | --- |
| The module's installer fetches the platform's npm package from the `npm` set, never from OpenCode's GitHub release or `opencode.ai/install`. | One source set serves every tool module, its three registries serve each tarball under the one integrity npm's upload fixed, and two of them, npmmirror and Tencent's mirror, serve mainland China. |
| The artifact is the tarball of the platform's package, never of `opencode-ai`. | `opencode-ai@1.19.5` holds a 479-byte placeholder `bin/opencode.exe` and a `postinstall.mjs` that runs npm to fetch the platform's package and copies its program over the placeholder. |
| On amd64 the artifact is the `-baseline` build on every system. | The other amd64 build needs a processor with AVX2. npm's `postinstall.mjs` takes the baseline build where `/proc/cpuinfo`, `sysctl` or Windows reports no AVX2, and one artifact per platform has to run on every machine of it. |
| On Linux the artifact is the glibc build, never the `-musl` one. | The musl build runs only where the system's loader is musl's. The glibc build names glibc 2.17 at most, below the agent's floor of 2.34 ([../../min_support.md](../../min_support.md)). |

The tarball is 75.5 MiB for linux-x64-baseline, 74.3 MiB for linux-arm64,
65.4 MiB for darwin-x64-baseline, 60.9 MiB for darwin-arm64, 75.9 MiB for
windows-x64-baseline and 69.9 MiB for windows-arm64. Unpacked it is the one
program, npm's `unpackedSize` of 214,387,010 bytes for linux-x64-baseline,
and 181 to 212 MB on the other platforms. That is the disk the module's copy
takes under the state root, once per machine whatever the number of
accounts, and a version switch holds a second copy beside it until the new
one passes `verify` ([../module_install.md](../module_install.md), "Module
versions").

**The version moves in the hub.** The tested version, 1.19.5, was the
version npm's `latest` dist-tag of `opencode-ai` named on 2026-11-10. The
versions and their digests come from the `npm` feed of each platform's own
package, `opencode-<platform>`, read from registry.npmjs.org: its versions
that are dotted numbers, which leaves the `0.0.0-<channel>-<date>` builds
of the `dev`, `beta` and snapshot channels out
([../module_install.md](../module_install.md), "Module versions"). `verify`
is `package/bin/opencode` with `--version`, which prints `1.19.5`. The agent
runs it with `HOME` set to `opencode/verify_home/` under the state root,
`USERPROFILE` on Windows, which it makes beside the module's copy.

| Rule | Reason |
| --- | --- |
| `verify` runs with the home folder pointing into the module's directory. | Every start of OpenCode, `--version` too, makes `.config/opencode`, `.local/share/opencode/log`, `.local/share/opencode/repos`, `.local/state/opencode` and `.cache/opencode/bin` in its home folder, which it reads from `HOME`, `USERPROFILE` on Windows. With the variable it writes under `verify_home/` alone, and an uninstall removes it with the module's directory. |

**The launcher starts the copy and sets nothing.** `opencode/bin/opencode`,
`opencode.cmd` on Windows, starts `package/bin/opencode` with its
arguments. OpenCode's check at start installs nothing: it names a newer
version on npm, which the hub's list of tested and untested versions does
not always hold, and the account's `autoupdate: false` in its
`opencode.json`, which the module does not write, turns it off. Only `opencode
upgrade` and `/update` install, by the method OpenCode finds for the copy it
runs: a copy under `~/.opencode/bin` or `~/.local/bin` is the install
script's, and any other asks the account's npm, yarn, pnpm, bun, Homebrew,
Scoop and Chocolatey for a package of OpenCode. The module's copy is none
of these and is root's, so such a run installs a copy of the account's own
and never writes the module's.

**The gateway is the machine's AI tools setting.** The module writes no
settings file: both copies read the account's
`~/.config/opencode/opencode.json`, to which the setting adds the hub as the
provider `neutrino` when the account's switch is on
([../ai_tools.md](../ai_tools.md)).

**CloudCLI and Codeg do not reach the module's copy.** The `PATH` of each
one's service names no launcher folder ([cloudcli.md](cloudcli.md), "The
service's `PATH` names directories, never a tool", [codeg.md](codeg.md)), so
neither requires this module.

**An uninstall keeps every account's own files.** It removes `opencode/`
under the state root, the record, and each enabled account's line, `env.sh`
and Windows entry as [../module_install.md](../module_install.md), "What an
uninstall removes", says. Its line in the uninstall dialog is "Each
account's settings in ~/.config/opencode stay, and so does a copy of
OpenCode installed outside this module."

`details` is `{has_module_copy, version, accounts: [{account, code,
params}]}`, as Claude Code's is ([claude_code.md](claude_code.md)). An apply refuses what
Claude Code's refuses ([claude_code.md](claude_code.md)). Its journal is the
agent's lines that name the module ([../../agent.md](../../agent.md), "Which
modules each system runs").
