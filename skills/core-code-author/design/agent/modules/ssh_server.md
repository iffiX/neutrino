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
127.0.0.1:<port> --host-key <file> --authorized-key <file> --shell <shell>`,
the two files in `ssh_server/run/<account>/` under the state root, owned by
the account, the directory mode 700 and each file 600, written again at
every apply.

## Keys

| Key | Made by | Kept | Reaches |
| --- | --- | --- | --- |
| the host key, one per machine | the agent, at the module's first apply: Ed25519 in OpenSSH form | `ssh_server/host_key` under the state root, root's alone, and a copy in each instance's run directory | the hub as the public key in the module's `details`, and each client as the `service` frame's `host_key` |
| the account's key, one per machine and enabled account | the hub, when the account is first enabled: Ed25519 | the private half sealed under the vault's data key in `config/devices/<id>/ssh_server.json`, kept while the account is available | the agent as the public half, the instance's one authorized key; a client as the private half in the `service` frame, which the client writes under `~/.ssh/neutrino/` ([../../client.md](../../client.md), "SSH for other programs") |

| Rule | Reason |
| --- | --- |
| An instance admits public-key authentication by the account's key alone. It offers no password and no keyboard-interactive method, and it reads no `sshd_config` and no `authorized_keys` of the account's. | The hub's key is the one credential, and nothing the person set up for the machine's own sshd changes what this server admits. |
| The host key stays on the machine; the hub holds only its public half. | A copy of the private half elsewhere is a second machine that can answer as this one. |
| Removing an available account deletes its key; enabling it again makes a new one. | A key outlives no account the person took away. |
| **Rotate** on the Credentials page makes a new pair for that account: the state carries the new public half, which replaces the instance's one authorized key at the apply, and the `ssh` entry's `account_key_fingerprint` changes, so each client reads the new private half ([../../ui_behavior.md](../../ui_behavior.md), "The Credentials page"). | A key copied off a client stops opening the machine at once. |

## Sessions

| Request | The instance |
| --- | --- |
| a shell with a pseudo-terminal | starts the account's shell, `shell_path` of its row or its login shell, as a login shell on a pseudo-terminal on Linux and macOS, and on a pseudo console (ConPTY) on Windows, PowerShell when the row names none |
| `exec` | runs the command through the account's shell, `-c` on Linux and macOS and `-Command` for PowerShell, with its stdin, stdout, stderr and exit status |
| the `sftp` subsystem | serves the account's files with `pkg/sftp`, as the account |
| local port forwarding, `direct-tcpip` | dials the requested port when the destination is `127.0.0.1`, `::1` or `localhost`, and refuses every other destination |
| remote forwarding, X11, agent forwarding, any other subsystem | refused |

`direct-tcpip` is what VS Code's Remote-SSH and JetBrains Gateway need to
reach the server they start on the machine's loopback, and limiting it to
loopback keeps the server from being a way onto the machine's LAN.

## The hub side

The state carries the module as `{instances: [{account, authorized_key,
shell_path, password}]}`, `authorized_key` the account key's public half in
OpenSSH form, `shell_path` the account row's, and `password` the account's
login, sent to a Windows machine alone ([../../protocol.md](../../protocol.md),
"The account layer in the state"). `details` is `{host_key,
host_key_fingerprint, instances: [{account, port, is_running, code}]}`,
`host_key` the public host key in OpenSSH form and `host_key_fingerprint`
its `SHA256:<base64>`. An apply refuses `account_invalid`,
`account_duplicate`, `key_missing`, each naming the `account`, and
`account_unknown {account}`; on Windows `credential_missing {account}` and
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
