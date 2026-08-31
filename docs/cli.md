# CLI

`nhub` runs the hub. `nagent` runs the agent on a machine the hub manages.
Everything either package can do is a subcommand of one of the two, and the
two share their verbs wherever they do the same thing.

## nhub

Runs as root. The panel it starts is root as well, for the reasons in
[standard/design/privilege.md](standard/design/privilege.md).

### setup

> `nhub setup`

First run. Prompts for the panel password, installs what the modules need,
renders every config, and starts the panel. Nothing else has to be run
afterwards.

Runs once. A hub that already has a panel password refuses and names
`nhub reset all` instead, so a second `setup` cannot land on top of a
configured box. Removing the package does not lift this: `dpkg --purge` leaves
`/etc/neutrino/hub` in place on purpose, because it holds the proxy node
credentials and the device keys.

With no arguments it asks, one question per screen, each with a default that
Enter takes.

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

```bash
sudo nhub setup
sudo nhub setup --stdin < answers.json
sudo nhub setup --json answers.json
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
  }
}
```

`mode` is one of `server`, `router`, `one_arm_router` or `bypass_router`;
the wizard shows each with its underscores as spaces. What each is for,
and which of `wan`, `lan`, `trunk`, `upstream_gateway` and `lan_vlan_id`
it reads, is what the wizard's own screens explain.

### run

> `nhub run`

Runs everything this machine needs in the foreground: the panel, the proxy
core and the AI gateway. On a box with units this is a second copy of what
systemd is already running; it is meant for a working copy, which has none.

> `--only-web`, `--only-xray`, `--only-cliproxyapi`

Runs one of them, and is what each unit's `ExecStart` names. The unit decides
who the process runs as and what it may reach for — the proxy core is
unprivileged with two capabilities — and `run` replaces itself with the binary
so nothing sits between systemd and the daemon it watches.

Running one by hand is how its output is read without `journalctl`.

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
the SSH keys, and the AI provider keys. Nothing recovers them but a backup of
`config/`; take one first ([standard/misc/config.md](standard/misc/config.md)).

> `nhub reset`

Lists what can be reset and does nothing. Resetting is always named.

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
