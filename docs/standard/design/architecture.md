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
  │ heartbeat over pinned TLS — report up, orders and services down
  │
neutrino_agent (root, stdlib only) ──── executes orders, serves its own page
  ▲
  │ loopback only
agent's own page (the machine's owner, no password)
```

Inside the hub package the layers only reach downward:

- `modules/<name>/` — one feature each (config, renderer, ops, provisioner),
  pure library. Modules cross-reference by id rather than by embedding each
  other's data: a device names a vault SSH key, an xray node and an AI
  provider each name a vault secret, an offer names a declared service. The
  providers themselves live in `modules/ai/`, and the AI gateway renders what
  that module stores.
- `system/` — wrappers around OS invocations more than one module needs. A
  module's own effects stay in its `ops`, `apply` or `provisioner`.
- `web/` — one router file per API module, models shared with the frontend
  by field name.
- `cli/` — every entry point, one `nhub` subcommand each.

The agent has no dependencies and opens no port toward the hub: it polls, so
it survives restarts, sleep and NAT in between. It fetches nothing and
decides nothing — what the hub "does" to a device is an order the agent
executes, and what the machine's own people do with a service is the
machine's ("The hub installs; the agent is an outpost").

## config/ is the single source of truth

Everything the gateway does is a function of the JSON files under `config/`.
State flows one way:

```
config/<module>/*.json  ->  render (pure library)  ->  /var/lib/neutrino/generated/*
                        ->  validate  ->  apply (systemctl / nft / ip)
```

- The web backend and `nhub apply` drive the exact same pipeline. A change
  made in the panel is a write to `config/` followed by a render+apply; there
  is no second path that edits `/etc` by hand.
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

## Libraries carry the logic; `nhub` carries the execution

Reusable logic lives in purely functional library packages. All execution
verbosity lives in `neutrino_hub/cli/`. This is not a formatting preference: it
is what lets one rendering implementation drive both the web panel and the
command line, and what keeps every library unit-testable with no daemon
running.

- Library packages (`neutrino_hub/modules/<name>/`, `neutrino_hub/system/`,
  `neutrino_hub/web/`, `neutrino_hub/utils/`) expose composable functions and
  classes with explicit constructor keywords. No `main()`, no `argparse`, no
  wiring-config classes.
- Each tool is a `neutrino_hub/cli/<name>.py` that wires the libraries together
  with plain-variable config sections, and one `nhub` subcommand.
  `cli/entry.py` holds the subcommand table and dispatches; what each command
  does is [../../cli.md](../../cli.md).

The mechanical placement rules are in
[../coding_style/layout_style.md](../coding_style/layout_style.md).

## Services are the machine's to take; modules are the hub's to install

Two different things reach a managed machine, and confusing them is what the
Modules/Services split exists to prevent
([agent.md](agent.md), "Who may tell the agent what").

- **A module** is software the machine has. The hub administers it: the panel
  decides, the hub fetches and installs, the agent executes. Nothing about a
  module is the machine's own choice.
- **A service** is something the hub publishes for the machine's people to
  use: a share to mount, a link to open, a port to forward, the AI gateway to
  point an account's tools at. The hub says what exists; the machine's own
  people decide what to do with it, on the machine, and the panel does not
  render those choices at all.

A service is anything the hub can publish: its own Samba shares, its Gitea,
its AI gateway, a container's exposed port, and the services somebody
declares on machines the hub does not run — a NAS's Samba, an HTTP server. A
module declares its own services and they live only while it runs; a person
declares the rest by hand and those are probed.

```
module (gitea, samba, the AI gateway, the container runtime)
  -> service entry   {id, type, title, payload, is_healthy, source, description}
                     types: web | port | ai | file
declared by hand
  -> service entry   the same shape, probed rather than module-backed
```

**The service list carries no secrets.** It is fleet-global and hashed, and
every agent holds a copy. The one secret a service takes from the hub — an
account's gateway key — is resolved per device when its heartbeat is answered
and travels nowhere else. A payload host that is the hub's own is resolved
per device into the address that device actually reaches.

**What a machine does with a service is the machine's state.** A mount's
credentials, which accounts point at the AI gateway, which ports are
forwarded: all of it lives in the agent's own store, survives a hub restore
untouched, and appears in no hub backup. The hub never learns a share's
password.

## Managed is a completed handshake

A device becomes managed two ways — the hub installs the agent over SSH and
hands it a token, or the owner pastes an enrollment link into the agent — and
either way management begins at the same moment: the first heartbeat the hub
authenticates. A generated token is an offer, not a relationship; an install
that fails after generating leaves a dangling offer that shows nowhere and is
overwritten by the next attempt.

Three states, and no fourth:

| State | Holds when | The page shows |
| --- | --- | --- |
| unmanaged | no token, or a token never authenticated | the Unmanaged section — a scan finds routers and printers, and they belong here |
| managed, reporting | token, authenticated, heartbeat inside the window | the Managed section, with live gauges |
| managed, quiet | token, authenticated, heartbeat stale | the Managed section, with when it was last seen — the hub cannot tell a machine that is off from one that is gone, and says so |

Severing propagates from whichever end acts, over no channel but the ones
that exist:

- **The hub lets go by answering no** — a deleted token refuses the beat, a
  hub reset or reinstalled answers with a certificate off the agent's pin,
  a hub older than its agent turns it away. Each is a definitive rejection,
  not an unreachable hub, and the agent treats all three alike: after a few
  in a row it drops its binding, goes back to waiting for a link, and says
  why on its own page. Only a hub that does not answer at all is retried
  forever.
- **The device lets go by leaving** — the agent's page, `nagent disconnect`,
  or the package's own removal — which tells the hub first; the hub drops
  the token and keeps the name and credentials the owner typed.
- A device that joins a different hub cannot tell the first one, which keeps
  a managed-and-quiet row until somebody forgets it there.

The agent mirrors the three states: unbound and waiting for a link, bound and
beating, and bound but rejected — the one state that resolves itself, always
into unbound and waiting for a link. Its binding lives in one file, and the
running service adopts what another process writes there, so the CLI and the
page need no service restart.

## The hub installs; the agent is an outpost

A managed machine's agent carries no dependencies and must keep none, so it
is given the smallest job that can be done well: **execute what it is told,
report what is true**. It does not decide when to install, does not fetch
anything from the internet, and holds no policy about failure or retry.
Everything that needs judgment, a network, or memory across restarts lives
on the hub, where there is a configuration directory, a vault, and one place
to look when something goes wrong.

Two hub-side things do the work, and there is exactly one of each:

- **The agent module cache** turns "this machine, on this platform, wants
  this module" into bytes on the hub's own disk. It resolves the manifest's
  entry for that platform, fetches it — presenting a browser's TLS
  fingerprint where a vendor gates on one, which is the whole reason the
  fetch cannot happen on the agent — checks that what arrived opens like the
  package kind it claims to be, and keeps it under
  `/var/lib/neutrino/agent_module_cache/`. It is a cache in the strict sense:
  losing it costs a download and nothing else. One fetch serves every device
  of that platform, and a second machine wanting the same module waits for
  the first fetch rather than starting its own.
- **The agent module controller** turns cached bytes into an install on one
  machine. It holds one queue per device and runs one order at a time,
  because `dpkg` and its equivalents hold a machine-wide lock and two
  installs racing is a failure with no useful diagnosis. That lock is the
  device's, not the controller's: the SSH bootstrap that puts the agent on
  a machine in the first place takes the same one, so installing the agent
  and installing a remote desktop cannot overlap by construction rather
  than by a check somebody remembered to write.

Every request enters the same door. The panel's device drawer and the
machine's own page (`sudo nagent gui`) both post the same thing — *this
device wants this module* — and the machine's own page reaches it the way
everything agent-side reaches the hub, by riding the next heartbeat. There
is no second path, no direct download, and no difference in behavior
between the two surfaces.

The queue is every action's, not only a download's. An uninstall, and an
install a distro's own package manager serves, have nothing to fetch, so
their orders skip the cache — but
they take the same per-device queue as a download, because they contend
for the same machine-wide package and service locks, and because one
queue is what makes "one thing at a time, in the order asked" true for
the machine rather than for one kind of action. The SSH bootstrap that
installs the agent itself takes the device's same lock. Every way
software moves on a managed machine is therefore one serialized stream,
and its output is one stream too: every order carries the output of what
it ran, success included, and the drawer and the machine's own page both
render the hub's copy of it, so the two surfaces cannot tell different
stories about what is happening to the machine.

An order therefore walks one way and never loops back:

```
a person asks (panel, or the machine's own page)
  → the agent module cache resolves the platform's artifact, fetching it once
  → the agent module controller queues an order for that device
  → the agent is handed the bytes over the pinned channel, installs, verifies
  → the agent reports the outcome; the controller closes the order
```

**Retry is a person's word, never a timer's.** A failed order stays failed
and is not retried on its own: a vendor refusing now refuses in a minute,
and a machine that retries every minute spends the night doing it. Asking
again — pressing the button on either surface — is a new order, and it runs.
Two things clear a failure without being asked, because both mean the
question is settled: the software turning up on the machine anyway (somebody
installed it by hand), and an order for the opposite action. An order is the
whole of what a click leaves behind — the hub keeps no standing record of
what a machine should have, and orders and failures live in the
controller's memory alone: a hub restart forgets them and the person asks
again ([kill_on_sight.md](../kill_on_sight.md), "Unasked survival
machinery").

What the agent keeps is only what it can answer for: which modules are
present, what state each is in, and the output of the last thing it ran. The
output of every order travels up with its result, success included, and is
shown beside the operation it came from, because a person reading "the
download failed" and a person reading the vendor's own words are not equally
able to fix it, and a person watching an install wants to see it work.

## The network the hub assumes

Every enrolled machine — on the LAN, on NetBird, on whatever overlay comes
later — is somebody's own: locally administered, deliberately joined. The hub
is not multi-tenant and does not defend one enrolled machine from another.

The wire gets no such trust. A "LAN" can be a campus network with a thousand
strangers on it, so the panel answers only where an interface was deliberately
exposed and on the overlay ([network.md](modules/network.md), "What answers, and
where"), behind a password, and the agent channel carries its secrets under
pinned TLS. Trusting the machines and distrusting the wire is the whole
model.

## The agent channel is pinned TLS; the panel is not

Desired state carries real secrets, so the wire between hub and agent is
treated as hostile even where the machines on it are not. The agent API is
served on its own TLS-only port with a self-signed certificate generated at
setup. The enrollment link carries the certificate's SHA-256 fingerprint, and
the agent pins it — verification is the fingerprint, not a chain, so no device
installs a CA and no name has to match.

The panel a browser reads stays plain HTTP on its own port: a self-signed
certificate in a browser is a warning on every page, while the same
certificate pinned by an agent is exact. Two audiences, two transports,
because they verify differently.

The wire-level detail — which port serves what, the enrollment ticket, what
each failure means to the agent, what an attacker in each position gets — is
[agent.md](agent.md).

## The credential vault

Every secret the hub keeps for somebody is sealed in one store:
`config/credentials/vault.json`. The file has two members and nothing
readable — the wrapped data key, and one AES-256-GCM ciphertext sealing
every record whole, names, kinds, metadata and timestamps included, so the
file does not even say what it holds. The rest of `config/` holds
references — `key_id`, `password_id`, `sudo_password_id`, `login_id`,
`secret_id` — and no secret material at all.

| kind | sealed |
| --- | --- |
| `token` | value |
| `login` | password, username |
| `ssh_key` | private_key, passphrase |

An `ssh_key`'s type and fingerprint are annotations rather than material, so
the panel reads them back without the key itself ever being opened. Inside
the outer seal each object is a ciphertext of its own, its
AAD binding it to its id and kind; two objects cannot be swapped. A locked
vault therefore hides even the list — the panel shows that credentials exist
to be unlocked, not what they are.

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
fingerprints and reference counts, never read out. A delete is allowed and
cascades: every reference to the object is cleared in the same step — devices
lose the key, shares and providers lose theirs, a token-keyed proxy node is
disabled because it cannot serve — and the answer says how many of each.

Two things stay out. The panel password and a device's heartbeat token are
verifiers rather than secrets — one kept as a scrypt hash, the other as a
SHA-256 digest, and neither ever needed back.

The CLIProxyAPI client keys are not vault records either: the hub generates
them itself and the panel shows them in full to their owner. They are still
sealed under the data key where they are stored, so
`config/cliproxyapi/cliproxyapi.json` carries no key material, and they unseal
at use — rendering the gateway's config, answering the AI page, handing a
managed device its key. A stored record without a seal is dropped when the
file is read, and the device holding it is issued a fresh key on its next
heartbeat.

`nhub vault rekey` wraps the data key under a new passphrase; nothing sealed
is re-encrypted.

## The AI gateway is metered at the hub

CLIProxyAPI's management API answers loopback callers only, unlocked by a
key sealed under the vault's data key. The panel drains its per-request
queue and accumulates what it held — requests and tokens, per client key and
per upstream provider — under `/var/lib/neutrino/cliproxyapi/`, and a client
key belongs to a device, so usage lands on the subscription that spent it.
The dashboard, the AI page and the status strip all read that one store.

An upstream is reached two ways. A **provider** is an API key somebody typed,
which lives in the vault and is rendered into the gateway's YAML like every
other setting. An **account** is a subscription somebody signed into: the
panel starts the flow through the same management API, hands the person the
URL to open, passes the code back, and the gateway writes a token file into
`/var/lib/neutrino/cliproxyapi/auth/` and serves with it without a restart.

**Auth files are the one deliberate exception to "backing up `config/`
reproduces the appliance."** They are live provider credentials that no render
produces and no apply installs, so they sit in the state root and a downloaded
backup does not carry them: a restored box signs in again. Putting them in
`config/` would put refresh tokens for somebody's Claude and ChatGPT
subscriptions into a file that travels — the vault protects what the hub was
given, and nothing protects an archive once it has left the box. Signing in is
therefore never a configuration change, and nothing about it lights an apply
bar.

Both kinds land in one pool per upstream, and the gateway rotates across it
rather than ranking accounts above keys or below them. The panel does not
model an order it does not control: it lists accounts beside providers and
says what the gateway does.

## The panel heals itself; nothing ever asks for a manual refresh

The panel is a single-page app, and the machine under it restarts — a
restored backup, a package upgrade, an operator's restart — while pages sit
open. Every open page, the login page included, watches one signal: the
unauthenticated session endpoint carries `panel_started_at`, a constant of
the server process. A page remembers the first value it saw; a later answer
with a different one means a restarted panel — new code, and sessions gone
with the old process — and the page reloads itself once. An unreachable
backend is only ever waited out, and the same identity answering again is a
network blip: the page's own channels resume in place. Downtime and 401s are
deliberately not signals — restarts are too brief to catch by polling, and a
signed-out answer cannot be told from a lockout.

## One identifier shape

A stored record is keyed by a UUIDv4 hex string, generated at creation and
meaning nothing. The exception is a device, keyed by what the network knows it
by: its MAC address, or the `id:`-prefixed machine id of a machine enrolled
from behind someone else's NAT.

## The web backend runs as root, and that is a boundary, not a habit

`neutrino_hub_web.service` runs as root because it must edit nftables, restart
services, and scan the LAN. That privilege is why the panel sits behind a
password — a scrypt hash, never the password itself — and why what reaches it
is narrowed in the nftables input chain rather than left to what the process
binds. Do not spread root-requiring calls through the codebase: they live in the
`neutrino_hub/system/` and `*/ops`/`apply` layers behind named operations, so
the surface that needs privilege is small and auditable. What the unit narrows,
and what it deliberately does not, is [privilege.md](privilege.md). If this
ever becomes multi-user or WAN-exposed, split the privileged helper out then —
the apply layer is already the seam to split on.
