# CLI

`nhub` runs the hub. `nagent` runs the agent on a machine the hub manages.
Everything either package can do is a subcommand of one of the two, and the
two share their verbs wherever they do the same thing.

> **This page is the decided shape, not what is installed today.** What ships
> now is `nhub install | render | serve | scan-secrets`, and a `nagent` that
> takes `--once` and `--no-ui` and has no subcommands at all.

## nhub

Runs as root. The panel it starts is root as well, for the reasons in
[standard/privilege.md](standard/privilege.md).

### setup

> `nhub setup`

First run. Prompts for the panel password, installs what the modules need,
renders every config, and starts the panel. Nothing else has to be run
afterwards.

Runs once. A hub that already has a panel password refuses and names
`nhub reset all` instead, so a second `setup` cannot land on top of a
configured box. Removing the package does not lift this: `dpkg --purge` leaves
`/etc/neutrino/config` in place on purpose, because it holds the proxy node
credentials and the device keys.

> `--password-stdin`

Read the password from standard input rather than prompting, for an unattended
install. The password is never an argument: an argument is visible in `ps` to
every user on the machine for as long as the command runs, and stays in the
shell history afterwards.

```bash
sudo nhub setup
printf '%s' "$PANEL_PASSWORD" | sudo nhub setup --password-stdin
```

### run

> `nhub run`

Runs the panel in the foreground. This is what `neutrino_web.service` starts,
and running it by hand is how its output is read without `journalctl`.

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

Prompts for a new panel password and stores its hash. Takes `--password-stdin`
on the same terms as `setup`.

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

> `--version`

Prints the package version and exits. The hub and the agent are released
together and a mismatch is not supported
([standard/agent_work_rule/release.md](standard/agent_work_rule/release.md)).
