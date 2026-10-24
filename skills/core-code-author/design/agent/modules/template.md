# A device module

A device module is software the hub administers on a managed machine. One
manifest in the hub names where the software comes from, one runner in the
agent makes the machine match the hub's `want`, and one flow takes every
module from the manifest to a published entry: the install, the run and the
publish on this page. Each module's own page in this directory holds what
differs for it; the agent around the modules, its states and `want`, is
[agent.md](../../agent.md). The hub maintains the set of modules itself, and
a module the agent has no runner for reads `unsupported`.

## The four kinds

| Kind | Modules | What the machinery does for it | What the module supplies |
| --- | --- | --- | --- |
| Carried by the agent | Terminal; Remote desktop, which also detects a person's own AnyDesk and TeamViewer | installs nothing: the agent's package holds what each needs, the entry is in every machine's state with no recipe, and the four presses are refused `module_not_optional` | its configuration file, its runner, one applier per system where the systems differ ([terminal.md](terminal.md), [remote_desktop.md](remote_desktop.md)) |
| Installed from the system's own sources | File share, Containers, ZFS storage | installs and removes the packages the manifest names with the system's package manager, by the `system_package` recipe; on Windows and macOS the file share drives the SMB server the system has and installs nothing, and Containers installs Podman's msi or pkg and keeps its machine image, all from the hub's cache, by the `podman_machine` recipe | its configuration, its renderer and its applier ([file_share.md](file_share.md), [containers.md](containers.md), [zfs.md](zfs.md)) |
| A service with a system account of its own | Gitea | fetches the release binary into the hub's cache and sends it down `package {module}`; the agent makes the account and the service, and the publisher's layout holds on every system | its configuration, one applier per system, the rendered `app.ini` ([gitea.md](gitea.md)) |
| A program run as a person's account | VS Code, code-server, CloudCLI, Codeg | the whole flow of this page: the unpack under the state root, one account service per instance, the forwarder, the `web` entry, the shared router and the shared panel | `config.py`, `constants.py` and `hooks.py` ([vscode.md](vscode.md), [code_server.md](code_server.md), [cloudcli.md](cloudcli.md), [codeg.md](codeg.md)) |

## The manifest

`data/manifests/<module>.json` in the hub is the one record of where a
module's software comes from and how a machine checks for it. The hub
resolves the entry for a machine's platform and sends the recipe inside the
state, so the agent is handed conclusions and holds no manifest logic
([agent.md](../../agent.md), "One socket, everything on it").

| Key | Holds |
| --- | --- |
| `name`, `title`, `installer`, `source`, `version`, `license`, `corresponding_source`, `description` | the module's identity: its manifest name, the title every surface shows, its installer tier (`agent`, `platform` or `hub`), its publisher, the pinned version, the licence and the source the licence asks for |
| `platforms.<os>-<arch>` | one entry per platform the module runs on; a platform with no entry cannot run the module, and the Modules page greys it out ([protocol.md](../../protocol.md), "The modules section, one entry per module") |
| `kind`, `installer`, `version`, `source`, `license`, `corresponding_source` | on a platform entry: the branch's own identity, in place of the manifest's for that platform alone; a branch's `installer` is `builtin` or `hub` |
| `url`, `sha256`, `package_kind` | on a platform entry: the publisher's file, its digest and how it unpacks; the digest is the publisher's, so a mirror serving the same file is covered by the same pin, and the `digest` GitHub's API gives a release asset, or an OCI registry's blob digest of the same bytes, counts as the publisher's |
| `components` | on a platform entry, in place of one `url`: a list of `{name, url, sha256, package_kind, directory}`, with `cn_url` optional on each, one per file the module takes; a manifest with one file lists none |
| `verify` | the command whose success means the software is installed, run after the unpack and at every observation; on Windows `cmd.exe` runs it, and it is the program's quoted path with `--version`, such as `"%ProgramData%\Neutrino\agent\state\vscode\code.exe" --version`, which fails when the file is missing |
| `uninstall` | `{packages, post_uninstall, is_data_kept}`: what an uninstall removes beyond the module's own directory; every shipped manifest keeps the data |
| `cn_url` | the mirror's address of the same file, which a `cn` hub fetches from when the entry has one; a file no mirror carries has none, and the `cn` hub fetches `url` itself |

What an entry names follows its tier, the branch's own or the manifest's.
An `agent` manifest names no platform, no `url` and no recipe. A `platform`
entry names `packages`, with `pre_install` where the system needs a step
first, and never a download. A `hub` entry names a download, as one `url`
or as `components`, and never `packages` for a program run as an account;
it resolves a `version`, a `license` and a `corresponding_source`, its own
or the manifest's, and a branch of any other tier resolves none of the
three. The loader refuses a manifest outside these shapes, so a wrong file
fails the suite.

`branch_identity(manifest, entry)` in `modules/devices/manifests.py` is the
one place a branch's identity is resolved. The catalog's row
(`catalog.resolve_module`), the Modules page's list (`list_modules`), the
cache's file title (`artifact_title`) and the state's recipe, whose `kind`
is the resolved branch's (`desired_state._recipes`), all read it.
Containers is the manifest that uses it: its Linux branches name no
identity of their own and keep the manifest's `platform` tier and
`system_package` kind, so their recipes are byte for byte as before, and
its Windows and macOS branches name `installer` `hub`, `kind`
`podman_machine` and their own pinned Podman release
([containers.md](containers.md)).

## The install

A program run as a person's account is installed in steps that each have
one owner:

1. The hub's cache fetches each archive the entry names into the module
   cache, from `cn_url` on a `cn` hub where the entry has one.
1. The cache checks the bytes against the pinned `sha256` and keeps nothing
   that differs. It refuses a file larger than 2 GiB, and after it places a
   new file it deletes the files it held for the same module, component and
   platform.
1. The agent opens `package {module, component}` for each component, or
   `package {module}` for a module with one archive, and the hub streams the
   cached file down with its digest in the close
   ([protocol.md](../../protocol.md), "The stream layer"), writing `hub:
   sending <title>, <sent> / <total> MB to <device>` into the module's
   output as it goes.
1. The agent unpacks each archive under `agent/<module>/<directory>/` in
   the state root, `<directory>` being the component's `directory`; an
   archive whose members all sit under one top directory is unpacked
   without it, so the component's files sit directly under its directory.
   A module with one archive unpacks it where its own page says. The
   unpack is sealed: owned by the agent's own account, root or SYSTEM,
   readable and executable by every account, writable by none, and on no
   `PATH`.
1. The agent runs the manifest's `verify` command; its success is
   `installed`.

Four component kinds are never unpacked. The agent keeps the file as the
publisher's bytes under `agent/<module>/<directory>/` in the state root, and
the module takes it from there:

| `package_kind` | The file | What the module does with it |
| --- | --- | --- |
| `msi` | a Windows Installer package | installs it with `installers.install_msi` |
| `pkg` | a macOS installer package | installs it with `installers.install_pkg` |
| `tar_zst` | a zstd-compressed tar, such as Podman's machine image for WSL | passes its path to the module's program |
| `raw_zst` | a zstd-compressed disk image, such as Podman's machine image for applehv | passes its path to the module's program |

The cache checks the head of each before it keeps it: `msi` and `pkg` by the
magic bytes it already checks for the agent's own packages, and the two zstd
kinds by `28 b5 2f fd`.

A runtime a module needs, Node.js among them, is one of its components,
pinned in its own manifest. A module reads no other module's directory and
depends on no other module being installed, so two modules that need the
same runtime carry it twice.

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
system's own directories ([cloudcli.md](cloudcli.md)). What the first start
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
([protocol.md](../../protocol.md), "The services section, one entry per
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
([ui_behavior.md](../../ui_behavior.md), "The Modules page").

## What a module owns

| Where | A program run as an account owns | The other kinds own |
| --- | --- | --- |
| agent, `modules/<module>/` | `config.py`, `constants.py`, `hooks.py` | its config, constants, runner, renderer where it renders, and one applier per system |
| hub | one line in the description table and `data/manifests/<module>.json` | the same, and its own router under `routers/agent/` |
| panel | nothing of its own: `instances_panel.tsx` draws it from the description table | its own panel component |
| tests | the mirror of each file it owns, under `agent/tests/modules/<module>/` and the hub's mirrored directories ([tests.md](../../tests.md)) | the same |
| docs | one page per language under `docs/guide/` | the same |

## What `modules/shared/` holds

| File | One concept |
| --- | --- |
| `base.py` | what a module runner is: the contract every module's runner meets |
| `package.py` | installing, removing and verifying one downloaded-package module |
| `unpacked_tree.py` | a module's archive from the hub, unpacked under the module's own directory and sealed |
| `system_package.py` | installing and uninstalling modules the machine's package manager carries |
| `installers.py` | installing a downloaded package the way this machine installs things, one function per package kind: `install_msi` and `uninstall_msi` run `msiexec`, waiting for the Windows Installer mutex, trying once more on 1618 and taking 0 and 3010 as success; `install_pkg` runs `installer -pkg <file> -target /`; the agent's self-update uses the same functions, and the scripts it renders stay as they are |
| `http_forward.py` | what every forwarder in front of a module's page shares: the listener, the token check, the pass-through |
| `log_tail.py` | the last lines of a log file, and the mask every journal passes through |
| `subprocess_run.py` | running one command for a module applier, with its output kept |
| `windows_acl.py` | running `icacls.exe` for a module on Windows, the exit code read and the output dropped |
| `account_service/` | one file per system: write the service definition for an account, start, stop, remove and query it; its `__init__.py` also holds `write_if_changed`, which writes a file only when its text differs, so an apply that changes nothing rewrites no file |
| `instances.py` | the generic runner of the account-program kind, which drives the hooks of each module |

An applier on Windows runs its cmdlets through the agent's one PowerShell
host in `platforms/` ([agent.md](../../agent.md), "The PowerShell host on
Windows").

## Icons

Each module has one monochrome line glyph, drawn after the software's own
mark for identification alone, as `images/icons/modules/<module>.svg`. The
panel imports it by module name, and a module with no file of its own is
drawn with `generic.svg` in the same directory.

## Disk layout

| | Linux | macOS | Windows |
| --- | --- | --- | --- |
| The unpack | `/var/lib/neutrino/agent/<module>/<component>/` | `/Library/Application Support/Neutrino/agent/state/<module>/<component>/` | `%ProgramData%\Neutrino\agent\state\<module>\<component>\` |
| The per-account data | `~/.local/share/neutrino/agent/<module>/` | `~/Library/Application Support/Neutrino/agent/<module>/` | `%LOCALAPPDATA%\Neutrino\agent\<module>\` |
| The service definition | the unit `neutrino_<module>@<account>.service` | `/Library/LaunchDaemons/com.neutrino.<module>.<account>.plist` | the scheduled task `neutrino_<module>_<account>` |
| The log | the unit's journal | `/Library/Logs/Neutrino/agent/<module>_<account>.log`, or the file the module names | `<account>.log` beside the program, or the file the module names |
