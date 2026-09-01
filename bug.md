# What was found and what was done

The three bugs you hit by hand, then a hunt for the rest, then the nine that
were left over. Every one has tests; the suite is 732 passed / 12 skipped,
black, prettier, eslint and `nhub scan-secrets` clean, and the integration
harness is green on a Debian 12 VM from install to reset.

How they were found: four Opus subagents read the Network, Proxy, Devices and
Services code paths in parallel while I drove a live VM through the panel's own
API. Nothing below is taken on an agent's word — each was reproduced or read
end to end before it was fixed.

## The three you reported

**Services and the wizard showed every optional module as installed.**
`SystemdServiceController.status()` decided "installed" by looking for the word
`not-found` in what `systemctl is-enabled` prints. Debian 12 prints
`Failed to get unit file state for netbird.service: No such file or directory`
instead — no `not-found` in it — so every missing unit read as present, and
Enable then failed with systemd's own error. Now it reads `LoadState`,
`ActiveState` and `UnitFileState` from `systemctl show`: machine-readable, one
call instead of two, no wording to guess at.

**Deleting the last exit node broke every apply.** The renderer raised on
"proxy on, no nodes", so every Apply failed with it — including the one that
would have turned the switch off. Now emptying the list switches the proxy off
in `config/`, turning it on with an empty list is refused, and the renderer
treats the state as off rather than unrenderable, so a hand-edited file cannot
wedge the box either.

**The device drawer disagreed with itself.** The Modules list read
`client.is_installed`, which is written when Install is *pressed* and never
cleared — not by a failed install, not by a stopped agent. The remote-desktop
block below it asks the machine over SSH. Now the features response carries
`is_agent_installed` and `is_agent_online`, and the list says "the agent is not
checking in, so what is on this device is unknown" instead of drawing
everything as absent.

## The two you mentioned in passing

**"All nodes went to 0 ms."** Three places rendered "not measured" as a
definite state: a disabled node was never probed and drew a red dot reading
*unreachable*; the dashboard drew an exit with no probe as alive; and
`time.monotonic()` counts from boot, so a panel starting early in one was
younger than its own cache and never probed at all. Fixed, all three.

**The DNS query count was wrong.** It counted every line in the log tail.
dnsmasq writes a `query`, a `forwarded` and a `reply` per lookup, plus a
`dnsmasq-dhcp` line per lease, into the same file — so the tile read three to
five times high. It now counts queries. The tile said "since boot"; it is a
256 KiB window, so it says "in the recent log". Following the log also replayed
the whole file as new arrivals on the first poll after the backlog.

## The worst one, which nobody had hit yet

**Switching to Router flushed every address and downed every port.** A machine
becoming a router holds no roles yet, and applying that state reached
`_apply_disabled` for every interface — which clears addresses and takes the
link down, including the one the panel was answering on. The box would have
gone off the network with no way back but a console. Introduced by me, in the
mode-first redesign, and caught before you pressed it.

## Found by driving the API

**systemd's start-rate limiter took DHCP and DNS down.** Every interface save
restarts `neutrino_hub_dnsmasq`. The default limit is five starts in ten
seconds; the sixth fails and the unit stays down until the window clears. Two
or three quick edits reach it — the LAN loses DHCP and DNS, and every later
save answers with the limiter's message. `StartLimitIntervalSec=0` now sits in
`[Unit]` for dnsmasq and xray, the two the panel restarts by design. (In
`[Service]`, where it is easy to put it, systemd silently ignores it — pinned
by a test.)

**A bad value written once broke every apply after it, including at boot.** A
`/0` prefix, a lease time dnsmasq cannot read, a MAC the kernel refuses, an
interface name this machine does not have: each was accepted, written, and only
then failed — and stayed written. The upstream-gateway case put the router unit
into a permanent boot failure on the test box. All four are now checked before
the write, and a next hop the kernel refuses is reported rather than raised, so
one interface can no longer take the whole apply down with it.

**Two exit nodes from one provider were one node.** A node's id was the first
label of its address, so `203.0.113.10` and `203.0.113.11` were both `203` and
the second was refused as a duplicate. It now carries a digest of address and
port.

## The rest, in one line each

- **Uninstalling podman** ran `apt-get remove -y debian rhel arch` — a dict of
  package names splatted for its keys — after already stopping the containers
  and deleting the Quadlets. Now goes through the family's own manager.
- **Samba's unit** was hardcoded to Debian's `smbd.service`, so on Fedora and
  Arch the panel installed it and then reported it missing for ever.
- **ToDesk's verify** was `which todesk`, which the hub's own probe documents
  as wrong. One Install press started a 50 MB re-download every 60 seconds,
  for ever. Fixed, plus a guard: a package whose verify never confirms is
  installed once, not on every re-check.
- **The device file** was a whole-file read-modify-write with no lock, rewritten
  by every heartbeat. Forget a device while one was in flight and it came back,
  credentials intact. Every write now re-reads first.
- **Installing the agent** minted a new token before the install ran, so a
  failed install killed a working agent permanently. A live agent keeps its
  token now.
- **Reboot and Shut down** were queued for any device that ever had the agent,
  even a dead one, and reported "exit 0" while nothing happened.
- **Forgetting a device** left its queued commands behind, to be delivered to
  whatever machine appeared on that MAC next.
- **Forgetting one device** un-pinned the SSH host key another still used.
- **Installing ZFS** added `contrib` to *every* apt source, including vendor
  repositories the panel itself had just installed — so every later
  `apt-get update` 404'd on a component that does not exist there.
- **Double-clicking Install** ran two installs of one module: two downloads
  writing one path, two package managers on one lock. The second press now
  joins the first.
- **A module that is not installed** answered Enable with systemd's raw error;
  it now says it is not installed. The journal endpoint took any line count,
  including `?lines=100000000`.
- **An unreachable device** reported its remote desktop as "not installed",
  advising you to install what may already be there. It now says it could not
  be asked, and why.
- **An unknown remote-desktop product** returned 200 and failed minutes later
  inside the task, because the validation sat in an async generator that
  calling never runs.
- **The balancer** accepted a probe interval of zero and a probe URL that is
  not one; **the resolvers** accepted an address that is not one and port 0.
- **Two of mine from the redesign**: "Apply ports" wrote the whole page draft
  — including an unapplied master switch — and the Proxy page never re-read
  the switch the node list can flip, so it showed "on" while nothing was
  proxied and the control did nothing.

## The nine that were left, and how each was settled

All nine are fixed and committed. What each one turned into:

1. **A dropped task socket left an undismissable log.** The stream hook now
   reopens once and replays the job from its first line — the panel restarting
   drops every socket it holds while the jobs behind them carry on. A second
   close with no result ends as a state the card can close, and refreshes the
   services list, because whatever the job did before it dropped is on the box.
2. **Reloading the browser lost a running install.** `GET /api/services/tasks`
   lists the jobs the panel is running, and the Services page adopts its
   module's job on load. No cancel: interrupting a package manager leaves dpkg
   needing `--configure -a`.
3. **The registry and the enrolment tickets never shrank.** Finished jobs are
   evicted past the most recent eight, which is what keeps a reopened drawer
   showing its install; lapsed tickets are swept whenever one is minted, and a
   ticket is minted only after the link it goes in is known to exist.
4. **A rejected xray config took the apply with it.** All three parts: the
   direct lists are checked when they are saved, the master switch off means
   they are not read at all, and an Apply that xray refuses still loads the
   firewall and restarts DNS, reporting the refusal.
5. **`is_proxy_in_path()` read a file written before it was loaded.** The
   ruleset is now written after the kernel takes it, in both the panel and
   `nhub apply`.
6. **Saving a device blanked its monitor.** The PUT answers with the metrics
   its agent reported, like every other view of a device.
7. **`nhub setup --stdin` asserted consent.** `--yes` is consent given on the
   command line; without it a module that does more than install packages is
   reported as not installed and the rest of the setup goes on.
8. **A SOCKS listener on a port that cannot be bound.** A port the box already
   holds is refused when it is saved, and xray is checked alive a second after
   its restart, with the reason carried out of its journal. No rollback.
9. **`repository_tree.md` was stale.** Rewritten around the two packages this
   repository actually ships.

Also asked for and done: every module page carries its unit's state beside the
title, so an xray that is not running is visible from the page it serves.

## The harness

`packaging/integration/` — one pytest file per page (`test_panel_api_network`,
`_proxy`, `_services`, `_devices`), beside `test_install_footprint.py`, which
checks a guest install left the machine addressing itself, and
`test_reset_hands_back.py`, which checks `nhub reset all` gave the network
back. `run_on_box.sh` walks a machine through the lot: snapshot, install, set
up, footprint, reset, set up again, then every page.

    ./run_on_box.sh /path/to/neutrino-hub_0.1.0_amd64.deb side_gateway

It needs a live box, so it is outside `hub/tests` and out of CI; without a
panel password every check skips. The two shell matrices it replaced are gone,
and what they proved that no API can see — configuration trees byte-identical
across an install, no manager masked, `resolv.conf` untouched — is
`machine_state.py` and the two files that read it.
