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
| `config/xray/nodes.json` | `nodes.example.json` | yes — node passwords / UUIDs |
| `config/xray/routing.json` | `routing.example.json` | no |
| `config/router/network.json` | `network.example.json` | no |
| `config/router/connections.json` | `connections.example.json` | yes — wireless passphrases |
| `config/web/settings.json` | `settings.example.json` | yes — password hash, session secret |
| `config/devices/devices.json` | `devices.example.json` | yes — device SSH creds |
| `config/credentials/vault.json` | `vault.example.json` | yes — every sealed secret |
| `config/credentials/vault.key` | — | yes — the master key |
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

**AI providers** — named API endpoints and tokens (Anthropic, OpenAI, Gemini,
or a custom relay) in `config/credentials/ai_providers.json` (gitignored;
example committed). Stored once here and handed to features that need them —
Dev Setup writes them into a device's AI tool configs. Keys never come back
out through the API; listings only say whether one is stored.

**The vault** — every other secret sits sealed in
`config/credentials/vault.json`, one AES-256-GCM ciphertext per object under
the master key in `config/credentials/vault.key` (mode 0600). Names, kinds
and timestamps stay readable; the material and the key never leave the box in
the clear — every backup is a `.tar.gz` envelope carrying a manifest and its
payload's checksum, and under a passphrase the payload is one sealed
container, master key inside. `nhub vault rekey` re-encrypts everything under
a fresh key.

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

- The Settings tab exports a `config/` tarball.
- A fresh machine: install the package, unpack the tarball into
  `/etc/neutrino/hub/`, run `sudo nhub setup`. The box converges to the same
  state.

## Field reference

Each `*.example.json` is annotated field-by-field. The load-bearing ones:

- **`nodes.json`** — `nodes[]` (each with `id`, `name`, `address`,
  `is_enabled`, `protocol`, and a `shadowsocks` or `vless` block) plus
  `balancer` (`strategy`: `leastPing` | `roundRobin` | `random`, `probe_url`,
  `probe_interval_s`). Disabled nodes are dropped from the rendered config.
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
- **`settings.json`** — panel port, argon2id password hash, session secret and
  TTL, and `client_package_path` for the neutrino_agent tarball.
