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
| `platforms/` | The contract itself: capability advertisement, honest `unsupported_platform` refusals for whatever a platform does not carry, platform-owned account floors, account homes resolved from the account database and never `$HOME`, the step-down environment carrying the target's identity, mount ownership mapping under the asking account's home. Linux: CIFS mount options, system-package installs. macOS, all with fakes and verified later on one real Mac: dscl personhood (floor 501, no service accounts, IsHidden), the xucred peer credential, mount_smbfs fed through a transient nsmb.conf with the password never on argv, Remote Login read both ways, launchd bootstrap/kickstart, the pkg kind, sysctl/vm_stat/top parsed defensively. |
| `modules/` | The package state machine: verify is dpkg's own status word (`rc` reads as absent), removal purges, both unconfirmed latches (an install or uninstall that ran but did not verify waits instead of retrying every recheck), the never-asked module that is reported and not touched. The one verb pair per platform: the SSH server's install puts the missing package before its unit, its uninstall genuinely removes the package on Linux and the capability on Windows, and macOS maps both onto Remote Login with no binary moved. Downloads and package-kind dispatch. |
| `services/` | One file per type. `ai`: the staged apply — each tool's own knobs written per account, untargeted accounts restored, the symmetric `no_target_user` guard. `file`: the stage machine (queued → installing tooling → mounting), credential hygiene proven three ways (never on argv, never in the store, never in a state payload), remount on start, the mount-point rules. `port`: a real relay on loopback ports, both directions, closed clean. `store`: round-trips with passwords structurally absent. |
| `control/` | The route matrix: every route × both transports × privileged, ordinary and tokenless callers. The token lifecycle: minted unclaimed and waiting forever, claimed by its first page request, expired by a stopped pulse, revoked at once; minting refused for another account by an ordinary caller, downscoped for one by root, refused entirely while the agent does not hold the loopback port. The Origin and Content-Type belts. Scope-shaped state (an ordinary account sees itself and no other). The page contract: the three sections, controls greyed never hidden, the code-to-word table asserted **complete** so a new code without a word fails the suite, the redraw guards. |
| `cli/` | The operator matrix: every command × root and ordinary × bound and unbound × service alive and dead — each cell asserting the words printed, the exit status, and that no cell lies about the machine. The `ui` session: waits while unclaimed, Ctrl-C revokes, a closed window is worded as one only when a page existed. |

## The hub block

Mirrored the same way under `hub/tests/`, summarized by area:

| Area | What its tests pin |
| --- | --- |
| `modules/<name>/` | Renderers and collectors stay pure and are tested as functions: config in, files or lists out. The service-list collector (module entries live only while the module serves, manual entries keep their probes, no credential in any entry), the catalog cache and its stamps, the vault, each module's applier where it fixes the machine (gitea owning its work root). |
| `web/` | Routers through a test client: the agent wire (both version gates and the generation gate, per-account key grant and revocation, a locked vault degrading instead of failing a beat), that a click is one order and a beat orders nothing by itself, the Origin belt on state-changing panel routes, session auth, every `{code, params}` refusal shape, and the models the frontend mirrors. |
| `cli/` | Setup's screens by their document form, root gates, apply's component list — the apply-path symmetry that has bitten twice is pinned here. |

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
