# Files

Where an installed Neutrino puts things, and the one question each location
answers.

## One root, three names

Every place Neutrino writes to is one `neutrino` root with exactly three
directories under it: `hub`, `agent` and `client`. That holds on Linux,
macOS and Windows, at the machine level and inside every user's profile. No
other directory anywhere is named after Neutrino: not `neutrino_agent`, not
`neutrino_client`, not `Neutrino Client`, not a module's own name beside the
three. The one place the product names `Neutrino Hub` and `Neutrino Client`
appear is the application entry a person launches, on every platform alike:
the macOS bundles `/Applications/Neutrino Hub.app` and `/Applications/Neutrino
Client.app`, the Windows Start menu shortcuts, the Linux desktop entries. A
package that has nothing to say for a question has
no directory there. Names that are not directories keep the `neutrino_<package>…` form:
sockets, pipes, systemd units, launchd labels and Windows services.

A layout change is a reinstall. Nothing moves an older layout into place, and
nothing reads from one.

Five questions, and the root that answers each on every system. `_rooted()`
in the hub's `utils/constants.py` reads the hub's column from one table per
system, and the agent's and the client's constants spell theirs the same
way. `NEUTRINO_DEV_ROOT` and `NEUTRINO_CONFIG_DIR` override them on every
system.

| Question | Linux | macOS | Windows |
| --- | --- | --- | --- |
| What did the package put here? | `/opt/neutrino/{hub,agent,client}` | `/Library/Application Support/Neutrino/{hub,agent,client}/app` | `C:\Program Files\Neutrino\{hub,agent,client}` |
| What has somebody decided? | `/etc/neutrino/{hub,agent,client}` | `/Library/Application Support/Neutrino/{hub,agent,client}/config` | `C:\ProgramData\Neutrino\{hub,agent,client}\config` |
| What has this machine accumulated? | `/var/lib/neutrino/{hub,agent,client}` | `/Library/Application Support/Neutrino/{hub,agent,client}/state` | `C:\ProgramData\Neutrino\{hub,agent,client}\state` |
| What happened? | `/var/log/neutrino/{hub,agent,client}` | `/Library/Logs/Neutrino/{hub,agent,client}` | `C:\ProgramData\Neutrino\{hub,agent,client}\log` |
| What is true only until the next boot? | `/run/neutrino/{hub,agent,client}` | `/var/run/neutrino/{hub,agent,client}` | named pipes `\\.\pipe\neutrino_<package>…` |

What a user's own account holds, one tree per user with the same three names:

| Holds | Linux | macOS | Windows |
| --- | --- | --- | --- |
| the client's bindings, settings and state | `~/.config/neutrino/client` | `~/Library/Application Support/Neutrino/client` | `%APPDATA%\Neutrino\client` |
| the client's log | the same directory | `~/Library/Logs/Neutrino/client` | `%LOCALAPPDATA%\Neutrino\client` |
| the client's control socket | `$XDG_RUNTIME_DIR/neutrino/client.sock` | `~/Library/Application Support/Neutrino/client/client.sock` | the pipe `neutrino_client_<user>` |
| what the agent installs for the account (CloudCLI's app, its npm cache and database) | `~/.local/share/neutrino/agent/cloudcli` | `~/Library/Application Support/Neutrino/agent/cloudcli` | `%LOCALAPPDATA%\Neutrino\agent\cloudcli` |
| build caches of the packaging scripts | `~/.cache/neutrino` | the same | the same |

A few locations are the operating system's rather than this project's, and
are where they are because nothing else works: `/usr/bin/nhub`, `nagent` and
`nclient` because a command has to be on the path (`/usr/local/bin` on macOS,
the program directory on `PATH` on Windows); `/lib/systemd/system/` and
`/Library/LaunchDaemons/` because the service managers read from there and
nowhere else; `/usr/share/doc/<package>/licenses/` because that is where a
package's licences are looked for; the polkit rule of the client's mount
helper under polkit's own directory; the agent's RustDesk host under
`/usr/lib/neutrino/agent/rustdesk/`, because RustDesk answers `--password`
only when its own binary, links resolved, sits under `/usr`. The application entry named
`Neutrino Client` writes everything under `Neutrino/client`.

## What each operation leaves behind

Four operations can take things away, and each answers to one rule: the
package manager owns what the package put here, the person owns what they
decided, and `purge` and `reset` are the two ways of saying "all of it", one
to dpkg, one to the hub.

| Operation | `/opt/neutrino/hub` | `/etc/neutrino/hub` | `/var/lib/neutrino/hub`, `/var/log/neutrino/hub`, `/run/neutrino/hub` |
| --- | --- | --- | --- |
| upgrade / reinstall | replaced whole | untouched, byte for byte | kept; the next render rewrites what it derives |
| `apt remove` | deleted | **kept** | kept |
| `apt purge` | deleted | **deleted** | deleted |
| `nhub reset all` | kept (still installed) | replaced from the examples; the vault key, the agent TLS identity and the panel's certificate authority go with it | cleared of everything the hub wrote |
| update from the panel or `nhub update` | replaced whole by the package manager, from a file under `/var/lib/neutrino/hub/hub_update/` | untouched, byte for byte | kept; the record of the update lands in `hub_update/state.json` |

`remove` keeps the decisions because that is dpkg's own convention: a package
can come back and find its configuration waiting. `purge` is the explicit
request to forget everything, and it honours that to the letter; what the
vault held is gone with it, so a backup taken first is the only way back.
`/etc/neutrino/agent` and `/etc/neutrino/client` belong to their own packages
and survive the hub's purge untouched. The same table holds for the agent
and the client with their own three directories.

## /opt/neutrino: what the packages put here

```
/opt/neutrino/
    hub/
        python/     the interpreter and the hub installed into it
        bin/        xray, cli-proxy-api, netbird, easytier-core, easytier-cli,
                    and on macOS and Windows tun2socks
    agent/
        python/     the interpreter, the agent, and the window's bindings
    client/
        the compiled client, its libraries and the carried programs
        libexec/mount_helper
```

Static. Nothing writes here after the install, and an upgrade replaces the
directory whole. Removing a package removes its directory entirely, which is
the property that makes it the right place for everything carried rather
than configured. On macOS and Windows the hub is one compiled `nhub` beside
its programs, and the agent and the client are compiled the same way.

Why the hub carries an interpreter at all, and what that costs, is in
[../agent_work_rule/release.md](../agent_work_rule/release.md).

## /etc/neutrino: what somebody decided

```
/etc/neutrino/
    hub/        the hub's configuration, one directory per module
    agent/      the agent's binding to its hub and its credentials
    client/     nothing today; a user's decisions are in the user's tree
```

Backing up `/etc/neutrino/` reproduces the appliance; nothing else at the
machine level needs backing up.

`config/` in a checkout is the hub's directory. The environment variable
`NEUTRINO_CONFIG_DIR` overrides both, which is what makes a second instance
testable. Details of the files themselves:
[../misc/config.md](../misc/config.md).

## /var/lib/neutrino: what the machine accumulated

```
/var/lib/neutrino/
    hub/
        generated/          rendered nftables, dnsmasq, hostapd, wpa_supplicant,
                            dhcpcd, smb.conf, xray and gateway configs
        geodata/            geoip.dat and geosite.dat
        cliproxyapi/        the AI gateway's accounts and tokens
        netbird/            the hub's own NetBird configuration and profile
        agent_module_cache/ the third-party packages the hub fetched for
                            managed machines
        agent_cache/        the agent packages this hub hands out
        services.json       which daemons the supervising service runs,
                            macOS and Windows only
        setup_token         the one-time token the setup wizard is reached
                            with, mode 0600, removed when setup finishes
        stood_down.json     which units the hub stopped so it could drive
                            the network
        xray_node_health.json
                            each exit node's recent measurements and the
                            exit the hub last pinned
        panel_tls_certificate.pem, panel_tls_key.pem
                            the certificate the panel serves and its key,
                            mode 0600, signed by the authority in
                            /etc/neutrino/hub/web/panel_tls/
        hub_update/         the hub's own package at the version running and
                            at the one being installed, the install script,
                            its log, and state.json
    agent/
        configured/         the desired state the hub sent, root only
        packages/           the module packages the hub sent
        vscode/             the VS Code CLI, read and run by every account
        cloudcli/           CloudCLI's Node.js, read and run by every account
    client/
        netbird/            the client's NetBird configuration and profile
        easytier/           the client's EasyTier networks and console file
```

State, not configuration: everything here is either derived from
`/etc/neutrino/` and rebuilt by the next render, or accumulated by a service
while it runs. Losing it costs a render or a re-login, never a decision.

`hub/agent_cache/` is the one thing here the package writes. The hub's own
package lays the agent builds it was made from straight into it, so enrolling
a device and letting an agent update itself need no network at all; an
upgrade replaces those files the way it replaces `/opt/neutrino/hub`, because
the package manager owns them. A platform the package seeded none for is
fetched once from the release its manifest names, checked against the hash
pinned there, and kept beside them. A file already here is served only while
it still hashes to what the manifest pins; one that does not is fetched
again. `nhub reset all` clears `agent_module_cache/` and leaves
`agent_cache/` alone: one is a cache the hub filled, the other is largely what
dpkg put there.

`hub/hub_update/` is where the hub updates itself from. The panel, or `nhub
update`, downloads the newest release's package into it beside the running
version's own package, writes the install script, and starts it outside the
panel's own process; the script installs, holds a health gate, and installs
the previous package when the gate fails, writing each turn into
`state.json`. Two packages stay: the one running and the one before it.

`hub/stood_down.json` is a note of what the hub did, not a copy of what
anybody else had: router mode stops the manager that was running and writes
down which units those were, so handing the machine back starts exactly
those. Losing the file costs one `systemctl unmask` by hand.

`agent/vscode/` and `agent/cloudcli/` hold programs the accounts of the
machine run, so those two directories alone are readable and executable by
every account (mode 755; on Windows the Users group gets read and execute),
while the rest of the agent's state stays root's.

**The databases live here rather than beside the binary that reads them.**
They ship with the package and are replaced by newer ones while the machine
runs, which makes them data rather than payload. xray looks beside its own
binary unless told otherwise, so every path that starts it says otherwise:
the unit, the supervisor, and the `xray -test` that validates a render before
it is accepted.

**A secret is protected by its directory on Windows.** Mode 0600 means
nothing there, so the installers create `C:\ProgramData\Neutrino\<package>`
with the descriptor `D:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)`, SYSTEM and the
administrators alone, and the vault key, the TLS private keys and the session
secret inherit it. On macOS the postinstall creates `config` and `state`
owned by root:wheel with mode 0700, and the `chmod 0600` on each secret holds
as on Linux. The agent's `state` alone is mode 755, so every account reaches
`vscode/` and `cloudcli/` under it.

## /var/log/neutrino: what happened

`hub/setup.log` holds the run of `nhub setup` that wrote it. Each run
truncates it, so its length is one setup rather than every setup this box
has had.

On Linux everything else logs to its unit's journal, where journald bounds it
by its own configuration. xray's access log is switched off in the rendered
config, its error log takes the console, and dnsmasq takes the console with
`log-facility=-`. The panel's DNS page reads dnsmasq's journal with
`journalctl --after-cursor`.

On macOS and Windows no journal exists. Each package's log directory holds one
file per process, `<name>.log`, rotated by size: for the hub one per child of
the supervising service, and `nhub` and the panel read the tail of that file
where Linux reads the unit's journal ([architecture.md](architecture.md)).
dnsmasq does not run there, so there is no DNS log. NetBird's own console
output goes to `netbird_console.log`; `netbird.log` is the file the hub's
start line names and the one `journal("netbird")` reads. The agent writes
`agent.log` and the client `client.log`.

## /run/neutrino: what is true until the next boot

```
/run/neutrino/
    hub/
        lockout             the panel's login lockout
        wpa_supplicant/     one control socket per radio the hub drives
        netbird.sock        the hub's NetBird daemon, macOS only
    agent/
        agent.sock          the root-only control socket
    client/
        easytier.sock       the EasyTier daemon's socket, open to local users
```

The lockout is on tmpfs deliberately: a reboot clearing it is part of the
design, and `nhub unlock` deletes the same file without one. The supplicant
sockets have their own directory rather than `/run/wpa_supplicant`, which is
where the machine's own supplicant puts its sockets; two of them in one
directory is a collision that shows up as whichever started second failing
to bind. On Windows the same things are named pipes: `neutrino_agent`,
`neutrino_client_easytier`, `neutrino_client_<user>`.
