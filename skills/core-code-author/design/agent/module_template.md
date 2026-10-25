# A device module

A device module is software the hub administers on a managed machine. One
manifest in the hub names where the software comes from, the runner named in
its platform entry makes the machine match the hub's `want`, and one flow
takes every module from the manifest to a published entry: the install on
[module_install.md](module_install.md), the run and the publish on this
page. Each module's own page under `modules/` holds what differs for it;
the agent around the modules, its states and `want`, is
[agent.md](../agent.md). The hub maintains the set of modules itself, and
a module the agent has no runner for reads `unsupported`.

## How a module runs

| Kind | Modules and their `runner` | What the machinery does for it | What the module supplies |
| --- | --- | --- | --- |
| Carried by the agent | Terminal, `terminal`; Remote desktop, `remote_desktop`, which also detects a person's own AnyDesk and TeamViewer | runs the module's applier; the four presses are refused `module_not_optional` | its configuration file, its runner, one applier per system where the systems differ ([modules/terminal.md](modules/terminal.md), [modules/remote_desktop.md](modules/remote_desktop.md)) |
| Software the module configures | File share, `samba` on Linux and `samba_native` on Windows and macOS; Containers, `podman` on Linux and `podman_machine` on Windows and macOS; ZFS storage, `zfs` | renders the module's files and drives the system's own service; on Windows and macOS the file share drives the system's SMB server, and Containers runs a Podman machine of one account | its configuration, its renderer and its applier ([modules/file_share.md](modules/file_share.md), [modules/containers.md](modules/containers.md), [modules/zfs.md](modules/zfs.md)) |
| A service with a system account of its own | Gitea, `gitea` | makes the account and the service, and the publisher's layout holds on every system | its configuration, one applier per system, the rendered `app.ini` ([modules/gitea.md](modules/gitea.md)) |
| A program run as a person's account | VS Code, `vscode`; code-server, `code_server`; CloudCLI, `cloudcli`; Codeg, `codeg` | the whole flow of this page: one account service per instance, the forwarder, the `web` entry, the shared router and the shared panel | `config.py`, `constants.py` and `hooks.py` ([modules/vscode.md](modules/vscode.md), [modules/code_server.md](modules/code_server.md), [modules/cloudcli.md](modules/cloudcli.md), [modules/codeg.md](modules/codeg.md)) |
| Container images | Hermes WebUI, `container` | runs the images as hub containers on the Containers module, one network per module, and the forwarder where the module has a page | its images in the manifest, the containers it composes on the hub, and its `hooks.py` where it has a page or a step after its first start ([module_install.md](module_install.md), "From container images", [modules/hermes_webui.md](modules/hermes_webui.md)) |

`runner` names the agent runner, and an agent that has no runner of that
name reports the module `unsupported`. Where a module's software comes
from, its manifest, its install and what its uninstall removes are
[module_install.md](module_install.md). A runner and an install method are
independent: Containers runs one way on every system and installs by two
methods.

## The run

One instance runs per account the configuration names. The account service
layer, `modules/shared/account_service/` with one file per system, writes
the service definition, starts, stops, removes and queries it:

| System | The service |
| --- | --- |
| Linux | the unit `neutrino_<module>@<account>.service` with `User=<account>`, its output in the unit's journal |
| macOS | the LaunchDaemon `com.neutrino.<module>.<account>` with `UserName`, its output where the module says, and `AbandonProcessGroup` where the module asks for it, so the processes the program started keep running when the job stops |
| Windows | a scheduled task under the account's login, the one the Credentials page holds for the instance, started at boot with no time limit and a limited token; a stop ends the task's whole process tree |

The service's environment is written from scratch, with nothing inherited
from a login profile or a version manager, and the module's `hooks.py`
composes it: the command line, the variables, the `umask` the module asks
for, and where stdout and stderr go. The runtime the module carries is
first on `PATH`, then the account's `~/.local/bin` and `~/bin`, then the
system's own directories ([cloudcli.md](modules/cloudcli.md)). What the first start
does, a registration or a first-run file, is the module's hook as well.

The instance listens on loopback alone, and the agent's forwarder,
`modules/shared/http_forward.py`, is in front of it on `127.0.0.1` at
the configured port, where the agent's end of a `connect` stream reaches it.
The hub generates a token from the instance's secret on every `service` ask,
`base64url(expiry || nonce || HMAC-SHA256(secret, expiry || nonce))` with
`expiry` 60 seconds ahead, and the forwarder checks it on the device with no
call to the hub and spends it once. The module's one rule for turning that
token into a login, a cookie of the forwarder's own, the page's own login
state or a value in the browser's storage, is its hook, and every module's
forwarder answers 401 to a request carrying neither a token nor the login.
A module whose page admits the browser by a token of its own, VS Code,
names no rule, and its server takes the token itself.

The per-account data, what the program writes for that account, is under
the account's own Neutrino tree, `~/.local/share/neutrino/agent/<module>/` on
Linux, `~/Library/Application Support/Neutrino/agent/<module>/` on macOS and
`%LOCALAPPDATA%\Neutrino\agent\<module>\` on Windows, made as the account.
An uninstall removes the service definitions, the forwarder's records and
the unpack under the state root, and keeps the per-account data directory
and every file in the account's home, as `is_data_kept` says in every
shipped manifest.

## The publish

Each instance a running module serves is one `web` entry in the services
section, `<module>_<device id>_<account>`, titled `<Title> (<account>)`, with
`is_token_required: true` and `description_code` `<module>_module`
([protocol.md](../protocol.md), "The services section, one entry per
published service"). The entry exists while the device reports the instance
running, and a client opens it at its own forward's address with the token
the `service` stream hands.

## The hub side

The hub describes every module once, in the description table
`modules/devices/module_table.py`: its kind, its configuration file name under
`config/devices/<id>/`, the fields the vault seals in it, the published
entry's `description_code`, and the panel kind the Modules page draws. The
four programs run as an account share one router,
`routers/agent/module_instances.py`, which serves `GET
/api/agent/module/<module>` and `POST /api/agent/module/<module>/set` for
each from that table; VS Code's terms acceptance stays in
`module_vscode_terms.py`. Their secrets, each instance's token secret and
CloudCLI's password, are generated the first time and kept sealed under the
vault's data key in `config/devices/<id>/<module>.json`, and the state
carries them opened. The panel draws the four with one `instances_panel.tsx`
([ui_behavior.md](../ui_behavior.md), "The Modules page").

## What a module owns

| Where | A program run as an account owns | The other kinds own |
| --- | --- | --- |
| agent, `modules/<module>/` | `config.py`, `constants.py`, `hooks.py` | its config, constants, runner, renderer where it renders, and one applier per system |
| hub | one line in the description table and `data/manifests/<module>.json` | the same, and its own router under `routers/agent/` |
| panel | nothing of its own: `instances_panel.tsx` draws it from the description table | its own panel component |
| tests | the mirror of each file it owns, under `agent/tests/modules/<module>/` and the hub's mirrored directories ([tests.md](../tests.md)) | the same |
| docs | one page per language under `docs/guide/` | the same |

A container module keeps its manifest, its line in the description table and
the hub's composition of its containers. Where it has a page or a step after
its first start, it also keeps `config.py`, `constants.py` and `hooks.py`
under `modules/<module>/`, which the `container` runner calls.

## What `modules/shared/` holds

| File | One concept |
| --- | --- |
| `base.py` | what a module runner is: the contract every module's runner meets |
| `package.py` | installing, removing and verifying one `hub` module, and switching it to another version |
| `unpacked_tree.py` | an archive from the hub, unpacked under the module's own directory and sealed |
| `system_package.py` | installing and uninstalling the packages of a `system` entry with the machine's package manager |
| `installers.py` | installing a downloaded package the way this machine installs things, one function per artifact kind: `install_msi` and `uninstall_msi` run `msiexec`, waiting for the Windows Installer mutex, trying once more on 1618 and taking 0 and 3010 as success; `install_pkg` runs `installer -pkg <file> -target /`; the agent's self-update uses the same functions, and the scripts it renders stay as they are |
| `source_fetch.py` | probing and ranking the sources of an image, an npm registry or a host an npm setting names ([module_install.md](module_install.md), "Choosing a source") |
| `http_forward.py` | what every forwarder in front of a module's page shares: the listener, the token check, the pass-through |
| `log_tail.py` | the last lines of a log file, and the mask every journal passes through |
| `subprocess_run.py` | running one command for a module applier, with its output kept |
| `windows_acl.py` | running `icacls.exe` for a module on Windows, the exit code read and the output dropped |
| `account_service/` | one file per system: write the service definition for an account, start, stop, remove and query it; its `__init__.py` also holds `write_if_changed`, which writes a file only when its text differs, so an apply that changes nothing rewrites no file |
| `instances.py` | the generic runner of the account-program kind, which drives the hooks of each module |

An applier on Windows runs its cmdlets through the agent's one PowerShell
host in `platforms/` ([agent.md](../agent.md), "The PowerShell host on
Windows").

## Icons

Each module has one monochrome line glyph, drawn after the software's own
mark for identification alone, as `images/icons/modules/<module>.svg`. The
panel imports it by module name, and a module with no file of its own is
drawn with `generic.svg` in the same directory.

## Disk layout

| | Linux | macOS | Windows |
| --- | --- | --- | --- |
| The unpack | `/var/lib/neutrino/agent/<module>/<directory>/` | `/Library/Application Support/Neutrino/agent/state/<module>/<directory>/` | `%ProgramData%\Neutrino\agent\state\<module>\<directory>\` |
| The per-account data | `~/.local/share/neutrino/agent/<module>/` | `~/Library/Application Support/Neutrino/agent/<module>/` | `%LOCALAPPDATA%\Neutrino\agent\<module>\` |
| The service definition | the unit `neutrino_<module>@<account>.service` | `/Library/LaunchDaemons/com.neutrino.<module>.<account>.plist` | the scheduled task `neutrino_<module>_<account>` |
| The log | the unit's journal | `/Library/Logs/Neutrino/agent/<module>_<account>.log`, or the file the module names | `<account>.log` beside the program, or the file the module names |
