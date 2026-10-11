# The Remote desktop module

The `remote_desktop` module is one of the two modules the agent's package
carries ([agent.md](../../agent.md), "The two modules the agent carries").
It holds one switch, off on a new machine. It is the one
place a desktop share is decided: the hub writes it, the state carries it,
and the agent makes it true and keeps it true across a restart of the
machine. `nagent rdp start` and `nagent rdp stop` are gone, from the command
line and from the control socket. The agent's code is
`modules/remote_desktop/`, with its config, constants and runner, one
applier per system, and `rdp/` under it, `modules/remote_desktop/rdp/`,
which reads who is at the screen and, through its `rustdesk.py`, writes
RustDesk's settings files.

## The desktop is the hub's order

With the switch on, the agent takes the machine's RustDesk over and runs its
own copy, the one in its package (the platform table's "RustDesk" row,
[agent.md](../../agent.md), "The platform layer"), under RustDesk's own
service names:

1. It stops RustDesk's service and session jobs and kills every RustDesk
   host on the machine whose program is not its copy. A process started with
   `--connect` is a viewer a person may be using and is left alone.
1. It keeps aside whatever is registered under RustDesk's service names and
   is not its own (a person's own RustDesk), in `remote_desktop/kept/` under
   the state root, and records what it registers in
   `remote_desktop/registered.json`.
1. It writes the settings files with the host stopped: the direct
   connection on port 21118, the rendezvous and relay servers set to the
   machine's own loopback, `127.0.0.1`, because an empty value means
   upstream's public server; and the seat password as `password = '<p>'` in
   the service's own `RustDesk.toml`, since `--password` from a copy outside
   the standard place sets nothing. The seat's host takes the password from
   the service and keeps it in the seat's `RustDesk.toml` in its own
   encrypted form, so the agent writes no password there. Every file it
   writes is copied to `kept/` before its first write and put back when the
   switch goes off.
1. It registers and starts its copy under RustDesk's names, as the
   platform table's "RustDesk" row says for each system, so the system's own
   service manager brings the host back after a restart and at each login.

With the switch off, the agent's copy does not run: it stops and removes what
`registered.json` names, kills every host of its copy, puts back what `kept/`
holds and starts it again when it ran before. No RustDesk process of the
agent's and no registration of the agent's is left. A person's own RustDesk
files are never changed or deleted. `nagent service uninstall` turns the
switch off first. A machine that leaves the hub cuts its share off at once
the same way, whatever the switch said: on `nagent leave`, and when a
`binding_unknown` refusal ends the binding because the device was removed on
the Devices page ([agent.md](../../agent.md), "What a refusal means to the
agent").

A failed step reports the module `failed` with `rdp_takeover_failed {step,
detail}` on the way on, or `rdp_restore_failed {step, detail}` on the way
off; the same press again tries it again ([agent.md](../../agent.md), "A
retry is the same press again").

**The seat password is the hub's.** A machine whose switch is on is given
one, generated once and sealed under the vault's data key in that device's
`rdp.json`. It is delivered in the `desktop` section of the state. The agent
writes it into RustDesk's settings whenever it changed and keeps it in a
root-only file so it knows what it already set. It enters neither the
agent's store nor any report.

The panel never shows it: the device drawer offers **Reset seat password**,
which generates a new one and disconnects every viewer. A client that presses
**Connect** opens a `service` stream, the hub unseals the password for that
one close, and the viewer is spawned with it.

**What leaves the machine.** With the rendezvous and relay servers on the
loopback the host sends nothing to RustDesk's servers. One thing remains
that no option of RustDesk 1.4.9 turns off: when its server starts on a
machine with a global IPv6 address, it asks three public STUN servers
(`stun.l.google.com`, `stun.cloudflare.com`, `stun.nextcloud.com`) for
that address, and on every machine it looks their names up. The request
carries no id and registers nothing.

The module reads `running` while the agent's RustDesk service runs under
RustDesk's names, whether anybody sits at the screen or not, so a headless
machine with the switch on reads `running`; `stopped` while the switch is
off and none of the agent's RustDesk processes runs.

**A share is declared only once it listens.** RustDesk's root service holds
no port of its own; it spawns a second process into the session of whoever
is logged in at the seat, and that process is what listens. The agent reads
the system's socket table, as the platform table's "Seat" row does, for its
copy listening on 21118; it opens no connection to the host. So a machine
with nobody logged in has nothing listening, which `rdp_nobody_seated`
refuses in front of, and a Wayland session that has not granted screen
capture reports `rdp_screen_not_allowed` instead of a desktop nobody can
see. Whose desktop a peer sees is whoever sits at the screen; the report's
`account` names them and decides nothing.

**An upgrade replaces the copy under a running host.** The package lays
the new copy over the old one while the host registered under RustDesk's
names keeps running the old program, which then fails to start its session
host from a file that is gone. So the agent, when it starts with the switch
on, compares the copy's running processes with the copy on disk and, when
one runs an older program, stops the host and starts it again under the
same registration and settings. On Linux that is the file each process
runs; on macOS, when each started against when the copy was written; on
Windows, the image each process really runs, read with
`QueryFullProcessImageName`: Windows Installer moves an executable in use
into `C:\Config.Msi` and gives the new one the build's own time, while
`Win32_Process` still names the old path, so neither the path WMI reports
nor a time tells a replaced host apart. This is not an apply of the state,
and the mark of the state last tried stays.

**A share made by the old command is kept.** An agent of a version that had
`nagent rdp start` recorded a share in its store. The package that upgrades
it takes away the RustDesk the old package installed at the system's
standard place, so the agent, when it starts and finds that record, takes
the machine's RustDesk over with its own copy as the switch's way on does,
and until the first state that names `remote_desktop` it keeps that share
running and reports it.
A share the agent runs for that record is declared with `origin`
`command`. A hub that receives `desktop.is_shared` true with `origin`
`command` from a device with no `remote_desktop.json` writes the switch on
for it, so an upgrade closes no share; a share declared with `origin`
`switch` is never adopted. A leave or a removal ends the record with the
share.

The declaration is the `desktop` section of every report,
`{is_shared, origin, account, share_id, port, attention, connected_count}`,
`origin` being `switch` for a share the switch made, `command` for one an
old command's record keeps running, and empty while nothing is shared. The hub
pairs it with the device's address, chosen for the caller's network
([protocol.md](../../protocol.md), "Devices on the channel"), and keeps it in
memory alone. It dies when the machine stops sharing, stops reporting, or the
hub restarts, and the next report from a machine still sharing puts it back.

The module also detects a person's own AnyDesk or TeamViewer, which is a
detection of this module and no module of its own: the commands that find
each program are the module's constants, under `REMOTE_DESKTOP_`. The agent
detects what is there, brings a stopped daemon up, reads the id a peer
connects to and sets the unattended password when the drawer asks, as the
seated account for AnyDesk and as root for TeamViewer, because that is where
each keeps its configuration.

## On a Mac

On a Mac the connections land in the `RustDesk --server` job of the signed-in
session (the LaunchAgent `com.carriez.RustDesk_server`), not in the root
service alone. That job takes its configuration from the root service once,
when it starts, and from then on pushes what it holds in memory back to the
service whenever that changes, so a file written under a running job is
overwritten within a second. So the host configures a Mac by booting out
the job and then the service, writing both copies, and bootstrapping the
service and then the job. The two plists keep upstream's labels, under
which the root helper answers the session's host; under a label of the
agent's own the host logs that it cannot reach `ipc_service`. The session
plist's `KeepAlive` is true, so the host comes back after macOS quits and
reopens it for the Screen Recording grant, and launchd starts both at boot
and at each login from `/Library/LaunchDaemons` and `/Library/LaunchAgents`,
the only folders it reads. The share is declared only once the direct port
listens, as everywhere.

A Mac shows a peer nothing until RustDesk holds both screen recording and
accessibility, which only somebody at that Mac grants, and the privacy
database that records them is closed to root, so the seat does not read it:
its attention is empty. Instead, the switch turning on puts a dialog on that
Mac's screen, in the signed-in session through `step-down`
([agent.md](../../agent.md), "Acting for an account"), naming the two
permissions, and opens the Screen Recording pane of the system settings;
RustDesk is started whether or not the person has granted them yet. The hub's
`rdp` entry carries the machine's `platform_os`, and a client shows a
standing hint under a Mac's entry ([client.md](../../client.md)).
