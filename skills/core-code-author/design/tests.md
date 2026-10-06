# Tests

Six blocks of tests, split by what they may touch. The **agent**, **client**
and **hub** blocks run in-process in milliseconds and touch nothing outside
their own temporary directories. The **android** and **ios** blocks run the
apps' unit tests on the build machine, with the phone's system services faked.
The **integration** block runs on live machines in the CI/CD release pipeline
and touches everything, because the seams it exists for (package managers,
systemd, wires between two machines) are exactly what the in-process blocks
fake.

| Block | Lives in | Runs | May touch |
| --- | --- | --- | --- |
| agent | `agent/tests/` | `pytest -q`, seconds, every commit | Fakes and `tmp_path` only: fake platforms, injected clocks, sockets on temporary paths; an autouse fixture redirects every store off the real machine |
| client | `client/desktop/tests/` | `pytest -q`, seconds, every commit | Fakes and `tmp_path` only: fake platforms and toolkits, the compiled and fetched parts stood in for |
| hub | `hub/tests/` | `pytest -q`, under a minute, every commit | FastAPI test clients and temporary config roots; never a unit, an interface, or `/etc` |
| android | `client/android/app/src/test/` | `./gradlew test lint`, every commit | JUnit on the JVM; a fake socket, fake Keystore and fake VpnService; never an emulator or a device |
| ios | `client/ios/<target>Tests/` | `xcodebuild test` on the simulator; paused with the app since 2026-10-03 | XCTest; a fake socket, fake Keychain and fake tunnel provider; never a device |
| integration | `packaging/integration/` | `run_on_box.sh` on the pipeline's VM pair; minutes | A whole machine: real installs, real systemd, real DHCP on a served wire, a real client VM |

## The mirror rule

Where a source file is testable on its own, its tests live in the file that
mirrors it: `agent/neutrino_agent/<package>/<module>.py` is tested by
`agent/tests/<package>/test_<module>.py`, and the hub tree likewise: a router
in `hub/neutrino_hub/web/routers/{hub,agent}/<page>.py` is tested by
`hub/tests/web/routers/{hub,agent}/test_<page>.py`. Every
test directory carries an `__init__.py` so mirrored names never collide,
and the shared fakes (the fake platform, the injected clock, the redirect
of every store into `tmp_path`) are in the block's `conftest.py`, never
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
| `streams/` | Shell and file streams behind the credit window: bytes out no faster than the hub's credit, bytes in no faster than this side's. A shell kept by id: attached again with its kept output first, shared by every stream attached at the smallest window, ended with its last stream unless it is persistent or shared, on a real pseudo-terminal and on a faked pseudo console. The `connect` stream: the dial goes to `127.0.0.1:<port>` and nowhere else, or to the one address a container port is published on; a port the machine does not publish now is refused `port_not_published {port}`, for each kind of published port as it starts and stops being published; a refused, timed-out or unreachable dial closes `connect_failed {reason}` within `AGENT_CONNECT_DIAL_TIMEOUT_S`; bytes both ways under credit; end of file on either side closes the stream after what was read is sent. A UDP `connect`: an echo on a real loopback UDP socket, two sources each getting their own replies; `port_not_published` for a number published on TCP alone; a source forgotten after `AGENT_UDP_IDLE_TIMEOUT_S` with the clock injected; the 65th source replacing the idlest; Podman's `host_bindings` carrying `protocol`, UDP ones included. The Terminal module: a shell for a named account through the platform's step-down in its home with its environment, the module's shell program, `account_unknown {account}` and `shell_program_unusable {path}` with no fallback, a container's shell untouched, a session already open keeping what it runs, the session's `account` the one the shell runs as, and Windows taking the shell program alone. |
| `modules/` | One runner per module (samba, gitea, podman, zfs, vscode): config, renderer, applier and runner each pinned as functions. The file share on Windows and macOS, its applier driven through a faked PowerShell or faked system tools that record every argument and answer canned output. The package state machine: verify is dpkg's own status word, removal purges, an unconfirmed install or uninstall waits instead of retrying. The RustDesk host and a person's own AnyDesk or TeamViewer, driven through their binaries with fakes. CloudCLI against a fake `npm` and a fake register endpoint, its service environment naming no gateway, each install step's failure code, and its forwarder: 401 for a request with neither token nor login state, a token traded for the login state once, the register and login endpoints never passed on, a WebSocket passed through. code-server the same way: one instance per account against a fake release archive, each install step's failure code, and its forwarder on `127.0.0.1` only. Gitea on macOS and Windows with faked system tools: the account made and read back, the LaunchDaemon or the service, `app.ini` with each system's paths and the `git` found, `gitea_git_missing` without one, and an uninstall that keeps the data. Every forwarder (VS Code, code-server, CloudCLI) binds loopback alone. |
| `ai_tools/` | The machine's AI tools against a fake cc-switch that records every argument list and the account it ran as: the client's steps in the client's order for each account the state names; nothing run when an account's records already carry the wanted settings; the records under the state root, never in an account's home; the switch back when the section turns off, when an account leaves the list, before `nagent service uninstall`, on `nagent leave` and on `binding_unknown`; cc-switch fetched from the hub when no copy is there or its version is not the section's, unpacked into `ai_tools/bin/` and run from there, and `cc_switch_download_failed` for every account with nothing run when the fetch fails; the account lock (two runs for one account never overlap, two accounts never wait on each other, a lock a killed process left blocks no one) and no switch once the binding is gone; every file a switch may write kept before the first switch and put back byte for byte, a tool directory made for the switch and taken away again, Codex's and Gemini's files read back naming the hub, and a switch back that cannot run cc-switch failing with the records kept; each system's way of running as the account (`runuser` on Linux, the account's uid and groups on macOS, the one-shot task under the account's login on Windows, `credential_missing` without one); the report's result and code per account. |
| `rdp/` | A share is declared only once the port answers; `rdp_nobody_seated` before anything is configured; the seat password set from the desired state and kept in a root-only file, never in the store or a report. The Remote desktop module on each system against faked service managers and process tables: the switch on stops and kills every RustDesk host that is not the agent's copy and leaves every `--connect` viewer, keeps aside what is registered under RustDesk's names in `remote_desktop/kept/`, writes the settings with the host stopped (the direct port, rendezvous and relay at `127.0.0.1`, the seat password in `RustDesk.toml`), registers the copy under RustDesk's names and records it in `registered.json`; the switch off leaves no process and no registration of the agent's and puts back what was kept; `nagent service uninstall` turns it off first; the share declared from the socket table with no connection to the host; a share recorded by the old command reported until the first state names the module; each step's failure `rdp_takeover_failed` or `rdp_restore_failed` with its `step`. |
| `platforms/` | The contract: capability advertisement, honest `unsupported_platform` refusals, the uid floor for human accounts, metrics from `/proc` and `/sys` with fakes and, for Windows and macOS, from canned `NtQuerySystemInformation`, PDH, `ps`, `ioreg` and `powermetrics` readings, every system filling the same document, `runuser` never `sudo`. |
| `packaging/` | What the deb and the rpm carry, staged into `tmp_path`: the interpreter tree under `/opt/neutrino/agent`, the unit, the vendored RustDesk host at its pinned hash, and the refusal for a machine no package is published for. The macOS and Windows packages carry RustDesk in the agent's own folder and register nothing of RustDesk's at install; the deb carries no RustDesk unit. |
| `cli/` | The operator matrix: every command × root and ordinary × bound and unbound × service alive and dead, each cell asserting the words printed and the exit status. The wording table complete. `nagent rdp` exists no more, on the command line or the control socket. |

## The client block

The same shape under `client/desktop/tests/`:

| Directory | What its tests pin |
| --- | --- |
| `core/` | The one socket to the hub: the four frames down, the ask and its answer up, reconnection. Enrollment: a link with `kind: "client"` accepted, a device link refused with `link_not_for_client`. The version lock: a client newer than its hub is asked to upgrade. The EasyTier daemon: every refusal by code, its state read back at start, the core run only while a network or a console is configured and started again with a doubling wait; the overlay driver against the real daemon behind a fake socket, the secret and the console's address in the request's body only. The hub row's way in (LAN, NetBird, EasyTier, Relay) from the address the socket reached. |
| `control/` | The local channel and its identity: a Unix socket on Linux and macOS, a named pipe on Windows, the peer read from the kernel and never from the body. The page served with both word catalogs inlined. Every route of the window and of `nclient service`. The EasyTier daemon's socket: one JSON line each way, open to every account, its pipe open to interactive users who cannot make an instance of it. |
| `gui/` | The window's seam, all fakes: the bridge forwards exactly method, path and body and nothing else the page says; a dead channel answers `control_channel_closed`; one shell per toolkit (WebKitGTK pinned to the 4.1 API, WebView2, WKWebView) refusing with a typed code naming what to install; the three trays. |
| `services/` | One file per kind. Every forwarded kind: a listener on `127.0.0.1` at the entry's local port, one `connect` stream per accepted connection and no dial to a device address; the port pick (the entry's own port when nothing listens on it on any address of the machine, else from 20000 up, recorded per entry). `web`: open at the slug address, `?tkn=` for a token entry. `port`: the forward and its refusals by code; a UDP entry's forward, where two local programs through one stream each get their own replies, at most 16 datagrams are held while the stream waits for its first credit, an open refused at **Connect** and later, the table holding one number for a TCP and a UDP entry, and the row's `/udp` text. An entry with empty health leaves its actions enabled. `file`: the stage machine of a mount at `127.0.0.1` and the local port, the credentials file root-only through the helper, the refusals by code. `ai`: the cc-switch driver naming the local port, adoption of what the person had before the first switch, all-or-nothing activation, restoration on `off`; with the agent's program directory present, the page's chip and **Configure** disabled with `ui.reason.ai_managed`, one deactivation of a chip that was on, and `nclient service ai apply` refused `ai_tools_managed`. `rdp`: the viewer started against the local port with the password in one argv and nowhere else, viewers closed on quit. The panel forward. The files adapter on Windows: the address plan (`198.19.255.1/24` for the adapter, one address per machine from `198.19.255.2` up, kept per hub and machine), and the SOCKS endpoint taking `<address>:445` of a machine it knows and refusing every other target. The store and the worker. <!-- scan: allow --> |
| `platforms/` | Linux, Windows and macOS behind one contract: the mount location's shape per platform, the Windows console and pipe helpers, `darwin` refusing what the Mac does not carry. |
| `packaging/` | What every package carries, staged into `tmp_path` with the compiled and fetched parts stood in for: the payload, the pinned cc-switch and RustDesk viewer, the icons, the deb and rpm, the msi and the pkg, and the refusal for a machine none is published for. |
| `cli/` | Every command × root refused and ordinary × bound and unbound × resident alive and dead; `gui`, `quit`, the mount helper, the `service` verbs, `easytier-daemon` put together over a temporary directory; the wording table complete in both languages. |

## The android and ios blocks

The mirror rule holds per language. `src/main/kotlin/<package path>/<Type>.kt`
is tested by `src/test/kotlin/<package path>/<Type>Test.kt`, and a Swift file
`<dir>/<Type>.swift` in a target by `<dir>/<Type>Tests.swift` in that target's
test bundle ([kotlin_style.md](../coding_style/kotlin_style.md),
[swift_style.md](../coding_style/swift_style.md)).

Both apps speak the channel of `docs/guide/protocol/channel.md` and share no
code with the desktop client. Their channel tests read
`hub/tests/web/channel_schema.json`, the hub's golden, by its path in the
repository and never from a copy, so a change to a channel model fails the
phones' tests in the same commit that fails the hub's. What else each pins:
enrollment from a scanned or pasted link with the fingerprint checked first,
the binding stored in the Keystore or the Keychain, the overlay switch per
hub, every refusal read as its `{code, params}`, the local listeners and
the in-app SMB client opening one `connect` stream per connection through a
fake socket, and a UDP forward as on the desktop: two local programs through
one stream, the 16 held datagrams, an open refused at **Connect** and later,
and one number held for a TCP and a UDP entry.

## The hub block

Mirrored the same way under `hub/tests/`, summarized by area:

| Area | What its tests pin |
| --- | --- |
| `modules/<name>/` | Renderers and collectors stay pure and are tested as functions: config in, files or lists out. The service-list collector (module entries live only while the module serves, manual entries keep their probes, no credential in any entry), the catalog cache and its stamps, the manifest loader's two gates and its order (every manifest names platform, hub or user and says where its software comes from, or is refused; the tiers come back in the order both surfaces draw, by title inside each), that only a hub-tier module names a license and the directions to its source, the RustDesk manifest's own pins (an exact asset URL and this hub's own sha256 per platform, never a `*-sciter` build, and the AGPL block's exact-tag source), the cc-switch manifest at the client's pin (its version, assets and sha256 values those of `packaging/shared/constants.py`) kept out of the modules and served on the `package` stream, a `cn` hub fetching a `{release}` file from the release address its build stamped and answering `hub_release_file_gone` when that release no longer carries it, the cache's checksum refusal, the agent package cache's four answers (a seeded platform served with nothing reached for, one the manifest publishes fetched once and kept, a release serving something else refused and cached nowhere, a platform with no url refused by name) and the hand-pinned build winning over both, the device-share registry (a share is the machine's last word, withdrawn when it stops and aged out when it goes quiet), the vault, each module's applier where it fixes the machine (gitea owning its work root). The enrolment ticket: written when made with its hash alone, mode 0600, its role, subject and expiry beside it; read back at start; deleted when spent or expired. The two DNS layers: dnsmasq's upstreams are the network layer's resolvers (the uplink's DHCP lease, a static uplink's own list, the uplinks by priority, `223.5.5.5` and `119.29.29.29` when none has any); the proxy's lists override them where set, an empty direct list follows the network layer, and each direct resolver gets its host route. The relay supervisor against a fake `ssh`: the start line, the backoff, the key file written root-only from the vault and `vault_locked` without it, the known-hosts file, and each state (`not_configured`, `connecting`, `connected`, `auth_failed`, `host_key_changed`, `unreachable`, `forward_refused`, `port_closed`, `vault_locked`) from the child's exit and output and from the self-check, where only the hub's own certificate fingerprint at the public address is `connected`. |
| `platforms/` | The hub's platform layer under the agent's fakes, `FakeServiceControlManager` for `sc`, `FakeLaunchd` for `launchctl`, and a fake `Popen` for the supervisor: a child started, stopped, started again after its backoff, its log file rotated; the service's own `service run` entry; `tun2socks` started with xray and stopped with it, the routes added and withdrawn in order. The exposure rendered into the recorded Windows rules and the pf anchor lives under `tests/modules/firewall/`, by the mirror rule. |
| `web/` | Routers through a test client: the agent wire (both version gates and the generation gate, per-account key grant and revocation, a locked vault degrading instead of failing a beat), that a click is one order and a beat orders nothing by itself (a user-tier module takes no order at all), the rdp declaration (recorded against the device the token resolved to, at the address the hub holds rather than one the beat named, withdrawn when the machine stops or is forgotten), the Origin belt on state-changing panel routes, session auth, every `{code, params}` refusal shape, the drawer's service asks (a closed verb set: a fresh mount must say whom it is for, a share cannot be asked for at all, a quiet agent takes nothing, and the beat's service rows land where the drawer reads), the converge step (its steps in order under the router lock, every device and client pushed before an engine stops, a failed step stopping none of the others, and each overlay switched on or off leaving what a fresh render of the stored configuration gives), and the models the frontend mirrors. The hub's side of `connect`: the checks in the `service` stream's order, the `panel` permission, the target for each source (an agent's `connect {port}`, a declared record's own address, the gateway and the panel on loopback), `agent_offline`, `connect_failed`, `connect_limit` at `CHANNEL_CONNECT_STREAMS_MAX`, and bytes relayed under each side's credit. A UDP `connect`: a UDP echo on loopback reached as a declared `generic_udp` record, two sources each getting their own replies; a frame dropped, not queued, when the far side has no credit, with the credit still granted back; a source forgotten after `CHANNEL_UDP_IDLE_TIMEOUT_S` with the clock injected; the 65th source replacing the idlest; an agent's UDP stream relayed frame for frame. The entry's `protocol` and the `_udp` id, a report without `host_bindings` read as TCP, the declared service form's `protocol`, and a `generic_udp` record never probed and its health empty. The agent port's caps ([connection.md](connection.md)): limits never keyed by the peer address, the first-byte and TLS handshake timeouts, sockets before `hello` with the oldest bare socket closed first and a real handshake completing on a port full of silent ones, all channel sockets, a message past `CHANNEL_MESSAGE_BYTES_MAX` and a body past `CHANNEL_REQUEST_BYTES_MAX` refused unread on real servers, a forwarded-address header from loopback ignored on the agent port and the panel, every path but the three channel ones 404, and failed admissions counted hub-wide from wrong credentials only, never from a timeout or a malformed frame; the largest `state`, `report` and command `close` of a large hub measured against the message cap. The relay's address as the last member of `urls` while it is enabled. The machine's AI tools: `ai_tool/enable` minting the device's key and `ai_tool/disable` and a device's removal revoking it, `gateway_not_serving` while the gateway serves no model, `ai_tool/set` dropping what the client's `clean_tool_configs` drops; the `ai_tools` section composed with the accounts of the device's VS Code, code-server and CloudCLI instances, the endpoint `device_gateway()` gives, the unchosen Claude slots filled, a password sent to a Windows machine alone, and `{is_enabled: false, cc_switch_version}` while the setting is off or the gateway serves no model; CloudCLI's state carrying no gateway address or key. The Terminal and Remote desktop modules: both entries in every device's state with their `want`, `account` empty for a Windows machine, the two files written by their `set` routes with their refusals, the four presses refused `module_not_optional`, the seat password generated when the switch first goes on, and a report of `desktop.is_shared` from a device with no `remote_desktop.json` writing the switch on. |
| `cli/` | Setup's step table for each `hub_os`, setup's screens by their document form, root gates, apply's component list — the apply-path symmetry that has bitten twice is pinned here — and `nhub apply` running the converge steps in the panel's order. |
| `packaging/` | Where the hub's build and its runtime must agree, staged into `tmp_path`: the agent-package manifest's shape per platform (hash, weight, and a url only a release stamps), the cache seeded with the one agent package of the hub's own system, architecture and family and no other, the refusal for a build whose name says no family or machine, and the file names the seeding writes resolved back by the runtime cache that reads them. The edition: `EDITION` stamped in every `_version.py`, a `cn` build exiting on a tree that holds a path of `PACKAGING_CN_LEFT_OUT_PATHS` and an `intl` build exiting on one that lacks it, the mainland source tree holding none of those paths and both install scripts stamped `cn`. `publish_cn.py` against a fake Gitee API: a file over 100 MB and a set over 1 GB each fail with the name and the size before any request that changes Gitee, the earlier attachments deleted before the first upload, a run again for the same tag reusing its release. |

## Editions

Every block runs twice in CI: on the full tree, and on the mainland tree
that `build_sources.py --edition cn` writes, where the hub, the agent and the
client run `pytest -q` and the frontend runs `npm run build`. A test that
needs a left-out feature lives in that feature's own mirrored directory and
is deleted with it. A test outside that directory that needs one carries
`@pytest.mark.feature("<name>")`, and the block's `conftest.py` skips it when
the edition table reports the feature absent
([architecture.md](architecture.md), "A left-out feature is reached through
one table"). The edition table's own test, `hub/tests/test_edition.py`, reads
every Python file of the hub and fails on an import of a left-out package
from outside that feature's files and the table.

## The integration block

Flat, one file per concern, because these mirror machine states rather than
source files. `run_on_box.sh` orders them: install, footprint, reinstall,
reset, set up again, a module install through the panel, the whole-page
sweep (one file per panel API), the pinned agent channel end to end, and
the device lifecycle, which, while the client is managed, also walks what
only two live machines can prove: the control channel answering each
identity over ssh, a declared port forwarded back through the client's
loopback, the operator's own commands typed as the operator would.

`packaging/ci/check.py` runs on every built package in the release
workflow. Its `hub_macos` check, on both macOS architectures, and its
`hub_windows` check install the package, find the service registered and
stopped, run `nhub setup --json` with the answers of a `server` hub that
installs its local agent, and expect the panel to answer
`http://127.0.0.1:8080/api/hub/display` with 200. They then stop the hub,
remove it, and run `install.sh` or `install.ps1` with `NEUTRINO_ASSET_DIR`
naming the built files, up to `nhub --version`. Its `agent_windows` and
`client_windows` checks first install the released 0.4.0 `.msi` pinned in
`packaging/shared/constants.py` and the built one over it, so every build
runs an upgrade's whole sequence. That one install may end in 3010, a
restart owed because 0.4.0's removal does not wait for its services; the
check accepts it, removes the package, takes the files of ours waiting for
the restart off Windows' list, and then installs the built `.msi` on a clean
machine, where no restart and no file waiting for one is accepted. An
upgrade from 0.4.0 is not otherwise supported. The hub has no Windows
package before 0.5.0, so `hub_windows` installs on a clean machine.

The VM lab under `packaging/lab/` adds machines for what no single box can
show:

| Lab machine | What it proves |
| --- | --- |
| a small VM on libvirt's NAT network standing in for the VPS | the relay: the forward, the self-check, each failure state, and the hub's certificate at the public address |
| an Android emulator that reaches the hub only through the relay | every page of the app with the hub's LAN out of reach |
| the Windows VM | a drive letter mounted through the files adapter, on the hub's LAN and through the relay |
| a box installed from the `cn` packages | no proxy and no NetBird anywhere, updates read from Gitee, Node.js fetched from npmmirror |

What belongs here is only what the in-process blocks cannot see: a real
`dpkg` refusing, a real systemd unit flapping, a lease on a served wire,
the protocol drill: an agent whose `PROTOCOL` is rewritten is rejected with
`protocol_too_old` and keeps its binding, and an agent whose hub names a newer
`software` reinstalls itself back to health.

## What a change owes

A new module, service type, route or CLI verb arrives with its mirrored test
file in the same commit. A new operator-visible behavior adds its cell to
the cli or control matrix. Changing a channel model fails the golden schema
test until `PROTOCOL` moves or the change is shown additive
([protocol.md](protocol.md), "Versioning"). A new `{code}` anywhere adds its
word to the page's table, which the completeness assertion enforces. The pipeline gains a case only when
the behavior needs a real machine to exist.
