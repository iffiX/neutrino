# Architecture

The load-bearing structural principles of this repo.

## The shape of the system

One box runs the hub. A Linux machine the hub manages runs the agent, as
root, headless. A person's own machine, Linux, Windows or macOS, runs the
client in that person's session, never as root. The hub box runs its own
agent too, and hosts no module itself.

```
config/ ──render──▶ /var/lib/neutrino/generated/ ──apply──▶ the daemons:
  ▲                                              xray, dnsmasq, cliproxyapi,
  │ every change is a write here                 nftables, the overlay, units
  │
web/ (FastAPI, root) ◀────── hub/frontend/ (browser, plain HTTP, password)
  ▲                    ▲
  │ one socket over    │ one socket over pinned TLS: the published
  │ pinned TLS:        │ list down, a service stream for its material
  │ reports up,        │
  │ the state down,    neutrino_client (a person's session, never root):
  │ streams both ways  a tray and a window; Open, Connect, Mount, Apply
  │
neutrino_agent (root, stdlib only) ──── hosts modules, applies the state,
  ▲                                     shares the desktop
  │ root-only Unix socket
nagent (root, on the machine)
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

The agent has no dependencies and listens on nothing: it keeps one socket
open to the hub and reconnects when it drops, so it survives restarts, sleep
and NAT in between. It decides nothing: the hub says in `state` what each
module is to be, and the agent observes, installs and configures until the
machine matches ("The hub says what is wanted; the agent observes, installs
and configures"). What a person does with a published service is the
client's, on that person's machine, and the agent has no part in it.

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
  does is [../../cli.md](../../../docs/cli.md).

The mechanical placement rules are in
[../coding_style/layout_style.md](../coding_style/layout_style.md).

## Services are the person's to take; modules are the hub's to install

Two different things leave the hub, and confusing them is what the
modules/services split exists to prevent
([agent.md](agent.md), "Who may tell the agent what").

- **A module** is software a managed machine hosts. The hub administers it:
  the panel's Samba, Gitea, Containers and ZFS pages pick the devices, the
  hub fetches and installs, the agent executes. Nothing about a module is the
  machine's own choice.
- **A service** is something the hub publishes for a person to use from
  their own machine: a link to open, a port to forward, the AI gateway to
  point their tools at, a share to mount, a desktop to view. The hub says
  what exists; the client on that person's machine is where every choice is
  made, and the panel does not render those choices at all.

A service is anything the hub can publish: a device's Samba shares, its
Gitea, a container's published port, the hub's own AI gateway, a desktop a
machine is sharing, and the services somebody declares by hand on machines
the hub does not run. A module's entries live only while the module runs on
an enabled device; a hand-declared entry is probed; a desktop entry is the
machine's own word and lives only while it keeps reporting.

```
module on a device (samba, gitea, podman)   -> service entry
the hub's AI gateway                        -> the one ai entry
a machine sharing its desktop               -> an rdp entry, from its reports
declared by hand (web, port, file)          -> the same shape, probed
  service entry: {id, type, title, payload, is_healthy, source, description}
  types: web | port | ai | file | rdp
```

**The service list carries no secrets.** It is composed once, fingerprinted,
and pushed to every client resolved for the address that client reaches the
hub on. The two secrets a service takes from the hub travel one at a time:
a client's gateway key rides its own socket, and a desktop's seat password
is unsealed for the one answer to a Connect. The panel's Services page shows
the four kinds it can declare or module-publish; a shared desktop appears
only in the device drawer and on clients.

**What a person does with a service is their machine's state.** A mount's
login and path, which tools point at the gateway, which ports are
forwarded: all of it lives in the client's own store on that machine, and
appears in no hub backup.

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
  why in `nagent status`. Only a hub that does not answer at all is retried
  forever.
- **The device lets go by leaving** — `nagent disconnect` or the package's
  own removal — which tells the hub first; the hub drops
  the token and keeps the name and credentials the owner typed.
- A device that joins a different hub cannot tell the first one, which keeps
  a managed-and-quiet row until somebody forgets it there.

The agent mirrors the three states: unbound and waiting for a link, bound and
beating, and bound but rejected — the one state that resolves itself, always
into unbound and waiting for a link. Its binding lives in one file, and the
running service adopts what another process writes there, so the CLI and the
page need no service restart.

## The hub says what is wanted; the agent observes, installs and configures

A managed machine's agent has no dependencies and must keep none, so it is
given the smallest job that can be done well. **It observes what is true,
makes the machine match the state, and reports the result.** Whether a
module is wanted, where its package comes from and whether to try again are
settled on the hub. That is where there is a configuration directory, a
vault, and one place to look when something goes wrong.

What is wanted is one word per module, `want`, in
`config/devices/<id>/modules.json`: `absent`, `installed`, `stopped` or
`running`. The Modules page writes it directly. The hub composes it with the
module's configuration and the recipes for the machine's platform into the
`state` it pushes ([protocol.md](protocol.md), "The channel").

There is no queue between the page and the machine. The state is the whole
of what a press leaves behind, and `config/` is where it is.

The agent observes each module it has a runner for, whoever installed it. It
reads whether the package is present, whether the unit is active, and whether
the hub's configuration has ever been applied. From those facts it reports
one of the closed states, and it makes each module the state mentions match
its `want`.

The bytes come from the hub. The agent opens a `package` stream for a
module's package, and the hub serves it from its own cache,
`/var/lib/neutrino/agent_module_cache/`. The cache fetches a package once for
every device of that platform, presenting a browser's TLS fingerprint where a
vendor gates on one. Losing it costs a download and nothing else.

Every way software moves on a managed machine is one serialized stream, and
its output is one stream too. Package operations on one machine run one at a
time, serialized on the agent, because `dpkg` and its equivalents hold a
machine-wide lock. The SSH bootstrap that puts the agent on a machine takes
the same lock.

During an install or an uninstall the agent opens a `log` stream and sends
the output line by line, success included. The drawer shows
the hub's copy of it as it arrives, so no surface tells a different story
about what is happening to the machine.

A change therefore walks one way and never loops back:

```text
a person presses a button on the Modules page
  → want is written to config/devices/<id>/modules.json
  → the hub pushes the state with the configuration and the recipes
  → the agent opens a package stream, installs, configures, starts or stops
  → the agent reports the observed state; the page shows it
```

**Retry is a person's word, never a timer's.** A step that failed is reported
`failed` with its code and is not retried while the state's hash is
unchanged. A vendor refusing now refuses in a minute, and a machine that
retries every minute spends the night doing it. Trying again is a change to
the state, from a person's press or a new configuration, never from a timer.

Software somebody installs or removes by hand is observed and shown, never
fought. A hand-installed module reports `installed`, and the first
**Configure** imports what the machine already has into the hub's
configuration. The hub keeps no record of a failure beyond the machine's own
report. A hub restart loses nothing, because `want` is in `config/`
([kill_on_sight.md](../kill_on_sight.md), "Unasked survival machinery").

What the agent keeps is only what it can answer for. That is which modules
are present, the state of each, whether the hub's configuration was applied,
and the output of the last thing it ran.

That output is shown beside the step it came from. A person reading "the
download failed" and a person reading the
vendor's own words are not equally able to fix it. A person watching an
install wants to see it work.

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

The wire itself is [protocol.md](protocol.md): which port serves what, the
frames, admission by protocol number, and, in "Admission and the binding",
what each refusal does to the binding. The enrolment ticket and what an
attacker in each position gets are [agent.md](agent.md).

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
