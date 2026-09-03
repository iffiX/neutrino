# The hub↔agent channel

The channel is how a managed device talks to the hub: one TLS port serving
only the `/api/agent/*` routes, verified by a pinned certificate fingerprint
instead of a certificate authority, and authenticated by a per-device token
instead of a session. Why the channel is shaped this way is
[architecture.md](architecture.md) ("The agent channel is pinned TLS",
"Managed is a completed handshake"); this page is the wire-level detail — what
happens on which port, in what order, what each failure means, and what an
attacker in each position actually gets.

## Two ports, one process

| Port | Transport | Serves | Authenticated by |
| --- | --- | --- | --- |
| `listen_port` (default 8080) | plain HTTP | the panel: UI and every management API | login session cookie |
| `agent_listen_port` (default 8443) | TLS, pinned | `/api/agent/*` and nothing else | enrollment ticket, then the device token |

Both are uvicorn servers in the one `nhub run --only-web` process, sharing one
`PanelRuntime` — that shared runtime is where a ticket minted on the panel
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
`run --only-web` also mint it when it is missing (a restored backup, an
upgrade), and **an existing pair is never regenerated**: the fingerprint is
pinned by every enrolled agent, and a new certificate is a fleet-wide
re-enrollment. `nhub reset all` deletes the pair the way it deletes the vault
key — the next owner mints an identity of their own.

The fingerprint is the SHA-256 of the certificate's DER encoding, 64 lowercase
hex characters, and it travels only out-of-band: inside an enrollment link a
signed-in person minted, never over the wire it is meant to verify.

## Joining: one ticket, five minutes, spent in one step

Minting happens on the panel port, behind the session: the Devices page's
per-device link, the blank link `nhub setup` prints, and the SSH install
action all call one minting path. A ticket is `secrets.token_urlsafe(18)`
(144 bits), held in panel memory only, dead after **five minutes** — long
enough to walk to another machine and paste, short enough that a forgotten
link is not a standing invitation. **Minting replaces whatever ticket was
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
ticket minted for a device carries its MAC and routes the enrollee onto that
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

| The hub answered… | Exception | Counts toward self-unbind | What the agent does |
| --- | --- | --- | --- |
| wrong certificate | `GatewayUntrusted` | never | backs off; nothing was sent, not even the request line |
| 401 / 403 | `GatewayRefused` | yes — three beats unbind | the hub deliberately no longer knows this machine |
| version mismatch (409, `agent_newer_than_hub`) | its own state | never | backs off and says the hub must be updated first |
| anything else, or nothing | `GatewayUnreachable` | never | backs off and retries |

The distinction is the point: a refusal is the one answer that can never heal
by retrying, so it is the only one that unbinds. An impersonator, an outage
and a version skew all look different from a hub that forgot you, and none of
them may cost a working binding.

## What an attacker in each position gets

**On the wire, or owning the network** (ARP, DHCP, DNS, a squatted IP): they
can answer the agent port, and the handshake completes — but they cannot
present a certificate whose DER digests to the pinned value without the
private key, so the agent hangs up having sent nothing. Pinning an exact
identity is stronger here than a CA chain: there is no authority to mis-issue,
only a second preimage to find. Downgrade is closed the same way — the
binding's URLs came out of a link the hub minted, are `https` by construction,
`http.client` follows no redirects, and https-without-a-pin refuses.

**Holding a captured link**: an unspent link within its five minutes joins
their machine as the device the link was minted for — the link *is* the
credential. Everything narrows that window: one outstanding ticket, five
minutes, single atomic spend, and the SSH install path minting and spending
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
  `{"code": "agent_newer_than_hub", ...}`, on enroll and heartbeat alike —
  and `nagent connect` prints that the hub must be updated first. Never a
  401: a version skew must not unbind anybody.

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
