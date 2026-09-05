# The device agent

The agent is the hub's presence on a managed machine: one service with the
platform's highest privilege that keeps the machine converged on what the hub
says should be true, and answers to the people sitting at it — each within
the scope their identity owns. It is pure standard library with no
dependencies, which is what lets one package run on whatever Python a device
already has. Why the system is shaped this way is
[architecture.md](architecture.md) ("The agent channel is pinned TLS",
"Managed is a completed handshake"); this page is the agent's own design:
who may command it, how state moves, how local people reach it, and where
the platform seam runs.

## Who may tell the agent what

Two authorities, and nothing else: the hub over the pinned channel, and the
machine's own people over the local control channel. What each may touch is
decided by which partition a thing belongs to and by who is asking — never
by which door they used.

**Functions and services.** Everything a managed machine offers splits in
two:

- **Functions** are machine software the hub administers — a remote
  desktop, the SSH server. The panel's device drawer switches them; the
  agent's page shows them and lets a privileged caller toggle them too. A
  local toggle is never applied locally: it rides up with the next
  heartbeat, the hub decides, and the answer comes back as desired state,
  so the drawer and the page cannot disagree for longer than one beat.
- **Services** are what the machine's people do with what the hub
  publishes — pointing an account's AI tools at the gateway, mounting a
  published share, opening a published link, forwarding a published port.
  They are visible and decided **only on the machine**: the panel neither
  renders nor controls them. The hub's part is the catalog of what exists
  and, for the AI service, the per-account credential; every other choice,
  and every secret it takes, stays local.

| Capability | Privileged | Ordinary account |
| --- | --- | --- |
| Read binding, status, functions, the service catalog | yes | yes |
| Connect to a hub / disconnect | yes | no |
| Toggle functions | yes, as the panel does | no |
| AI service: switch an account's tools | yes, any account | own account only |
| Mounts: attach a published share | yes, at any path | yes, where the account may write |
| Port forwards | yes | yes — a forward is machine-wide and every scope sees it |

Privileged means the platform's own idea of administrative identity: uid 0
on Linux and macOS, an elevated Administrators token on Windows — under UAC
the same person's non-elevated shell is an ordinary account, which is the
distinction UAC exists to draw.

## Desired state, and how it moves

The agent beats every few seconds. Up goes what the machine is: hostname,
agent version, metrics, the platform tuple, the machine's human accounts —
the platform's own judgment of who is a person, root and system accounts
never listed — each function's state, the most recent error worth showing,
and any pending requests. Down comes what should be true: the desired
functions, the catalog when the agent's copy is stale (compared by
`catalog_hash`, so a converged fleet is never re-shipped it), the AI
credentials for accounts the hub has granted, queued commands, and the
hub's version.

**The catalog** is the hub's answer to "what exists for this machine", in
two halves under one hash: the function manifests, and the service offers
rendered from the hub's own state — a declared share, a published link, a
container's exposed port. Offers carry no secrets, ever; the one secret a
service takes from the hub — an account's gateway key — travels only in
that device's per-beat reply.

**Status is typed.** A function or service reports `state` plus
`{code, params}` — never an English sentence — and every surface does its
own wording. The agent's `last_error` crosses the wire the same way, so a
device that is unhappy says why on the panel, not only on its own page.

## Services on the machine

The agent's page lists services grouped by kind — AI, links, ports, mounts
— each group under its own divider. Service choices are machine state: they
live in the agent's own store, survive a hub restore untouched, and appear
in no hub backup.

**AI.** One chip per account: a privileged caller sees every human account,
each chip carrying that account's cc-switch state; an ordinary caller sees
one chip — their own. Switching a chip on asks the hub for that
(device, account) pair's gateway key and points the account's tools at the
gateway; switching it off puts the account's own configuration back and
revokes the pair's key. Keys per pair are what makes usage meter to the
person and revocation cut exactly one account on one machine; the AI page's
Access panel lists them. Acting on an account that is empty or not among
the reported ones is refused with `{"code": "no_target_user"}`, and the
guard is symmetric: activation and deactivation check it alike, so a
cleanup can never be skipped by the same gap that let the setup mis-target.
`nagent connect` remembers the invoking `SUDO_USER`, which is the chip a
single-user machine finds preselected.

**Links.** Every published web service renders as a link that opens it.
There is nothing to toggle and no state to keep.

**Ports.** A published port — a `generic_tcp` service, a container's
exposed port — forwards to this machine on a click: a relay from
`127.0.0.1`, on the same number when it is free and otherwise on a free one
the row names. A forward binds the loopback the whole machine shares, so it
is machine state every scope sees. Containers are started and stopped on
the hub's own panel, never from here.

**Mounts.** A published share attaches where the person says. The form asks
for the share's own username and password and a path — typed, or picked in
the browse dialog the agent feeds, whose listing runs as the caller's
identity, so an ordinary account browses only what it may write. The
password becomes a root-only credentials file on this machine and never
travels to the hub. A path under the asking account's home is
ownership-mapped to that account; anywhere else follows the share's own
permissions. A mount point that is not an empty directory is refused
(`{"code": "mountpoint_not_empty"}` — mounting over content hides it), and
a machine without CIFS tooling says so (`{"code": "cifs_missing"}`).

## The local control channel

Local access rides two transports serving one API, and identity comes from
the operating system, not from a password:

- **A control socket** — a Unix socket on Linux and macOS, a named pipe on
  Windows. Any local account may connect; the peer's identity is read from
  the kernel (`SO_PEERCRED`, `LOCAL_PEERCRED`, pipe impersonation), and the
  caller gets the scope that identity owns. `nagent` talks here.
- **The loopback page** on `127.0.0.1:8765`, for browsers, which cannot
  speak the socket. Every API request carries a token; a token is minted
  over the socket, is bound to the identity that asked, and dies with the
  agent process. Requests are additionally checked for the page's own
  `Origin` and a JSON `Content-Type`, which is what keeps a website in a
  local browser from posting here. A tokenless request gets a page that
  says how to open one, and nothing else.

`nagent ui` is how a person opens the page: it fetches a token over the
socket as whoever ran it and opens the browser on a URL carrying it.
The desktop menu entry runs `nagent ui`, so a double-click lands in the
clicking account's own scope; `sudo nagent ui` opens the privileged page.
One page serves both — what it shows is the token's scope.

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
- attach a share for an account at a location, detach it, ask if attached
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
peer identity withholds. The loopback page gives them the same and no more,
because its tokens are minted to an identity over that same socket. A
website in their browser gets nothing at all: it holds no token, and the
`Origin` and `Content-Type` checks refuse the request shapes a cross-site
form can produce.

**Rooting the hub box** is outside the model: the key, the vault and the
panel all live there. The panel port itself is plain HTTP by
[architecture.md](architecture.md)'s local-trust decision; the agent channel
is hardened separately because it crosses networks the panel never does.

## One version, enforced at the door

The hub and the agent share a release version, with no compatibility window
([../../memory.md](../../memory.md), "Versioning"). The channel enforces it:
every enroll and heartbeat carries the agent's version, and every reply
carries the hub's.

- **Agent older**: the reply's newer number is the update request — a polling
  agent hears about a hub upgrade on its first beat after the restart. It
  downloads the hub's baked native package for its family over the pinned,
  token-authed channel, verifies the SHA-256 the hub states, and installs it
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
