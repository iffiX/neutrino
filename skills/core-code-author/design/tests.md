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

One directory per subpackage under `agent/tests/`, summarized by what each
file owns:

| Directory | What its tests pin |
| --- | --- |
| `core/` | The one socket: the hello and the report, every field each carries, every frame shape the hub may send, including shapes this build cannot read, which become a typed `last_error` and never a dead process. Desired state: a copy lands on every `state` frame, the applied hash moves only once every enabled module applied, a failed apply keeps asking. The engine: one order at a time in its own thread, no retry and no memory of failure. Commands: only the allowlisted actions run, `run_command` is absent. Enrollment: the link's payload, every url tried, the fingerprint checked before a byte leaves. The store: atomic writes, root-only, no secret inside. |
| `control/` | The root-only socket: 0600 under 0700, connections persist, one thread each; an unexpected handler exception answers `agent_internal` with the class name and never drops the connection. |
| `streams/` | Shell and file streams behind the credit window: bytes out no faster than the hub's credit, bytes in no faster than this side's. |
| `modules/` | One runner per module (samba, gitea, podman, zfs): config, renderer, applier and runner each pinned as functions. The package state machine: verify is dpkg's own status word, removal purges, an unconfirmed install or uninstall waits instead of retrying. The RustDesk host and a person's own AnyDesk or TeamViewer, driven through their binaries with fakes. |
| `rdp/` | A share is declared only once the port answers; `rdp_nobody_seated` before anything is configured; the seat password set from the desired state and kept in a root-only file, never in the store or a report. |
| `platforms/` | The contract: capability advertisement, honest `unsupported_platform` refusals, the uid floor for human accounts, metrics from `/proc` and `/sys` with fakes, `runuser` never `sudo`. |
| `packaging/` | What the deb and the rpm carry, staged into `tmp_path`: the interpreter tree under `/opt/neutrino_agent`, the unit, the vendored RustDesk host at its pinned hash, and the refusal for a machine no package is published for. |
| `cli/` | The operator matrix: every command × root and ordinary × bound and unbound × service alive and dead, each cell asserting the words printed and the exit status. `rdp start` and `rdp stop` through the control socket. The wording table complete. |

## The client block

The same shape under `client/tests/`:

| Directory | What its tests pin |
| --- | --- |
| `core/` | The one socket to the hub: the four frames down, the ask and its answer up, reconnection. Enrollment: a link with `kind: "client"` accepted, a device link refused with `link_not_for_client`. The version lock: a client newer than its hub is asked to upgrade. |
| `control/` | The local channel and its identity: a Unix socket on Linux and macOS, a named pipe on Windows, the peer read from the kernel and never from the body. The page served with both word catalogs inlined. Every route of the window and of `nclient service`. |
| `gui/` | The window's seam, all fakes: the bridge forwards exactly method, path and body and nothing else the page says; a dead channel answers `control_channel_closed`; one shell per toolkit (WebKitGTK pinned to the 4.1 API, WebView2, WKWebView) refusing with a typed code naming what to install; the three trays. |
| `services/` | One file per kind. `web`: open in the browser. `port`: the loopback relay, the entry's own port when free, else a free one named. `file`: the stage machine of a mount, the credentials file root-only through the helper, the refusals by code. `ai`: the cc-switch driver, adoption of what the person had before the first switch, all-or-nothing activation, restoration on `off`. `rdp`: the viewer spawned with the password in one argv and nowhere else, viewers closed on quit. The store and the worker. |
| `platforms/` | Linux, Windows and macOS behind one contract: the mount location's shape per platform, the Windows console and pipe helpers, `darwin` refusing what the Mac does not carry. |
| `packaging/` | What every package carries, staged into `tmp_path` with the compiled and fetched parts stood in for: the payload, the pinned cc-switch and RustDesk viewer, the icons, the deb and rpm, the msi and the pkg, and the refusal for a machine none is published for. |
| `cli/` | Every command × root refused and ordinary × bound and unbound × resident alive and dead; `gui`, `quit`, the mount helper, the `service` verbs; the wording table complete in both languages. |

## The hub block

Mirrored the same way under `hub/tests/`, summarized by area:

| Area | What its tests pin |
| --- | --- |
| `modules/<name>/` | Renderers and collectors stay pure and are tested as functions: config in, files or lists out. The service-list collector (module entries live only while the module serves, manual entries keep their probes, no credential in any entry), the catalog cache and its stamps, the manifest loader's two gates and its order (every manifest names platform, hub or user and says where its software comes from, or is refused; the tiers come back in the order both surfaces draw, by title inside each), that only a hub-tier module names a license and the directions to its source, the RustDesk manifest's own pins (an exact asset URL and this hub's own sha256 per platform, never a `*-sciter` build, and the AGPL block's exact-tag source), the cache's checksum refusal, the agent package cache's four answers (a seeded platform served with nothing reached for, one the manifest publishes fetched once and kept, a release serving something else refused and cached nowhere, a platform with no url refused by name) and the hand-pinned build winning over both, the device-share registry (a share is the machine's last word, withdrawn when it stops and aged out when it goes quiet), the vault, each module's applier where it fixes the machine (gitea owning its work root). |
| `web/` | Routers through a test client: the agent wire (both version gates and the generation gate, per-account key grant and revocation, a locked vault degrading instead of failing a beat), that a click is one order and a beat orders nothing by itself (a user-tier module takes no order at all), the rdp declaration (recorded against the device the token resolved to, at the address the hub holds rather than one the beat named, withdrawn when the machine stops or is forgotten), the Origin belt on state-changing panel routes, session auth, every `{code, params}` refusal shape, the drawer's service asks (a closed verb set: a fresh mount must say whom it is for, a share cannot be asked for at all, a quiet agent takes nothing, and the beat's service rows land where the drawer reads), and the models the frontend mirrors. |
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
