# Files

Where an installed Neutrino puts things, and the one question each location
answers.

Five roots, and no sixth. A path that does not obviously belong to one of them
belongs to none of them, and the answer is to work out which question it
answers rather than to add a directory.

| Root | Holds | Question it answers |
| --- | --- | --- |
| `/opt/neutrino/` | The interpreter, `xray`, `cli-proxy-api` | What did the package put here? |
| `/etc/neutrino/` | `hub/`, `agent/` | What has somebody decided? |
| `/var/lib/neutrino/` | `generated/`, `geodata/`, `cliproxyapi/`, statistics | What has this machine accumulated? |
| `/var/log/neutrino/` | The panel's and dnsmasq's logs | What happened? |
| `/run/neutrino/` | The login lockout | What is true only until the next boot? |

Three more locations are the operating system's rather than this project's,
and are where they are because nothing else works: `/usr/bin/nhub` because a
command has to be on the path, `/lib/systemd/system/` because systemd reads
units from there and nowhere else, and `/usr/share/doc/neutrino-hub/licenses/`
because that is where a package's licences are looked for.

## What each operation leaves behind

Four operations can take things away, and each answers to one rule: the
package manager owns what the package put here, the person owns what they
decided, and `purge` and `reset` are the two ways of saying "all of it" —
one to dpkg, one to the hub.

| Operation | `/opt/neutrino` | `/etc/neutrino/hub` | `/var/lib`, `/var/log`, `/run` |
| --- | --- | --- | --- |
| upgrade / reinstall | replaced whole | untouched, byte for byte | kept; the next render rewrites what it derives |
| `apt remove` | deleted | **kept** | kept |
| `apt purge` | deleted | **deleted** | deleted |
| `nhub reset all` | kept (still installed) | replaced from the examples; the vault key and the agent TLS identity go with it | cleared of everything the hub wrote |

`remove` keeps the decisions because that is dpkg's own convention — a
package can come back and find its configuration waiting. `purge` is the
explicit request to forget everything, and it honours that to the letter;
what the vault held is gone with it, so a backup taken first is the only way
back. `/etc/neutrino/agent` is the agent package's and survives the hub's
purge untouched.

## /opt/neutrino — what the package put here

```
/opt/neutrino/
    python/     the interpreter and the hub installed into it
    bin/        xray, cli-proxy-api
```

Static. Nothing writes here after the install, and an upgrade replaces the
whole tree. Removing the package removes it entirely, which is the property
that makes it the right place for everything carried rather than configured.

Why the hub carries an interpreter at all, and what that costs, is in
[../agent_work_rule/release.md](../agent_work_rule/release.md).

## /etc/neutrino — what somebody decided

```
/etc/neutrino/
    hub/        the hub's configuration, one directory per module
    agent/      the agent's, when a machine runs one
```

A directory each, because a machine may run both and one root is one place to
look. Backing up `/etc/neutrino/` reproduces the appliance; nothing else here
needs backing up.

`config/` in a checkout is this directory. The environment variable
`NEUTRINO_CONFIG_DIR` overrides both, which is what makes a second instance
testable. Details of the files themselves:
[../misc/config.md](../misc/config.md).

## /var/lib/neutrino — what the machine accumulated

```
/var/lib/neutrino/
    generated/      rendered nftables, dnsmasq, hostapd, wpa_supplicant, dhcpcd,
                    smb.conf, xray and gateway configs
    geodata/        geoip.dat and geosite.dat
    cliproxyapi/    the AI gateway's accounts and tokens
    stood_down.json which units the hub stopped so it could drive the network
```

State, not configuration: everything here is either derived from
`/etc/neutrino/` and rebuilt by the next render, or accumulated by a service
while it runs. Losing it costs a render or a re-login, never a decision.

`stood_down.json` is a note of what the hub did, not a copy of what anybody
else had: router mode stops the manager that was running and writes down
which units those were, so handing the machine back starts exactly those. No
configuration of another manager is ever read, copied or restored. Losing the
file costs one `systemctl unmask` by hand.

**The databases live here rather than beside the binary that reads them.** They
ship with the package and are replaced by newer ones while the machine runs,
which makes them data rather than payload. xray looks beside its own binary
unless told otherwise, so every path that starts it says otherwise: the unit,
and the `xray -test` that validates a render before it is accepted. A path that
forgets fails at the moment a configuration is checked, which is the failure
this arrangement is written down to prevent.

## /var/log/neutrino — what happened

The panel's own log and the dnsmasq query log the DNS page reads. Owned by the
unprivileged service accounts that write them, which is why the installer
chowns rather than leaves them to root.

## /run/neutrino — what is true until the next boot

The login lockout, and the control sockets of the supplicants the hub runs.

The lockout is on tmpfs deliberately: a reboot clearing it is part of the
design, and `nhub unlock` deletes the same file without one.

```
/run/neutrino/
    wpa_supplicant/ one control socket per radio the hub drives
```

Its own directory rather than `/run/wpa_supplicant`, which is where the
machine's own supplicant puts its sockets. Two of them in one directory is a
collision that shows up as whichever started second failing to bind, and the
hub is not the one entitled to win that.
