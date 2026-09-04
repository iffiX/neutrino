# The AI module

How the AI gateway behaves: what CLIProxyAPI serves, how a request picks its
upstream, what each panel surface owns, and which names a machine is allowed
to see. The system-level story — metering at the hub, the sealed keys, the
no-backup rule for accounts — is [architecture.md](../architecture.md); this
page is the module's behavior, pinned to the carried binary (7.2.146, probed
live on 2026-09-04).

## What serves

One CLIProxyAPI process per hub, on `listen_port` (default 8317), driven
entirely by the rendered YAML. Two kinds of credential feed it:

- **Providers** — API-key endpoints, stored in `config/ai/providers.json`,
  each keyed by a vault token. The kind names the protocol spoken
  (`anthropic`, `openai`, `gemini`, `custom`), never the vendor behind it.
- **Accounts** — OAuth subscription logins (auth files in the state root,
  hot-reloaded within ~2 s, never in a backup). Login kinds the binary has:
  `anthropic`, `codex`, `antigravity`, `kimi`, `xai`. There is no Gemini
  OAuth in 7.2.146; Google models arrive by API key, Vertex import, or the
  antigravity flow.

## How a request routes

1. **The model name picks the upstream family.** A name only one family
   serves goes there; families never compete for a name they do not claim.
2. **Inside a family, every credential is one pool.** Accounts and API-key
   providers deduplicate into the pool and rotate round-robin; the only
   ordering hook is a per-credential `priority` (default 0, not surfaced in
   the panel). A credential that fails is marked (`failed`, `unavailable`,
   `quota` — the account row's status dot) and the rotation skips it.
3. A name nothing claims is refused: `400 unknown provider for model`.

The Providers panel's list order is the serving order **among API-key
providers**; it does not rank accounts against them, and the panel says so
in one hint sentence rather than pretending to a cross-kind ordering the
binary does not have.

## Names are the gateway's to define

The gateway is the single namespace for model names. A provider record's
`models` list maps upstream names and may alias them (`real = alias`), and
what `/v1/models` then shows **is** the catalog every machine sees. A device
never invents a name; its tools pick from the gateway's list.

An alias that collides with a name an account already serves joins that
name's pool and rotates with it — so borrowing a family's real names for
another upstream is only clean while no account of that family is signed in.

Client menus (Claude Code's `/model`, Codex's picker) enumerate their own
built-in slots, not the gateway's catalog. A slot's meaning is remapped in
the tool's configuration (Claude Code: `ANTHROPIC_MODEL` and the three
`ANTHROPIC_DEFAULT_*_MODEL` variables; Codex: profiles), and any
gateway-listed name can be used past the menu by spelling it out
(`--model`, `/model <name>`). Which gateway names a device's slots map to
is a per-device setting the agent syncs into the tool configs — the
device-side mapping UI follows cc-switch's design (phase 5; until then the
mapping is whatever the switch wrote).

## What each panel surface owns

| Surface | Owns |
| --- | --- |
| Activity | Status dots, today's counters, the probe line (`/v1/models` as served), journal, and the chip-switched usage tables |
| Providers | API-key provider records, their aliases, their serving order, enable/disable — staged behind the panel's apply, with the gateway-behind signal |
| Accounts | Subscription sign-in (redirect flows finish by pasting the dead callback page's address; device flows show a pairing code), status, revocation — immediate, never staged |
| Access | Client keys for machines no agent manages, plus the endpoint line; managed devices are keyed automatically over the agent channel |
| Gateway port | `listen_port`, staged behind its own apply |

## Metering

The panel drains the management API's usage queue (a destructive pop; the
collector is the only reader) into per-key × per-provider cells — days kept
forever, hours 48 h, minutes 90 min. `failed` counts upstream failures only:
a request refused before reaching a provider (bad name, bad client key) is
never queued. Token fields are the vendor's own accounting — `input_tokens`
includes what the cache served, so a cache share is `cache_read / input`.

The management key that unlocks the queue is machine-generated, sealed under
the vault's data key beside the module's config, working copy in the state
root; it is deliberately not a user-facing credential, so no cascade delete
can switch metering off.
