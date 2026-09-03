# CLI

`nhub` runs the hub. `nagent` runs the agent on a machine the hub manages.
Everything either package can do is a subcommand of one of the two, and the
two share their verbs wherever they do the same thing.

## nhub

Runs as root. The panel it starts is root as well, for the reasons in
[standard/design/privilege.md](standard/design/privilege.md).

### setup

> `nhub setup`

First run. Prompts for the panel password and the vault passphrase — the one
a backup is later restored with — installs what the modules need, renders
every config, and starts the panel. Nothing else has to be run afterwards.

Runs once. A hub that already has a panel password refuses and names
`nhub reset all` instead, so a second `setup` cannot land on top of a
configured box. Removing the package does not lift this: `dpkg --purge` leaves
`/etc/neutrino/hub` in place on purpose, because it holds the proxy node
credentials and the device keys.

The mode decides whether it configures this machine's network at all. As a
`router` or a `one_arm_router` it addresses the interfaces; as a `server` or a
`side_gateway` it addresses nothing — the address, route and lease each port
arrived with are the ones it keeps, and the panel answers on them. So a VPS or
a laptop has the same address after setup as before it, and the last screen
says which of the two this run is.

With no arguments it asks where the questions get answered — here in the
terminal, or in a browser on another machine — and then asks them, one
question per screen, each with a default that Enter takes.

The browser is the same questions on the panel's own port, opened with a
one-time token the terminal prints. It is the panel's port because that is the
one the firewall opens to the served networks; the panel itself is therefore
started last, once the wizard has given it back. Pressing `t` stops waiting
and asks in the terminal instead, so a link that will not open is not a dead
end.

> `--stdin`, `--json <path>`

Take every answer as one JSON object instead of asking — from standard input,
or from a file. The two are mutually exclusive, and the document has to be
complete: a key this does not know is refused rather than ignored, because a
misspelled `upstream_gatway` silently becoming "no upstream router" is found a
week after the install.

Nothing is ever taken as an argument. An argument is visible in `ps` to every
user on the machine for as long as the command runs, and stays in the shell
history afterwards; `--stdin` additionally keeps the password off the disk,
which `--json` cannot.

> `--yes`

Agree to what installing the named modules entails. Some modules do more than
install packages — ZFS builds a kernel module, and a module may add a
repository outside the distribution — and the wizard's screens put that in
front of a person before it happens. A document names modules and cannot
agree to anything, so without this flag such a module is reported as not
installed and the rest of the setup goes on.

```bash
sudo nhub setup
sudo nhub setup --stdin < answers.json
sudo nhub setup --json answers.json
sudo nhub setup --yes --stdin < answers.json
```

```json
{
  "password": "…",
  "network": {
    "mode": "router",
    "wan": ["enp2s0"],
    "lan": ["enp1s0"],
    "address": "192.168.8.1",
    "prefix_len": 24
  },
  "proxy": {
    "links": ["ss://…", "vless://…"],
    "is_local": false,
    "socks_proxy_port": 1080,
    "is_socks_direct_enabled": false,
    "socks_direct_port": 1080
  },
  "services": ["samba", "podman"],
  "listen_port": 8080
}
```

`proxy` may be left out, which is what skipping it on the screen means. What
its keys do depends on what the box routes, and the screen asks each of them
rather than working any of them out: a box that serves a network sends
everything its devices send through the proxy, splitting Chinese destinations
out, and may also publish a SOCKS port that deliberately bypasses it
(`is_socks_direct_enabled`); a `server` diverts nothing, so its proxy *is* a
SOCKS port, on `socks_proxy_port`. `is_local` is this box's own traffic, on
either.

`services` names optional modules to install and nothing more — each is
configured on its own panel page afterwards. A document naming one has agreed
to whatever installing it does, which on a terminal is a question the screen
asks per module.

`listen_port` is the port the panel answers on; leaving it out keeps 8080.
The wizard asks for it whatever shape the box is, because every one of them
answers somewhere.

`mode` is one of `server`, `router`, `one_arm_router` or `side_gateway`;
the wizard shows each with its underscores as spaces. What each is for,
and which of `wan`, `lan`, `trunk`, `upstream_gateway` and `lan_vlan_id`
it reads, is what the wizard's own screens explain.

Once it has run, setup asks the panel for one enrollment link and prints it,
so the first machine can be brought in without opening the panel at all.

### run

> `nhub run`

Runs everything this machine needs in the foreground: the panel, the proxy
core and the AI gateway. On a box with units this is a second copy of what
systemd is already running; it is meant for a working copy, which has none.

> `--only-web`, `--only-xray`, `--only-cliproxyapi`, `--only-dnsmasq`

Runs one of them, and is what each unit's `ExecStart` names. The unit decides
who the process runs as and what it may reach for — the proxy core is
unprivileged with two capabilities — and `run` replaces itself with the binary
so nothing sits between systemd and the daemon it watches.

`--only-dnsmasq` names the generated configuration file outright and reads no
configuration directory, because how a distribution hands its dnsmasq a
drop-in is not something every family agrees on: Debian passes `--conf-dir` on
the command line and Arch reads `/etc/dnsmasq.d` not at all.

Running one by hand is how its output is read without `journalctl`.

### stop

> `nhub stop`

Stops everything the hub runs on this box: the panel, the AI gateway, the LAN
name service, the proxy core, and the routing state. The mirror of `run`, and
named the same way — the values are the hub's own service names rather than
systemd unit files.

> `--only-web`, `--only-xray`, `--only-cliproxyapi`, `--only-dnsmasq`,
> `--only-router`

Stops one of them, spelled the way `run` spells the same service: the pair is
read together, and a person who has typed one should not have to look up the
other. `--only-router` is the one name `run` has no use for, because the
routing state is a unit that finishes rather than a process to watch.

> `--only-supplicant --interface wlp3s0`, `--only-dhcpcd --interface enp2s0`

The two engines that run one unit per interface, named as `run` names them.
With no `--only` these are stopped too, on every interface `config/` says the
hub was driving: a box left holding a lease it asked for has not stopped
running the hub, whatever the panel is doing.

The optional modules are left running. Samba serves shares whether or not this
box routes anything, so a plain `nhub stop` is the hub going quiet rather than
the machine going down.

Nothing is disabled, so everything comes back at the next boot. Removing the
hub is the package manager's business, and undoing a setup is `reset`.

### apply

> `nhub apply`

Renders every module's config from `config/` and makes it true on the box:
writes the generated files, validates each with the real tool, and reloads
what changed.

The panel does this on every save, so `apply` is for the times the panel
cannot: after editing `config/` by hand, or when the panel itself will not
start.

### unlock

> `nhub unlock`

Clears the panel's login lockout and every fail2ban SSH ban. The lockout is a
file on tmpfs, and the panel notices it is gone on the next login attempt
without a restart.

### reset

> `nhub reset password`

Prompts for a new panel password and stores its hash. Takes `--stdin`, which
here is the password itself rather than a document — every command's `--stdin`
is the input that command needs.

> `nhub reset all`

Returns every module's config to its committed example and clears the panel
password, so the next `nhub setup` runs on a fresh box.

This destroys the proxy node credentials, the device records and their tokens,
the SSH keys, the wireless passphrases, and the AI provider keys. Nothing
recovers them but a backup of `config/`; take one first
([standard/misc/config.md](standard/misc/config.md)).

It also stops driving the network, on a machine where it was. The units the hub
started on each radio and uplink are stopped, the hub's own firewall table and
policy route are removed, name resolution goes back to the machine's own, and
whatever manager was stood down is started again. **No address is taken off
anything** — every interface keeps what it has, so the session that asked for
the reset is still there when it finishes.

Then everything the hub runs is stopped, as `nhub stop` does. A reset is the
box as it was before anybody set it up, and on that box none of this is
running: the panel has no password to let anyone in with, and every service
is configured from the examples rather than from what this machine was. It is
reached over SSH afterwards, until `nhub setup` runs again.

> `nhub reset`

Lists what can be reset and does nothing. Resetting is always named.

### vault

> `sudo nhub vault rekey`

Wraps the vault's data key under a new master passphrase, prompting for it
twice. Nothing sealed is re-encrypted — the records stay as they are, and
every backup taken afterwards opens with the new passphrase. Takes
`--stdin`, which here is the new passphrase.

### scan-secrets

> `nhub scan-secrets`

Checks what a commit would carry for secret material, across the whole
working copy. The one subcommand that never needs root: it reads the
checkout, not the machine. A finding is either real and removed, or safe
and marked `scan: allow` on its line.

## nagent

Most machines never see this. The agent installs with a desktop entry, and
clicking it opens the agent's own page on `http://127.0.0.1:8765`, which is
where the enrollment link is pasted. These commands do the same things from a
terminal, for machines with no desktop and for reading what went wrong.

### connect

> `nagent connect <link>`

Joins the hub the link names. The link comes from the hub's Devices page,
which mints a one-time token:

```
neutrino://enroll?url=https://192.168.100.1&token=<token>
```

A machine that has already joined a hub is asked before its binding is
replaced.

> `--yes`

Replaces an existing binding without asking.

### disconnect

> `nagent disconnect`

Leaves the hub. The machine keeps the agent and its local page, and can join
again.

### run

> `nagent run`

Runs the agent in the foreground. This is what the systemd unit, the launchd
job and the Windows scheduled task start.

> `--no-ui`

Does not serve the local page on `http://127.0.0.1:8765`. For a machine nobody
sits in front of.

### status

> `nagent status`

Reports what this machine is bound to, whether the agent is running, and
whether the hub answers — by sending one heartbeat, which is the only way to
tell a reachable hub from an unreachable one.

```
neutrino-agent 0.1.0
hub        https://192.168.100.1   connected
service    running
heartbeat  ok, 42 ms — next report in 5s
```

Three things break independently, and a device missing from the hub's panel
looks the same for all three: the machine never joined, the service is not
running, or the hub cannot be reached from here. This says which.

## Both

> `--dev`

Puts the five roots under `hub_dev_root/` in the working copy, so a checkout
runs a whole appliance of its own and deleting one directory undoes it. It
comes before the subcommand — `nhub --dev setup` — because the roots are
resolved as the hub is imported. `nhub --dev run` starts the frontend's dev
server as well. What `--dev` still does to the machine is in
[standard/design/install_and_dev.md](standard/design/install_and_dev.md).

> `--version`

Prints the package version and exits. The hub and the agent are released
together and a mismatch is not supported
([standard/agent_work_rule/release.md](standard/agent_work_rule/release.md)).
