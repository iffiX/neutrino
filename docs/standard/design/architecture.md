# Architecture

The load-bearing structural principles of this repo.

## The shape of the system

One box runs the hub; every other machine runs at most the agent.

```
config/ ──render──▶ /var/lib/neutrino/generated/ ──apply──▶ the daemons:
  ▲                                              xray, dnsmasq, cliproxyapi,
  │ every change is a write here                 nftables, hostapd, units
  │
web/ (FastAPI, root) ◀────── hub/frontend/ (browser, plain HTTP, password)
  ▲
  │ heartbeat over pinned TLS — report up, desired state down
  │
neutrino_agent (root, stdlib only) ──── reconciles features and mounts
  ▲
  │ loopback only
agent's own page (the machine's owner, no password)
```

Inside the hub package the layers only reach downward:

- `modules/<name>/` — one feature each (config, renderer, ops, provisioner),
  pure library. Modules reference each other by id, never by import of
  behavior: a device references a vault object, an offer references a
  declared service, the AI gateway renders the providers the credentials
  module stores.
- `system/` — wrappers around OS invocations; the only code that shells out.
- `web/` — one router file per API module, models shared with the frontend
  by field name.
- `cli/` — every entry point, one `nhub` subcommand each.

The agent has no dependencies and opens no port toward the hub: it polls, so
it survives restarts, sleep and NAT in between. Everything the hub "does" to
a device is desired state the agent converges on.

## The two-tier principle: library vs. scripts

Reusable logic lives in purely functional library packages. All execution
verbosity lives in `neutrino_hub/cli/`. This is not a formatting preference; it lets the
same rendering logic drive both the web panel and the command-line tools without
duplication, and keeps every library unit-testable with no daemon running.

- Library packages (`neutrino_hub/modules/<name>/`, `neutrino_hub/system/`, `neutrino_hub/web/`, `neutrino_hub/utils/`)
  expose composable functions and classes with explicit constructor keywords.
  No `main()`, no `argparse`, no wiring-config classes.
- Each tool is a `neutrino_hub/cli/<name>.py` that wires the libraries together with
  plain-variable config sections. The tools are `install.py`, `render_all.py`,
  `web.py` and `scan_secrets.py`, one `nhub` subcommand each.

The mechanical placement rules are in
[../coding_style/layout_style.md](../coding_style/layout_style.md).

## config/ is the single source of truth

Everything the gateway does is a function of the JSON files under `config/`.
State flows one way:

```
config/<module>/*.json  ->  render (pure library)  ->  /var/lib/neutrino/generated/*
                        ->  validate  ->  apply (systemctl / nft / ip)
```

- The web backend and `neutrino_hub/cli/render_all.py` drive the exact same
  pipeline. A change made in the panel is a write to `config/` followed by a
  render+apply; there is no second path that edits `/etc` by hand.
- Backing up `config/` (and restoring it on a fresh machine) reproduces the
  whole appliance. Nothing load-bearing lives only in `/etc` or in a daemon's
  memory.
- Because `config/` is the contract, `config/<module>/<name>.example.json` is
  committed and documents every field; the real file may be `.gitignore`d for
  secrets. See [config.md](../misc/config.md).

## Render and apply are separate layers

Keep system effects out of the rendering logic. A renderer is a pure function
from `config/` data to a generated artifact (a dict, a string, a file); it never
runs `systemctl`, `nft`, or `ip`. A thin apply layer validates the artifact and
then touches the system.

```text
# BAD — renderer shells out; impossible to test without root and a live nft
class RouterNftRenderer:
    def render(self):
        ruleset = self._build_ruleset()
        subprocess.run(["nft", "-f", "-"], input=ruleset)   # effect inside render

# GOOD — render is pure; apply validates then applies
class RouterNftRenderer:
    def render(self) -> str:            # pure: config -> ruleset text
        return self._build_ruleset()
modules/router/routes.py  ->  RouterRulesetApplier.apply(ruleset)   # nft -c then nft -f
```

Litmus test: if you deleted systemd and nft tomorrow, every renderer should
still import, run, and pass its tests unchanged. If it would not, an effect has
leaked into the rendering layer.

## Services are the unit; the hub is the broker

A service is anything a device can consume: the hub's own routing, the hub's
Samba shares, the AI gateway, and the services somebody declares on machines
the hub does not run — a NAS's Samba, an HTTP server, a Docker engine. A
device never integrates with a service directly; the hub renders what a
service offers into the device catalog, and a device subscribes.

```
service       hub-provided, or declared in config/services/declared.json
  -> offer          pure render: one catalog entry per thing a device can take
  -> subscription   per-device wish in devices.json:
                    {is_enabled, is_activated, settings}
```

- **The catalog carries no secrets.** It is fleet-global and hashed, and every
  agent holds a copy. A share's password or an AI key is resolved per device
  into `desired_features[<id>].config` when that device's heartbeat is
  answered, and travels nowhere else.
- **Settings flow both ways through the hub.** An offer declares its settings
  (`mountpoint`), the panel and the agent's own page both render the form from
  that one declaration, and an edit on the agent's page travels up as a
  `feature_requests` entry and comes back as desired state. The hub is the
  only decider, so the two pages cannot disagree for longer than one beat.
- **Subscriptions reconcile; nothing is executed remotely.** The agent
  converges on desired state every beat, which is what re-mounts a share
  after a reboot with no fstab entry and no command queue.

Which offers exist is itself a function of `config/`: a gateway offer is
rendered only in `router` and `side_gateway` modes, a mount offer only for a
share that exists. There is one AI service, the hub's own gateway; an outside
model endpoint becomes a provider behind it, never an offer of its own.

### How a device subscribes

Subscriptions live in `devices.json` under `client.features`, keyed by offer
id. A toggle on the panel writes the wish there; a toggle or a setting typed
on the agent's own page arrives as a `feature_requests` entry and is written
to the same place. The heartbeat carries everything, in both directions:

1. The agent posts its report — platform, metrics, per-feature state, the
   hash of the catalog it holds, and any local requests.
2. The hub stores the report, folds the requests into the stored
   subscriptions, and answers with `desired_features`: one entry per
   subscription, `{is_enabled, is_activated, settings, config}`, the config
   resolved for this device alone — the vault opened for its share password,
   its AI key minted, its mountpoint filled in. The catalog itself rides
   along only when the agent's hash is stale.
3. The agent reconciles the machine toward what came down, then reports the
   new state on its next beat. A state is `{code, params}`; the pages do the
   wording.

A feature nobody has decided about is inspected and reported, never acted on;
an offer gone from the catalog stops being reported. Removal is the same
loop: a subscription switched off is converged on, not commanded.

## Managed is a completed handshake

A device becomes managed two ways — the hub installs the agent over SSH and
hands it a token, or the owner pastes an enrollment link into the agent — and
either way management begins at the same moment: the first heartbeat the hub
authenticates. A minted token is an offer, not a relationship; an install
that fails after minting leaves a dangling offer that shows nowhere and is
overwritten by the next attempt.

Three states, and no fourth:

| State | Holds when | The page shows |
| --- | --- | --- |
| unmanaged | no token, or a token never authenticated | the Unmanaged section — a scan finds routers and printers, and they belong here |
| managed, reporting | token, authenticated, heartbeat inside the window | the Managed section, with live gauges |
| managed, quiet | token, authenticated, heartbeat stale | the Managed section, with when it was last seen — the hub cannot tell a machine that is off from one that is gone, and says so |

Severing propagates from whichever end acts, over no channel but the ones
that exist:

- **The hub lets go by deleting the token** — forgetting the device. The
  agent's next heartbeats are refused, which is its own condition and not an
  unreachable hub; after a few in a row the agent drops its binding, goes
  back to waiting for a link, and says why on its own page. A hub whose
  device records were reset or restored sheds its old fleet the same way.
- **The device lets go by leaving** — the agent's page, `nagent disconnect`,
  or the package's own removal — which tells the hub first; the hub drops
  the token and keeps the name and credentials the owner typed.
- A device that joins a different hub cannot tell the first one, which keeps
  a managed-and-quiet row until somebody forgets it there.

The agent mirrors the three states: unbound and waiting for a link, bound and
beating, and bound but refused — the one state that resolves itself. Its
binding lives in one file, and the running service adopts what another
process writes there, so the CLI and the page need no service restart.

## The credential vault

Every secret the hub keeps for somebody is sealed in one store:
`config/credentials/vault.json`, one AES-256-GCM ciphertext per object under
a random data key. The rest of `config/` holds references — `key_id`,
`password_id`, `sudo_password_id`, `login_id`, `secret_id` — and no secret
material at all.

| kind | sealed | plaintext meta |
| --- | --- | --- |
| `token` | value | — |
| `login` | password, username | — |
| `ssh_key` | private_key, passphrase | key_type, fingerprint |

Names, kinds and timestamps stay readable, so the file says what it holds
without saying what anything is. Each object's AAD binds its ciphertext to its
id and kind; two objects cannot be swapped.

The data key never sits in `config/`. The store carries it wrapped under the
master passphrase chosen at setup (scrypt → AES-256-GCM), so backing up
`config/` produces a file that is safe as it stands; the working copy the
panel decrypts with — with nobody at the keyboard — is state at
`/var/lib/neutrino/vault.key` (mode 0600). A box without that state file is a
locked vault: every operation that needs the key refuses with
`vault_locked`, and a restore is what unlocks it, proving the archive —
name, manifest, every member's digest, the wrapped key opening under the
passphrase — before anything touches disk and writing the unwrapped key
last. On the box itself the panel is root and the vault claims nothing
against root.

Secrets travel one way through the API: written in, listed back as ids,
fingerprints and reference counts, never read out. Deleting an object still
referenced is refused before it is allowed.

Two things stay out: the panel password, which is a hash and not a kept
secret, and the CLIProxyAPI client keys, which the hub mints itself, shows in
full to their owner, and renders whole into the gateway's own config.

`nhub vault rekey` wraps the data key under a new passphrase; nothing sealed
is re-encrypted.

## The network the hub assumes

Every enrolled machine — on the LAN, on NetBird, on whatever overlay comes
later — is somebody's own: locally administered, deliberately joined. The hub
is not multi-tenant and does not defend one enrolled machine from another.

The wire gets no such trust. A "LAN" can be a campus network with a thousand
strangers on it, so the panel answers only on served interfaces and the
overlay, behind a password, and the agent channel carries its secrets under
pinned TLS. Trusting the machines and distrusting the wire is the whole
model.

## The agent channel is pinned TLS; the panel is not

Desired state carries real secrets, so the wire between hub and agent is
treated as hostile even where the machines on it are not. The agent API is
served on its own TLS-only port with a self-signed certificate generated at
setup. The
enrollment link carries the certificate's SHA-256 fingerprint, and the agent
pins it — verification is the fingerprint, not a chain, so no device installs
a CA and no name has to match.

The panel a browser reads stays plain HTTP on its own port: a self-signed
certificate in a browser is a warning on every page, while the same
certificate pinned by an agent is exact. Two audiences, two transports,
because they verify differently.

## The AI gateway is metered at the hub

CLIProxyAPI's management API is served on loopback only, unlocked by a key
held in the vault. The panel accumulates what it reports — requests and
tokens, per client key, per day — under `/var/lib/neutrino/cliproxyapi/`, and
a client key belongs to a device, so usage lands on the subscription that
spent it. The dashboard, the AI page and the status strip all read that one
store.

## One identifier shape

A stored record is keyed by a UUIDv4 hex string, minted at creation and
meaning nothing. The exception is a device, keyed by what the network knows it
by: its MAC address, or the `id:`-prefixed machine id of a machine enrolled
from behind someone else's NAT.

## The web backend runs as root, and that is a boundary, not a habit

`neutrino_hub_web.service` runs as root because it must edit nftables, restart
services, and scan the LAN. That privilege is the reason the panel binds only to
the LAN and NetBird interfaces (enforced again by the nftables input chain)
and sits behind an argon2id password. Do not spread root-requiring calls through
the codebase: they live in the `neutrino_hub/system/` and `*/ops`/`apply` layers behind
named operations, so the surface that needs privilege is small and auditable. If
this ever becomes multi-user or WAN-exposed, split the privileged helper out
then — the apply layer is already the seam to split on.
