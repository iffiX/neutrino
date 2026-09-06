# Tests

Three blocks of tests, split by what they may touch: the **agent** block and
the **hub** block run in-process in milliseconds and touch nothing outside
their own temporary directories; the **integration** block runs on live
machines in the CI/CD release pipeline and touches everything, because the
seams it exists for — package managers, systemd, wires between two machines
— are exactly what the in-process blocks fake.

| Block | Lives in | Runs | May touch |
| --- | --- | --- | --- |
| agent | `agent/tests/` | `pytest -q`, seconds, every commit | Fakes and `tmp_path` only: fake platforms, injected clocks, sockets on temporary paths; an autouse fixture redirects every store off the real machine |
| hub | `hub/tests/` | `pytest -q`, under a minute, every commit | FastAPI test clients and temporary config roots; never a unit, an interface, or `/etc` |
| integration | `packaging/integration/` | `run_on_box.sh` on the pipeline's VM pair; minutes | A whole machine: real installs, real systemd, real DHCP on a served wire, a real client VM |

## The mirror rule

Where a source file is testable on its own, its tests live in the file that
mirrors it: `agent/neutrino_agent/<package>/<module>.py` is tested by
`agent/tests/<package>/test_<module>.py`, and the hub tree likewise. Every
test directory carries an `__init__.py` so mirrored names never collide,
and the shared fakes — the fake platform, the injected clock, the redirect
of every store into `tmp_path` — live in the block's `conftest.py`, never
copied into files.

A scenario that crosses files lives with **the surface the operator
touches**: `sudo nagent status` asking a live in-process control server is
`cli/test_status.py`'s case, not the server's, because the thing under test
is what the person typed. The server file keeps the route-level matrix; the
cli file keeps the operator's walk.

## The agent block

One directory per package, summarized by what each file owns:

| Directory | What its tests pin |
| --- | --- |
| `core/` | The heartbeat: every field the payload carries, every shape the reply may take — including shapes this build cannot read, which must become a typed `last_error` and never a dead process. The refusal counter and the three-beat self-unbind. Wire generations: a stale answer triggers a reinstall and never counts toward unbinding. Enrollment links, the pinned channel's exception mapping, the self-update digest check and the detached install commands (a same-version reinstall must actually apply), the reconcile worker's scheduling. |
| `platforms/` | The contract itself: capability advertisement, honest `unsupported_platform` refusals for whatever a platform does not carry, platform-owned account floors — uid on POSIX, local profiles on Windows with the built-in accounts excluded — account homes resolved from the account database and never `$HOME`, the step-down environment carrying the target's identity, mount ownership mapping under the asking account's home. Linux: CIFS mount options, system-package installs. macOS, all with fakes and verified later on one real Mac: dscl personhood (floor 501, no service accounts, IsHidden), the xucred peer credential, mount_smbfs fed through a transient nsmb.conf with the password never on argv, Remote Login read both ways, launchd bootstrap/kickstart, the pkg kind, sysctl/vm_stat/top parsed defensively. Windows, all with fakes and verified later on the pipeline VM: pipe impersonation judging privilege as an elevated Administrators token, account homes read from the profile database (SYSTEM's systemprofile, not a `C:\Users` child), the share mapped inside the target account's own session — picked by session enumeration, an Active session console or RDP first, a Disconnected one as fallback — with the password on no argument vector, the mapping script closed by its trailing blank line and believed only on its printed success marker, refused typed when the account has no session, the agent's data root under ProgramData with the credentials directory restricted there, a free drive letter writable to the account that claims it, the agent's own service read and started through the control manager and hosted behind its handshake — running reported before the loop is waited on, a stop answered and nothing else acted on, the minute-tolerant SSH capability install, native Win32 metrics with the processor load taken between two samples. |
| `modules/` | The package state machine: verify is dpkg's own status word (`rc` reads as absent), removal purges, both unconfirmed latches (an install or uninstall that ran but did not verify waits instead of retrying every recheck), the never-asked module that is reported and not touched. The one verb pair per platform: the SSH server's install puts the missing package before its unit, its uninstall genuinely removes the package on Linux and the capability on Windows, and macOS maps both onto Remote Login with no binary moved. Downloads and package-kind dispatch. RustDesk: the direct-mode options carry no rendezvous or relay server, a configuration write lands at every path the service and the session read and keeps what it did not come to change, the permanent password is on the one argument vector the binary offers and in no file the module writes, `--config` appears in no vector at all, and the id is read with the binary's own verb. |
| `services/` | One file per type. `ai`: the staged apply — each tool's own knobs written per account, untargeted accounts restored, the symmetric `no_target_user` guard. `file`: the stage machine (queued → installing tooling → mounting), credential hygiene proven three ways (never on argv, never in the store, never in a state payload), remount on start, the mount-point rules, the platform asked with each record's own account. `port`: a real relay on loopback ports, both directions, closed clean. `rdp`: sharing takes the privileged scope and the rustdesk module, the access password reaches RustDesk and a root-only file and neither the store nor the declaration, a configured share reads `starting` — `waiting_for_approval` on macOS — until the direct port answers and is declared only then, unshare closes every file sharing opened, and the peer a client is told to dial is the bare address on the default port. `store`: round-trips with passwords structurally absent. |
| `control/` | The route matrix over the socket: every route × privileged, ordinary and unreadable peers — an identity the kernel cannot vouch for refused, never guessed, and a body naming another account changing nothing about the scope. The dispatch guard: an unexpected handler exception answers `agent_internal` carrying only the exception's class name and never drops the connection. Scope-shaped state (an ordinary account sees itself and no other). No route serves a page: the window loads it from the package's files. The page contract, pinned on the frontend files: the three sections, controls greyed never hidden, the code-to-word table asserted **complete** so a new code without a word fails the suite, the two remote desktop panels and every share state worded, the share panel standing with no entry behind it and greyed outside the privileged scope, the redraw guards, the bridge adapter under the old call sites with no `fetch` left. |
| `gui/` | The window's seam, all fakes: the bridge forwards exactly method, path and body — scope from the channel, never from anything the page sent — and a dead channel answers `control_channel_closed`; the fd channel speaks one handed-over connection request after request against a live server, rebuilds from a bare descriptor, and stays dead once it fails; the shells dispatch per platform, embed the bridge end to end through a fake toolkit, refuse typed naming what to install, and pin the WebKitGTK 4.1 API. |
| `packaging/` | What every package carries, staged into `tmp_path` with the fetched and compiled parts stood in for: the machines the packages are published for and the refusal for one they are not, the agent tree stamped and moded, what a carried interpreter loses, the build machine's own paths taken back out. Per format: the deb and rpm laying the payload under one prefix with an entry point that runs the carried interpreter and a dependency field naming C libraries and no Python, the msi registering a service rather than a task and chaining WebView2 only where it is absent, the pkg's install names moved off /Library/Frameworks. The two icon containers, member for member against the source PNGs. |
| `cli/` | The operator matrix: every command × root and ordinary × bound and unbound × service alive and dead — each cell asserting the words printed, the exit status, and that no cell lies about the machine. The `gui` handover: the invoker connecting and spawning the window process with the descriptor passed, the window role answering in the opener's scope, Windows hosting the window in the invocation over per-request pipes, the sudo step-down keywords, and nothing printed for a person to copy. The page-mirroring verbs: `module list` in the six-token table, install and uninstall posting the page's own ask and following the operation stream against a faked sequence, the SSH uninstall's confirmation, the service listing's per-kind nesting and numbering, the ai apply's atomic target set as one posted body, the share password and the desktop's access password through getpass and never argv, the rdp verbs' share, unshare, connect and show, and the CLI wording tables held complete against the page's code list. |

## The hub block

Mirrored the same way under `hub/tests/`, summarized by area:

| Area | What its tests pin |
| --- | --- |
| `modules/<name>/` | Renderers and collectors stay pure and are tested as functions: config in, files or lists out. The service-list collector (module entries live only while the module serves, manual entries keep their probes, no credential in any entry), the catalog cache and its stamps, the manifest loader's installer-tier gate (every manifest names platform, hub or user, or is refused), the RustDesk manifest's own pins (an exact asset URL and this hub's own sha256 per platform, never a `*-sciter` build, and the AGPL block's exact-tag source), the cache's checksum refusal and the corresponding source kept beside the binary, the agent package cache's four answers (a seeded platform served with nothing reached for, one the manifest publishes fetched once and kept, a release serving something else refused and cached nowhere, a platform with no url refused by name) and the hand-pinned build winning over both, the device-share registry (a share is the machine's last word, withdrawn when it stops and aged out when it goes quiet), the vault, each module's applier where it fixes the machine (gitea owning its work root). |
| `web/` | Routers through a test client: the agent wire (both version gates and the generation gate, per-account key grant and revocation, a locked vault degrading instead of failing a beat), that a click is one order and a beat orders nothing by itself (a user-tier module takes no order at all), the rdp declaration (recorded against the device the token resolved to, at the address the hub holds rather than one the beat named, withdrawn when the machine stops or is forgotten), the Origin belt on state-changing panel routes, session auth, every `{code, params}` refusal shape, and the models the frontend mirrors. |
| `cli/` | Setup's screens by their document form, root gates, apply's component list — the apply-path symmetry that has bitten twice is pinned here. |
| `packaging/` | Where the hub's build and its runtime must agree, staged into `tmp_path`: the agent-package manifest's shape per platform (hash, weight, and a url only a release stamps), the refusal for a build whose name says no family or machine, and the file names the seeding writes resolved back by the runtime cache that reads them. |

## The integration block

Flat, one file per concern, because these mirror machine states rather than
source files. `run_on_box.sh` orders them: install, footprint, reinstall,
reset, set up again, a module install through the panel, the whole-page
sweep (one file per panel API), the pinned agent channel end to end, and
the device lifecycle — which, while the client is managed, also walks what
only two live machines can prove: the control channel answering each
identity over ssh, a declared port forwarded back through the client's
loopback, the operator's own commands typed as the operator would.

What belongs here is only what the in-process blocks cannot see: a real
`dpkg` refusing, a real systemd unit flapping, a lease on a served wire,
the same-version wire-generation drill — an old-generation agent watching
the hub upgrade and reinstalling itself back to health.

## What a change owes

A new module, service type, route or CLI verb lands with its mirrored test
file in the same commit. A new operator-visible behavior adds its cell to
the cli or control matrix. A wire change bumps the generation and extends
the drill. A new `{code}` anywhere adds its word to the page's table, which
the completeness assertion enforces. The pipeline gains a case only when
the behavior needs a real machine to exist.
