# The Gitea module

The `gitea` module runs Gitea, the release binary its publisher builds
(MIT), one instance per machine, on Linux, macOS and Windows, the way
Gitea's own page "Installation from binary" describes. One applier per
system sits behind one runner in `agent/neutrino_agent/modules/gitea/`, and
the configuration, the rendered `app.ini`, the accounts made through the
gitea CLI, the published `web` entry and the verbs are the same on every
system.

| | Linux | macOS | Windows |
| --- | --- | --- | --- |
| Binary | `/usr/local/bin/gitea` | `gitea/gitea` under the state root | `gitea\gitea.exe` under the state root |
| Data: the database, the repositories, the log, `custom/` | `/var/lib/gitea` | `gitea_data/` under the state root, owned by the account, mode 700 | `gitea_data\` under the state root, SYSTEM and the administrators alone as the root is |
| `app.ini` | `/etc/gitea/app.ini`, root and the group `git`, mode 640 | `gitea_data/custom/conf/app.ini`, the account's, mode 600 | `gitea_data\custom\conf\app.ini` |
| Runs as | the system account `git` the module makes | the hidden account `neutrino_gitea`, made with `sysadminctl` the way the file share makes its accounts, with the full name `Neutrino Gitea`, the shell `/usr/bin/false` and the data directory as its home, and read back before it counts | LocalSystem, `RUN_USER` being `<computer name>$` as Gitea's page prescribes |
| Service | `neutrino_gitea.service` | the LaunchDaemon `com.neutrino.gitea` with `UserName`, its output in `/Library/Logs/Neutrino/agent/gitea.log` | the service `neutrino_gitea`, made with `sc.exe`, started at boot and again after a failure |
| Git | the distribution's `git`, installed with the binary | the command line tools' or Xcode's own `git`, else Homebrew's, never `/usr/bin/git` | Git for Windows, found on the machine's `Path` as the service reads it, else under `%ProgramFiles%\Git\cmd` |
| SSH | the system's `sshd` as `git` | none; clones and pushes over HTTP | none; clones and pushes over HTTP |

**Git is the machine's.** The module installs none on macOS and Windows: an
install or an apply there that finds no usable `git` is refused
`gitea_git_missing`, and `app.ini` names the one found in `[git] PATH`. On a
Mac without the developer tools `/usr/bin/git` is a stub that opens a dialog
on the screen, so it is never run and never named.

**The binary comes from its publisher.** `data/manifests/gitea.json` pins
the release at one version for every system: `linux-amd64`, `linux-arm64`,
`darwin-10.12-amd64`, `darwin-10.12-arm64` and `windows-4.0-amd64`, each with
the sha256 dl.gitea.com publishes beside it. The Windows build is the one
that runs `git`, as on Linux; the `gogit` build is not used. The hub's cache
fetches it and sends it down `package {module: gitea}`.

**The accounts are made through the gitea CLI as the server's own account**:
`runuser -u git` on Linux, a process with the account's uid, gid, home and
`USER` on macOS, and the agent itself on Windows, which is LocalSystem as
the service is.

**Uninstall takes what the module added and keeps the data**: the unit,
the LaunchDaemon or the service, the binary and `app.ini` go; the data
directory and the account stay, so an install afterwards serves the same
repositories and accounts. On Windows and macOS its journal reads the end of
its own log, `log/gitea.log` under its data directory. Removing the agent
takes the LaunchDaemon and the
service with its own ([agent.md](../../agent.md), "One socket, everything on
it").
