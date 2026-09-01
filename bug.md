# What was found and what was done

One night's work: the three bugs you hit by hand, then a hunt for the rest.
Twenty commits, all local — nothing pushed. Every one has tests; the suite is
681 passed / 12 skipped, black, prettier, eslint and `nhub scan-secrets` clean.

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

## Left undone, deliberately

Real, verified, not fixed — each needs a design decision or more surgery than a
night's unattended work should take:

1. **A dropped task socket leaves an undismissable log.** `useTaskStream` sets
   an error the card never reads, so an install whose websocket drops leaves a
   truncated log with no result badge and no Close button, and the Services
   list is never refetched.
2. **Reloading the browser loses a running install.** Task ids live only in
   React state; there is no listing endpoint and no way to cancel a job. The
   card reads "not installed" with a live Install button while the install runs.
3. **`TaskStreamRegistry` and `runtime.enrollments` never shrink.** Every
   install, reboot and password set holds up to 2000 lines for the life of the
   process.
4. **A rejected xray config aborts the apply before the firewall and resolver
   are touched** — and a bad entry in the direct lists is read even with the
   proxy off, so the master switch cannot be used as the escape hatch its
   documentation promises.
5. **`is_proxy_in_path()` reads the ruleset file, which is written before it is
   loaded**, so the dashboard can report where traffic was *about* to go.
6. **Saving a device blanks its monitor** for one poll: the PUT response is
   built with no metrics, so the tile flips offline until the next refresh.
7. **`nhub setup --stdin` asserts consent** on the person's behalf — an answers
   document naming `zfs` starts a kernel-module build with no consent recorded.
   The HTTP path is sound; only the file path is not.
8. **A SOCKS listener on an occupied or privileged port** kills xray and takes
   LAN DNS with it, while the apply reports success: `xray run -test` builds the
   config but never binds, and `Type=simple` makes the restart return 0.
9. **`docs/standard/design/repository_tree.md` is stale** — it describes a
   layout from before the `hub/` and `agent/` split.

## The harness

`packaging/integration/panel_api.py` — signs in, walks every operation the four
panels offer, and checks what the box does. 126 checks: deleting to nothing
(every node, every listener, every VLAN, every exposed interface, fifty devices
added and forgotten), adding far more than anybody would (30 VLANs, 30
listeners, 1000 direct domains), and sequences that leave one page's state
stale in another. It runs on the machine under test, beside the two shell
matrices, and is deliberately not in pytest — it needs a live box.

    python3 panel_api.py <password> [network|proxy|services|devices ...]

A package was built from this code and both shell matrices run against a clean
install of it: guest/server untouched on Debian 12, guest/side-gateway
untouched on Ubuntu 24.04, owner round trip clean on Debian 12. The deb is at
`~/neutrino_dist/neutrino-hub_0.1.0_amd64.deb` and on xenode.

The VM `apitest` on xenode is patched to this code and green if you want to
poke at it; `fresh1` is where you left it.
