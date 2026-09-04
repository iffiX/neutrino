# Using `config/`

`config/` is the single source of truth for the whole appliance. Every daemon's
real configuration is generated from these JSON files: the gateway renders them
into `/var/lib/neutrino/generated/`, validates, and applies. Back up `config/` and
you can rebuild the box; change a file (by hand or through the web panel) and a
render+apply makes it live.

This page is the operator's guide to those files. The engineering rules about
*how code reads* `config/` live in
[standard/design/architecture.md](../design/architecture.md).

## Real files vs. `.example.json`

Every configurable file ships as `config/<module>/<name>.example.json`, which is
**committed** and documents every field with placeholder values. The real file
(`<name>.json`) is what the gateway reads. Files that hold secrets are
`.gitignore`d and never committed, so no node password, admin hash or device
key ever reaches git history.

| Real file (read at runtime) | Committed example | Secret? |
| --- | --- | --- |
| `config/xray/nodes.json` | `nodes.example.json` | no — secrets live in the vault |
| `config/xray/routing.json` | `routing.example.json` | no |
| `config/router/network.json` | `network.example.json` | no |
| `config/router/connections.json` | `connections.example.json` | yes — wireless passphrases |
| `config/web/settings.json` | `settings.example.json` | yes — password hash |
| `config/devices/devices.json` | `devices.example.json` | yes — device SSH creds |
| `config/ai/providers.json` | `providers.example.json` | no — keys live in the vault |
| `config/credentials/vault.json` | `vault.example.json` | yes — every sealed secret |
| `config/devices/packages/*` | — | no (build artifacts, just large) |

`.gitignore` ignores the real names and `config/devices/packages/` wholesale,
while keeping every `*.example.json` tracked.

## Credentials

The secrets the gateway uses on your behalf are managed in the panel's
**Credentials** tab, not by editing files.

**SSH keys** — pasted once, validated, and sealed in the vault as `ssh_key`
objects; the key type and fingerprint stay readable beside the ciphertext.
Devices reference a key by its id, so one key can serve many devices and the
material never sits in a device's config. Deleting a device leaves its key in
place; the tab warns before deleting a key still in use.

**Logins** — one account each, a password with an optional username, sealed
as `login` objects. A device's SSH password and sudo password reference them
by id, and so does a declared Samba share's `login_id`; the tab warns before
deleting a login something still uses.

**Tokens** — one bare secret string each, sealed as `token` objects. AI
providers reference them by id, and so does each proxy node's `secret_id`;
the tab warns before deleting a token either still uses. Values never come
back out through the API.

**AI providers** — named API endpoints (Anthropic, OpenAI, Gemini, or a
custom relay) in `config/ai/providers.json` (gitignored; example committed),
managed on the AI page. A provider holds no key of its own: its `secret_id`
references a token from the Credentials page, and deleting the provider
leaves the token where it is.

**The vault** — every secret sits sealed in
`config/credentials/vault.json`, whose only readable member is the wrapped
data key: the records ride as one AES-256-GCM ciphertext, names and kinds
included, so the file says nothing about what it holds. The data key rides
wrapped under the master passphrase chosen at setup, and the working copy is
state at `/var/lib/neutrino/vault.key` (mode 0600) — so `config/` holds no
unsealed secret, and a box without the state key is a locked vault that
refuses with `vault_locked`, listings included, until a restore supplies the
passphrase. `nhub vault rekey` wraps the data key under a new passphrase;
nothing sealed is re-encrypted.

## First-run flow

1. `sudo nhub setup` (see [../../cli.md](../../cli.md)). It prompts for the
   panel password, copies each missing `<name>.json` from its `.example.json`,
   renders everything and starts the panel.
2. Add the proxy nodes on the panel's Proxy page, which decodes `ss://` and
   `vless://` share links into `config/xray/nodes.json`.
3. After editing anything by hand, `sudo nhub apply`. This renders, runs
   `xray run -test` / `nft -c` / `dnsmasq --test`, and restarts the daemons.

## Day-to-day changes

Two equivalent paths, both driven by the same render pipeline:

- **Web panel** (normal path): a change in the UI writes `config/`, then renders
  and applies automatically.
- **Edit the JSON, then run** `sudo nhub apply`. Useful over
  SSH or for bulk edits.

Either way, once the file is written it is already the backup-worthy state.
Never hand-edit files under `/var/lib/neutrino/generated/` — they are regenerated
and your edit will be lost.

## Backup and migrate

- The Settings tab exports one plain `.tar.gz`: a manifest naming what it is,
  a `SHA256SUMS` digest list, then the `config/` tree. Safe to store as it
  stands — the vault's data key travels only wrapped under the master
  passphrase.
- Restore uploads it on the Settings tab and always asks for the vault
  passphrase: everything is verified in memory — manifest, every digest, the
  wrapped key opening — before a byte lands, and the unwrapped data key is
  written to `/var/lib/neutrino/vault.key` last.

## Field reference

Each `*.example.json` is annotated field-by-field. The load-bearing ones:

- **`nodes.json`** — `nodes[]` (each with `id`, `name`, `address`,
  `is_enabled`, `protocol`, `secret_id` — the vault `token` holding the node's
  password or uuid — and a `shadowsocks` or `vless` block) plus `balancer`
  (`strategy`: `leastPing` | `roundRobin` | `random`, `probe_url`,
  `probe_interval_s`). Disabled nodes and nodes whose reference does not
  resolve are dropped from the rendered config.
- **`routing.json`** — `is_geoip_split_enabled` (default `true`: CN domains/IPs
  go direct, everything else through JustMySocks), `is_local_proxy_enabled`
  (the gateway's own traffic through the proxy — default `false`), and the DNS
  servers for each side.
- **`connections.json`** — `connections[]`, one per wireless network the box
  knows: `ssid`, `key_mgmt` (`WPA-PSK` | `SAE` | `NONE`), `psk` (the
  passphrase or the 64-character key derived from it), `priority` (higher wins
  between two in range), `is_hidden`, and `source`. An empty `psk` on a known
  network means its key was held somewhere that could not be read; the panel
  asks for it once.
- **`network.json`** — `mode` first, one of `router`, `one_arm_router`,
  `side_gateway` or `server`: it says what the whole machine is, and whether
  the hub addresses its interfaces at all. Then one entry per interface with a
  `role`: `wan` (uplink, DHCP or static, optional cloned MAC for
  MAC-registration networks), `lan` (served network with its address and DHCP
  range — set `upstream_gateway` to an existing network's router to run as a
  side gateway, where that router is the box's way out over the same wire),
  `split` (an 802.1Q trunk), or `disabled`. Each also carries `is_exposed`:
  whether what this box listens on answers there. A VLAN is a further interface
  entry named `<trunk>.<id>` with a `vlan: {parent, id}` block and a role of
  its own; the trunk's untagged traffic is the `<trunk>.main` entry
  (`id: null`), created with the split and configured like any other interface.
  Global switches: `uplink_policy` (`failover`/`balance`) and
  `is_inter_lan_allowed` (off fences the served networks from each other; every
  network still reaches the internet and the overlay).
- **`settings.json`** — panel port, agent port, password hash and session
  TTL. The session secret is state at `/var/lib/neutrino/session.secret`,
  generated by the panel when missing. The agent package the panel installs over SSH rides inside the hub
  package; drop a ``.deb``/``.rpm`` into ``config/devices/packages/`` to pin
  a different build.
