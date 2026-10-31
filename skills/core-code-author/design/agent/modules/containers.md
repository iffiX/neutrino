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
| The runner | `PodmanModuleRunner`, runner `podman` | `PodmanMachineModuleRunner`, runner `podman_machine` | `PodmanMachineModuleRunner`, runner `podman_machine` |
| Podman | the distribution's, 3.4 or later | the tested 6.1.4 for amd64, or the version the machine chose, from the hub's cache, on WSL 2 | the tested version of `podman.json`, a 6.x for arm64 and a 5.8.x for amd64, or the version the machine chose, from the hub's cache |
| The systemd that runs the units | the machine's own | the Podman machine's | the Podman machine's |
| Who runs Podman | root | root inside the machine; the machine's own commands run as the account | as on Windows |

## Linux

`PodmanModuleRunner`, under `agent/neutrino_agent/modules/podman/`, is the
runner `podman`. Its Linux entries name the method `system` with the
packages `podman` and `runc`, and the machine's package manager installs them
([module_install.md](../module_install.md), "From the system's
packages").

| Rule | Reason |
| --- | --- |
| Every declared container and every hub container is a systemd unit, `/etc/systemd/system/<name>.service`, whose `ExecStart` runs `podman run`. The unit uses only what Podman 3.4 has, and is the same on every Podman version. | The supported distributions have Podman 3.4 and later ([min_support.md](../../min_support.md)), so one unit format serves every machine. |
| The unit has `Wants=` and `After=network-online.target` and a `RequiresMountsFor=` for each host folder a volume binds; `Type=notify`, `NotifyAccess=all`, `Delegate=yes`, `KillMode=mixed`, `Environment=PODMAN_SYSTEMD_UNIT=%n`, `Restart=on-failure`, `SuccessExitStatus=143` and a hub container's `success_exit_codes` after it, `TimeoutStartSec=900` and `TimeoutStopSec=<stop>`; `ExecStartPre=-/bin/rm -f %t/%N.cid`; `ExecStart=podman run --cidfile=%t/%N.cid --cgroups=split --runtime runc --sdnotify=conmon -d --replace --rm --name <name>`; `ExecStop=podman stop --ignore -t <timeout> --cidfile=%t/%N.cid`; and `ExecStopPost=-podman rm -f --ignore --cidfile=%t/%N.cid`. `<timeout>` is 10, or a hub container's `stop_timeout_s` ("Hub containers"), and `<stop>` is `<timeout>` plus 60. | These are the settings `podman generate systemd --new` and Quadlet write. `conmon` is the unit's main process, so a stopped unit's container stays stopped, a container killed from outside fails the unit and systemd starts it again, and a container a hard stop left is replaced at the next start. A container that ends on the stop's SIGTERM exits 143 and reads stopped, while one killed from outside with SIGKILL exits 137, a failure that `Restart=` answers. A first pull takes longer than the default start timeout. Podman 3.4's `podman rm` has no `-t`, and its `podman run` fails on a cid file that is already there. |
| Every unit's `podman run` names `--runtime runc`. Every family's entry installs `runc` beside `podman`, and its `verify` checks both, `podman --version && runc --version`. The install leaves `runc` out where a `runc` is already on the machine's path, and an uninstall removes `podman` and keeps `runc`. | Ubuntu 22.04's crun 0.17 answers EPERM to `fchmodat2`, so an image built on glibc 2.39 or later fails at its first start: Hermes WebUI's first start looped there. Docker CE's `containerd.io` includes its own `runc` and conflicts with the distribution's package, and another program can run on the same `runc`. |
| A container's environment is one root-only file, `/var/lib/neutrino/agent/podman/env/<name>.env`, mode 0600 in a directory of mode 0700, which the unit's `podman run` reads with `--env-file`. The unit file is mode 0644 and holds no value of the environment, and neither does the command line. | Every account on the machine reads a unit file and a process's command line, and the environment holds secrets, such as Hermes WebUI's password and the module's gateway key. Podman reads an environment file the same way from 3.4 on: one `KEY=value` per line, the value as written, and `#` starting a comment line. |
| Every unit ends with `[Install]` and `WantedBy=multi-user.target`. Every apply runs `systemctl enable --no-reload` on the unit of each container that starts with the box, and `systemctl disable --no-reload` on each other one, before its `daemon-reload`; a removed unit is disabled before its file goes. | A unit's `[Install]` section starts nothing at boot until the unit is enabled, so a module's Stop and Start change no unit file. A unit that dropped the section at Stop changed, and the apply restarted the running container before the module's stop ended it in the middle of its start. |
| After its `daemon-reload` every apply restarts each container whose unit or environment file changed when it starts with the box or its unit is active, and starts each other container that starts with the box and whose unit is not active. | An apply makes the declared containers true, and a container that starts with the box runs after it whether or not its files changed. |
| Every rendered file, the environment file among them, starts with the generated marker, and an apply removes only marked files. | A file a person wrote beside them is theirs. |
| An apply first stops and removes each marked Quadlet file an earlier build wrote, `<name>.container` in `/etc/containers/systemd/` or `/usr/share/containers/systemd/`, and starts again, after its `daemon-reload`, each container whose unit was active. | Earlier builds wrote a container as a Quadlet file on a newer Podman, and the unit Quadlet generates from it has the name of the container's unit. |
| The registry mirrors are one drop-in, `/etc/containers/registries.conf.d/99_neutrino_mirrors.conf`. | The distribution's own `registries.conf` stays as it is. |
| The module's `is_active` is the state of `podman.socket`. | Podman has no daemon, and its API socket is the engine. |
| The install, and every apply while the module's `want` is `running`, run `systemctl enable --now podman.socket`. | Podman starts with the machine from its install on, on a distribution that ships the socket disabled too. |
| **Stop** stops and disables every declared container's and every hub container's unit with one `systemctl disable --now`, then runs `systemctl disable --now` on `podman.service` and on `podman.socket`; a container a person started by hand keeps running. The apply of a task under `want: stopped` enables none of the units and starts none. **Start** enables the units again by the apply's rule above. | A stopped module reads `stopped` and stays so across a restart ([agent.md](../../agent.md), "A stopped module stays stopped"), and a hand-started container is the person's. An apply under `stopped` that started the containers would run them only for the Stop to end them, and one that enabled them would leave them to start at the next boot if the agent stopped between its two steps. Ubuntu's package enables `podman.service`, which requires the socket: in the lab it started the socket at the next boot, and Containers read `running`. |
| A declared container starts and stops through `systemctl`, and one a person started by hand through `podman` itself. | systemd supervises a declared container; a hand-started one has no unit. |
| Where Podman's network backend is CNI, as with Podman 3.4, the agent sets `cniVersion` to `0.4.0` in `/etc/cni/net.d/<network>.conflist` right after its `podman network create`. | Ubuntu 22.04's Podman 3.4.4 writes `1.0.0`, which its CNI plugins 0.9.1 reject: a container on the network then fails with `CNI network "<network>" not found`. The distribution's own default network says `0.4.0`. |

The report reads `podman ps -a --format json` and `podman inspect`, and a
container's journal is `journalctl -u <name>.service`.

The Podman report gives each container's `host_bindings` as one `{address,
port, protocol, detected}` per published host port, on TCP and UDP alike,
`address` empty for every address and `detected` as "Services of a
container" says; `published_ports` reads the ports the machine publishes,
per protocol, from it ([agent.md](../../agent.md), "The connect stream").
The bindings come from `ps`'s `Ports`, which Podman 3.4 writes as
`hostPort` and `hostIP` and later versions as `host_port` and `host_ip`; the
reader takes both. The report gives a hub container's environment as empty
([protocol.md](../../protocol.md), "The modules section, one entry per
module").

The report gives each container's `volumes` as a configuration writes them,
a host folder by its path and a named volume by its name. It leaves out an
anonymous volume, the one Podman names with 64 hex digits: every unit runs
`podman run --rm`, and Podman removes a container's anonymous volumes with
the container.

## Windows and macOS

`PodmanMachineModuleRunner`, `name` `podman` and runner `podman_machine`, is
the second runner in the same directory, and the engine builds it under
`hub_packages` on Windows and macOS. It renders the Linux files with the
Linux renderers, `PodmanUnitRenderer` and `PodmanRegistriesRenderer`, and
writes them inside the Podman machine. Podman inside the machine is the
machine image's own, and runs the same units as Linux. In this section "the
machine" is the Podman machine and
"the computer" is the Windows or macOS system the agent runs on;
`C:\Users\<account>` means the account's profile, the home the
platform layer resolves from `ProfileList`.

### What the install puts on the computer

The manifest's Windows and macOS entries name the method `hub`, each with
its own tested version ([module_install.md](../module_install.md), "The
manifest"). The hub's cache fetches each artifact and sends it down
`package {module: podman, artifact, digest}`. The agent keeps each file as
the publisher's bytes under `podman/<directory>/` in the state root and
unpacks none.

| Artifact | Windows amd64 | macOS |
| --- | --- | --- |
| `wsl` | the WSL msi, pinned at 3.0.3 for every version, kind `msi` | none |
| `podman` | Podman's msi at the entry's version, kind `msi` | Podman's pkg at the entry's version, kind `pkg` |
| `image` | the machine image for WSL, `podman-machine.x86_64.wsl.tar.zst`, kind `tar_zst` | the machine image for applehv, kind `raw_zst` |

| Step | What the agent runs, as SYSTEM or root | Reason |
| --- | --- | --- |
| Windows features | `dism.exe /English /Online /Enable-Feature /FeatureName:<feature> /All /NoRestart` for `VirtualMachinePlatform` and for `Microsoft-Windows-Subsystem-Linux`; an exit other than 0 and 3010 ends the install `windows_feature_failed {feature, exit_code}` | WSL 2 needs both, on Windows Home too |
| WSL | the WSL msi through `installers.install_msi`, skipped when Windows Installer's product list holds the WSL package at the pinned version or newer | Podman's msi installs no WSL, and the system's own `wsl.exe` reports WSL as not installed until it is |
| Podman on Windows | `msiexec /i <msi> /qn /norestart /l*v <log> ALLUSERS=1 MACHINE_PROVIDER=wsl` through `installers.install_msi` | `ALLUSERS=1` puts Podman in `C:\Program Files\Podman` and on the computer's `PATH`, where SYSTEM and every account find it |
| Podman on macOS | `installer -pkg <file> -target /` through `installers.install_pkg` | the system's installer is the one that installs a pkg |

A failed msi or pkg ends the install `podman_install_failed {artifact,
exit_code}`.

| Rule | Reason |
| --- | --- |
| A dism exit of 3010 is a restart owed: the agent writes the reboot mark, holding the computer's boot time, and while the boot time is the mark's, or the key `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending` exists, the module reports `installing` with `{code: reboot_required}`. | dism reports a feature `Enabled` before the restart, so the feature's state cannot show that a restart is owed. |
| The agent never restarts the computer. A person does, with the tab's **Restart now** or the device's **Reboot**. | A restart closes every program open on the computer. |
| While the restart is owed, Containers' task waits in its step `restart`, holding no step lock, checks every 30 seconds and keeps no tried hash until it ends; other modules' tasks go on ([agent.md](../../agent.md), "The steps"). | The install goes on after the restart with no press, and nothing else on the machine waits for the restart. |
| On macOS the pkg's receipt is `com.redhat.podman`. Its scripts write `/etc/paths.d/podman-pkg` and `/usr/local/etc/man.d/podman.man.conf`, and run `podman-mac-helper install`, which installs nothing when the agent runs the installer. | The helper installs for the account `SUDO_USER` or `USER` names and refuses root, and the agent runs as root with no `SUDO_USER`. |

### The account and its machine

The Run settings are the configuration's `machine`, `{account, cpus,
memory_gib, disk_gib}`, with the account's `password` added by the hub for a
Windows machine. A 0 CPUs is half the computer's logical processors,
Podman's default. A 0 memory is half the computer's memory in whole GiB, at
most 4 GiB and at least 1, and Podman's own 2 GiB where the agent cannot
read the computer's memory. On Windows the disk limit is 1 GiB or more, and
a 0 is refused `machine_disk_invalid {disk_gib}`. On macOS a 0 disk is 100
GiB at an init, and leaves the disk of a machine taken over as it is.

| Rule | Reason |
| --- | --- |
| The machine is the account's default one, `podman-machine-default`. The agent creates it when the account has none, with `podman machine init --rootful --image <kept image>`, and takes over one that exists, with `podman machine set --rootful` on the stopped machine when it is not rootful. | The person's own `podman ps` as that account shows the containers the panel declares. |
| On Windows the machine runs in WSL's NAT mode. The init leaves user-mode networking off, and a machine taken over with it on gets `podman machine set --user-mode-networking=false` on the stopped machine, as it gets `--rootful`. | User-mode networking gives every container every port on the computer's loopback: on the lab machine a container reached a listener on Windows' `127.0.0.1` through gvproxy's address, `192.168.127.254`. |
| Every `podman machine` and `wsl` command runs as the account, through the platform's `run_as_account`: the one-shot task under the account's login on Windows, a child with the account's uid on macOS. The agent writes `.wslconfig` as the account too. | WSL refuses SYSTEM with `WSL_E_LOCAL_SYSTEM_NOT_SUPPORTED`, `podman machine` refuses root on macOS, and the account keeps owning its own files. |
| On macOS every `podman machine` command has `TMPDIR` set to the account's own temporary directory, which `getconf DARWIN_USER_TEMP_DIR` prints when run as the account, read once per account. | Podman keeps a running machine's sockets and helper files under `$TMPDIR/podman` and uses `/tmp` when `TMPDIR` is not set, as in a child the agent starts; the account's sessions have that directory. |
| The init reads the image the hub sent, and runs in Containers' step `machine`, about 40 seconds on Windows. | The hub's cache is the one source of the machine's bytes. |
| On macOS the kept image stays root's with mode 0600, and before the init the agent gives the machine's account alone read on it with one access list entry, `user:<account> allow read`, after it drops every entry an earlier init added. On Windows the module's directory is open to every account. | The init runs as the account: on the lab Mac an image only root read failed the init `permission denied`. |
| On WSL the agent resizes the disk right after the init and before the first start, with `wsl --manage podman-machine-default --resize <size>GB`. This first resize also runs `wsl --shutdown` as the account, which stops the account's other WSL systems. | WSL creates a 1 TB disk whatever size Podman asks for. |
| On WSL the CPUs and the memory are `processors=<n>` and `memory=<n>GB` under `[wsl2]` in the account's `%USERPROFILE%\.wslconfig`, a 0 written as the default's number; the agent makes the file or the section when it is missing, changes these two keys and keeps every other line. | WSL ignores Podman's numbers and reads this file, which is the person's own and applies to every WSL system of the account. |
| A change of CPUs, memory or disk in the configuration, against the last one applied, runs `wsl --shutdown` as the account on WSL, which stops every WSL system of that account, then resizes the disk when it grew, and starts the machine before the apply writes into it. The panel warns before the apply. | WSL reads `.wslconfig`, and resizes a disk, only while none of the account's WSL systems runs; a person's own edit of the file is theirs and restarts nothing. |
| On macOS a change runs `podman machine set --cpus --memory --disk-size` on the stopped machine, then starts it. | Podman sets an applehv machine's resources itself. |
| A 0 memory takes its number when the agent makes the machine and when the Run settings change. A machine made under another default keeps its size while the Run settings stay. | A size change on WSL stops every WSL system of the account, so only an apply the person pressed after the panel's warning changes the size. |
| The default memory is one function in the agent's runner, `default_memory_gib`, and the report's `machine` adds its number for the computer as `default_memory_gib`. The report reads the computer's memory once per agent start. | The hub compares the container modules' need with the machine's memory, a stored 0 among them, and reads that number from the report. |
| A disk other than 0 and smaller than the machine's disk now, its virtual size, is refused `machine_disk_shrink {disk_gib, current_gib}`, a machine taken over among them; a disk of 0 on Windows `machine_disk_invalid {disk_gib}`; CPUs past the computer's logical processors `machine_cpus_invalid {cpus, max}`, memory past its size `machine_memory_invalid {memory_gib, max}`, an empty account `machine_account_missing`, and an account the computer does not have `account_unknown {account}`. The step `machine` refuses an empty account `machine_account_missing` with no container declared as well. | Shrinking a disk can cut the data on it; WSL shrinks one when asked, so the rule is the module's. |
| On WSL, when the `.wslconfig` write or the resize right after the init fails, the agent removes the machine the init made, with `podman machine rm -f` as the account, and the apply fails with the step's code. | The new machine holds nothing yet, and kept with WSL's 1 TB disk it would refuse every smaller limit; the next apply makes it again and sizes it. |
| A new account stops the old account's machine and removes its keeper before the new one starts; the old machine, its images and named volumes and the old account's `.wslconfig` stay as they are. | Two running machines publish the same ports on `127.0.0.1`, and the old machine's data is the person's. |

### Memory for the container modules

Every container runs in the one Podman machine, so the container modules
share its memory. A container module's manifest names the memory its
containers need as `memory_mib` ([module_install.md](../module_install.md),
"The manifest").

| Rule | Reason |
| --- | --- |
| The hub sums the `memory_mib` of every container module `modules.json` asks for with a `want` other than `absent`, and rounds the sum up to whole GiB. | A module counts from the press of its **Install**, so the advice shows before its first start. |
| The machine's memory is the reported machine's `memory_gib` while the report names the stored account's machine running, else the stored `memory_gib`, else the reported `default_memory_gib`. | A machine made under an older default keeps its size until the Run settings change, and the report shows its size. |
| While the sum passes the machine's memory, the module list and the Containers view carry `memory_need`, `{need_gib, memory_gib}`, and the panel shows it as a hint ([../../ui_behavior.md](../../ui_behavior.md), "The machine page"). Nothing is refused. | The person chooses the memory: a machine with less still runs the modules, more slowly. |
| Linux has no advice. | Linux runs the containers on the machine itself, with all its memory. |

Ayakaleaf's first start peaked at 2584 MB in a 4 GiB machine, and in a 2 GiB
machine it finished only by swapping. Hermes WebUI's first start took 410 MiB
of its own memory on a Linux machine, and its manifest names 1024
([hermes_webui.md](hermes_webui.md)).

### The keeper

The keeper starts the machine at boot, with nobody signed in, and starts it
again when it stops. It is an account service
([module_template.md](../module_template.md), "The run"): the scheduled task
`neutrino_podman_<account>` at startup under the account's login on Windows,
and the LaunchDaemon `com.neutrino.podman.<account>` with `UserName` on
macOS.

| Rule | Reason |
| --- | --- |
| The keeper's script loops by itself: every 30 seconds it checks the machine's state and starts the machine when it is not running. | Task Scheduler did not start the task again after its program exited, whatever its restart settings. |
| Before each start on Windows it deletes `%TEMP%\podman\podman-machine-default-api.sock`. | A file left by a restart with the machine running keeps `win-sshproxy.exe` from binding at the next start. |
| A start that fails is followed by `podman machine stop`, the same deletion, and one more start. | Windows reserves a port range at boot that can hold the machine's ssh port; Podman finds the conflict at the next start and moves the port. |
| A state the keeper cannot read is unknown: the keeper waits for the next round and neither starts nor stops the machine. | In a 2 GiB machine under Ayakaleaf's TeX step `podman machine inspect` printed nothing, the start that followed failed `already running`, and the stop after it took the running machine and the step down. |
| On macOS the script sets `TMPDIR` from `getconf DARWIN_USER_TEMP_DIR` before its first command. | The keeper, the agent's machine commands and the account's sessions then reach the same machine files. |
| On macOS the keeper's LaunchDaemon has `AbandonProcessGroup`. | The machine's processes are children of the keeper's `podman machine start`, and launchd ends the job's whole process group when the job stops. |
| **Stop** runs the root script that stops and disables every declared container and every hub container with one `systemctl disable --now`, then stops the keeper, then runs `podman machine stop` as the account. The machine then stops answering the read, and the module reads `stopped`. A container a person started by hand stops with the machine. | A running machine keeps its memory, about 3 GiB on the lab machine, while the module is stopped. A keeper left running starts the stopped machine again within 30 seconds. |
| Each time the agent reads the image references in the machine's store, for a container module's presence check and before it stops the machine, it saves them into the module's record. While the machine or its image list does not answer the read, a container module's presence check reads that saved list, and the module reads `stopped`. | A stopped machine lists no images, and a running machine can miss a read. A container module that read `absent` while Containers was stopped had its uninstall skipped: on the lab machine Hermes WebUI's four volumes and its two images, 3.2 GB, stayed in the machine. A list saved only at the stop missed the images pulled after it, and Hermes WebUI read `absent` once while the running machine missed a read. |
| **Start** applies the configuration, and the apply starts the keeper. The keeper starts the machine, and the apply waits until the machine answers the read. | The keeper is the one program that starts the machine. |
| An apply under `want: stopped` checks the configuration and keeps it, and the next **Start** writes it. It starts neither the keeper, the machine nor a container. A Stop of a machine Stop already stopped runs nothing. | A press wakes the machine once, and only a container module's uninstall wakes a stopped machine. On the lab machine an apply of the Run settings during Stop started the machine to write its files and stopped it again, and the Start after it started the machine a second time. A Stop's configure on the lab Mac started the keeper and waited 180 seconds for a machine that never answered. |
| A stop lasts across the computer's next boot. **Stop** disables the keeper's task or LaunchDaemon, and **Start** enables it again before it starts it. With no record of an apply, as when the machine never answered the read, **Stop** stops and disables the keeper of the account the configuration names and stops that machine, and the uninstall removes that keeper with its task or LaunchDaemon and its log. | The account service layer disables a service it stops ([module_template.md](../module_template.md), "The run"), and a stopped module stays stopped ([agent.md](../../agent.md), "A stopped module stays stopped"). On the lab Mac a machine that never answered left no record, and its keeper stayed loaded across a reboot and ran on after the uninstall. |
| A container module's uninstall while the machine is stopped starts the keeper and waits until the machine answers the read. It then removes the module's containers and their files in the machine, and stops the keeper and the machine again. | The uninstall's steps run through the machine's Podman. On Linux they run while Containers is stopped as well. |

A published port answers about 30 seconds after a boot with nobody signed
in. On Windows the machine keeps running when the keeper's task stops and
when the account signs in or out; on macOS this is not proven.

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
| The read uses the ssh URL on both systems. | As SYSTEM, Podman's Windows client rejects both an `npipe:` URL and the machine's `unix://` path; on macOS the machine's API socket is under the account's temporary directory, and the ssh URL reads only the settings file and the key. |
| A container a person started by hand starts, stops and restarts through the read's command, as SYSTEM or root. | Linux drives such a container through `podman` itself, and it has no unit in the machine. |
| The read output goes through the Linux reader, given this command in place of `podman`. | One parser for `ps` and `inspect` on every system. |
| The module's `is_active` is whether the machine answers the read. | The machine's Podman is the engine there, as `podman.socket` is on Linux. |
| The script holds every file base64-encoded, removes an earlier build's Quadlet files as an apply on Linux does, compares each file with the one in the machine, writes the changed ones with their modes, removes the stale marked files, enables and disables the units, runs `systemctl daemon-reload`, restarts and starts the units as an apply on Linux does and prints one `changed: <file>` line per change. | Each call costs about 3 seconds, so an apply is one call. |

### Files in the machine

| Rule | Reason |
| --- | --- |
| The units are in `/etc/systemd/system/` in the machine, and the environment files in `/var/lib/neutrino/agent/podman/env/`, the Linux paths. | Both are on the machine's own disk, where systemd reads a unit at boot. In the WSL machine `/etc/containers` is the account's `%APPDATA%\containers`, and Podman 6 on macOS mounts the account's `~/.config/containers` there, each after boot. |
| A unit rendered for the machine runs `podman run --cgroups=enabled` with no `--runtime`, and a Linux unit `--cgroups=split --runtime runc`. | The WSL machine runs systemd under cgroupfs, where split mode fails with "controller pids is not available"; the applehv machine runs systemd's own cgroups v2, where `enabled` works too. The machine keeps its image's own runtime. |
| The mirrors drop-in is `/etc/containers/registries.conf.d/99_neutrino_mirrors.conf` in the machine. | Podman reads it at a pull, after the mount, so the account's folder under that path serves. |
| macOS uses the same paths and the same cgroups mode. | One code path writes into every Podman machine. |
| The root script stops, disables and removes the boot unit `/etc/systemd/system/neutrino_containers.service` an earlier build wrote with the generated marker, as it removes every marked unit the configuration does not name. | A unit in `/etc/systemd/system/` starts at boot from its link in `multi-user.target.wants/`, so no unit has to start the containers after the mount. |

Podman 5.8 leaves `/etc/containers` on the macOS machine's own disk, and
Podman 6 mounts the account's `~/.config/containers` there with
`etc-containers.mount`, as it mounts `%APPDATA%\containers` on WSL. The
`podman_macos` job read each entry's machine settings: Podman 6.1.4 lists
the mount on `/etc/containers`, and Podman 5.8.9 does not. No applehv
machine has started under the agent, and the boot on a real Apple silicon
Mac is not proven.

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
hub.

| Rule | Reason |
| --- | --- |
| On Windows an apply refuses a port published on UDP, a `/udp` in `ports` or a `port` service with UDP checked, `udp_not_forwarded {name, port}`. | WSL's localhost forwarding carries TCP alone: on the lab machine a container's UDP port had no listener on `127.0.0.1`, and a datagram sent there by SYSTEM or by the account came back as port unreachable. |

### The journal

A container's journal is `journalctl -u <name>.service` in the machine, run
by the root script. One journal read runs in the machine at a time, and a
read of the same containers asked while it runs takes its lines: each root
script of an account waits for the one before it, about 4 s each on
Windows. The module's journal reads the keeper's log first and
then the agent's own lines that name the module, as every module on Windows
and macOS reads its sources ([agent.md](../../agent.md), "Which modules
each system runs"). The keeper's log is `<account>.log` under `podman\` in
the state root on Windows, made by the agent with modify granted to the
account, and `/Library/Logs/Neutrino/agent/podman_<account>.log`, the
LaunchDaemon's `StandardOutPath` and `StandardErrorPath`, on macOS.

### The uninstall

The uninstall runs in the order of this table, so the root script reaches
the machine while it still runs. A machine that **Stop** stopped is started
by its keeper first, and the uninstall waits until it answers the read:

| What | After the uninstall |
| --- | --- |
| The declared containers, their units and environment files in the machine, and the mirrors drop-in | stopped and removed, by one root script |
| The keeper, its script and its log | removed, so nothing starts the machine again |
| The machine | stopped, and kept with its disk, images and named volumes in the account's profile; on Windows its WSL system stays registered |
| Podman | uninstalled: on Windows the msi by `installers.uninstall_msi`; on macOS `/opt/podman/` and the two files the pkg's scripts write deleted, and the receipt forgotten with `pkgutil --forget com.redhat.podman` |
| The kept artifacts and the reboot mark | removed from the state root |
| The account's `.wslconfig`, WSL and both Windows features | kept |

A reinstall finds the account's default machine and takes it over, and the
hub's configuration brings back the containers with their volumes, as
`is_data_kept` says. WSL serves the person's other WSL systems, and turning
a feature off owes another restart.

### Disk layout

| | Windows | macOS |
| --- | --- | --- |
| Podman | `C:\Program Files\Podman\` | `/opt/podman/` |
| The kept artifacts | `%ProgramData%\Neutrino\agent\state\podman\<directory>\` | `/Library/Application Support/Neutrino/agent/state/podman/<directory>/` |
| The reboot mark | `%ProgramData%\Neutrino\agent\state\podman\reboot_mark` | none |
| The keeper's script | `%ProgramData%\Neutrino\agent\state\podman\keeper.cmd` | `/Library/Application Support/Neutrino/agent/state/podman/keeper.sh` |
| The keeper | the scheduled task `neutrino_podman_<account>` | `/Library/LaunchDaemons/com.neutrino.podman.<account>.plist` |
| The keeper's log | `%ProgramData%\Neutrino\agent\state\podman\<account>.log` | `/Library/Logs/Neutrino/agent/podman_<account>.log` |
| The machine | `C:\Users\<account>\.local\share\containers\podman\machine\wsl\`, its disk `ext4.vhdx` there | `~/.local/share/containers/podman/machine/applehv/` |
| The machine's settings | `C:\Users\<account>\.config\containers\podman\machine\wsl\podman-machine-default.json` | `~/.config/containers/podman/machine/applehv/podman-machine-default.json` |
| The machine key | `C:\Users\<account>\.local\share\containers\podman\machine\machine` | `~/.local/share/containers/podman/machine/machine` |
| The running machine's sockets | `%TEMP%\podman\` of the account | `podman/` under the account's own temporary directory |
| The WSL resources | `C:\Users\<account>\.wslconfig` | none |
| The units | `/etc/systemd/system/` in the machine | `/etc/systemd/system/` in the machine |
| The environment files | `/var/lib/neutrino/agent/podman/env/` in the machine | `/var/lib/neutrino/agent/podman/env/` in the machine |
| The mirrors drop-in | `/etc/containers/registries.conf.d/` in the machine, which is `C:\Users\<account>\AppData\Roaming\containers\registries.conf.d\` | `/etc/containers/registries.conf.d/` in the machine, which is `~/.config/containers/registries.conf.d/` with Podman 6 |

## Hub containers

A hub container is one a `container` module runs on Containers
([module_install.md](../module_install.md), "From container images"). The
hub composes them into the `podman` state as `hub_containers`, one list
beside `containers`, and the agent renders each as it renders a declared
container on the same system.

| Rule | Reason |
| --- | --- |
| A hub container is `{module, name, image, ports, volumes, environment, command, is_autostart, services, source_sets, after, page_port, stop_timeout_s, success_exit_codes}`, `image` as `{digest, sources}`; the agent adds the label `neutrino.module=<module>` and joins it to the network `neutrino_<module>`, which an apply makes when it is missing. | The label names the container's module on the machine, and the containers of one module reach each other by name. |
| `source_sets` is the list of source sets the container's tools fetch from, copied from its module's `container` entry, empty where it lists none. Before the agent writes the container's environment file, it probes each set and writes every variable of the set, with the fastest source, into the container's environment; an `environment` value `{<set>}` is that set's fastest source ([module_install.md](../module_install.md), "Source sets"). | Which source is fastest depends on the machine's own network, and the container's tools read the address from their environment. |
| `after` lists the module's hub containers this one starts after, by name, and its unit names each of theirs in `Requires=` and `After=`. | A container that mounts a volume another container fills from its image at the first mount has to start second ([hermes_webui.md](hermes_webui.md)). |
| A container module's start and stop drive its units with one `systemctl` call, and a stop that fails keeps systemd's own words in its `detail`. | systemd then orders the units by their `After=`: Ayakaleaf's app stops first, then mongo and redis. A stop of mongo alone stopped the app inside mongo's job, and once in the lab it failed with `systemctl` exit 1 and no words kept. |
| `page_port`, where present, is the container's port that the module's forwarder serves. The agent publishes it on `127.0.0.1` at a loopback port it picks at the first apply and keeps in the module's record, and puts the forwarder in front of it at the forwarder's own port, which the agent takes too. | The forwarder holds its own port, and a port picked one time keeps the container's unit the same across applies. |
| The port a `page_port` is published at is in no entry, and the `connect` stream does not serve it. | Every request from a client reaches the page through the forwarder's check. |
| `stop_timeout_s`, where present, is the seconds `podman stop` gives the container between SIGTERM and SIGKILL, in place of 10, and its unit's `TimeoutStopSec` is that number plus 60 ("Linux"). | Ayakaleaf's app flushes the open edits for about 19 seconds after SIGTERM, and 10 seconds killed it first ([ayakaleaf.md](ayakaleaf.md)). systemd ends a stop that outlasts `TimeoutStopSec`, so the unit gives `podman stop` the room its timeout takes. |
| `success_exit_codes`, where present, lists the exit codes beside 143 that the container ends a clean stop with, and its unit's `SuccessExitStatus=` names them after 143. | Ayakaleaf's app exits 2 on SIGTERM once its flush has ended, and a unit that reads 2 as a failure ends every clean stop `failed` ([ayakaleaf.md](ayakaleaf.md)). |
| The agent renders a hub container's image as the reference it finds in Podman's store with the image's digest, under one of its `sources`. | Podman stores an image pulled from a mirror under the mirror's name. |
| Containers renders the hub containers of a module only after that module's install has pulled its images: an apply of Containers leaves out the containers of a module whose images are not on the machine yet, and the module's install, once its last image is pulled, marks Containers to be applied again. | Containers is applied before the container modules, and a unit that named an image the machine lacks would have Podman pull it from a source the module's install did not choose. |
| A container's owner is read in this order: the label `neutrino.module` makes it a hub container of that module, a name among the declared ones makes it declared, and any other container is one a person started by hand. | Each container has one owner, and the label outlasts every record. |
| `neutrino_` starts no declared container's name: `container/set` refuses a new name with it `container_name_reserved {name}`. A declared container that came from an import keeps its name. | A person's container never takes the name of a hub container. |
| A container with the label `neutrino.module` is never imported into the declared containers. While `config/devices/<id>/modules.json` does not name its module, as on a hub the machine joined or one that lost its configuration, Containers renders none of its containers and they stop. Their named volumes stay until the module's uninstall, and the module's install starts its containers on them again. | A label names the module that owns the container. In the lab a machine that joined another hub had its Ayakaleaf containers imported as declared ones: the mongo container's anonymous volume, written as a folder, was gone at its next start, and the module's install was refused `container_name_duplicate {name}`. |
| A hub container's row in **Running** has the module's title and **Journal** as its one button. The hub refuses `container/start`, `/stop`, `/restart` and a container's shell on it with `container_hub_owned {name}`. | The module runs its containers as its configuration says, and a press or a shell beside it changes them behind the module. |

## A refused declared container

An apply checks each declared container on its own. The `validate` verb
checks the whole configuration, so a save on the tab is refused with the
code of the first container the checks refuse.

| Rule | Reason |
| --- | --- |
| An apply leaves out each declared container the checks refuse and applies the rest: the other declared containers, the hub containers, the mirrors and the Run settings. It then fails with the first refusal, such as `image_invalid {name, image}`, and Containers reads `failed` with that code, which its tab shows as the error notice. | In the lab a machine that joined another hub had a container started by hand whose image the report gave as empty. The new hub imported it, the agent refused the whole configuration, and Ayakaleaf's containers kept the earlier hub's environment: each sign-in through the forwarder found no cookie of the new name. |
| A left-out container is rendered as one the configuration does not name, and a unit an earlier apply wrote for it goes. | That unit runs settings the configuration has since replaced. |
| The hub containers' names are taken before the declared ones, so a declared container with a hub container's name is the one refused, `container_name_duplicate {name}`. | A person's container never keeps a module's containers from their update. |
| The import leaves out a reported container whose image is empty or contains a space ([../../protocol.md](../../protocol.md), "Taking over a machine"). | The agent refuses such a declaration `image_invalid {name, image}`. |
| A container module's start fails `containers_not_applied` while the hub containers the last apply of Containers wrote for the module differ from the ones the state names. The module then reads `failed` until a press tries it again ([../../agent.md](../../agent.md), "A retry is the same press again"). | The module's containers run on an earlier state's units and environment files, which its own step cannot change. |
| Until the first apply of Containers after the agent starts, every module's hub containers count as written. Once that apply fails before its files are written, none do. | An agent that starts applies nothing it already tried, and its units are the last apply's. The runner keeps what an apply wrote in memory alone, so a failed apply after the start leaves nothing to compare. |

## Reaching the machine

Every container reaches the agent's `127.0.0.1` listeners at
`host.containers.internal`, on the same port ([agent.md](../../agent.md),
"The listeners a container reaches").

| System | How `host.containers.internal` reaches the listeners |
| --- | --- |
| Linux | the renderer writes `host.containers.internal:<gateway>` into every declared and hub container, `<gateway>` being the gateway address of the container's network, as `--add-host` on the unit's `podman run`. The agent relays its listeners on that address, with a rule in ufw or firewalld for each relay where either runs. |
| Windows | Podman maps `host.containers.internal` in the NAT-mode machine to the computer's address on WSL's vEthernet adapter, `172.20.208.1` on the lab machine. The agent relays its listeners on that address, with one inbound Windows Firewall rule for each relayed port, scoped to the adapter. |
| macOS | the Podman machine's gvproxy maps `host.containers.internal` to the Mac's loopback, where every container reaches every port: the agent's listeners and every other program's |

| Rule | Reason |
| --- | --- |
| An apply on Linux makes the networks first, reads each network's gateway with `podman network inspect`, and hands the addresses to the renderer. | The renderer stays pure, and a module's network has its address once the apply makes it. |
| The firewall rules of the relays follow the relays, and each goes when its relay closes ([agent.md](../../agent.md), "The listeners a container reaches"). | On Ubuntu with ufw at its defaults, on Rocky 9 with firewalld at its defaults and on Windows with its firewall on, the system's firewall dropped a container's connection to the relay until the rule was added. |
| On macOS the agent opens no relay. The Podman machine there has gvproxy as its one network, and gvproxy gives every container every port on the Mac's loopback. | A Mac's loopback service with no login of its own is open to every container on that Mac; the agent's listeners keep their own checks ([agent.md](../../agent.md), "What an attacker in each position gets"). |
| A container module that uses the AI gateway, as its line in the description table says, has a gateway key of its own. The hub generates it, seals it in `config/devices/<id>/<module>.json`, registers it under the device and the module, and voids it at the module's uninstall. | The module's containers call the gateway on their own, and a key per module shows its use as a row of its own ([hub_components/ai.md](../../hub_components/ai.md), "A key per device as well as per client"). |
| The hub composes the gateway's address as `NEUTRINO_GATEWAY_URL` and the key as `NEUTRINO_GATEWAY_KEY` into the environment of the module's containers: the address is `http://host.containers.internal:8317` on a managed machine, and the gateway's `listen_port` in place of 8317 on the hub's own machine. | The address is the agent's forward, or on the hub's machine the gateway's own port, each relayed to the container. |
| The key does not follow the machine's AI tools setting. | The setting points a person's tools at the gateway; the module's containers need the gateway whatever the setting says. |

## The last apply's record

| Rule | Reason |
| --- | --- |
| Every apply writes the names of the declared containers, and of the hub containers by module, into the module's record under `platform.agent_data_dir()`, root-only. | The report, a container's buttons and its journal tell a declared container from a hand-started one. |
| Until its first apply after a start, the runner reads the names from the record. | An agent that starts on a state it already tried applies nothing ([agent.md](../../agent.md), "A retry is the same press again"), and its declared containers still run through systemd. |
| On Windows and macOS the names are in the record the runner keeps of its last apply, beside the Run settings and the image references saved at the machine's last stop ("The keeper"). | One record per runner. |

## A container's shell

A `shell` stream opened with `{module: podman, container}` runs
`podman exec -it -e NEUTRINO_SHELL_ID=<id> <container> sh -c <shell>` on
the agent's pseudo-terminal, on Windows its pseudo console, where `podman`
is the read's command on Windows and macOS. `<id>` is 32 random hex digits,
new for each shell, and `<shell>` runs the container's bash where it has
one, else its sh. The shell is never kept.

| Rule | Reason |
| --- | --- |
| Once the shell has ended, by its own exit or by the stream's close, the agent ends its `podman exec` and then runs `podman exec <container> sh -c <sweep> sh <id>`. The sweep kills every process in the container whose environment holds `NEUTRINO_SHELL_ID=<id>`, and every process in the session of one. | The shell runs in Podman's exec session, which outlives the `podman exec` that started it: on Podman 4.3.1 the shell and every program it started kept running. |
| The sweep uses the builtins of POSIX `sh` alone and reads `/proc/<pid>/environ` and `/proc/<pid>/stat`. | The shell needs `sh` already, and an image may hold no other program. |
| An `exit` closes the stream with the shell's exit code; the sweep runs after it and changes no code. | The exit code is the shell's, and the sweep ends only what the shell left behind. |

A killed process whose parent dies first becomes a child of the
container's first process. A first process that reaps no child, such as
`sleep infinity`, keeps it as a zombie entry until the container restarts.

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
| A service whose port the container does not publish, whose `kind`, `scheme` or protocol is unknown, or whose port appears twice is refused `service_invalid {name, port}`, as a `port` service with no protocol is refused `service_protocol_none {port}`. | A service is the type of one published host port, and one with no such port, a second one for the same port, or a value the agent does not know gives the agent nothing to publish. |
| A container is one app, `podman_<device>_<container>`, and each of its entries is named by its port: a `web` entry has the id its TCP `port` entry has, `podman_<device>_<container>_<port>`, and a UDP `port` entry adds `_udp`. A hub container's ports are entries of its module's app instead ([../../protocol.md](../../protocol.md), "Apps"). | A client keeps its local port per entry id, so a port whose type changes keeps it. |
| A TCP binding is a `web` entry or a `port` entry, never both. | A client shows the binding once in the app's row, and one service appears once. |
| `<device>` is the device's id and `<container>` the container's name, which `CONTAINER_NAME_PATTERN` keeps to lowercase letters, digits, `_` and `-`. | An id holds no character a client or a file name has to escape. |
| Every entry of a container is healthy while the container runs. | The container's state is the one health the hub reads for it. |
| The `connect` stream serves a `web` entry as a TCP connection to the published port. | A web page is TCP on the port the container publishes. |

The agent detects the type of each published TCP port of a running
container, at `127.0.0.1`, once per container start:

| Step | The agent | The result |
| --- | --- | --- |
| Read | reads for about 300 ms before it sends anything | bytes from the service: `tcp` |
| HTTP | sends `HEAD / HTTP/1.0` | a reply that starts `HTTP/` with a status other than 400: `http` |
| TLS | makes a TLS handshake with no certificate check and sends the same request | a reply that starts `HTTP/`: `https`; no such reply after a plain one of 400: `http` |
| None | | `tcp` |

| Rule | Reason |
| --- | --- |
| The read comes first. | SSH, a database and other services that send first take an HTTP request as a protocol error. |
| A plain reply with the status 400 goes on to the TLS step, and `https` wins when TLS answers. | A web server with TLS on the port, nginx among them, answers a plain request with 400. |
| Each step opens a connection of its own. A result is kept per container id, start time and port, and a container that starts again is detected again. A port that does not accept the connection yet keeps `detected` empty and is tried again at the next report. | A probe opens connections to the service, and its type changes only with a new start; the service of a container that started a moment ago can still be opening its port. |
| A UDP port is never probed, and its `detected` is empty. | A UDP service sends nothing back to a datagram it does not understand. |
| The result is `host_bindings[i].detected`, `http`, `https` or `tcp`, and empty before the probe. | The panel shows it beside **Auto**, and the hub lists the port by it. |
| One function detects for both runners, in the status reading of `modules/podman/`. | Linux and the Podman machine publish ports to the same `127.0.0.1`. |
