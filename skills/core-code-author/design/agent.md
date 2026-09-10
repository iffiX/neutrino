# The device agent

The agent is the hub's presence on a managed machine: one service with the
platform's highest privilege that executes the hub's orders, reports what
is true, and answers to the people sitting at it — each within the scope
their identity owns. Its own code is pure standard library; the package
carries the interpreter that runs it and the bindings its window draws
through, so it installs on a machine with no Python and touches none the
machine already has. Running on whatever Python a device happened to have was
a property this project had and gave up: a window needs bindings, and a
machine's own interpreter is not a place to install them.
Why the system is shaped this way is
[architecture.md](architecture.md) ("The agent channel is pinned TLS",
"Managed is a completed handshake"); this page is the agent's own design:
who may command it, how state moves, how local people reach it, and where
the platform seam runs.

## Who may tell the agent what

Two authorities, and nothing else: the hub over the pinned channel, and the
machine's own people over the local control channel. What each may touch is
decided by which partition a thing belongs to and by who is asking — never
by which door they used.

**Modules and services.** Everything a managed machine offers splits in
two, and the words mean the same thing on the hub's pages and the agent's:
a module is what a machine has installed, a service is what the hub
publishes.

- **Modules** are machine software the hub administers — a remote desktop,
  the SSH server, cc-switch, a share's mount tooling. Everything that puts
  software on a machine or takes it off is a module: a service never
  installs anything as a side effect, so the Modules panel is the whole
  answer to "what has the hub put here". The panel's device drawer
  switches them; the agent's page shows them and lets a privileged caller
  toggle them too. A local toggle is never applied locally: it rides up
  with the next heartbeat, the hub decides, and the answer comes back as
  an order, so the drawer and the page cannot disagree for longer than one
  beat. **The agent never downloads a module**: the hub's cache fetches it
  and its controller hands the bytes down, one order at a time per machine
  ([architecture.md](architecture.md), "The hub installs; the agent is an
  outpost") — and uninstall rides the same queue, so every module action
  is ordered, exclusive, and leaves its output behind. One pair of verbs
  everywhere: a module is **installed and uninstalled**, and the mechanics
  are each platform's own. The SSH server's uninstall genuinely removes
  the package on Linux and the capability on Windows; on macOS, whose
  sealed system volume nothing may remove, install and uninstall drive
  Remote Login on and off and no binary moves. A platform that carries a
  module natively with nothing to switch (SMB mounting on Windows and
  macOS) shows the row as **built in**, with no button.
- **Services** are what the machine's people do with what the hub
  publishes — pointing an account's AI tools at the gateway, mounting a
  published share, opening a published link, forwarding a published port.
  They are visible and decided **only on the machine**: the panel neither
  renders nor controls them. The hub's part is the service list and, for
  the ai type, the per-account credential; every other choice, and every
  secret it takes, stays local. A service that needs software on the
  machine **declares the modules it depends on** — the dependency is
  declared, compared and worded, never resolved by the service installing
  something itself.

| Capability | Privileged | Ordinary account |
| --- | --- | --- |
| Read binding, status, modules, the service list | yes | yes |
| Connect to a hub / disconnect | yes | no |
| Install and uninstall modules | yes, as the panel does | no |
| ai service: an account's tools | yes, any account | own account only |
| file service: attach a share | yes, at any path | yes, where the account may write |
| port service: forward | yes | yes — a forward is machine-wide and every scope sees it |

A control the caller's scope does not own is **disabled, never hidden**:
an ordinary account sees the Connect button and the module toggles greyed
out, because a page that hides what privilege would show reads as broken
rather than as locked.

Privileged means the platform's own idea of administrative identity: uid 0
on Linux and macOS, an elevated Administrators token on Windows — under UAC
the same person's non-elevated shell is an ordinary account, which is the
distinction UAC exists to draw.

## What the beat carries

The agent beats every few seconds. Up goes what the machine is: hostname,
agent version, metrics, the platform tuple, the machine's human accounts —
the platform's own judgment of who is a person, root and system accounts
never listed — each module's state, the most recent error worth showing,
and any pending requests. Down comes the catalog when the agent's copy is
stale (compared by `catalog_hash`, so a converged fleet is never
re-shipped it), any order the controller has open for this machine, the
device's operation stream, the AI credentials for accounts the hub has
granted, queued commands, and the hub's version.

**A click is one order, not a standing wish.** The hub keeps no record of
what a machine "should" have: pressing a button creates one order, the
order runs once, and what the machine reports afterwards is simply shown.
Software somebody installs or removes by hand is displayed, never fought.
Orders and failures live in the controller's memory; a hub restart forgets
them, and the person asks again — before release, machinery whose only
purpose is surviving a restart is refused outright
([kill_on_sight.md](../kill_on_sight.md), "Unasked survival machinery").

**The catalog** is the hub's answer to "what exists for this machine", in
two halves under one hash: the module manifests, and the service list.
The list carries no secrets, ever; the one secret a service takes from
the hub — an account's gateway key — travels only in that device's
per-beat reply.

**The service list is typed.** Every entry is
`{id, type, title, payload, is_healthy, source, description, modules}`,
and the five types are closed until a sixth earns its place:

| type | payload | agent behavior |
| --- | --- | --- |
| `web` | url | Open |
| `port` | host, port | Connect / Disconnect (a loopback forward) |
| `ai` | endpoint, protocol, models[] | per-account configuration, applied together |
| `file` | protocol, host, share | Config, then Mount / Unmount |
| `rdp` | protocol, host, port | Connect (the local client, at that address) |

Entries come from three sources and only three: a hub module declares its
own (Gitea a web entry, Samba a file entry per share, the AI gateway an ai
entry, the container runtime a port entry per published container port),
live only while the module runs — health is the module's, never a second
opinion; a person declares one by hand for something outside the hub,
probed the way declared services are; or **a managed machine declares one
for itself**, which only the `rdp` type is. `description` is the declarer's
one line of provenance — "published by container mysql:8.0" — worded by
whoever declared, so the types themselves stay general. A payload host that
is the hub's own address (loopback included) is resolved per device at
heartbeat time to the address that device actually reaches, the way the ai
endpoint always was; a device-declared host is another machine's and is
never rewritten.

**Where a machine is comes from its channel.** The hub records the peer
address of every beat and uses that wherever a device's own address is
needed: the share it publishes, the LAN its catalog is composed for, the
address the panel shows. A scan sees only the LANs this box serves, and a
stored SSH host is a credential rather than a location, so neither is the
answer: SSH installs the agent and drives power, nothing more. The record
follows the machine, because a beat from a new address is the machine at
that address.

**The `device` source is the machine's own word, and it expires.** Only an
agent can declare an rdp entry: the panel's form offers no such type and no
hub module publishes one. The declaration rides the heartbeat as
`{is_shared, share_id, port}`, the hub pairs it with the address it holds
for that device — never one the beat names — and the entry lives in the
panel's memory alone. It dies when the machine stops sharing, when the
machine stops beating, and when the hub restarts; each time, the next beat
from a machine that is still sharing puts it back. The access password a
share is set up with is the machine's: it is never in the declaration,
never in a backup, and the hub is never told it.

**A service names the modules it needs.** `modules` lists the module names
the entry cannot work without — an ai entry names `cc_switch`, a file
entry names `samba_mount`, an rdp entry names `rustdesk`, web and port
entries name nothing. The list is
composed hub-side with the rest of the catalog, and every surface
satisfies it the same one way: compare the names against the machine's
reported module states. A service whose dependencies are not all on the
machine renders **greyed but present**, its controls disabled, under a
notice in the error color naming the missing modules and that installing
them takes the privileged page. An ordinary caller can go no further; a
privileged caller's notice carries one action that queues every missing
module, in order, through the one install queue — nothing installs
implicitly, and the Operation output shows the queue working.

**Status is typed.** A module or service reports `state` plus
`{code, params}` — never an English sentence — and every surface does its
own wording. The agent's `last_error` crosses the wire the same way, so a
device that is unhappy says why on the panel, not only on its own page.

**Module states are one closed table.** Every module on every platform
speaks the same six tokens — a surface that meets a token outside this
table shows "waiting for the agent", which is the word for a machine that
has not reported:

| Steady | Transient | Shared |
| --- | --- | --- |
| `absent`, `installed` | `installing`, `uninstalling` | `failed`, `unsupported` |

A module kind the agent has no runner for is `unsupported` — an older agent
meeting a newer hub's catalog is a machine that cannot have it, not one that
has not answered — and a row in that state offers no button on either surface.
A row the platform carries natively is worded **built in** rather than
installed, and `failed` is always accompanied by its `{code, params}`,
worded from the surface's own table. Three invariants
hold everywhere a state is drawn: every transient token is in the
surface's busy set, or a row mid-step offers the opposite button; a
surface's optimistic step (the state it paints the moment a person
clicks) stands at most two minutes before the machine's own report — or
its silence — takes over; and a new `code` lands with its wording in the
same change, which the page's completeness test enforces.

## The agent's page

Three sections under outer titles set in the hub's module-page style —
**Status**, **Modules**, **Services** — in that order on the agent as on
the hub. Status is one panel: the connection card, its controls greyed for
an ordinary caller. Modules is one panel of rows, install/uninstall each,
greyed likewise. **Every row is the same three lines** — its title, where
its software comes from, and where it stands — with the description as the
row's tooltip rather than a fourth line, and the rows in one order the hub
decides so the drawer and the page cannot disagree: what the machine's own
packages carry, then what this hub fetches from a public repository, then
what a person installs from a vendor themselves, by title inside each. The
middle line names a repository, a company, or `system`; where the hub
conveys the bytes itself the name links to the exact source and the license
follows it, which is the whole of what a copyleft license obliges — no copy
of the source is kept here. Services is
one panel per type — Web, Ports, AI, Files, Remote desktop, Remote
desktops — and a panel with staged,
unapplied edits lights its frame the way the hub's panels do; unhealthy
entries render greyed with their state, never hidden. Remote desktop is
the one panel that stands with no entry behind it: sharing is decided on
the machine, so the panel is there whether or not the fleet publishes
anything.

**A service that acts on accounts names them on its own panel.** AI's
enabled users are a multi-select — one machine serves several people's
tools; a mount and a share are single-select chips — a mount belongs to
one home, a screen seats one person. The chip list is the scoped account
list every state read already carries, so an ordinary caller is shown
themselves and nobody else, and root or the hub is shown everyone; naming
anyone else from an ordinary scope is refused, and naming an account the
machine does not have is refused by name. The share's chip preselects the
account at the screen, and a mount's the record's own.

One **Operation output** panel closes the Modules section, and it is the
same panel the hub's drawer shows: whenever an agent install, reinstall
or uninstall, or a module install or uninstall, is running or has just
run, the panel is present with that operation's stream. The hub holds the one per-device stream and both surfaces render
it, so an operation started on either side appears on both, line for
line — neither surface keeps a private log, and the two can no more
disagree about what is running than the module rows can.

**The hub's drawer mirrors the page for a managed device**, in its own
order — Modules, Operation output, Services, Remote desktop — and its
Services block is operable: an ask there is the page's own verb, queued on
the device's command channel and run by the agent in the privileged scope,
with the typed refusal riding the result back for the drawer to word. The
verb set is closed — the AI apply, a mount naming whom it is for, an
unmount, a share naming its account and password, an unshare — and what
cannot be asked from there is not offered: a port forward opens on the
machine's own loopback. A share's access password rides inside the one
ask, the way a mount's credentials do, and lands in a root-only file on
the machine. The drawer's rows are the machine's last
beat, which carries the mount records and the AI rows up beside the module
report, credentials in none of it.

The page redraws only when the payload actually changed, and never while
the person holds a text selection, a focused form field, or an open
dialog — a self-refresh that eats a selection is a bug, not a cadence.

**Web.** One row per entry: title, url, description line, an Open button.

**Ports.** Connect starts a relay from `127.0.0.1` — the entry's own port
number when free, otherwise a free one the row names — and Disconnect
closes it. A forward binds the loopback the whole machine shares, so it is
machine state every scope sees.

**AI.** Depends on the `cc_switch` module, so the panel stands behind the
missing-modules notice until that is on the machine. One chips row of the
machine's human accounts — a privileged caller sees them all, an ordinary
caller exactly their own — beside a Config button and an Apply button. A chip stages whether that account's
tools point at the gateway; Config stages what they point with, per tool
and honestly per tool's own knobs: Claude Code's four role slots
(default, opus, sonnet, haiku), Codex's one model and its reasoning
effort, Gemini's one model — every choice drawn from the ai entry's
`models[]`. Apply commits the staged set: the agent asks the hub for each
targeted account's (device, account) key, writes the tools' own
configuration, and puts an untargeted account's configuration back,
revoking its pair's key. Keys per pair are what makes usage meter to the
person; the AI page's Access panel lists them. Acting on an account that
is empty or not among the reported ones is refused with
`{"code": "no_target_user"}`, and the guard is symmetric — activation and
deactivation check it alike. No chip is ever preselected: what the page
stages is only ever what a person chose.

**Files.** Config asks for the share's own username and password and a
path — typed, or picked in the browse dialog the agent feeds, whose
listing runs as the caller's identity, so an ordinary account browses only
what it may write. Mount attaches, Unmount detaches. The panel depends on
the `samba_mount` module — the mount tooling, `cifs-utils` on Linux —
declared like every other dependency rather than installed on the way to
a mount. The password becomes a root-only credentials file on this
machine and never travels to the hub. A path under the asking account's
home is ownership-mapped to that account;
anywhere else follows the share's own permissions. What shape a location
takes is the platform's own judgment — an absolute path on Linux and
macOS, an unused drive letter on Windows — and a location off that shape
is refused (`{"code": "mountpoint_invalid"}`). A mount point that is
not an empty directory is refused (`{"code": "mountpoint_not_empty"}` —
mounting over content hides it).

**Remote desktop.** Share asks for an access password, checks the
`rustdesk` module the way every dependency is checked, writes RustDesk's
direct-connection configuration to every path the service and the desktop
session read, and sets the password. Direct mode only: no rendezvous
server and no relay, `direct-server` on port 21118, and reachability is the
LAN's or the overlay's job. **One share per machine, owned by its
account**: an ordinary caller shares their own seat and stops their own
share, and the privileged scope controls anyone's — the mechanics run in
the root daemon either way. The share is declared
upward only once the direct port answers, so the fleet is never offered a
desktop that cannot be reached. macOS says **waiting for approval** until
then rather than claiming otherwise: screen recording there is one
person's allowance in System Settings, and no configuration substitutes
for it. Unshare closes the direct server in every file sharing opened and
withdraws the declaration.

**Which desktop a peer reaches is the seat's, never the caller's.** The
privileged scope decides who may configure the share; it does not decide
what is shown. RustDesk's root service holds no port of its own — it
spawns a second process into the session of whoever is logged in at the
seat, and that process is what listens on 21118. So sharing from a root
shell shares the logged-in person's desktop, and a machine with nobody
logged in has nothing listening at all, which is what `rdp_no_desktop`
refuses in front of and what waiting for the port to answer would
otherwise sit through. Setting the password is the same story from the
other side: it travels over the service's own socket, which starts
accepting after the platform's service control has already returned, so
the call is repeated until it takes rather than reported as a refusal —
nothing else the binary offers proves that socket is up.

**Remote desktops.** One row per machine the fleet says is sharing, its
own excluded, and Connect launches the local RustDesk client at that
address. The password is not the hub's to pass on: whoever shared the
machine tells whoever connects.

Service choices are machine state: they live in the agent's own store,
survive a hub restore untouched, and appear in no hub backup. The one
secret a service on the machine keeps — a mount's login, a share's access
password — lives in a root-only file beside the store, never in it.

## The local control channel

Local access is one transport serving one API, and identity comes from the
operating system, not from a password: **a control socket** — a Unix socket
on Linux and macOS, a named pipe on Windows. Any local account may connect;
the peer's identity is read from the kernel (`SO_PEERCRED`,
`LOCAL_PEERCRED`, pipe impersonation), and the caller gets the scope that
identity owns. Nothing a request carries can name a different caller.
`nagent` talks here, and so does the agent's window. Connections persist
between requests, so a handed-over connection keeps the scope its opener
owned for its whole session.

`nagent gui` is how a person opens the agent's window: the invoking process
connects to the socket — fixing the session's scope as whoever ran the
command — and hands the connected descriptor to a window process running as
the desktop user, `SUDO_USER` under sudo and the invoker otherwise, so no
privileged GUI process exists. The window embeds the platform's own web
view — WebKitGTK pinned to the 4.1 API on Linux, WebView2 on Windows,
WKWebView on macOS — loads the page from the package's own files, and
carries the page's requests over that one inherited connection through a
message bridge: the shell forwards method, path and body, and nothing
else the page says reaches the agent. Nothing is printed for a person to
copy, and no browser is ever launched for the agent's own page — `service
web open` still opens one, because a published remote URL is not the
agent's page. A machine without its web view refuses with a typed code
naming the package to install.

Windows is the one deviation: the elevated invocation hosts the window
itself and opens the pipe per request, the kernel reading the same
identity on each one — elevation there is a token on the same desktop
session, and a hand-off to a de-elevated process buys nothing a per-request
kernel read does not already give.

The desktop menu entry runs `nagent gui`, so a double-click lands in the
clicking account's own scope; `sudo nagent gui` opens the privileged
window. One page serves both — what it shows is the connection's scope.

## Acting for an account

The agent holds the platform's highest privilege, so reaching down to an
account is the platform's own step: `runuser` on Linux, `su` on macOS —
never `sudo`, for the same reason the hub bans it
([privilege.md](privilege.md)). Windows has no general way to become
another user without their password, so account work there is file work:
the agent writes into the account's profile, where inherited ACLs make the
files the account's own, and runs a process as an account only for the one
that is logged on.

That asymmetry sets a law for every feature: **prefer file-level operations
— read, write, remove in the account's home — and treat running a process
as the account as an optional capability.** A feature built on file
operations works on all three platforms; one built on run-as works on two.

## The platform layer

`neutrino_agent/platforms/` holds one class per platform behind one
contract, and a new platform is a new class — nothing above the seam
changes. The contract names intents, not mechanisms:

- enumerate human accounts; read a local caller's identity
- read, write, remove a file as an account; run a process as an account
- judge a proposed mount location; attach a share for an account at a
  location, detach it, ask if attached
- control the agent's own service; power actions; read metrics
- install and remove a package of a given kind

"Attach a share" rather than "mount" is deliberate: on Linux and macOS it
is a root mount with ownership mapped to the account, on Windows it is
stored credentials plus a per-session mapping, and one verb has to cover
both. Each platform likewise owns its account floor (uid 1000 on Linux,
501 on macOS, local profiles on Windows) — shared code never hardcodes a
number.

A platform advertises which capabilities it has, so surfaces grey out what
a machine cannot do; invoking an absent one anyway is refused with
`{"code": "unsupported_platform"}`, never guessed at.

## Two ports, one process

| Port | Transport | Serves | Authenticated by |
| --- | --- | --- | --- |
| `listen_port` (default 8080) | plain HTTP | the panel: UI and every management API | login session cookie |
| `agent_listen_port` (default 8443) | TLS, pinned | `/api/agent/*` and nothing else | enrollment ticket, then the device token |

Both are uvicorn servers in the one `nhub run --only-web` process, sharing one
`PanelRuntime` — that shared runtime is where a ticket generated on the panel
port is spent on the agent port. The panel app does not include the agent
routes, so they cannot be reached in plaintext; there is no fallback and no
migration path, because nothing released ever spoke the old way.

The firewall opens the agent port toward **every served network**, exposed or
not, beside the DHCP and DNS accepts: exposure gates what the box hosts for
people, and an agent heartbeating is the hub managing its own devices, not a
service somebody opted into. The panel port opens only where exposure says so.

## The identity agents pin

`nhub setup` writes a self-signed pair under `config/web/agent_tls/`
(`certificate.pem` in the clear, `key.sealed` — the private key sealed under
the vault's data key, unsealed into `/var/lib/neutrino/agent_tls_key.pem`
mode 0600 for serving): EC P-256, valid ten years — the
validity window is decoration, because verification is the fingerprint, and
the certificate merely has to outlive the box. `nhub apply` and
`run --only-web` also generate it when it is missing (a restored backup, an
upgrade), and **an existing pair is never regenerated**: the fingerprint is
pinned by every enrolled agent, and a new certificate is a fleet-wide
re-enrollment. `nhub reset all` deletes the pair the way it deletes the vault
key — the next owner generates an identity of their own.

The fingerprint is the SHA-256 of the certificate's DER encoding, 64 lowercase
hex characters, and it travels only out-of-band: inside an enrollment link a
signed-in person generated, never over the wire it is meant to verify.

## Joining: one ticket, five minutes, spent in one step

Generation happens on the panel port, behind the session: the Devices page's
per-device link, the blank link `nhub setup` prints, and the SSH install
action all call one path. A ticket is `secrets.token_urlsafe(18)`
(144 bits), held in panel memory only, dead after **five minutes** — long
enough to walk to another machine and paste, short enough that a forgotten
link is not a standing invitation. **Generating replaces whatever ticket was
out**: there is exactly one open invitation at a time, so the machine the
link was just made for is the only one that can join, and refreshing the page
quietly retires the link before it. A hub restart forgets tickets entirely.

The link is `neutrino://enroll/<base64url payload>` over one JSON object:

```json
{"urls": ["https://192.168.93.1:8443", "..."], "token": "...", "fp": "<sha256 hex>"}
```

`urls` carries every served address on the agent port, because only one of
them is on the joining machine's network and neither end knows which. The
base64url alphabet holds no character a shell splits or a URL escapes, so the
link pastes anywhere unquoted.

The agent tries each URL in turn. For every `https` URL it builds a TLS
connection with chain and hostname verification off and **verifies the peer
certificate's SHA-256 digest against `fp` immediately after the handshake,
before any request bytes leave the machine** — a mismatch closes the socket
and aborts the whole enrollment loudly rather than trying the next address,
because something answering with the wrong certificate is being impersonated,
and moving on quietly would hide that. An `https` URL with no fingerprint to
pin refuses to connect at all. The TLS floor is 1.2, set explicitly on the
client context.

The hub spends the ticket **atomically**: it is removed from the store in the
same step that fetches it (`dict.pop`), then judged — expired or unknown reads
identically as 401 — so two machines racing one link cannot both join. A
ticket generated for a device carries its MAC and routes the enrollee onto that
row; a blank ticket lands on the row the reported MACs name, or a new one.
The MAC decides **which row**, not **whether** — the ticket is the whole
authenticator, which is why a link is treated like a password and why it
lives five minutes.

The reply is the device token, `secrets.token_urlsafe(24)` (192 bits). The
agent stores `{gateway_url, token, fingerprint}` in its binding file,
root-owned mode 0600.

## Every later connection

Heartbeat, leave, report, download: each opens a fresh pinned connection —
the fingerprint is re-verified on **every** connection, not once at enrollment
— and carries the token in the JSON body. The hub looks the token up with
`secrets.compare_digest`, constant-time, against every stored device token.
Nothing about an agent is trusted from its network position; the token is the
entire identity.

## What each failure means to the agent

A binding either connects, or it cannot. Every definitive rejection — the hub
answered and said no — self-unbinds after three consecutive beats; only a hub
that did not answer at all is retried forever.

| The hub answered… | Exception | Counts toward self-unbind | The unbind reason says |
| --- | --- | --- | --- |
| wrong certificate | `GatewayUntrusted` | yes | the hub's identity changed (it was reset or reinstalled) |
| 401 / 403 | `GatewayRefused` | yes | the hub no longer knows this machine |
| version mismatch (409, `agent_newer_than_hub`) | `GatewayVersionRefused` | yes | this agent is newer than the hub |
| anything else, or nothing | `GatewayUnreachable` | no | — a broken wire is not an answer; the agent backs off and retries |

One counter covers all three rejection kinds: consecutive rejections of any
kind total together, and the third drops the binding. Only a successful beat
resets the counter — an unreachable beat in the middle of a run of rejections
neither counts nor resets, so an outage cannot launder a hub that keeps
saying no. The three-beat grace exists for the hub's sake: a hub caught
mid-restore refuses for a moment without shedding its fleet.

While the counter runs, `last_error` carries the channel's own wording, so
the local page and `nagent status` say which no is being heard before the
unbind lands. The reason left behind after it names the cause in plain words
and ends the same way every time: rejoin by pasting a fresh link from the
hub's Devices page. Rejoining is always that one action; there is no
bound-but-stuck state to diagnose. A wrong certificate still hands an
impersonator nothing — the agent hangs up before a byte is sent — but one
that keeps answering for three beats does talk the machine into unbinding,
and that is the trade accepted here: an attacker who owns the wire could
already deny the heartbeat, and what they gain over that is making the
owner paste one link.

## What an attacker in each position gets

**On the wire, or owning the network** (ARP, DHCP, DNS, a squatted IP): they
can answer the agent port, and the handshake completes — but they cannot
present a certificate whose DER digests to the pinned value without the
private key, so the agent hangs up having sent nothing. Pinning an exact
identity is stronger here than a CA chain: there is no authority to mis-issue,
only a second preimage to find. Downgrade is closed the same way — the
binding's URLs came out of a link the hub generated, are `https` by construction,
`http.client` follows no redirects, and https-without-a-pin refuses.

**Holding a captured link**: an unspent link within its five minutes joins
their machine as the device the link was generated for — the link *is* the
credential. Everything narrows that window: one outstanding ticket, five
minutes, single atomic spend, and the SSH install path generating and spending
in the same action. A spent or replaced link is dead.

**Impersonating an agent** without a token: enrollment needs the one live
ticket; heartbeats need 192 bits through a constant-time compare. Neither is
guessable, and the transport gives nothing away to help.

**Replay**: enrollment is replay-proof at the application layer — the ticket
dies on first spend. Heartbeats carry no nonce on purpose: every connection
is a fresh TLS handshake with fresh keys, so a captured beat can neither be
read nor re-sent (no 0-RTT early data exists on this stack), and the only
party able to replay plaintext already holds the token, to whom a replay adds
nothing. An application nonce would defend only against an attacker who can
already strip TLS — who fails the fingerprint check first.

**A local account on the managed machine**: the control socket answers them
with their own scope and nothing more — the binding, the install verbs and
other accounts' settings are the privileged scope's, which the kernel-read
peer identity withholds. The agent's window gives them the same and no
more, because its whole session rides a connection `nagent gui` opened as
the person who ran it. A website in their browser gets nothing at all: the
agent listens on no local port, so there is nothing for a cross-site form
to post to.

**Rooting the hub box** is outside the model: the key, the vault and the
panel all live there. The panel port itself is plain HTTP by
[architecture.md](architecture.md)'s local-trust decision; the agent channel
is hardened separately because it crosses networks the panel never does.

## One version, enforced at the door

The hub and the agent share a release version, with no compatibility window
([../../memory.md](../../../docs/memory.md), "Versioning"). The channel enforces it:
every enroll and heartbeat carries the agent's version, and every reply
carries the hub's.

- **Agent older**: the reply's newer number is the update request — a polling
  agent hears about a hub upgrade on its first beat after the restart. It
  downloads the hub's native package for its family and machine over the
  pinned, token-authed channel, verifies the SHA-256 the hub states, and
  installs it
  **detached** (a transient systemd unit), because the install restarts the
  agent service that started it. A failed attempt is not retried for the same
  target version and lands in `last_error`.
- **Agent newer**: the hub refuses the connection — 409
  `{"code": "agent_newer_than_hub", ...}`, on enroll and heartbeat alike.
  `nagent connect` prints that the hub must be updated first and writes no
  binding; a bound agent counts each such beat as a rejection and unbinds on
  the third, like any other no. The 409 is distinct from a 401 so the agent
  can say which thing is wrong — update the hub, then rejoin — not so the
  binding survives it.

## Atomicity is a rule, not a habit

Everything the channel and the panel mutate follows two laws:

- **On disk**: every `config/` write goes through `write_config` — a
  temporary file in the same directory, then `os.replace` — so a crash
  mid-write cannot leave a truncated file.
- **In the process**: every mutation takes the one `CONFIG_WRITE_LOCK`
  (re-entrant, in `utils/json_file.py`), **re-reads its file inside the
  lock**, applies the change, and writes — never writing a snapshot taken
  before somebody else's change. One global lock rather than one per file,
  because references cross files — a provider names a vault object, a device
  names a key — and a composite operation must nest under a single lock to
  be one step. Reads take no lock; a stale read is tolerable, a lost write
  is not. In-memory stores spend-and-judge in one operation, the way the
  enrollment ticket is popped before it is inspected.

The reason it is a law: the panel's sync routes run concurrently in a thread
pool, and a heartbeat writes the same file a rename on the panel writes. The
read-modify-write that loses is the one that read before the lock.
