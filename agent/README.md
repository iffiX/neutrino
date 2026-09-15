# neutrino_agent

The device agent for [neutrino](https://github.com/iffiX/neutrino) is one root
service on a managed Linux machine, with one socket open to the hub. It makes
every module the hub's state names match the `want` that state gives it, reports
what is true on the machine every few seconds, and runs the commands the hub
opens over the same socket. Sharing this machine's desktop is decided on
the machine, and every report declares it upward.

Its code is Python standard library only. The package includes the interpreter
that runs it and the RustDesk host it configures, so it installs on a machine
with no Python and uses none the machine already has. Linux is the only
platform, with `neutrino_agent/platforms/linux.py` as the one implementation of
the platform contract. Everything a person does with what the hub publishes is
`neutrino_client`, a separate package in that person's own session.

## Installing

The hub installs it: the **Devices** page signs in over SSH and runs the
installer. On a machine the hub cannot reach first, install the native package
for that machine's family and paste an enrollment link, which **Add by link**
on the same page shows and which is valid for five minutes:

```bash
sudo apt install ./neutrino-agent_<version>_amd64.deb      # Debian family
sudo dnf install ./neutrino-agent-<version>-1.x86_64.rpm   # Fedora family
sudo nagent join '<enroll-link>'
```

The package enables and starts `neutrino_agent.service`. A machine that has
joined no hub runs the same service and serves the same control socket, with no
binding to report.

## The commands

`nagent` is the command line on the machine. Every subcommand except
`--version` needs root; run as another account, one prints its reason and the
`sudo` line, then exits with status 2. `status`, `sync` and the two `rdp`
actions reach the running service over its control socket.

| Command              | What it does                                                                                                                                                                      |
| -------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `nagent join <link>` | Spends the link's ticket at the hub, writes the binding and starts the service. With the link omitted it prompts for one; `--yes` replaces an existing binding.                   |
| `nagent leave`       | Posts the binding to the hub and deletes it. The agent and its service stay, and the machine joins again with a fresh link.                                                       |
| `nagent status`      | Prints the version, the hub this machine is bound to, the service state and whether the socket is up. An error line names the refusal and the step after it.                      |
| `nagent sync`        | Sends this machine's report to the hub now.                                                                                                                                       |
| `nagent rdp start`   | Shares this desktop at the seat password the hub set. `--user <account>` names whose desktop; with it omitted, the account that invoked `sudo`, or the one account at the screen. |
| `nagent rdp stop`    | Stops sharing this desktop.                                                                                                                                                       |
| `nagent run`         | Runs the agent in the foreground, which is what the systemd unit starts.                                                                                                          |
| `nagent --version`   | Prints the package version.                                                                                                                                                       |

## The socket to the hub

The agent opens one WebSocket to the hub over TLS pinned to the SHA-256
fingerprint in the enrollment link, checked on every connection before request
bytes leave the machine, and it reconnects after the socket drops. It sends a
`hello` when the socket opens, then a `report` every few seconds and at once
when something changed. The hub sends the `state` whenever its own copy of it
changes, and opens its streams on the same socket.

Every action is a stream: its `open` is the request, its `close` is the result,
and the kind is the whole vocabulary.

| Opened by | Kind      | Arguments and result                                                                                                                        |
| --------- | --------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| hub       | `shell`   | `{cols, rows}`, or `{module: podman, container}`; terminal bytes both ways, closed with `{exit_code}`                                       |
| hub       | `file`    | one operation `{op, path, ...}`, where `op` is `list`, `download`, `upload`, `rename`, `remove`, `directory_create` or `directory_download` |
| hub       | `command` | `{module, verb, ...args}`, closed with `{exit_code, output, result}`                                                                        |
| agent     | `log`     | `{module}` for an install or an uninstall, output up line by line, closed with `{state}`                                                    |
| agent     | `package` | `{module}` for a module's package bytes, `{}` for the agent's own; the close's params hold the `sha256`                                     |

The verbs a `command` names for the agent itself are the closed set
`AGENT_VERBS` in `neutrino_agent/core/commands.py`: `reboot`, `shutdown`,
`reinstall`, `resize`, `kill`, `remote_desktop_read` and
`remote_desktop_password_set`. No verb runs a shell string. Every other module's
verbs are its runner's, spelled without the module's name, because the `module`
field is the prefix. The frames, the credit window and the close codes are in
[the protocol design page](../skills/core-code-author/design/protocol.md).

Installing a module follows from the `want` the state gives it, one of
`absent`, `installed`, `stopped` and `running`. The agent makes each mentioned
module's actual state equal that word, and leaves a module the state passes over
alone, observed and reported all the same.

## Where its files are

| Path                                  | Holds                                                                                            |
| ------------------------------------- | ------------------------------------------------------------------------------------------------ |
| `/etc/neutrino/agent/agent.json`      | the binding: `{gateway_url, id, token, fingerprint, machine_id}`, mode 0600                      |
| `/etc/neutrino/agent/state.json`      | what the machine decided for itself                                                              |
| `/etc/neutrino/agent/desired.json`    | the last state the hub sent                                                                      |
| `/etc/neutrino/agent/credentials/`    | the desktop's seat password, in its own root-only file                                           |
| `/var/lib/neutrino_agent/configured/` | one mark per module the hub has configured, which tells `installed` from `stopped` and `running` |
| `/var/lib/neutrino_agent/packages/`   | a package coming down a `package` stream, until its digest is checked                            |
| `/run/neutrino_agent/agent.sock`      | the control socket, 0600 under a 0700 directory, so the kernel admits root alone                 |
| `/opt/neutrino_agent/`                | the interpreter and the agent's own code                                                         |
| `/usr/lib/neutrino_agent/rustdesk/`   | the desktop host the package includes                                                            |

## The package tree

| Where                          | Job                                                                                                       |
| ------------------------------ | --------------------------------------------------------------------------------------------------------- |
| `neutrino_agent/cli/`          | The `nagent` subcommands, one file each, and the wording of every code a surface prints                   |
| `neutrino_agent/core/`         | The binding, the socket session, the commands, the module engine and the desired state the engine applies |
| `neutrino_agent/streams/`      | One handler per stream kind, each on a thread of its own                                                  |
| `neutrino_agent/modules/`      | One runner per module: Samba, Gitea, Podman, ZFS, plus the package install and removal every runner uses  |
| `neutrino_agent/platforms/`    | One class per platform behind one contract; `linux.py` is the only implementation                         |
| `neutrino_agent/rdp/`          | The desktop share and what it declares upward                                                             |
| `neutrino_agent/control/`      | The root-only Unix socket the running agent serves, and the client side `nagent` uses                     |
| `neutrino_agent/constants.py`  | Every fixed value of the protocol and the paths                                                           |
| `neutrino_agent/exceptions.py` | The package's own exception kinds                                                                         |

The design behind the tree is in
[the agent design page](../skills/core-code-author/design/agent.md).

## Running the tests

```bash
pip install -e agent
pip install -e "hub[dev]"
black --check agent
cd agent && pytest -q
```

The `hub[dev]` install is where `black` and `pytest` come from; the agent itself
declares no dependency. The tests mirror the package: `tests/<area>/test_<module>.py`
for each source file, plus `tests/packaging/` over the package builds.

## Building the packages

```bash
python3 agent/packaging/build_deb.py --output-dir dist/ --architecture amd64
python3 agent/packaging/build_rpm.py --output-dir dist/ --architecture x86_64
```

Each package is fixed to one architecture, because it includes an interpreter
and a compiled desktop host, so each build runs in a container of the family and
the machine it is for. `packaging/build_release.py` drives that matrix for
`amd64` and `arm64`. The hub's own package build seeds its cache from the agent
packages already built, so a hub and the agents it installs are one version.

## Working on this repo

Read [`AGENTS.md`](../AGENTS.md) first: it indexes the standard and says which
document settles what. [`skills/core-code-author/`](../skills/core-code-author/SKILL.md)
holds the detail.
