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
    generated/      rendered nftables, dnsmasq, smb.conf, xray and gateway configs
    geodata/        geoip.dat and geosite.dat
    cliproxyapi/    the AI gateway's accounts and tokens
```

State, not configuration: everything here is either derived from
`/etc/neutrino/` and rebuilt by the next render, or accumulated by a service
while it runs. Losing it costs a render or a re-login, never a decision.

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

The login lockout, and nothing else. It is on tmpfs deliberately: a reboot
clearing the lockout is part of the design, and `nhub unlock` deletes the same
file without one.
