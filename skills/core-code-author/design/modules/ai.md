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

## A key per device as well as per client

A managed device whose AI tools use the gateway has a gateway key of its
own. `config/cliproxyapi/cliproxyapi.json` keeps `device_keys` beside
`client_keys`, sealed the same way, and the renderer writes both lists into
the gateway's `api-keys`. `ensure_device_key`, beside `ensure_client_key` in
`modules/clients/ai_keys.py`, mints a device's key when the device's AI tools
setting goes on. The key is revoked when the setting goes off and when the
device is removed. No module's state carries it: the device's `ai_tools`
section does ("How a managed machine's tools are pointed at the gateway").

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
(`--model`, `/model <name>`). Which gateway names a machine's slots map to
is the tool configuration the switch writes: the client's **Configure**
dialog on a person's computer, the Modules page's **Global configuration**
on a managed machine.

## What each panel surface owns

| Surface | Owns |
| --- | --- |
| Activity | Status dots, today's counters, the probe line (`/v1/models` as served), journal, and the chip-switched usage tables |
| Providers | API-key provider records, their aliases, their serving order, enable/disable — staged behind the panel's apply, with the gateway-behind signal |
| Accounts | Subscription sign-in (redirect flows finish by pasting the dead callback page's address; device flows show a pairing code), status, revocation — immediate, never staged |
| Access | Client keys for machines no agent manages, plus the endpoint line; a managed device is keyed when its AI tools setting goes on, on the Modules page, and its key reaches it over the agent channel. The hub holds a key of its own beside them, minted on the first apply and shown nowhere: it is what the hub probes `/v1/models` with, and it keeps the gateway's key list from ever being empty, since CLIProxyAPI with no key configured asks nobody for one |
| Gateway port | `listen_port`, staged behind its own apply |

## How a client points its tools at the gateway

The client does not write a tool's configuration itself. It hands the hub
to cc-switch as one more provider and lets cc-switch write Claude Code's
`settings.json`, Codex's `config.toml` and Gemini's `.env`, in each tool's
own format. What the client owns is the order of operations, because
cc-switch replaces a tool's file whole when it switches and would otherwise
drop what the person had in it.

The endpoint a tool is given is the client's own local port,
`http://127.0.0.1:<local-port><path>`, `<path>` being the path of the `ai`
entry's `endpoint`, empty for the endpoint the hub publishes. The client listens there while it runs and the
hub is the exit of any tool, and sends each connection to the gateway as a
`connect` stream ([../protocol.md](../protocol.md), "The connect stream").
The key is this client's own gateway key from the `service` stream, and the
gateway checks it on every request. A tool works only while the client
runs, and the client's AI page says so ([../client.md](../client.md), "The
AI page").

Before the hub is ever made current for a tool, the client hands cc-switch
what the person already had, through cc-switch's own stores:

| Step | cc-switch command | What it keeps |
| --- | --- | --- |
| List | `provider list` | cc-switch takes a configuration it has never seen into its store as the provider `default`, which is what switching back returns to |
| MCP servers | `mcp import` | The tool's live MCP servers, which cc-switch then writes into every configuration it makes |
| Shared settings | `config common extract` on the live file, then `config common set` | Claude's `permissions`, `hooks`, `statusLine`; Codex's `approval_policy`, `sandbox_mode`; Gemini's own variables |
| The hub | `provider add --common-config` with the endpoint, key and model flags, then `use` | The hub's provider carries the shared settings, so both stand in the file at once |

A common snippet the person already set is never replaced. cc-switch's
extract counts the provider's own model as shared for Gemini (`GEMINI_MODEL`)
and, defensively, Codex (`model`); the client takes those keys out of the
snippet before saving it, or the snippet would override the hub's choice.

Two things stay the client's own. Codex's reasoning effort has no flag in
cc-switch's `provider add`, so a chosen effort is set as a top-level key of
`config.toml` after the switch. And cc-switch's `provider delete` asks
`(y/N)` on its terminal with no flag in the prompt's place, so the client
runs it on a terminal of its own (a pty on Linux, a pseudo console on
Windows) and answers `y`.

The client records, per tool, which provider was current before the hub,
whether the tool had a configuration file and a directory at all, and the
bytes of every file a switch may write as they were before the first
switch, or that the file was absent: Claude Code's `~/.claude/settings.json`,
Codex's `~/.codex/config.toml` and `auth.json`, Gemini's `~/.gemini/.env` and
`settings.json`. The record is `{is_present, is_dir_present, kept,
kept_modes, previous, added}`, `kept_modes` being each kept file's own mode
outside Windows and `added` the provider settings last written. A tool whose
record says it already carries the wanted settings is not run again, so
nothing runs when nothing changed.

cc-switch writes a tool's files only into a directory that is there, and
says nothing else when it skips one, so a switch makes the directory of a
tool that has none, and every tool named as switched has its file read back
naming the hub: Claude Code's endpoint, key and model, Codex's and Gemini's
endpoint. cc-switch writes those files with the person's own file mask, so
every file that then holds the gateway key, Claude Code's `settings.json`,
Codex's `auth.json` and Gemini's `.env`, is set to mode 600 outside
Windows. Deactivating switches back to the recorded provider, deletes the
hub's entry, then writes each kept file back byte for byte with its own
mode, takes away each
that was absent, and takes away a directory the switch made once it is
empty; cc-switch's own switch back re-writes a file in its own layout, so
its result is never what is left. A switch back that cannot run cc-switch,
or cannot read its list of providers, fails and keeps the records, so the
person's own files are still there to put back at the next try. What the
adoption imported into cc-switch's MCP store and common snippet stays there
afterwards: it is the person's own, in the place cc-switch keeps it.

## How a managed machine's tools are pointed at the gateway

A managed machine's AI tools are pointed at the gateway by the steps of the
client's section above, run by the agent: the same cc-switch, the same
commands in the same order, the same record per tool, the same switch back.
This section states only what differs, so the two cannot drift.

The setting is one per managed machine, on the Modules page's **Global
configuration** ([../ui_behavior.md](../ui_behavior.md), "The Modules
page"): whether the machine's AI tools use the gateway, and the tool
configuration the client's **Configure** dialog saves
(`{claude: {default, opus, sonnet, haiku}, codex: {model,
model_reasoning_effort}, gemini: {model}}`). It is off on a new machine. The
hub keeps it in `config/devices/<id>/ai_tools.json` and sends it in the
device's `ai_tools` section ([../protocol.md](../protocol.md), "The
sections").

| | On a person's computer | On a managed machine |
| --- | --- | --- |
| Who runs the steps | the client | the agent |
| As whom | the person, in their own session | each account the hub names, never root or SYSTEM: `runuser -u <account> --` on Linux, a process with the account's uid and groups on macOS, a one-shot scheduled task under the account's login on Windows ([../agent.md](../agent.md), "The machine's AI tools") |
| The accounts | the person's own | every account with an instance in the machine's VS Code, code-server or CloudCLI configuration, worked out by the hub and sent in the state |
| The endpoint | `http://127.0.0.1:<local-port><path>`, the client's forward | `http://<hub-address>:<listen-port>`, the gateway as the machine reaches it on the LAN, from `device_gateway()` in `modules/clients/ai_keys.py` |
| The key | the client's own, from the `service` stream | the device's own, from the `ai_tools` section |
| The unchosen models | the gateway's first model, from the `service` stream | the gateway's first served model, filled in by the hub before the state is sent |
| The cc-switch | the copy the client's package carries | the copy the agent fetches from the hub into `ai_tools/bin/` under its state root, the same pinned version |
| The record per tool | `original/<tool>.json` under the client's configuration | `ai_tools/<account>/<tool>.json` under the agent's state root, never in the account's home ([../agent.md](../agent.md), "The machine's AI tools") |
| Switched back | when the chip goes off | when the setting goes off, when the account's last instance is removed, before `nagent service uninstall`, and when the machine leaves the hub |

cc-switch keeps its own store in the account's home on a managed machine,
as on a person's computer. An account gained while the setting is on is
switched at the next state. While the gateway serves no model, the hub sends
the setting as off, so every account is switched back; the stored setting
and the device's key stay, and the next state after the gateway serves again
switches the accounts back to the hub.

A desktop client on a managed machine leaves its AI page to the agent
([../client.md](../client.md), "The AI page"), because both would write the
provider `neutrino` into the same account's cc-switch store with different
endpoints.

## Metering

The panel drains the management API's usage queue (a destructive pop; the
collector is the only reader) into per-key × per-provider cells — days kept
forever, hours 48 h, minutes 90 min. `failed` counts upstream failures only:
a request refused before reaching a provider (bad name, bad client key) is
never queued. Token fields are the vendor's own accounting — `input_tokens`
includes what the cache served, so a cache share is `cache_read / input`.

Usage is counted per key id, so a device key is a row of its own in the AI
page's usage table, beside each client's.

The management key that unlocks the queue is machine-generated, sealed under
the vault's data key beside the module's config, working copy in the state
root; it is deliberately not a user-facing credential, so no cascade delete
can switch metering off.
