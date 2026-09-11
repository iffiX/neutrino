# The device agent

The agent is the hub's presence on a managed Linux machine: one root service
that keeps one socket open to the hub, hosts what the hub asks it to host,
reports what is true, and shares the machine's desktop when told. It draws no
window and listens on no port. Its own code is pure standard library; the
package carries the interpreter that runs it, so it installs on a machine
with no Python and touches none the machine already has. Everything a person
does with what the hub publishes belongs to the client, a separate package
in that person's own session ([architecture.md](architecture.md), "The shape
of the system"); this page is the agent's own design: who may command it, how
state moves, how the machine's root reaches it, and where the platform seam
runs.

## Who may tell the agent what

Two authorities, and nothing else: the hub over the pinned socket, and the
machine's own root over the local control socket. There is no third door and
no per-account scope: an ordinary account on the machine talks to the client,
never to the agent.

**Modules and services** are the two words that hold everywhere, on the
hub's pages, in the agent, and in the client:

- **Modules** are software the hub administers on a machine: Samba, Gitea,
  Podman, ZFS and the RustDesk host. The hub's Samba, Gitea, Containers and
  ZFS pages pick the devices that host each, and that pick is the device's
  desired state. **The agent never downloads a module**: the hub's cache
  fetches it and the module controller hands the bytes down as one order,
  one at a time per machine ([architecture.md](architecture.md), "The hub
  installs; the agent is an outpost"). Uninstall rides the same queue, so
  every module action is ordered, exclusive, and leaves its output behind.
- **Services** are what the hub publishes and what a client consumes: a web
  link, a port, the AI gateway, a share, a shared desktop. The agent composes
  none of them and renders none of them. Its only part is the one entry a
  machine declares for itself, its own desktop, described below.

| The hub may | Root on the machine may |
| --- | --- |
| Push desired state and open orders, commands and streams | Bind the machine to a hub, or unbind it |
| Install and uninstall modules, and configure them | Ask for the desired state now (`nagent sync`) |
| Reboot, shut down, reinstall the agent | Share the desktop and stop sharing it |
| Read and set up a person's own AnyDesk or TeamViewer | Read the binding and status |

Root is uid 0. `nagent` refuses any other account; the one thing anybody may
run is `nagent --version`.

## One socket, everything on it

The agent opens one WebSocket to the hub over TLS pinned by the enrollment
link's fingerprint, and reconnects when it drops. The hub never dials a
machine; SSH exists only to install or reinstall an agent from the Devices
page. Text frames are JSON, a binary frame is a stream id and its bytes.

Up: a `hello` when the socket opens, then a `report` every few seconds and
at once when something changed: hostname, agent version, the platform
tuple, metrics, each module's state, the most recent error worth showing,
and the desktop declaration. Down: the desired state whenever the hub's
copy differs from the hash the agent last applied, and every stream the hub
opens. **The hub opens every stream**, and there are four kinds: an order
(install this, uninstall that), a command (reboot, shut down, a module's own
verbs, a person's remote desktop tool), a validation, and the two that carry
bytes both ways, a shell and a file browser, each behind a credit window so
a long transfer never starves the reader. An order runs in its own thread,
one at a time, and closes with how it went; its output is one stream the
hub holds and both the drawer and the machine's own log read line for line.

**Presence is memory only.** Online, version and last seen live in the hub's
session registry; a hub restart forgets every machine until it reports again,
and nothing about a socket reaches `config/`.

**Desired state is one document per device.** The hub composes it from
`config/devices/<dir>/`: `modules.json`, which modules are on; one file per
module with its configuration; `rdp.json`, the sealed seat password; plus
the catalog resolved for the machine's platform and what the hub knows about
where it sits. It travels under one hash. The agent keeps a root-only copy,
compares on connect and on every `state` frame, and applies what differs in
one fixed module order: an enabled module that is installed is applied, an
installed module that is disabled is stopped, a module that is not installed
is left alone until an order installs it. The applied hash moves only once
every enabled module applied, so a failed apply keeps asking for the same
state until it takes. **Editing a module of an offline device is refused,
never queued**: the person is told the machine is away, and asks again when
it is back.

**The agent is handed conclusions, never a table to search.** The catalog it
receives is already resolved for its platform; it carries no manifest logic
and no version table. A module kind it has no runner for is `unsupported`,
which is an older agent meeting a newer hub, and the version lock
([../agent_work_rule/release.md](../agent_work_rule/release.md)) makes that a
prompt to upgrade rather than a state to reason about.

**A click is one order, not a standing wish.** Pressing a button creates one
order, the order runs once, and what the machine reports afterwards is
simply shown. The agent keeps no retry policy and no memory of past
failures: an order that failed is reported failed and never repeated,
because deciding to try again is the hub's, and there it is a person's word,
never a timer's. Software somebody installs or removes by hand is displayed,
never fought. Orders and failures live in the controller's memory; a hub
restart forgets them, and the person asks again. Before release, machinery
whose only purpose is surviving a restart is refused outright
([../kill_on_sight.md](../kill_on_sight.md), "Unasked survival machinery").

**Status is typed.** A module reports `state` plus `{code, params}`, never an
English sentence, and every surface does its own wording. The agent's
`last_error` crosses the wire the same way, so a device that is unhappy says
why on the panel. Module states are one closed table on every surface:

| Steady | Transient | Shared |
| --- | --- | --- |
| `absent`, `installed` | `installing`, `uninstalling` | `failed`, `unsupported` |

A surface that meets a token outside this table shows "waiting for the
agent", the word for a machine that has not reported. Three invariants hold
wherever a state is drawn: every transient token is in the surface's busy
set, or a row mid-step offers the opposite button; a surface's optimistic
step stands at most two minutes before the machine's own report, or its
silence, takes over; and a new `code` lands with its wording in the same
change, which the catalog completeness test enforces.

## The desktop is the machine's own word

Sharing a desktop is the one thing decided on the machine and reported
upward rather than ordered down. `sudo nagent rdp start [--user <name>]`
configures RustDesk for direct connection on port 21118, no rendezvous
server and no relay, and `nagent rdp stop` withdraws it. With no `--user`
the seat is `SUDO_USER`, else the one account at the screen.

**The seat password is the hub's.** A machine reporting the RustDesk host
installed is given one, generated once, sealed under the vault's data key in
that device's `rdp.json`, and delivered inside the desired state. The agent
sets it into RustDesk whenever it changed and keeps it in a root-only file
so it knows what it already set; it enters neither the agent's store nor any
report. The panel never shows it: the device drawer offers **Reset seat
password**, which mints a new one and disconnects every viewer. A client
that presses Connect asks the hub over its own socket, the hub unseals the
password for that one answer, and the viewer is spawned with it.

**A share is declared only once it answers.** RustDesk's root service holds
no port of its own; it spawns a second process into the session of whoever
is logged in at the seat, and that process is what listens. So a machine
with nobody logged in has nothing listening, which `rdp_nobody_seated`
refuses in front of, and a Wayland session that has not granted screen
capture reports `rdp_screen_not_allowed` rather than a desktop nobody can
see. The declaration rides every report as `{share_id, port, viewers,
attention}`; the hub pairs it with the address it holds for that device,
never one the report names, and keeps it in memory alone. It dies when the
machine stops sharing, stops reporting, or the hub restarts, and the next
report from a machine still sharing puts it back.

A person's own AnyDesk or TeamViewer is not a module. The agent detects what
is there, brings a stopped daemon up, reads the id a peer connects to and
sets the unattended password when the drawer asks, as the seated account for
AnyDesk and as root for TeamViewer, because that is where each keeps its
configuration.

## The local control channel

One Unix socket, 0600 under a 0700 directory, so the kernel refuses anyone
but root before a request is read and no handler judges identity. `nagent`
is its only client: `connect` binds the machine to the hub a link names,
`disconnect` unbinds it, `status` reads the binding, `sync` asks the running
service to fetch the desired state now, `rdp start` and `rdp stop` share and
unshare the desktop, and `run` is what systemd starts. Connections persist
between requests and each is served on its own thread. Every refusal is
`{"code": ...}`; a handler exception never drops the connection, the caller
gets `agent_internal` with the exception's class name and the traceback goes
to the agent's log.

An agent that has never enrolled still answers here, waiting for a link.
The binding, the applied desired state and what the machine decided for
itself live in one root-owned store written atomically; secrets never enter
it.

## Acting for an account

The agent is root, so reaching down to an account is `runuser -u <account>
--`, never `sudo`, for the reason the hub bans it
([privilege.md](privilege.md)). Today that reach is one thing: the seat
whose desktop is shared, whose RustDesk configuration lives in that
account's own session. Everything else the agent does is root's own work.

## The platform layer

`neutrino_agent/platforms/` holds one class per platform behind one
contract, and `linux.py` is the only implementation: the agent is Linux
only, and Windows and macOS are the client's platforms. The contract names
intents, not mechanisms: enumerate human accounts, resolve an account's
home, run a process as an account, control the agent's own service, power
actions, read host metrics, install and remove a package of a kind. Metrics
come from `/proc` and `/sys` with nothing but the standard library; NVIDIA
is the one exception, read through `nvidia-smi` where the driver installed
it. A platform advertises the capabilities it has; invoking an absent one is
refused with `{"code": "unsupported_platform"}`, never guessed at.

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
them is on the joining machine's network and neither end knows which. A
client link is the same object with `"kind": "client"`, minted on the Clients
page; the client refuses a device link and the agent a client one. The
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
