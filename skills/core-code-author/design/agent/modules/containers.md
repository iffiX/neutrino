# The Containers module

The `podman` module is Containers: the Podman containers a machine runs as
systemd units, declared on the hub in one configuration for every system. On
Linux the machine's own Podman runs them as root. On Windows and macOS they
run inside a Podman machine, a Linux virtual machine of one account on the
computer, where Podman runs them as root
([agent.md](../../agent.md), "Which modules each system runs"). Its entry in
the state, its verbs and its routes are in
[protocol.md](../../protocol.md), "The modules section, one entry per
module".

| | Linux | Windows | macOS |
| --- | --- | --- | --- |
| The runner | `PodmanModuleRunner`, kind `system_package` | `PodmanMachineModuleRunner`, kind `podman_machine` | `PodmanMachineModuleRunner`, kind `podman_machine` |
| Podman | the distribution's, 3.4 or later | 6.1.4 for amd64, pinned in `podman.json`, from the hub's cache, on WSL 2 | the release `podman.json` pins, a 6.x for arm64 and a 5.8.x for amd64, from the hub's cache |
| The systemd that runs the units | the machine's own | the Podman machine's | the Podman machine's |
| Who runs Podman | root | root inside the machine; the machine's own commands run as the account | as on Windows |

## Linux

`PodmanModuleRunner`, under `agent/neutrino_agent/modules/podman/`, is a
`system_package` module: its recipe names `podman` and `podman-docker`, and
the machine's package manager installs them.

| Rule | Reason |
| --- | --- |
| From Podman 4.4 a declared container is a Quadlet file, `/etc/containers/systemd/<name>.container`; below 4.4 it is a plain unit, `/etc/systemd/system/<name>.service`, that runs `podman run`. | A Podman older than 4.4 reads no `.container` file, and the supported distributions have 3.4 and later ([min_support.md](../../min_support.md)). |
| Every rendered file starts with the generated marker, and an apply removes only marked files. | A file a person wrote beside them is theirs. |
| The registry mirrors are one drop-in, `/etc/containers/registries.conf.d/99_neutrino_mirrors.conf`. | The distribution's own `registries.conf` stays as it is. |
| The module's `is_active` is the state of `podman.socket`. | Podman has no daemon, and its API socket is the engine. |
| A declared container starts and stops through `systemctl`, and one a person started by hand through `podman` itself. | systemd supervises a declared container; a hand-started one has no unit. |

The report reads `podman ps -a --format json` and `podman inspect`, and a
container's journal is `journalctl -u <name>.service`.

The Podman report gives each container's `host_bindings` as one `{address,
port, protocol, detected}` per published host port, on TCP and UDP alike,
`address` empty for every address and `detected` as "Services of a
container" says; `published_ports` reads the ports the machine publishes,
per protocol, from it ([agent.md](../../agent.md), "The connect stream").

## Windows and macOS

`PodmanMachineModuleRunner`, `name` `podman` and kind `podman_machine`, is
the second runner in the same directory, and the engine builds it under
`hub_packages` on Windows and macOS. It renders the Linux files with the
Linux renderers, `PodmanQuadletRenderer` and `PodmanRegistriesRenderer`, and
writes them inside the Podman machine. Podman inside the machine is the
machine image's own, always 4.4 or later, so every declared container is a
Quadlet file there. In this section "the machine" is the Podman machine and
"the computer" is the Windows or macOS system the agent runs on;
`C:\Users\<account>` means the account's profile, the home the
platform layer resolves from `ProfileList`.

### What the install puts on the computer

The manifest's Windows and macOS branches are `installer` `hub`, each with
its own identity fields ([template.md](template.md), "The manifest"). The
hub's cache fetches each component and sends it down `package {module:
podman, component}`. The agent keeps each file as the publisher's bytes
under `podman/<component>/` in the state root and unpacks none.

| Component | Windows amd64 | macOS |
| --- | --- | --- |
| `wsl` | the WSL msi, pinned at 3.0.3, `package_kind` `msi` | none |
| `installer` | Podman's msi, pinned at 6.1.4, `package_kind` `msi` | Podman's pkg at the branch's version, `package_kind` `pkg` |
| `image` | the machine image for WSL, `podman-machine.x86_64.wsl.tar.zst`, `package_kind` `tar_zst` | the machine image for applehv, `package_kind` `raw_zst` |

| Step | What the agent runs, as SYSTEM or root | Reason |
| --- | --- | --- |
| Windows features | `dism.exe /English /Online /Enable-Feature /FeatureName:<feature> /All /NoRestart` for `VirtualMachinePlatform` and for `Microsoft-Windows-Subsystem-Linux`; an exit other than 0 and 3010 ends the install `windows_feature_failed {feature, exit_code}` | WSL 2 needs both, on Windows Home too |
| WSL | the WSL msi through `installers.install_msi`, skipped when Windows Installer's product list holds the WSL package at the pinned version or newer | Podman's msi installs no WSL, and the system's own `wsl.exe` reports WSL as not installed until it is |
| Podman on Windows | `msiexec /i <msi> /qn /norestart /l*v <log> ALLUSERS=1 MACHINE_PROVIDER=wsl` through `installers.install_msi` | `ALLUSERS=1` puts Podman in `C:\Program Files\Podman` and on the computer's `PATH`, where SYSTEM and every account find it |
| Podman on macOS | `installer -pkg <file> -target /` through `installers.install_pkg` | the system's installer is the one that installs a pkg |

A failed msi or pkg ends the install `podman_install_failed {component,
exit_code}`.

| Rule | Reason |
| --- | --- |
| A dism exit of 3010 is a restart owed: the agent writes the reboot mark, holding the computer's boot time, and while the boot time is the mark's, or the key `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending` exists, the module reports `installing` with `{code: reboot_required}`. | dism reports a feature `Enabled` before the restart, so the feature's state cannot show that a restart is owed. |
| The agent never restarts the computer. A person does, with the tab's **Restart now** or the device's **Reboot**. | A restart closes every program open on the computer. |
| While the restart is owed, an apply raises `ModuleInstallPending`, the agent keeps no tried hash for it, and the state is applied again every 30 seconds under the same hash ([agent.md](../../agent.md), "Status is typed"). | The install goes on after the restart with no press. |

### The account and its machine

The Run settings are the configuration's `machine`, `{account, cpus,
memory_gib, disk_gib}`, with the account's `password` added by the hub for a
Windows machine. A 0 CPUs is half the computer's logical processors and a 0
memory is 2 GiB, Podman's defaults. A 0 disk is 100 GiB at an init, and
leaves the disk of a machine taken over as it is.

| Rule | Reason |
| --- | --- |
| The machine is the account's default one, `podman-machine-default`. The agent creates it when the account has none, with `podman machine init --rootful --image <kept image>`, and takes over one that exists, with `podman machine set --rootful` on the stopped machine when it is not rootful. | The person's own `podman ps` as that account shows the containers the panel declares. |
| Every `podman machine` and `wsl` command runs as the account, through the platform's `run_as_account`: the one-shot task under the account's login on Windows, a child with the account's uid on macOS. The agent writes `.wslconfig` as the account too. | WSL refuses SYSTEM with `WSL_E_LOCAL_SYSTEM_NOT_SUPPORTED`, `podman machine` refuses root on macOS, and the account keeps owning its own files. |
| The init reads the image the hub sent, and runs inside the apply, about 40 seconds on Windows. | The hub's cache is the one source of the machine's bytes, on a `cn` hub too. |
| On WSL the agent resizes the disk right after the init and before the first start, with `wsl --manage podman-machine-default --resize <size>GB`. | WSL creates a 1 TB disk whatever size Podman asks for. |
| On WSL the CPUs and the memory are `processors=<n>` and `memory=<n>GB` under `[wsl2]` in the account's `%USERPROFILE%\.wslconfig`, a 0 written as the default's number; the agent makes the file or the section when it is missing, changes these two keys and keeps every other line. | WSL ignores Podman's numbers and reads this file, which is the person's own and applies to every WSL system of the account. |
| A change of CPUs, memory or disk in the configuration, against the last one applied, runs `wsl --shutdown` as the account on WSL, which stops every WSL system of that account, then resizes the disk when it grew, and starts the machine before the apply writes into it. The panel warns before the apply. | WSL reads `.wslconfig`, and resizes a disk, only while none of the account's WSL systems runs; a person's own edit of the file is theirs and restarts nothing. |
| On macOS a change runs `podman machine set --cpus --memory --disk-size` on the stopped machine, then starts it. | Podman sets an applehv machine's resources itself. |
| A disk other than 0 and smaller than the machine's disk now, its virtual size, is refused `machine_disk_shrink {disk_gib, current_gib}`; CPUs past the computer's logical processors `machine_cpus_invalid {cpus, max}`, memory past its size `machine_memory_invalid {memory_gib, max}`, an empty account `machine_account_missing`, and an account the computer does not have `account_unknown {account}`. | Shrinking a disk can cut the data on it; WSL shrinks one when asked, so the rule is the module's. |
| A new account stops the old account's machine and removes its keeper before the new one starts; the old machine, its images and named volumes and the old account's `.wslconfig` stay as they are. | Two running machines publish the same ports on `127.0.0.1`, and the old machine's data is the person's. |

### The keeper

The keeper starts the machine at boot, with nobody signed in, and starts it
again when it stops. It is an account service
([template.md](template.md), "The run"): the scheduled task
`neutrino_podman_<account>` at startup under the account's login on Windows,
and the LaunchDaemon `com.neutrino.podman.<account>` with `UserName` on
macOS.

| Rule | Reason |
| --- | --- |
| The keeper's script loops by itself: every 30 seconds it checks the machine's state and starts the machine when it is not running. | Task Scheduler did not start the task again after its program exited, whatever its restart settings. |
| Before each start on Windows it deletes `%TEMP%\podman\podman-machine-default-api.sock`. | A file left by a restart with the machine running keeps `win-sshproxy.exe` from binding at the next start. |
| A start that fails is followed by `podman machine stop`, the same deletion, and one more start. | Windows reserves a port range at boot that can hold the machine's ssh port; Podman finds the conflict at the next start and moves the port. |

A published port answers about 30 seconds after a boot with nobody signed
in. The machine keeps running when the keeper's task stops and when the
account signs in or out.

### Reads and writes

| Path | What runs | When | Cost on Windows |
| --- | --- | --- | --- |
| Read | the agent itself, as SYSTEM or root: `podman --url ssh://root@127.0.0.1:<port>/run/podman/podman.sock --identity <key>` with `ps -a --format json`, `inspect` and `info` | every report | median 291 ms |
| Root script | one root script on standard input, `podman machine ssh --username root podman-machine-default sh -s`, run as the account | an apply, a declared container's start, stop or restart, a container's journal | about 3 s |
| Shell | the agent, as SYSTEM or root: the read's command with `exec -it <container>` and the container's shell, on the pseudo console or pseudo-terminal a shell takes | a container's `shell` stream | |

| Rule | Reason |
| --- | --- |
| `<port>` is read once per report, before its first command, from `SSH.Port` in the machine's settings file, `C:\Users\<account>\.config\containers\podman\machine\wsl\podman-machine-default.json` on Windows and `~/.config/containers/podman/machine/applehv/podman-machine-default.json` on macOS. | A start can move the port. |
| `<key>` is the account's machine key, `C:\Users\<account>\.local\share\containers\podman\machine\machine` on Windows and `~/.local/share/containers/podman/machine/machine` on macOS, read where it is. | SYSTEM and root read the account's profile, and a copy is a second secret to keep. |
| The read uses the ssh URL on both systems. | As SYSTEM, Podman's Windows client rejects both an `npipe:` URL and the machine's `unix://` path. |
| A container a person started by hand starts, stops and restarts through the read's command, as SYSTEM or root. | Linux drives such a container through `podman` itself, and it has no unit in the machine. |
| The read output goes through the Linux reader, given this command in place of `podman`. | One parser for `ps` and `inspect` on every system. |
| The module's `is_active` is whether the machine answers the read. | The machine's Podman is the engine there, as `podman.socket` is on Linux. |
| The script holds every file base64-encoded, compares each with the file in the machine, writes the changed ones, removes the stale marked files, runs `systemctl daemon-reload`, restarts the changed units and prints one `changed: <file>` line per change. | Each call costs about 3 seconds, so an apply is one call. |

### Files in the machine

| Rule | Reason |
| --- | --- |
| The Quadlet files are in `/usr/share/containers/systemd/` in the machine. | In the WSL machine `/etc/containers` is the account's `%APPDATA%\containers` on Windows, mounted after systemd's generators run, so a file in `/etc/containers/systemd/` starts nothing at boot. |
| Every `.container` file the module renders for the machine has `CgroupsMode=enabled` under `[Container]`, added by the renderer when it renders for a machine, and a Linux file has no such line. | The machine runs systemd under cgroupfs, where Quadlet's default split mode fails with "controller pids is not available", and the Linux files keep their bytes. |
| The mirrors drop-in is `/etc/containers/registries.conf.d/99_neutrino_mirrors.conf` in the machine. | Podman reads it at a pull, after the mount, so the account's Windows folder under that path serves. |
| macOS uses the same Quadlet directory, the same drop-in path and the same cgroups line. | One code path writes into every Podman machine. |

### Volumes

A folder of the computer in a volume is written in the system's own form,
`C:\data:/data` on Windows and `/Users/me/data:/data` on macOS. A named
volume is written as on Linux and is on the machine's disk.
`modules/podman/machine_paths.py`, pure, translates the folder:

| System | Folder | In the machine |
| --- | --- | --- |
| Windows | a folder on a fixed drive, such as `C:\data` | `/mnt/c/data`, WSL's own mount of the drive |
| macOS | a folder under `/Users`, `/private` or `/var/folders` | the same path, which Podman shares into the machine |
| either | any other folder, a UNC path among them | refused `volume_not_shared {name, volume}` |

Such a folder has no path inside the machine, so the apply refuses it
before the container fails to start on it.

### Ports

A published port answers on the computer's `127.0.0.1`: on Windows through
WSL's localhost forwarding, a `wslrelay.exe` listener of the account's, and
on `127.0.0.1` alone, never on `::1` or a LAN address; on macOS through
Podman's own forwarder. The agent's `connect` stream dials `127.0.0.1` for
every container port on these systems ([agent.md](../../agent.md), "The
connect stream"), and a machine on the LAN reaches a container through the
hub. The lab proved a TCP port through WSL's forwarding; a UDP port through
it is not proven.

### The journal

A container's journal is `journalctl -u <name>.service` in the machine, run
by the root script. The module's journal reads the keeper's log first and
then the agent's own lines that name the module, as every module on Windows
and macOS reads its sources ([agent.md](../../agent.md), "Which modules
each system runs"). The keeper's log is `<account>.log` under `podman\` in
the state root on Windows, made by the agent with modify granted to the
account, and `/Library/Logs/Neutrino/agent/podman_<account>.log`, the
LaunchDaemon's `StandardOutPath` and `StandardErrorPath`, on macOS.

### The uninstall

The uninstall runs in the order of this table, so the root script reaches
the machine while it still runs:

| What | After the uninstall |
| --- | --- |
| The declared containers, their files in the machine and the mirrors drop-in | stopped and removed, by one root script |
| The keeper, its script and its log | removed, so nothing starts the machine again |
| The machine | stopped, and kept with its disk, images and named volumes in the account's profile; on Windows its WSL system stays registered |
| Podman | uninstalled: the msi by `installers.uninstall_msi`, the pkg's files and its receipt on macOS |
| The kept components and the reboot mark | removed from the state root |
| The account's `.wslconfig`, WSL and both Windows features | kept |

A reinstall finds the account's default machine and takes it over, and the
hub's configuration brings back the containers with their volumes, as
`is_data_kept` says. WSL serves the person's other WSL systems, and turning
a feature off owes another restart.

### Disk layout

| | Windows | macOS |
| --- | --- | --- |
| Podman | `C:\Program Files\Podman\` | `/opt/podman/` |
| The kept components | `%ProgramData%\Neutrino\agent\state\podman\<component>\` | `/Library/Application Support/Neutrino/agent/state/podman/<component>/` |
| The reboot mark | `%ProgramData%\Neutrino\agent\state\podman\reboot_mark` | none |
| The keeper's script | `%ProgramData%\Neutrino\agent\state\podman\keeper.cmd` | `/Library/Application Support/Neutrino/agent/state/podman/keeper.sh` |
| The keeper | the scheduled task `neutrino_podman_<account>` | `/Library/LaunchDaemons/com.neutrino.podman.<account>.plist` |
| The keeper's log | `%ProgramData%\Neutrino\agent\state\podman\<account>.log` | `/Library/Logs/Neutrino/agent/podman_<account>.log` |
| The machine | `C:\Users\<account>\.local\share\containers\podman\machine\wsl\`, its disk `ext4.vhdx` there | `~/.local/share/containers/podman/machine/applehv/` |
| The machine's settings | `C:\Users\<account>\.config\containers\podman\machine\wsl\podman-machine-default.json` | `~/.config/containers/podman/machine/applehv/podman-machine-default.json` |
| The machine key | `C:\Users\<account>\.local\share\containers\podman\machine\machine` | `~/.local/share/containers/podman/machine/machine` |
| The WSL resources | `C:\Users\<account>\.wslconfig` | none |
| The Quadlet files | `/usr/share/containers/systemd/` in the machine | `/usr/share/containers/systemd/` in the machine |
| The mirrors drop-in | `/etc/containers/registries.conf.d/` in the machine, which is `C:\Users\<account>\AppData\Roaming\containers\registries.conf.d\` | `/etc/containers/registries.conf.d/` in the machine |

## Services of a container

Each published port of a container is a service of one type, on all three
systems. A container's `services` names the type per host port, `{port,
kind, scheme, protocols}`, `protocols` a list of `tcp` and `udp`, and a port
it does not name is `auto`. A container with no `services` renders the same
files as a container that names every port `auto`, and a `/udp` in `ports`
publishes that port on UDP, as it does without the service type.

| `kind` | What the agent publishes | What the hub lists |
| --- | --- | --- |
| `auto` | the port as `ports` writes it | for the TCP binding, by what the agent detected: `http` or `https` gives one `web` entry, `url` `<scheme>://<host>:<port>/`; `tcp`, or nothing yet, gives one `port` entry; a UDP binding always gives a `port` entry |
| `web` | the port on TCP | one `web` entry, `url` `<scheme>://<host>:<port>/`, `scheme` `http` or `https` as chosen |
| `port` | the port on each protocol in `protocols`, so a checked UDP adds a UDP publish beside the TCP one; a port with neither is refused `service_protocol_none {port}` | one `port` entry per protocol |

| Rule | Reason |
| --- | --- |
| A container's `web` entry has the id its TCP `port` entry has, `podman_<device>_<container>_<port>`, and a UDP `port` entry adds `_udp`. | A client keeps its local port per entry id, so a port whose type changes keeps it. |
| A TCP binding is a `web` entry or a `port` entry, never both. | A client shows a `web` entry on its Web page and a `port` entry on its Ports page, and one service appears once. |
| `<device>` is the device's id and `<container>` the container's name, which `CONTAINER_NAME_PATTERN` keeps to lowercase letters, digits, `_` and `-`. | An id holds no character a client or a file name has to escape. |
| Every entry of a container is healthy while the container runs. | The container's state is the one health the hub reads for it. |
| The `connect` stream serves a `web` entry as a TCP connection to the published port. | A web page is TCP on the port the container publishes. |

The agent detects the type of each published TCP port of a running
container, at `127.0.0.1`, once per container start:

| Step | The agent | The result |
| --- | --- | --- |
| Read | reads for about 300 ms before it sends anything | bytes from the service: `tcp` |
| HTTP | sends `HEAD / HTTP/1.0` | a reply that starts `HTTP/`: `http` |
| TLS | makes a TLS handshake with no certificate check and sends the same request | a reply that starts `HTTP/`: `https` |
| None | | `tcp` |

| Rule | Reason |
| --- | --- |
| The read comes first. | SSH, a database and other services that send first take an HTTP request as a protocol error. |
| Each step opens a connection of its own. A result is kept per container id, start time and port, and a container that starts again is detected again. A port that does not accept the connection yet keeps `detected` empty and is tried again at the next report. | A probe opens connections to the service, and its type changes only with a new start; the service of a container that started a moment ago can still be opening its port. |
| A UDP port is never probed, and its `detected` is empty. | A UDP service sends nothing back to a datagram it does not understand. |
| The result is `host_bindings[i].detected`, `http`, `https` or `tcp`, and empty before the probe. | The panel shows it beside **Auto**, and the hub lists the port by it. |
| One function detects for both runners, in the status reading of `modules/podman/`. | Linux and the Podman machine publish ports to the same `127.0.0.1`. |
