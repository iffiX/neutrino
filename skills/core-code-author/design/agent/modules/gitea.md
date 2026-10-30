# The Gitea module

The `gitea` module runs Gitea, the release binary its publisher builds
(MIT), one instance per machine, on Linux, macOS and Windows, the way
Gitea's own page "Installation from binary" describes. One applier per
system sits behind one runner in `agent/neutrino_agent/modules/gitea/`, and
the configuration, the rendered `app.ini`, the accounts made through the
gitea CLI, the published app with its `web` and `ssh` entries and the verbs
are the same on every system.

| | Linux | macOS | Windows |
| --- | --- | --- | --- |
| Binary | `/usr/local/bin/gitea` | `gitea/gitea` under the state root | `gitea\gitea.exe` under the state root |
| Data: the database, the repositories, the log, `custom/` | `/var/lib/gitea` | `gitea_data/` under the state root, owned by the account, mode 700 | `gitea_data\` under the state root, SYSTEM and the administrators alone as the root is |
| `app.ini` | `/etc/gitea/app.ini`, root and the group `git`, mode 640 | `gitea_data/custom/conf/app.ini`, the account's, mode 600 | `gitea_data\custom\conf\app.ini` |
| Listens on | `127.0.0.1` alone, at the configured port | the same | the same |
| Runs as | the system account `git` the module makes | the hidden account `neutrino_gitea`, made with `sysadminctl` the way the file share makes its accounts, with the full name `Neutrino Gitea`, the shell `/usr/bin/false` and the data directory as its home, and read back before it counts | LocalSystem, `RUN_USER` being `<computer name>$` as Gitea's page prescribes |
| Service | `neutrino_gitea.service`, disabled at **Stop** and enabled at **Start** | the LaunchDaemon `com.neutrino.gitea` with `UserName`, its output in `/Library/Logs/Neutrino/agent/gitea.log`, disabled with `launchctl disable` at **Stop** and enabled at **Start** | the service `neutrino_gitea`, made with `sc.exe`, started at boot and again after a failure; its start type `disabled` at **Stop** and `auto` at **Start** |
| Git | the distribution's `git`, which the entry's `packages` names and the system's package manager installs before the binary | the command line tools' or Xcode's own `git`, else Homebrew's, never `/usr/bin/git` | Git for Windows, found on the machine's `Path` as the service reads it, else under `%ProgramFiles%\Git\cmd` |
| SSH | Gitea's own SSH server, on `127.0.0.1` alone | the same | the same |

**Gitea listens on loopback alone.** `app.ini` names `HTTP_ADDR =
127.0.0.1`, and the `web` entry is reached through the agent's end of a
`connect` stream, which dials `127.0.0.1` at the port the server listens on,
`HTTP_PORT`, which the module reports as `port`; the hub puts that port in
the URL the module reports ([agent.md](../../agent.md), "The connect
stream"). `app.ini` also names `PUBLIC_URL_DETECTION = auto`, so the links
and clone addresses Gitea shows name the address the page was opened at, a
client's own forward, in place of `ROOT_URL`. The module
opens no port in any firewall, and the hub dials nothing on the machine: the
entry is healthy while the machine reports the server running. A Gitea that
listened on every address moves to loopback at the next apply, which an
agent of another build runs once for every module the state names: it
renders `app.ini` again and restarts the server on the changed file. The
panel shows no link to it; a client opens it as it opens every `web` entry.

**Gitea's own SSH server is its `ssh` entry.** `app.ini` names
`START_SSH_SERVER = true`, `SSH_LISTEN_HOST = 127.0.0.1` and
`SSH_LISTEN_PORT`, a port the agent takes from 2222 up at the first apply,
keeps in the module's root-only record under its state root and writes into
every render of `app.ini` after, and reports as `ssh_listen_port`; a machine
that reports none publishes no `ssh` entry, so git over SSH reaches Gitea through a
client and never through the machine's own sshd or the agent's SSH server.
The hub publishes that port as the `ssh` entry of the Gitea app, a TCP
`port` entry beside `web` ([../../protocol.md](../../protocol.md), "Apps").
`SSH_DOMAIN` is `127.0.0.1` and `SSH_PORT` the local port of the `ssh`
entry, from the state's `ssh_port`, so the clone address the page shows,
`ssh://git@127.0.0.1:<port>/<owner>/<repository>.git`, is the forward's
address on every client ([../../protocol.md](../../protocol.md), "The local
name and the local port"). A `.localhost` name is not used there, since git
and ssh do not resolve one on every system, and the forward listens on
`127.0.0.1` alone. Gitea makes its own SSH host key in its data directory,
and a person adds their SSH keys in Gitea itself.

**Git is the machine's.** The module installs none on macOS and Windows: an
install or an apply there that finds no usable `git` is refused
`gitea_git_missing`, and `app.ini` names the one found in `[git] PATH`. On a
Mac without the developer tools `/usr/bin/git` is a stub that opens a dialog
on the screen, so it is never run and never named.

**The binary comes from its publisher.** `data/manifests/gitea.json` names
the release binary, kind `binary`, at one tested version for every system:
`linux-amd64`, `linux-arm64`, `darwin-10.12-amd64`, `darwin-10.12-arm64` and
`windows-4.0-amd64`. Its versions and digests come from Gitea's GitHub
releases, and its sources are dl.gitea.com and the GitHub release, which
serve the same files. The Windows build is the one that runs `git`, as on
Linux; the `gogit` build is not used. The hub's cache fetches it and sends
it down `package {module: gitea, artifact, digest}`.

**An older version asks first.** Gitea migrates its database forward at its
first start on a new version, and an older Gitea cannot read it. The
manifest therefore names `is_data_forward_only`, and the machine page asks
before it installs a version older than the one installed
([module_install.md](../module_install.md), "Module versions").

**The accounts are made through the gitea CLI as the server's own account**:
`runuser -u git` on Linux, a process with the account's uid, gid, home and
`USER` on macOS, and the agent itself on Windows, which is LocalSystem as
the service is.

**The data belongs to the server's account.** The `account` step makes the
account when it is missing, and hands the data over to the account when
another uid owns one of Gitea's own folders in the data directory,
`custom/`, `data/` or `log/`. On Linux the handover gives the data
directory with everything under it, and `app.ini` goes to the account's
group with it. On macOS it gives those three folders alone: the data
directory is also the account's home, where macOS writes `Library/` with
files root cannot give away. A handover gives each folder after what it
holds, so one cut short runs again at the next start. A `git` account
removed by hand comes back with a new uid, and Gitea fails to start on
data the old uid owns. A symbolic link under the data keeps its owner.

**A start waits for the server.** A `configure` that runs the server waits
until it listens on `127.0.0.1` at its port, at most 60 seconds, and
otherwise fails `apply_failed {detail}`, the detail naming the port and
the last error Gitea logged, else the last line of its output. A Gitea that
launchd or systemd keeps starting again then reads `failed`.

**Uninstall takes what the module added and keeps the data**: the unit,
the LaunchDaemon or the service, the binary and `app.ini` go; the data
directory and the account stay, so an install afterwards serves the same
repositories and accounts. On Windows and macOS its journal reads the end of
its own log, `log/gitea.log` under its data directory. Removing the agent
takes the LaunchDaemon and the
service with its own ([agent.md](../../agent.md), "One session, everything on
it").
