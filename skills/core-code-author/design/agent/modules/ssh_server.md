# The SSH server module

The `ssh_server` module is the agent's own SSH server, carried in the
agent's package beside Terminal and Remote desktop: one instance per enabled
account, each running as that account on `127.0.0.1`, admitting the one key
the hub made for that account on that machine. Through it every program that
speaks SSH reaches the machine through a desktop client, `ssh`, `scp`,
`sftp`, `rsync`, `git` and VS Code's Remote-SSH among them, beside the
machine's own sshd, which keeps the configuration its person gave it. It is
no app: it is a function of every machine, as Terminal and Remote desktop
are, and no client's Apps page and not the panel's Services page shows it.

## What runs

| Rule | Reason |
| --- | --- |
| The server is `neutrino_ssh_server`, one Go program of `agent/sshserver/` built static for each platform the agent ships on, with `golang.org/x/crypto/ssh` and `github.com/pkg/sftp`. The agent's package carries it under its program directory, `bin/neutrino_ssh_server`, `bin\neutrino_ssh_server.exe` on Windows, as it carries RustDesk; the agent itself stays pure standard library. | A server the agent carries works the same on every machine, and the agent's own code installs on a machine with no Python. |
| Its platform entries name the method `agent` with empty `params`, so it installs nothing, is a tab on every machine, is locked checked in the module catalog, and takes none of the four presses, which are refused `module_not_optional {name}` ([../module_install.md](../module_install.md), "Install methods"). | The binary is in the agent's package, as Terminal's code is. |
| Its one setting is its enabled accounts ([../../agent.md](../../agent.md), "The two layers and the accounts"). The module reads `running` while every enabled account's instance runs, and `stopped` while it enables none. | A server runs only for an account the person chose. |
| Each instance runs as its account through the account service layer: the unit `neutrino_ssh_server@<account>.service` with `User=<account>` on Linux, the LaunchDaemon `com.neutrino.ssh_server.<account>` with `UserName` on macOS, and the scheduled task `neutrino_ssh_server_<account>` under the account's login on Windows ([../module_template.md](../module_template.md), "The run"). | The process is the account, so a shell, a command and an sftp session need no change of identity and reach exactly what the account reaches. |
| An instance listens on `127.0.0.1` alone, at a port the agent takes from 22000 up at the instance's first start and keeps in the instance's record. The module opens no port in any firewall. | The hub reaches it through the agent's `connect` stream, and nothing on the LAN reaches it at all. |

The agent starts each instance as `neutrino_ssh_server --listen
127.0.0.1:<port> --host-key <file> --authorized-key <file> --shell <shell>
--path-folders <file>`, the three files in `ssh_server/run/<account>/` under
the state root, the account's run folder. `path_folders` holds the
launcher folders a session's `PATH` starts with, one per line ("The `PATH`
of a session").

| Rule | Reason |
| --- | --- |
| The run folder and every file in it are root's, SYSTEM's on Windows, and the account reads them and changes nothing: on Linux and macOS the folder is mode 700 and each file 600, root's alone, of the group `root` on Linux and `wheel` on macOS, each with an access entry that lets the one account read it, on Linux `setfacl --set` with `u:<account>:rx` on the folder and `u:<account>:r` on each file, the group and the others given nothing, which `ls -l` shows as 750 and 640 with a `+` since the group's bits show the entries' mask, and on macOS `chmod +a`; on Windows the folder's access list, set whole on its handle, gives the account Read, SYSTEM and the administrators full control, inherited by every file and nothing inherited from above. | The agent writes the three files, and root writes only into a folder no account can change ([../../privilege.md](../../privilege.md), "The agent touches an account's files as that account"). An entry names the one account, so nothing rests on a group: a primary group several accounts share on Linux, and `staff` on a Mac, would let each of them read the others' host keys. |
| The agent writes each file whole: a new file made afresh beside it, following no link, given its mode and owner on the open file, and renamed in. A file that holds its text already is not written. | A session reads the old text or the new one, never part of one. |
| A run folder an earlier version gave the account is taken back at the first apply: on Linux and macOS given to root on its open descriptor, following no link, on Windows its access list set again on its handle, a junction where the folder goes removed and never followed. Once it is root's, every file the account had in it is deleted on Linux and macOS, links among them, and on Windows the copy of the machine's host key it held, `host_key`; the instance's own key is `instance_host_key`. What stays the agent reads none of. | The layout cuts over at the first apply, and no code reads the old one ([../../agent.md](../../agent.md), "One session, everything on it"). |

## Keys

| Key | Made by | Kept | Reaches |
| --- | --- | --- | --- |
| the host key, one per instance | the agent, at the instance's first apply, with `neutrino_ssh_server --make-host-key`: Ed25519 in OpenSSH form | `instance_host_key` in the account's run folder alone, root's, which the account reads | the hub as the public key in the instance's row of the module's `details`, and each client as the `service` frame's `host_key` of the account's `ssh` entry |
| the account's key, one per machine and enabled account | the hub, when the account is first enabled: Ed25519 | the private half sealed under the vault's data key in `config/devices/<id>/ssh_server.json`, kept while the account is available | the agent as the public half, the instance's one authorized key; a client as the private half in the `service` frame, which the client writes under `~/.ssh/neutrino/` ([../../client.md](../../client.md), "SSH for other programs") |

| Rule | Reason |
| --- | --- |
| An instance admits public-key authentication by the account's key alone. It offers no password and no keyboard-interactive method, and it reads no `sshd_config` and no `authorized_keys` of the account's. | The hub's key is the one credential, and nothing the person set up for the machine's own sshd changes what this server admits. |
| The host key stays on the machine; the hub holds only its public half. | A copy of the private half elsewhere is a second machine that can answer as this one. |
| Each instance has a host key of its own, and an account reads its own alone. Disabling an account deletes its run folder with its host key, and enabling it again makes a new one. The one machine host key of an earlier version, `ssh_server/host_key`, is deleted at the first apply, and a client takes each instance's key with its next `service` frame. | The server runs as the account and reads its host key, so each account holds the private half of what it serves; with one key per machine every enabled account could answer as every other one. |
| Removing an available account deletes its key; enabling it again makes a new one. | A key outlives no account the person took away. |
| **Rotate** on the Credentials page makes a new pair for that account: the state carries the new public half, which replaces the instance's one authorized key at the apply, and the `ssh` entry's `account_key_fingerprint` changes, so each client reads the new private half ([../../ui_behavior.md](../../ui_behavior.md), "The Credentials page"). | A key copied off a client stops opening the machine at once. |

## Sessions

| Request | The instance |
| --- | --- |
| a shell with a pseudo-terminal | starts the account's shell, `shell_path` of its row or its login shell, as a login shell on a pseudo-terminal on Linux and macOS, and on a pseudo console (ConPTY) on Windows, PowerShell when the row names none; the shell's and an `exec`'s `PATH` start with the launcher folders of the command line programs the account is enabled in, as a Terminal shell's do ([terminal.md](terminal.md)), read from `path_folders` as the shell or the command starts ("The `PATH` of a session") |
| `exec` | runs the command through the account's shell, `-c` on Linux and macOS and `-Command` for PowerShell, with its stdin, stdout, stderr and exit status |
| the `sftp` subsystem | serves the account's files with `pkg/sftp`, as the account |
| local port forwarding, `direct-tcpip` | dials the requested port when the destination is `127.0.0.1`, `::1` or `localhost`, and refuses every other destination |
| remote forwarding, X11, agent forwarding, any other subsystem | refused |

`direct-tcpip` is what VS Code's Remote-SSH and JetBrains Gateway need to
reach the server they start on the machine's loopback, and limiting it to
loopback keeps the server from being a way onto the machine's LAN.

## The `PATH` of a session

| Rule | Reason |
| --- | --- |
| The agent writes `path_folders` from the instance's `programs` in the state, the launcher folder of each program in the order of the command line programs, at the account's `account` step, and writes it only when its text changes, whole, as the run folder's other files are written. | A session reads the old list or the new one, never part of one. |
| The instance's service, its arguments and its environment do not change with the account's programs, and checking or unchecking a program starts no instance again. | Every open session of the account stays connected while the person checks or unchecks a program. |
| The server reads the file each time a shell or an `exec` starts and puts its folders at the front of that process's `PATH`, each once. A session already open keeps the `PATH` it started with, and a session started afterwards has the new folders, or none after the last program lets the account go. The `sftp` subsystem reads nothing. | A process's environment is fixed at its start, so the next session is the first that can carry a change. |
| A missing or unreadable file gives the session no folders, and the session starts. | A file the account removed from its own run directory costs the account its folders, never its sessions. |
| On Windows a shell or an `exec` starts from the account's environment as the registry holds it at that moment, built from the instance's own token as the Terminal's logon builds it, with the folders of `path_folders` at the front. The environment the instance's task started with is not passed on. | The account's user `PATH` names a program's launcher folder while the account is enabled in it, and the task's environment keeps that folder after the program lets the account go. |
| On Windows the server opens the file with delete sharing. | Windows fails a rename over a file that another process holds open without it, which would fail the agent's write. |

## The hub side

The state carries the module as `{instances: [{account, authorized_key,
shell_path, password, programs}]}`, `authorized_key` the account key's public
half in OpenSSH form, `shell_path` the account row's, `password` the
account's login, sent to a Windows machine alone, and `programs` the command
line programs the account is enabled in ([../../protocol.md](../../protocol.md),
"The account layer in the state"). `details` is `{instances: [{account,
port, is_running, code, host_key, host_key_fingerprint}]}`, `host_key` the
instance's public host key in OpenSSH form and `host_key_fingerprint` its
`SHA256:<base64>`, both empty before the key is made. An apply refuses `account_invalid`,
`account_duplicate`, `key_missing`, each naming the `account`, and
`account_unknown {account}`; on Windows `account_no_profile {account}` for an
account that never signed in, `credential_missing {account}` and
`credential_invalid {account}`.

Each account the module enables is one `ssh` entry, named by its account,
of the row `ssh_server_<device id>` in `apps`, which no page shows
([../../protocol.md](../../protocol.md), "Apps"). The `ssh` permission kind
reaches it. A desktop client forwards each entry at its local port while it
runs and takes the private key and the host key with the `service` frame
([../../client.md](../../client.md), "SSH for other programs"); a phone uses
none of it.

Its journal on Linux is the units' journal; on macOS each LaunchDaemon's
output names `/Library/Logs/Neutrino/agent/ssh_server_<account>.log`, and on
Windows the task appends to `ssh_server_<account>.log` under the log root.
