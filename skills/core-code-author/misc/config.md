# Using `config/`

`config/` is the single source of truth for the whole appliance. Every daemon's
real configuration is generated from these JSON files: the gateway renders them
into `/var/lib/neutrino/hub/generated/`, validates, and applies. Back up `config/` and
you can rebuild the box; change a file (by hand or through the web panel) and a
render+apply makes it live.

This page is the operator's guide to those files. The engineering rules about
*how code reads* `config/` live in
[standard/design/architecture.md](../design/architecture.md).

On an installed hub `config/` is `/etc/neutrino/hub` on Linux,
`/Library/Application Support/Neutrino/hub/config` on macOS and
`C:\ProgramData\Neutrino\hub\config` on Windows, and the state root holding
`generated/` and the working vault key is beside it on each system
([../design/files.md](../design/files.md)).

## Real files vs. `.example.json`

Every configurable file ships as `config/<module>/<name>.example.json`, which is
**committed** and documents every field with placeholder values. The real file
(`<name>.json`) is what the gateway reads. Files that hold secrets are
`.gitignore`d and never committed, so no node password, admin hash or device
key ever reaches git history.

An example's records are placeholders: a step that writes a real file from
an example copies its shape and none of its records, so no `_example_` id
of `clients.example.json` is ever a client. Its default permission names
every kind but `panel`, which signs a client into the panel without the
password and is turned on for one client at a time.

| Real file (read at runtime) | Committed example | Secret? |
| --- | --- | --- |
| `config/xray/nodes.json` | `nodes.example.json` | no — secrets live in the vault |
| `config/xray/routing.json` | `routing.example.json` | no |
| `config/router/network.json` | `network.example.json` | no |
| `config/router/connections.json` | `connections.example.json` | yes — wireless passphrases |
| `config/web/settings.json` | `settings.example.json` | yes — password hash |
| `config/web/identity.json` | `identity.example.json` | no — the hub's own id and name, generated at setup |
| `config/web/panel_tls/` | none | yes: the panel's certificate authority, `authority.pem` in the clear and `authority_key.sealed` under the vault's data key, generated at setup |
| `config/devices/devices.json` | `devices.example.json` | yes — device SSH creds |
| `config/devices/<id>/vscode.json` | none | yes: each VS Code instance's connection token, sealed under the vault's data key, beside its account, its port and the vault login a Windows machine starts it with |
| `config/ai/providers.json` | `providers.example.json` | no — keys live in the vault |
| `config/cliproxyapi/cliproxyapi.json` | `cliproxyapi.example.json` | yes: the AI gateway's client keys, device keys and the hub's own key, sealed |
| `config/netbird/netbird.json` | `netbird.example.json` | yes: the reusable setup key clients join the overlay with, sealed |
| `config/easytier/easytier.json` | `easytier.example.json` | yes: the mode, the network secret and the console address with its token, both sealed |
| `config/overlay/relay.json` | `relay.example.json` | no: the relay's `is_enabled`, `host`, `ssh_port`, `account`, `public_port`, and `key_id`, the id of the SSH key in the vault |
| `config/credentials/vault.json` | `vault.example.json` | yes — every sealed secret |
| `config/devices/packages/*` | — | no (build artifacts, just large) |

`.gitignore` ignores the real names and `config/devices/packages/` wholesale,
while keeping every `*.example.json` tracked.

The EasyTier engine's start line is a systemd drop-in,
`/etc/systemd/system/neutrino_hub_easytier.service.d/arguments.conf`, mode
0644. In console mode it names the console address with its token. systemd
shows every unit's start line to any local user over D-Bus, as `ps` shows any
process's arguments, so a local account on the hub can read that token; a
stricter mode on the file hides nothing. On macOS and Windows no drop-in
exists: the supervising service starts EasyTier with that line, and the
process list shows it in the same way.

The relay's start line is the drop-in
`/etc/systemd/system/neutrino_hub_relay.service.d/arguments.conf`, mode 0644.
It names the host, the ports, the account and the paths of the key file and
the known-hosts file under the state root, and no secret: the key file is
mode 0600 and readable by root alone.

## Credentials

The secrets the gateway uses on your behalf are managed in the panel's
**Credentials** tab, not by editing files.

**SSH keys** — pasted once, validated, and sealed in the vault as `ssh_key`
objects; the key type and fingerprint stay readable beside the ciphertext.
Devices and the relay reference a key by its id, `key_id`, so one key can
serve many devices and the material never sits in a device's config or in
`relay.json`. Deleting a device leaves its key in place; the tab warns before
deleting a key still in use, the relay's included.

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
state at `/var/lib/neutrino/hub/vault.key` (mode 0600) — so `config/` holds no
unsealed secret, and a box without the state key is a locked vault that
refuses with `vault_locked`, listings included, until a restore supplies the
passphrase. `nhub vault rekey` wraps the data key under a new passphrase;
nothing sealed is re-encrypted.

## First-run flow

1. `sudo nhub setup` (see [../../cli.md](../../../docs/cli.md)), or `nhub setup` in
   an administrator PowerShell on Windows. It prompts for the
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
Never hand-edit files under `/var/lib/neutrino/hub/generated/` — they are regenerated
and your edit will be lost.

## Backup and migrate

- The Settings tab exports one plain `.tar.gz`: a manifest naming what it is,
  a `SHA256SUMS` digest list, then the `config/` tree. Safe to store as it
  stands — the vault's data key travels only wrapped under the master
  passphrase.
- Restore uploads it on the Settings tab and always asks for the vault
  passphrase: everything is verified in memory — manifest, every digest, the
  wrapped key opening — before a byte lands, and the unwrapped data key is
  written to `/var/lib/neutrino/hub/vault.key` last.

## Field reference

Each `*.example.json` is annotated field-by-field. The load-bearing ones:

- **`nodes.json`** — `nodes[]` (each with `id`, `name`, `address`,
  `is_enabled`, `protocol`, `secret_id` — the vault `token` holding the node's
  password or uuid — and a `shadowsocks` or `vless` block) plus `balancer`
  (`probe_url`, `reference_url`, `probe_interval_s`). Every node whose
  reference resolves is rendered, switched on or off, so the hub measures all
  of them; `is_enabled` states which ones the hub may pick as the exit. A node
  whose reference does not resolve is dropped from the rendered config.
- **`routing.json`** — `is_geoip_split_enabled` (default `true`: CN domains/IPs
  go direct, everything else through JustMySocks), `is_local_proxy_enabled`
  (the gateway's own traffic through the proxy, default `false`), and the
  proxy's two resolver lists, `remote_dns` and `direct_dns`, each a list of
  `{address, port}` asked in order. An empty `direct_dns` follows the
  network's resolvers ([../design/modules/proxy.md](../design/modules/proxy.md),
  "Where names resolve").
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
  MAC-registration networks; a static uplink lists its resolvers in `dns`,
  `[{address, port}]`, and with none listed the built-in fallbacks answer), `lan` (served network with its address and DHCP
  range — set `upstream_gateway` to an existing network's router to run as a
  side gateway, where that router is the box's way out over the same wire),
  `split` (an 802.1Q trunk), or `disabled`. Each also carries `is_exposed`:
  whether what this box listens on answers there. A VLAN is a further interface
  entry named `<trunk>.<id>` with a `vlan: {parent, id}` block and a role of
  its own; the trunk's untagged traffic is the `<trunk>.main` entry
  (`id: null`), created with the split and configured like any other interface.
  Top-level `static_leases` lists the devices that always get one address,
  each `{mac_address, address, name}`: the address lies in a network that
  assigns addresses, and `name` is optional and resolves on the served
  networks.
  Global switches: `uplink_policy` (`failover`/`balance`) and
  `is_inter_lan_allowed` (off fences the served networks from each other; every
  network still reaches the internet and the overlay).
  Top-level `overlays` holds one row per overlay engine,
  `{provider, is_enabled, is_exposed}`, `provider` being `netbird` or
  `easytier`; every row with `is_enabled` runs, and any set of them, none
  included, is allowed. A row without `is_enabled`, the 0.4.0 shape where the
  list named the one engine the box ran, reads as enabled, so an upgraded box
  runs that engine and no other; the next write stores `is_enabled` on every
  row. A file with no `overlays` at all reads as one enabled, exposed NetBird
  row.
- **`relay.json`**, in `config/overlay/`: `is_enabled`, `host`, `ssh_port`
  (default 22), `account`, `key_id` and `public_port` (default 8443). The
  relay is configured when `host`, `account` and `key_id` are set; a missing
  file reads as a relay that is off and not configured
  ([../design/modules/network.md](../design/modules/network.md), "The relay,
  the third way in").
- **`identity.json`** — the hub's own `id` (a uuid generated at setup) and
  `name` (the hostname until the Settings page changes it); the `welcome`
  frame carries both, and `nhub reset all` deletes the file.
- **`settings.json`** — panel port (`listen_port`, HTTP), panel HTTPS port
  (`https_listen_port`, default 443, served whether HTTPS is on or off),
  agent port, password hash, session TTL, and `is_https_enabled`, false
  until the Settings page or setup turns it on; while it is on the HTTP port
  redirects to the HTTPS port. The session secret is state at `/var/lib/neutrino/hub/session.secret`,
  generated by the panel when missing. The agent package the panel installs over SSH rides inside the hub
  package; drop a ``.deb``/``.rpm`` into ``config/devices/packages/`` to pin
  a different build.
