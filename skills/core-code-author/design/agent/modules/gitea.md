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
| `app.ini` | `/etc/gitea/app.ini`, the account's, mode 640, in `/etc/gitea`, the account's, mode 770 | `gitea_data/custom/conf/app.ini`, the account's, mode 600 | `gitea_data\custom\conf\app.ini` |
| Listens on | `127.0.0.1` alone, at the configured port | the same | the same |
| Runs as | the system account `git` the module makes | the hidden account `neutrino_gitea`, made with `sysadminctl` the way the file share makes its accounts, with the full name `Neutrino Gitea`, the shell `/usr/bin/false` and the data directory as its home, and read back before it counts | LocalSystem, `RUN_USER` being `<computer name>$` as Gitea's page prescribes |
| Service | `neutrino_gitea.service`, disabled at **Stop** and enabled at **Start** | the LaunchDaemon `com.neutrino.gitea` with `UserName`, its output in `/Library/Logs/Neutrino/agent/gitea.log`, disabled with `launchctl disable` at **Stop** and enabled at **Start** | the service `neutrino_gitea`, made with `sc.exe`, started at boot and again after a failure; its start type `disabled` at **Stop** and `auto` at **Start** |
| Git | the distribution's `git`, which the entry's `packages` names and the system's package manager installs before the binary | the command line tools' or Xcode's own `git`, else Homebrew's, never `/usr/bin/git`; with none, the install's step `command_line_tools` installs Apple's Command Line Tools | the module's own MinGit, unpacked in `gitea\git\` under the state root |
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

**Gitea brings its git on macOS and Windows.** `app.ini` names the git
Gitea runs in `[git] PATH`, and no `PATH` of the machine's changes.

| Rule | Reason |
| --- | --- |
| On Windows the manifest names Git for Windows' MinGit beside the binary, the zip `MinGit-<version>-64-bit.zip` from Git for Windows' GitHub release, one artifact for the one architecture the module runs on, its digest the one GitHub gives the asset. It unpacks into `gitea\git\` under the state root, and `[git] PATH` names its `cmd\git.exe`. | MinGit is the build Git for Windows publishes for programs that run git themselves. A git of the module's own is the same on every machine, and Gitea alone runs it. |
| The MinGit artifact comes before the binary, and keeps its own digest for every version of Gitea ([../module_install.md](../module_install.md), "Module versions"). | The binary's step finds git in place, and a version switch moves the binary alone. |
| On Windows `app.ini` names `SCRIPT_TYPE = sh` in `[repository]`. | MinGit holds `sh` and no `bash`, and Gitea writes its hooks for the shell it names. |
| A Windows Gitea whose MinGit is missing owes its install, which runs again at the next **Install** or **Start** ([../../agent.md](../../agent.md), "The steps"). | A Gitea installed before the module carried MinGit gets it at the next press. |
| On macOS an install that finds no usable `git` runs the step `command_line_tools` before the binary's: it installs Apple's Command Line Tools with `softwareupdate`, as Homebrew's installer does, under the step lock `package_manager`. The placeholder file that makes `softwareupdate` list the tools is made in `/tmp` following no link. The step is in the plan only while no `git` is found. | A Mac without the developer tools has no git, and the Command Line Tools are Apple's own package of it. In the lab `softwareupdate` took about 7 minutes. |
| `gitea_git_missing` is the failure of that step: no `git` found after it ran. An apply on macOS that finds no `git` owes the install, as on Windows. | The step is the one way the module gets git on a Mac. |
| On a Mac without the developer tools `/usr/bin/git` is a stub that opens a dialog on the screen, so it is never run and never named. | A dialog on the screen of a machine nobody watches waits forever. |

**What a report reads.** `gitea --version` runs once per program file.
`gitea admin user list --admin` runs with it, after a `configure`, after the
module's own `admin` and `password` verbs, and every 10 minutes otherwise. Each
read starts a process and the agent reports every few seconds, so an
administrator a person makes in Gitea's own page shows within 10 minutes.

**The binary comes from its publisher.** `data/manifests/gitea.json` names
the release binary, kind `binary`, at one tested version for every system:
`linux-amd64`, `linux-arm64`, `darwin-10.12-amd64`, `darwin-10.12-arm64` and
`windows-4.0-amd64`. Its versions and digests come from Gitea's GitHub
releases, and its sources are dl.gitea.com and the GitHub release, which
serve the same files. The Windows build is the one that runs `git`, as on
Linux; the `gogit` build is not used. The hub's cache fetches it and sends
it down `package {module: gitea, artifact, digest}`.

**Gitea only upgrades.** Gitea migrates its database forward at its first
start on a new version, and an older Gitea cannot read it: in the lab
1.27.3 to 1.27.2 and 28.0.0 to 1.27.3 failed. The manifest names
`is_data_forward_only`, so the module installs no version older than the
newest it has run on the machine ([module_install.md](../module_install.md),
"Module versions").

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

**What is in the account's folders is touched as the account.** The data
directory and, on Linux, `/etc/gitea` are the server account's, so the
account can put a link anywhere in them
([../../privilege.md](../../privilege.md), "The agent touches an account's
files as that account"):

| Rule | Reason |
| --- | --- |
| The folders inside the data directory, `.ssh` and its mode 700 among them, and `app.ini` are made, written, read and removed as the server's account: through `runuser -u git` on Linux and through a process of the account's uid and group on macOS. | As the account, a link it planted reaches only what it reaches itself. |
| The data directory, `/var/lib/gitea` on Linux and `gitea_data/` on macOS, and `/etc/gitea` sit in folders of root's: root makes each and gives it to the account on its open descriptor, each level opened with no link followed. | Each is a name in root's folder, which no account can replace. |
| A handover is root's, since no account can take the files another uid owns: each entry is opened from its folder's open descriptor with no link followed and given on that descriptor, a link is left as it is, and a file that has a second name elsewhere is left, since that name may be a file of root's. | A link or a second name planted in the data then turns no change of owner onto a file outside it. |
| Each entry the handover opens is given only while its real path, read from the open descriptor itself, `/proc/self/fd/<fd>` on Linux and `fcntl` with `F_GETPATH` on macOS, starts with the folder handed over: `/var/lib/gitea/` on Linux, and on macOS each of `custom/`, `data/` and `log/` under its own path. An entry outside is left, with a line in the agent's log, and so is what it holds; a folder found outside while its contents are walked is left from there on, with one line. No path is checked before its open. | The account owns the folders in the data, so it can move one out of the data between the listing and the open, and the descriptor then holds a folder elsewhere. The descriptor's own path names where the opened entry is; a path checked before the open races the same move. |
| On Linux root reads `app.ini` for its port and its address through no link and waiting on no pipe; on macOS the account reads it. | The file sits in the account's folder. |
| Gitea's own log, `log/gitea.log` in the data directory, is read as the server's account on Linux and macOS: the end of it for the journal on macOS, and for the last error a start that does not listen names on both. On Windows the data directory is SYSTEM's, and SYSTEM reads the log. | The log sits in the account's folder, where the account can put a link to a file only root reads. |

**A start waits for the server.** A `configure` that runs the server waits
until it listens on `127.0.0.1` at its port, at most 60 seconds, and
otherwise fails `apply_failed {detail}`, the detail naming the port and
the last error Gitea logged, else the last line of its output. A Gitea that
launchd or systemd keeps starting again then reads `failed`.

**A Gitea taken over stays as it is until a press.** The hub takes Gitea
over only while it holds the secrets of the instance it installed
([../../protocol.md](../../protocol.md), "The modules section, one entry
per module"). While its entry carries `is_taken_over`, its task's one step
is `configure`, which checks the configuration and writes nothing: no
`account` step runs, `app.ini`, the unit, the LaunchDaemon or the service
and the record's SSH port stay as they are, and the server neither starts
nor stops. The person's first press writes them
([../../agent.md](../../agent.md), "The steps").

**Uninstall takes what the module added and keeps the data**: the unit,
the LaunchDaemon or the service, the binary, MinGit on Windows and `app.ini`
go; the data directory stays, so an install afterwards serves the same
repositories and accounts. On macOS the account `neutrino_gitea` goes too,
deleted with `dscl . -delete` after the job, which leaves its home, the
data directory, in place; the next install makes the account again and its
`account` step hands the data to it. macOS 15 refuses that deletion with
`eDSPermissionError` to a process without Full Disk Access, the agent's
LaunchDaemon among them, and to `sysadminctl -deleteUser` as well: the
account then stays, hidden, with no shell and a password nobody holds,
and the uninstall writes the system's line into the module's log and goes
on. On Linux the account `git` stays: its
name is not Neutrino's, and it can be the person's own. On Windows and
macOS its journal reads the end of its own log, `log/gitea.log` under its
data directory. Removing the agent
takes the LaunchDaemon and the
service with its own ([agent.md](../../agent.md), "One session, everything on
it").
