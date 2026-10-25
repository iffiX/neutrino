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
| ios | `client/ios/NeutrinoTests/`, `client/ios/NeutrinoUITests/` | `swift-format lint --strict --recursive` and `xcodebuild test` on the iOS Simulator, in the `ios` job of `ci.yml` on GitHub's `macos-15` runner, every commit; the `ios_core` job builds the app for a device with the RustDesk core, checks the app defines `_nd_attach_frames`, and keeps the unsigned `.ipa` as the run's artifact `client_ios_device_test` for a test on an iPhone | XCTest; a fake socket, a fake Keychain, a fake SMB client and a fake RustDesk core; never a device |
| integration | `packaging/integration/` | `run_on_box.sh` on the pipeline's VM pair; minutes | A whole machine: real installs, real systemd, real DHCP on a served wire, a real client VM |

## The mirror rule

Where a source file is testable on its own, its tests live in the file that
mirrors it: `agent/neutrino_agent/<package>/<module>.py` is tested by
`agent/tests/<package>/test_<module>.py`, and the hub tree likewise: a router
in `hub/neutrino_hub/web/routers/{hub,agent}/<page>.py` is tested by
`hub/tests/web/routers/{hub,agent}/test_<page>.py`; the agent's
`modules/shared/` is mirrored by `tests/modules/shared/` and
`modules/remote_desktop/rdp/` by `tests/modules/remote_desktop/rdp/`. Every
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
| `core/` | The one socket: the hello and the report, every field each carries, every frame shape the hub may send, including shapes this build cannot read, which become a typed `last_error` and never a dead process; the `welcome`'s `time` taken as the hub clock's offset, and a `welcome` without one leaving it at zero. Desired state: a copy lands on every `state` frame, the applied hash moves only once every enabled module applied, a failed apply keeps asking. The engine: one order at a time in its own thread, and no retry. A failed install reading `install_failed` with its code, also over software the check finds, and a failed configure, start, stop or uninstall reading `failed`; both read the same after the agent starts again, until the next attempt replaces them or a state stops naming the module; a retried install running even where the check passes, and an uninstall of an `install_failed` module cleaning up what the check does not find. Commands: only the allowlisted actions run, `run_command` is absent. Enrollment: the link's payload, every url tried, the fingerprint checked before a byte leaves. The store: atomic writes, root-only, no secret inside. The engine building `PodmanMachineModuleRunner` under `hub_packages` on Windows and macOS and `PodmanModuleRunner` on Linux; an `installing` row taking the runner's `{code, params}`, an install's `installing` row kept while a read of every module taken before it started ends, and a pending install applied again every 30 seconds under the same hash with no tried hash kept. |
| `control/` | The root-only socket: 0600 under 0700, connections persist, one thread each; an unexpected handler exception answers `agent_internal` with the class name and never drops the connection. |
| `streams/` | Shell and file streams behind the credit window: bytes out no faster than the hub's credit, bytes in no faster than this side's. A shell kept by id: attached again with its kept output first, shared by every stream attached at the smallest window, ended with its last stream unless it is persistent or shared, on a real pseudo-terminal and on a faked pseudo console. The `connect` stream: the dial goes to `127.0.0.1:<port>` and nowhere else, or to the one address a container port is published on; a port the machine does not publish now is refused `port_not_published {port}`, for each kind of published port as it starts and stops being published; a refused, timed-out or unreachable dial closes `connect_failed {reason}` within `AGENT_CONNECT_DIAL_TIMEOUT_S`; bytes both ways under credit; end of file on either side closes the stream after what was read is sent. The AI gateway forward: a listener on `127.0.0.1:8317` alone while the `ai_tools` section is on and none while it is off or on the hub's own machine, nothing accepted while the agent has no channel and the waiting connections served when it is back, one `connect {id}` to the hub per accepted connection, and bytes both ways under credit. A UDP `connect`: an echo on a real loopback UDP socket, two sources each getting their own replies; `port_not_published` for a number published on TCP alone; a source forgotten after `AGENT_UDP_IDLE_TIMEOUT_S` with the clock injected; the 65th source replacing the idlest; Podman's `host_bindings` carrying `protocol`, UDP ones included. The `exec` stream: without `is_tty`, stdout on `fd` 1 and stderr on `fd` 2, stdin closed on `eof`, the exit code in the close, a missing program refused `shell_program_unusable`, and the process killed when the stream closes first; with `is_tty`, the pseudo-terminal path with the `argv`; the Terminal module's account through the step-down, as a shell. The Terminal module: a shell for a named account through the platform's step-down in its home with its environment, the module's shell program, `account_unknown {account}` and `shell_program_unusable {path}` with no fallback, a container's shell untouched, a session already open keeping what it runs, the session's `account` the one the shell runs as, and Windows taking the shell program alone. A container's shell in a Podman machine on Windows and macOS: `exec -it <container>` through the machine's read command, on the pseudo console on Windows, never kept, `container_unknown {name}` before anything starts for a container the machine does not list or when no machine is set, and the machine's own code when it cannot be reached. A container's shell: its `exec -it` with `NEUTRINO_SHELL_ID`, the sweep run through the same podman command once the shell exits, its exit code kept, and once the stream closes, and the sweep's script run with `sh` against real processes, ending the marked ones and their sessions and leaving the rest. |
| `modules/` | One runner per module (samba, gitea, podman, zfs, vscode): config, renderer, applier and runner each pinned as functions. `shared/`: the package and unpack machinery, the forwarder and the `account_service` layer pinned as functions, and the service definitions of VS Code, code-server and CloudCLI (the unit, the plist and the task texts) pinned unchanged. Codeg's forwarder: a `?tkn=` that verifies answering the page that stores the token and setting the login cookie, a Bearer header, the `codeg-token.` subprotocol or a good login cookie passed on, and 401 for everything else. The file share on Windows and macOS, its applier driven through faked system tools, the PowerShell host among them, that record every request and answer canned output. The package state machine: verify is dpkg's own status word, removal purges, an unconfirmed install or uninstall waits instead of retrying. The RustDesk host and a person's own AnyDesk or TeamViewer, driven through their binaries with fakes. CloudCLI against a fake `npm` and a fake register endpoint, its service environment naming no gateway, each install step's failure code, and its forwarder: 401 for a request with neither token nor login state, a token traded for the login state once, the register and login endpoints never passed on, a WebSocket passed through. code-server the same way: one instance per account against a fake release archive, each install step's failure code, and its forwarder on `127.0.0.1` only. Gitea on macOS and Windows with faked system tools: the account made and read back, the LaunchDaemon or the service, `app.ini` with each system's paths and the `git` found, `gitea_git_missing` without one, and an uninstall that keeps the data. Every forwarder (code-server, CloudCLI, Codeg) and every VS Code instance binds loopback alone, and Gitea's `app.ini` on every system names `127.0.0.1` alone. Every forwarder's token check against the hub's time with the clocks injected: a fresh token accepted on a machine whose clock is hours behind or ahead of the hub's, and still accepted after the machine's clock is set while the socket stays open. `installers.py` against a faked `msiexec` and `installer`: the msiexec command line, the wait for the Windows Installer mutex, one retry on 1618, 0 and 3010 a success, and the self-update's rendered scripts unchanged. Containers on Windows and macOS against faked `podman`, `wsl.exe` and `dism.exe`: the feature step and its 3010, `reboot_required` while the reboot mark holds the current boot time and not after a restart, the WSL msi skipped at the pinned version or newer, the init with the kept image, the disk resized after the init, the `.wslconfig` merge keeping the person's other keys, `wsl --shutdown` on a change, each `machine_*` refusal, the old machine stopped on a new account, the reads through the ssh URL with the port read again from the machine's settings file, the root script run with `sh` in `tmp_path` (the units written 0644 and the environment files 0600, the stale marked files, an earlier build's Quadlet files and boot unit removed, the units enabled and disabled, the `changed:` lines), the machine's unit with `--cgroups=enabled` beside the Linux unit with `--cgroups=split`, the folder translation and `volume_not_shared`, a UDP publish refused on Windows `udp_not_forwarded`, the keeper's script, task and plist texts pinned unchanged, and an uninstall that keeps the machine. The service probe against servers on loopback: http, https with a self-signed certificate, a TCP server that sends first and one that stays silent, a result kept per container start, and UDP never probed; `services` rendered into the publishes, a checked UDP adding its own, `service_invalid {name, port}` and `service_protocol_none`. One unit per container on every Podman version, with the lifecycle settings Containers names, enabled when its container starts with the box and disabled when it does not or is removed, its environment in a file of mode 0600 read with `--env-file` and no value of it in the unit or on its command line, and an earlier build's marked Quadlet files stopped and removed with each active container started again; on Windows `machine_disk_invalid` for a disk of 0, and a failed sizing after the init removing the new machine. `host.containers.internal:<gateway>` in every declared and hub container on Linux, with the gateway of its network, as `--add-host` on the unit's `podman run`, and a hub container's image rendered as the reference found in the store by its digest. The agent's source chooser against fake registries and hosts: the ranking by speed with the first byte breaking a near tie, an image pulled from the fastest source and from the next after a failed pull, npm run with the fastest registry and with the next after a failure or an integrity that differs, and the fastest host set for an npm setting. A `hub` module switched to another version beside the old files, and the old files put back with `version_switch_failed` after a failed `verify`. The relays on each Podman bridge's gateway, bound to the bridge, opened and closed as bridges come and go, and the gateway's port relayed on the hub's own machine. Hermes WebUI's hooks against a faked `podman` and a webui on loopback: a `?tkn=` that verifies traded for the webui's cookie under the name `cookie_name` gives and a redirect, the cookie passed on with `Host` unchanged, 401 for `/api/auth/login` and for a request with neither; the four gateway keys written once `config.yaml` exists and again when the base URL changes; `installing` until the keys and `/health` hold; and a version change making `agent` and `app` again. |
| `ai_tools/` | The machine's AI tools against a fake cc-switch that records every argument list and the account it ran as: the client's steps in the client's order for each account the state names; nothing run when an account's records already carry the wanted settings; the records under the state root, never in an account's home; the switch back when the section turns off, when an account leaves the list, before `nagent service uninstall`, on `nagent leave` and on `binding_unknown`; cc-switch fetched from the hub when no copy is there or its version is not the section's, unpacked into `ai_tools/bin/` and run from there, and `download_failed` for every account with nothing run when the fetch fails; the account lock (two runs for one account never overlap, two accounts never wait on each other, a lock a killed process left blocks no one) and no switch once the binding is gone; every file a switch may write kept before the first switch and put back byte for byte, a tool directory made for the switch and taken away again, Codex's and Gemini's files read back naming the hub, and a switch back that cannot run cc-switch failing with the records kept; each system's way of running as the account (`runuser` on Linux, the account's uid and groups on macOS, the one-shot task under the account's login on Windows, `credential_missing` without one); the report's result and code per account. |
| `modules/remote_desktop/rdp/` | A share is declared only once the port answers; `rdp_nobody_seated` before anything is configured; the seat password set from the desired state and kept in a root-only file, never in the store or a report. The Remote desktop module on each system against faked service managers and process tables: the switch on stops and kills every RustDesk host that is not the agent's copy and leaves every `--connect` viewer, keeps aside what is registered under RustDesk's names in `remote_desktop/kept/`, writes the settings with the host stopped (the direct port, rendezvous and relay at `127.0.0.1`, the seat password in `RustDesk.toml`), registers the copy under RustDesk's names and records it in `registered.json`; the switch off leaves no process and no registration of the agent's and puts back what was kept; `nagent service uninstall` turns it off first; the share declared from the socket table with no connection to the host; a share recorded by the old command reported until the first state names the module; each step's failure `rdp_takeover_failed` or `rdp_restore_failed` with its `step`. On Linux and macOS, a fresh machine with none of the four settings files, root's `RustDesk.toml` read every half second for at most 30 seconds after a start until RustDesk writes an id and a key pair, the seat password written again with the host stopped when that file then holds an empty or another password, the same check at each report with no command while the seat password is there, RustDesk's sealed password opened with the machine id against libsodium-made vectors so a state push with the seat password sealed restarts nothing, and the seat's settings folders made as the home's owner and given back to it from root at each switch on and at the agent's start. |
| `platforms/` | The contract: capability advertisement, honest `unsupported_platform` refusals, the uid floor for human accounts, metrics from `/proc` and `/sys` with fakes and, for Windows and macOS, from canned `NtQuerySystemInformation`, PDH, `ps`, `ioreg` and `powermetrics` readings, every system filling the same document, `runuser` never `sudo`. The Win32 decoders fed the buffers `GetAdaptersAddresses` and `NetUserEnum` returned on a Windows machine, and compared with what PowerShell's cmdlets returned there. The PowerShell host against a fake process speaking its line protocol: the start on the first request, one request at a time, a refusal and an error each by its kind, the timeout, the memory ceiling and the idle stop. The host's library holding no `exit` and a function for every operation the agent sends. Windows' `run_as_account` under its lock per account: two runs for one account in turn, two accounts at once. |
| `packaging/` | What the deb and the rpm carry, staged into `tmp_path`: the interpreter tree under `/opt/neutrino/agent`, the unit, the vendored RustDesk host at its pinned hash, and the refusal for a machine no package is published for. The macOS and Windows packages carry RustDesk in the agent's own folder and register nothing of RustDesk's at install; the deb carries no RustDesk unit. |
| `cli/` | The operator matrix: every command × root and ordinary × bound and unbound × service alive and dead, each cell asserting the words printed and the exit status. The wording table complete. `nagent rdp` exists no more, on the command line or the control socket. |

## The client block

The same shape under `client/desktop/tests/`:

| Directory | What its tests pin |
| --- | --- |
| `core/` | The one socket to the hub: the four frames down, the ask and its answer up, reconnection, and within a round a refused address dialled again every `CLIENT_REDIAL_INTERVAL_S` until the round's connect time ends and a silent address dialled once. Enrollment: a link with `kind: "client"` accepted, a device link refused with `link_not_for_client`. The version lock: a client newer than its hub is asked to upgrade. The EasyTier daemon: every refusal by code, its state read back at start, the core run only while a network or a console is configured and started again with a doubling wait; the overlay driver against the real daemon behind a fake socket, the secret and the console's address in the request's body only. The hub row's way in (LAN, NetBird, EasyTier, SSH relay, Direct, SakuraFrp, OpenFrp) from `reached_through`, and a candidate's path read from `ssh_relay_url`, `sakurafrp_url` and `openfrp_url`, all three ranking 4. |
| `control/` | The local channel and its identity: a Unix socket on Linux and macOS, a named pipe on Windows, the peer read from the kernel and never from the body. The page served with both word catalogs inlined. Every route of the window and of `nclient service`. The EasyTier daemon's socket: one JSON line each way, open to every account, its pipe open to interactive users who cannot make an instance of it. |
| `gui/` | The window's seam, all fakes: the bridge forwards exactly method, path and body and nothing else the page says; a dead channel answers `control_channel_closed`; one shell per toolkit (WebKitGTK pinned to the 4.1 API, WebView2, WKWebView) refusing with a typed code naming what to install; the three trays. |
| `services/` | One file per kind. Every forwarded kind: a listener on `127.0.0.1` at the entry's local port, one `connect` stream per accepted connection and no dial to a device address; a TCP forward that accepts nothing while its hub has no channel, stays bound, and serves the waiting connections when the channel is back; the port pick (the entry's own port when nothing listens on it on any address of the machine, else from 20000 up, recorded per entry). `web`: open at the slug address, `?tkn=` for a token entry. `port`: the forward and its refusals by code; a UDP entry's forward, where two local programs through one stream each get their own replies, at most 16 datagrams are held while the stream waits for its first credit, an open refused at **Connect** and later, the table holding one number for a TCP and a UDP entry, and the row's `/udp` text. An entry with empty health leaves its actions enabled. `file`: the stage machine of a mount at `127.0.0.1` and the local port, the credentials file root-only through the helper, the refusals by code. `ai`: the cc-switch driver naming the local port, adoption of what the person had before the first switch, all-or-nothing activation, restoration on `off`; every file a switch may write kept before the first switch and put back byte for byte, a tool directory made for the switch and taken away again, Codex's and Gemini's files read back naming the hub, and a switch back that cannot run cc-switch failing with the records kept; with the agent's program directory present, the page's chip and **Configure** disabled with `ui.reason.ai_managed`, one deactivation of a chip that was on, and `nclient service ai apply` refused `ai_tools_managed`. `rdp`: the viewer started against the local port with the password in one argv and nowhere else, viewers closed on quit. The panel forward. The files adapter on Windows: the address plan (`198.19.255.1/24` for the adapter, one address per machine from `198.19.255.2` up, kept per hub and machine), and the SOCKS endpoint taking `<address>:445` of a machine it knows and refusing every other target. The store and the worker. <!-- scan: allow --> |
| `platforms/` | Linux, Windows and macOS behind one contract: the mount location's shape per platform, the Windows console and pipe helpers, `darwin` refusing what the Mac does not carry. |
| `packaging/` | What every package carries, staged into `tmp_path` with the compiled and fetched parts stood in for: the payload, the pinned cc-switch and RustDesk viewer, the icons, the licences of exactly what each package carries in each edition (for the hub, `licenses/hub_notices.txt` among them: the libraries bundled into the panel page, the Python interpreter and the hub's Python packages), the deb and rpm, the msi and the pkg, and the refusal for a machine none is published for. |
| `cli/` | Every command × root refused and ordinary × bound and unbound × resident alive and dead; `gui`, `quit`, the mount helper, the `service` verbs, `easytier-daemon` put together over a temporary directory; the wording table complete in both languages. The `terminal` verbs: the bare form as `open`, each verb's exit statuses, `exec` returning the remote code and 125 and 126 for its own, stdout and stderr kept apart with stdin and stdout not terminals, a session id prefix with one, none and several matches. |

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
phones' tests in the same commit that fails the hub's. A golden that more
than one package or app reads is always data like this schema, and no test
compares two code files ([layout_style.md](../coding_style/layout_style.md)).
What else each pins:
enrollment from a scanned or pasted link with the fingerprint checked first,
the binding stored in the Keystore or the Keychain, the overlay switch per
hub on Android, every refusal read as its `{code, params}`, the local listeners and
the in-app SMB client opening one `connect` stream per connection through a
fake socket, the redial of a refused address within a round and a forward
that accepts nothing while its hub has no channel, as on the desktop. The
iOS app's tests also pin a round that dials the hub's address on every
published virtual network, and the close of every channel, share connection
and listener when the background time ends, with each forward listening
again on its port on the return to the foreground. Its terminal is pinned to
the 16 colours of the shared palette in both themes and to each theme's
background, text, cursor and selection; a tab that attaches again keeps its
output until the replay's first bytes, and keeps it when the session is
gone. The lines a row's actions wrap into are pinned by their widths, the
part of the safe area a keyboard covers by its frame, and the Terminals
page stays at its end as the software keyboard comes and goes. Its
share page is pinned
against a fake SMB
client: folders before files, each by name; the numbered name an upload and
a new folder take; the code of each failure, the hub's own among them; a
login kept only once the share took it, in the fake Keychain or until the
app quits, and forgotten on `share_login_rejected`; the share's forward
opening one `connect {id}` stream per connection; a cancelled read and a
cancelled write leaving no file; one transfer at a time in the order added,
a waiting row going at its **Cancel**, and the shown bytes taken from the
forward's count in the transfer's direction and kept below the size; a
transfer the background cut, running or waiting, showing
`share_interrupted`, with its retry; the bytes a forward's connection
carries up and down; and an item from Photos named by the
name Photos suggests with the extension of its file, written through the
upload of a file from Files, with an item not handed over shown as
`share_photo_unavailable` while the others upload. Its remote desktop is pinned, as
Android's is, against a fake core: a Connect reading the seat password and
opening the viewer on a forward of its own, which opens one `connect {id}`
stream per connection, accepts nothing while the hub has no channel and
ends with the viewer; one viewer at a time; the viewer's state after each
report of the core; `rdp_core_missing` without a core; the codecs and
qualities offered and kept per entry; the viewport's zoom and pan, and the
picture moved above the keyboard and the key bar and back; the mouse
events of each gesture; the typing pace; marked text sent nowhere; a paste
to a Linux host; and the viewer and its forward closed when the background
time ends.

When `NEUTRINO_SCREENS` names a directory, `ScreenshotTests` writes PNG
files of the changed screens there: the terminal in both themes, the remote
desktop viewer before and after the key bar and a simulated keyboard come
up, the Settings page and a share's login sheet in both themes, the Web,
Files and Desktops lists with rows of different text widths, the Terminals
page with its key row and **New terminal** and no keyboard, with its
**Keyboard** and **Keys** buttons, with the key row hidden, with the
software keyboard opened by **Keyboard** and closed again by a tap on empty
space, and the sidebar layout of a phone with a camera housing, turned to
each side, on Terminals with **New terminal** in the machines card, on Join
with **Scan** in the page header, and on a share with its **+**. It also
records the Terminals page as **Keyboard** and **Keys** turn on and off.
A shot with the keyboard and a recording are taken by the job from the
Simulator's screen, which a test asks for by a file it writes. Without it
the test is skipped.
The `ios` job sets it through `TEST_RUNNER_NEUTRINO_SCREENS` on every run
and keeps the files as the artifact `ios_screens`.

The UI tests in `client/ios/NeutrinoUITests/` drive the app with taps: on
the Join page a tap on the paste field brings up the software keyboard and
hides the bottom bar under it, a tap on a control leaves the keyboard up,
and a tap on empty space closes it and brings the bar back.

The iOS app on a phone is checked by hand: the release's `.ipa`, signed with
a free Apple ID, on an iPhone on iOS 16; the behaviour of iOS 17 and newer is
checked in the Simulator. The share page is checked there against a Samba
share and a Windows share that asks for SMB signing. The remote desktop is
checked on the phone alone, since the Simulator carries no core: the core
starting, the picture's colours and row stride, VP8, VP9 and AV1 at 1080p
and their frame rates, the gestures, Chinese typing, **Paste** and the
clipboard both ways, a rotation, a return from the background, a refused
password, the sound, and the app's size.

The Android app also pins the Hubs row's word for every `reached_through`,
`ssh_relay`, `sakurafrp` and `openfrp` among them, and a candidate's path
read from the three server addresses of the state, as on the desktop.

## The hub block

Mirrored the same way under `hub/tests/`, summarized by area:

| Area | What its tests pin |
| --- | --- |
| `modules/<name>/` | Renderers and collectors stay pure and are tested as functions: config in, files or lists out. The service-list collector (module entries live only while the module serves, manual entries keep their probes, no credential in any entry, and a container port by its service: `auto` with `http` detected a `web` entry, `port` with TCP and UDP two `port` entries, a `web` port in no `port` entry, the `web` entry under the TCP entry's id), the catalog cache and its stamps, the manifest loader's gates and its order (every platform entry names a runner and one of the five methods with the `params` its method fixes, and every artifact a kind and a digest of its kind's form, or the manifest is refused; the methods come back in the order both surfaces draw, by title inside each), that only a `hub` or `container` entry shows a licence and the address of its source, `resolve_platform_entry` (the four key forms in their order, and the catalog, the module list, the cache and the recipe reading the one entry), the RustDesk manifest's own pins (an exact asset URL and this hub's own sha256 per platform, never a `*-sciter` build, and the AGPL block's exact-tag source), the cc-switch manifest at the client's pin (its version, assets and sha256 values those of `packaging/shared/constants.py`) kept out of the modules and served on the `package` stream, `{release}` expanded to each release site the build stamped and to none in a checkout, the cache's digest refusal, its 2 GiB limit, the zstd magic, each file named by its digest, a file of a version no machine names deleted after a new one is placed while every named version's files stay, the `hub: fetching` and `hub: sending` lines, the hub's fetcher against fake sources with the clock injected (the 5 s wait of the probe, the ranking by speed, a measure at the current offset every 30 s and the move to a source 1.5 times as fast, a 20 s stall moving to the next source by a Range request, a source answering a Range request with the whole file used from the start alone, a digest mismatch dropping its source, and `download_failed` naming each source and its reason), each feed kind against recorded answers (the versions newest first, a tag that is no dotted number left out, a version missing an artifact on a platform not listed for it, and each digest from the publisher), the agent package cache's four answers (a seeded platform served with nothing reached for, one the manifest publishes fetched once from the release sites and kept, a site serving something else dropped and its file cached nowhere, a build with no release sites refusing the rest by name) and the hand-pinned build winning over both, the device-share registry (a share is the machine's last word, withdrawn when it stops and aged out when it goes quiet), the vault, each module's applier where it fixes the machine (gitea owning its work root). The install of an agent over SSH: EPEL with CRB enabled before the `.rpm` on the RHEL family, by `/etc/os-release`, a refused step ending the task before the package, and no step for a `.deb` or on Fedora. A device's Gitea entry healthy while the device reports the server running, with nothing dialled. The firewall: a hub port accepted from a sender inside an exposed segment and dropped from every other sender, in a base chain of its own, every other port left to the chain's accept policy, the peer ports and DHCP open with no switch, a changed IPv6 prefix keeping its switch, a row with the earlier `is_exposed` read as both families, Direct's port open to every sender on the enabled interfaces, and firewalld's rich rules written in the zones of the exposed interfaces, runtime and permanent, found by their marker, written again when the half-minute check finds them changed, and taken out by a reset. The traffic history, with the counter readings and the boot time faked: each reading's difference added to the hour, day and month totals of every interface but loopback, the write of `traffic_history.json` every 5 minutes, hours kept 8 days, days 13 months and months 10 years, a restart without a reboot adding the difference from the saved counters, a reboot told by a changed boot time and counted from its first reading, and the same on every system. The LAN scan: the exposed IPv4 segments in every mode, a segment over 256 addresses cut to the /24 that holds the hub's address, no IPv6 segment, and an IPv6 neighbour never stored as a device's IPv4 address. The enrolment ticket: written when made with its hash alone, mode 0600, its role, subject and expiry beside it; read back at start; deleted when spent or expired. The two DNS layers: dnsmasq's upstreams are the network layer's resolvers (the uplink's DHCP lease, a static uplink's own list, the uplinks by priority, `223.5.5.5` and `119.29.29.29` when none has any); the proxy's lists override them where set, an empty direct list follows the network layer, and each direct resolver gets its host route. The relay supervisor against a fake `ssh`: the start line, the backoff, the key file written root-only from the vault and `vault_locked` without it, the known-hosts file, and each state (`not_configured`, `connecting`, `connected`, `auth_failed`, `host_key_changed`, `unreachable`, `forward_refused`, `port_closed`, `vault_locked`) from the child's exit and output and from the self-check, where only the hub's own certificate fingerprint at the public address is `connected`. The frp module against recorded vendor answers: frpc's file written from named fields alone, so a vendor config holding `plugin`, `visitors`, `webServer`, `includes` or another tunnel's proxy gives a file without them, with `localIP`, `localPort` the vendor's loopback port and `loginFailExit` set by the hub; each vendor's tunnel filter (UDP, another local port, OpenFrp's `autoTls`, SakuraFrp's forced authentication flag) and each node's region; OpenFrp's rotated `Authorization` resealed, its login polled every 5 s and ended at 5 minutes on a fake clock; every frp state from frpc's output and the self-check; and `urls` holding SakuraFrp's, OpenFrp's and the relay's addresses in that order. |
| `platforms/` | The hub's platform layer under the agent's fakes, `FakeServiceControlManager` for `sc`, `FakeLaunchd` for `launchctl`, and a fake `Popen` for the supervisor: a child started, stopped, started again after its backoff, its log file rotated; the service's own `service run` entry; `tun2socks` started with xray and stopped with it, the routes added and withdrawn in order. The exposure rendered into the recorded Windows rules and the pf anchor lives under `tests/modules/firewall/`, by the mirror rule. The network read through iphlpapi on Windows is tested under `tests/system/`, its decoders fed tables recorded on a Windows machine. |
| `web/` | Routers through a test client: the agent wire (both version gates and the generation gate, an agent at 3 admitted at `hello` for its own `package` stream alone, with no `state` pushed and every other stream closed `protocol_too_old`, shown updating and then mismatched when no package serves its platform or it comes back at 3, kept update-only under a `+dev` hub, and refused at `join`, a client at 3 refused, per-account key grant and revocation, a locked vault degrading instead of failing a beat), that a click is one order and a beat orders nothing by itself (a module the agent carries takes no order at all), the rdp declaration (recorded against the device the token resolved to, at the address the hub holds rather than one the beat named, withdrawn when the machine stops or is forgotten), the Origin belt on state-changing panel routes, session auth, every `{code, params}` refusal shape, `device/add` creating a row named by its host and starting the install in one request, the drawer's service asks (a closed verb set: a fresh mount must say whom it is for, a share cannot be asked for at all, a quiet agent takes nothing, and the beat's service rows land where the drawer reads), the converge step (its steps in order under the router lock, every device and client pushed before an engine stops, a failed step stopping none of the others, and each overlay switched on or off leaving what a fresh render of the stored configuration gives), and the models the frontend mirrors. The hub's side of `connect`: the checks in the `service` stream's order, the `panel` permission, the target for each source (an agent's `connect {port}`, a declared record's own address, the gateway and the panel on loopback, and an agent's gateway stream joined to the gateway on loopback, refused `permission_denied {kind: ai}` while that machine's AI tools setting is off and no container module that uses the gateway is installed there), the gateway listening on `127.0.0.1` alone, `agent_offline`, `connect_failed`, `connect_limit` at `CHANNEL_CONNECT_STREAMS_MAX`, and bytes relayed under each side's credit. The hub's side of `exec`: the checks in order with `permission_denied {kind: terminal}` for a client without `terminal` or outside its device list, the `fd` byte and `eof` relayed unchanged, the agent's `exit_code` in the client's close, and `terminals` holding exactly the machines the `terminal` kind allows. A UDP `connect`: a UDP echo on loopback reached as a declared `generic_udp` record, two sources each getting their own replies; a frame dropped, not queued, when the far side has no credit, with the credit still granted back; a source forgotten after `CHANNEL_UDP_IDLE_TIMEOUT_S` with the clock injected; the 65th source replacing the idlest; an agent's UDP stream relayed frame for frame. The entry's `protocol` and the `_udp` id, a report without `host_bindings` read as TCP, the declared service form's `protocol`, and a `generic_udp` record never probed and its health empty. The agent port's caps ([connection.md](connection.md)): limits never keyed by the peer address, the first-byte and TLS handshake timeouts, sockets before `hello` with the oldest bare socket closed first and a real handshake completing on a port full of silent ones, all channel sockets, a message past `CHANNEL_MESSAGE_BYTES_MAX` and a body past `CHANNEL_REQUEST_BYTES_MAX` refused unread on real servers, a forwarded-address header from loopback ignored on the agent port and the panel, every path but the three channel ones 404, and failed admissions counted hub-wide from wrong credentials only, never from a timeout or a malformed frame; the largest `state`, `report` and command `close` of a large hub measured against the message cap. The relay's address as the last member of `urls` while it is enabled. An agent port change: every online client and agent pushed its state with the new `urls` before the process restarts on the new port, a port equal to another of the three, or a new port another program listens on, refused `port_already_in_use`, and `SettingsView` counting the clients and agents with a binding row and no live session. The machine's AI tools: `ai_tool/enable` minting the device's key and `ai_tool/disable` and a device's removal revoking it, `gateway_not_serving` while the gateway serves no model, `ai_tool/set` dropping what the client's `clean_tool_configs` drops; the `ai_tools` section composed with the accounts of the device's VS Code, code-server, CloudCLI and Codeg instances, `base_url` naming the agent's AI gateway forward at 8317, and the gateway's own port on the hub's own machine, the unchosen Claude slots filled, a password sent to a Windows machine alone, and `{is_enabled: false, cc_switch_version}` while the setting is off or the gateway serves no model; CloudCLI's state carrying no gateway address or key. The shared instances router: the four instance modules served from the description table, each module's sealed fields its own, VS Code's terms acceptance in its own file. The Terminal and Remote desktop modules: both entries in every device's state with their `want`, `account` empty for a Windows machine, the two files written by their `set` routes with their refusals, the four presses refused `module_not_optional`, the seat password generated when the switch first goes on, and a report of `desktop.is_shared` from a device with no `remote_desktop.json` writing the switch on. The Podman routes: `machine/set` refusing `unsupported_platform` for a Linux machine, `unknown_credential`, `credential_missing` and, on Windows, `machine_disk_invalid` for a disk of 0; `machine` in a Windows and a macOS state with the password in the Windows one alone and never in a Linux state; the Linux `podman` section with its `system` recipe; `container/set` keeping `services`; and `PodmanDeviceView` holding `detected`, each running container's `source` and the reported machine. The version routes: `module/version` listing newest first with the tested version marked and the newer ones untested, `version/set` writing the choice into `modules.json` with empty following the tested one, `version_unknown` for a version the feeds did not list, and `version_locked` for an `agent`, `builtin` or `system` module. A container module that uses the gateway: its key generated, sealed in its module file, written into the gateway's `api-keys` beside the keys of `cliproxyapi.json`, composed into its containers' environment and voided at its uninstall, and `is_forwarded` true for its machine while the AI tools setting is off. The frp routes against fake vendor servers: each refusal code, `User-Agent` on every request, no vendor request from a state view's `GET`, and `reached_through` `sakurafrp`, `openfrp` or `ssh_relay` by the listener a socket arrived on; a connection or panel port set to a frp loopback port refused `port_already_in_use`. |
| `cli/` | Setup's step table for each `hub_os`, setup's screens by their document form, root gates, apply's component list — the apply-path symmetry that has bitten twice is pinned here — and `nhub apply` running the converge steps in the panel's order. |
| `packaging/` | Where the hub's build and its runtime must agree, staged into `tmp_path`: the agent-package manifest's shape per platform (hash, weight, and the release sites only a release stamps), the cache seeded with the one agent package of the hub's own system, architecture and family and no other, the refusal for a build whose name says no family or machine, and the file names the seeding writes resolved back by the runtime cache that reads them. The edition: `EDITION` stamped in every `_version.py`, a `cn` build exiting on a tree that holds a path of `PACKAGING_CN_LEFT_OUT_PATHS` and an `intl` build exiting on one that lacks it, the mainland source tree holding none of those paths, the two `cn` install scripts written with `cn`, every script and the hub's `HUB_RELEASE_SITES` holding the stamped release sites, and each `cn` file's name holding `-cn`. `publish_cn.py` against a fake CNB API: every file of the release uploaded to the tag's release, the mainland tree and `latest.json` committed on `main`, and a run again for the same tag reusing its release and uploading nothing twice. frpc taken into every hub package of both editions at its pin, with its licence. `install.sh` against a stand-in `dnf` and `subscription-manager`: EPEL with CRB enabled on Rocky, AlmaLinux and RHEL before the package and under the one sudo, for each of the three packages, a refused step installing nothing, and no step on Fedora or any other system. |

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

## Coverage

The `python` job of `ci.yml` runs the hub's and the agent's suites, and the
`client` job runs the client's. Each suite runs with `--cov` over its own
package (`neutrino_hub`, `neutrino_agent`, `neutrino_client`) and writes
`coverage.xml` in its block's directory. The `agent_oldest_python` job and the
mainland jobs run their suites without coverage.

`codecov/codecov-action` uploads each file to Codecov under the flag `hub`,
`agent` or `client`. It signs in with the job's GitHub OIDC token, which needs
`id-token: write` on the job. Each upload's `network_filter` names its
package's directory, because the three packages share file names such as
`cli/entry.py`.

A job passes or fails on its tests alone, whatever its coverage. pytest-cov
comes with the hub's dev extra, and the `client` job installs it by name
beside pytest.

## The integration block

Flat, one file per concern, because these mirror machine states rather than
source files. `run_on_box.sh` orders them: install, footprint, reinstall,
reset, set up again, a module install through the panel, the whole-page
sweep (one file per panel API), the pinned agent channel end to end, and
the device lifecycle, which, while the client is managed, also walks what
only two live machines can prove: the control channel answering each
identity over ssh, a declared port forwarded back through the client's
loopback, the operator's own commands typed as the operator would, and an
`nclient terminal exec` round trip whose exit code is checked and whose
stderr arrives apart from its stdout.

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

The `podman_macos` job of `ci.yml` runs Containers' install on macOS: on
`macos-15` with the pinned Podman 6.x for arm64, and on `macos-15-intel`
with the pinned 5.8.x for amd64. It fetches the entry's pkg and image into
a cache keyed by their digests and checks each one. Then
`packaging/ci/podman_macos.py`, as root, drives the agent's
`PodmanDarwinApplier` and `PodmanMachine` as the runner's account. It
installs the pkg through `install_pkg` and runs `podman --version`, `podman
machine init --image` and `podman machine inspect`. It checks the settings
file's ssh port, the key and the API socket under the account's `TMPDIR`,
sets the CPUs and the memory, and grows the disk. A smaller or equal size
is refused, and the run removes the machine and uninstalls Podman with its
receipt. It starts no machine.

The VM lab under `packaging/lab/` adds machines for what no single box can
show:

| Lab machine | What it proves |
| --- | --- |
| a small VM on libvirt's NAT network standing in for the VPS | the relay: the forward, the self-check, each failure state, and the hub's certificate at the public address |
| an Android emulator that reaches the hub only through the relay | every page of the app with the hub's LAN out of reach |
| the Windows VM | a drive letter mounted through the files adapter, on the hub's LAN and through the relay |
| the Windows VM `nmxwin`, from its copy taken before Podman, beside a Linux hub | Containers from start to end: the install, `reboot_required` and **Restart now**, the Run settings, an nginx container with a volume picked by **Browse…** opened from a client and from the phone's Web page, the journal, stop, start, restart and the mirrors, a restart with nobody signed in bringing every container back, a CPU and memory change, a disk grown and a smaller one refused, a UNC volume refused, a changed Windows password giving `credential_invalid`, the account's own `podman ps` showing the same containers, and an uninstall that keeps the machine, with the containers and their volumes back after a reinstall |
| the hub, signed in to a SakuraFrp and an OpenFrp test account | each vendor's sign-in, OpenFrp's browser login, the tunnel list with latency, the apply, the hub's certificate at each node's public address, and a client's row reading **SakuraFrp** or **OpenFrp** |
| a box installed from the `cn` packages | no proxy and no side gateway mode anywhere, NetBird on the hub, the desktop client and the phone, and its update, Node.js and CloudCLI each fetched from the fastest of their sources |

What belongs here is only what the in-process blocks cannot see: a real
`dpkg` refusing, a real systemd unit flapping, a lease on a served wire,
the protocol drill: an agent whose `PROTOCOL` is rewritten below 3 is
rejected with `protocol_too_old` and keeps its binding, and an agent whose hub
names a newer `software` reinstalls itself back to health. A 0.5.2 agent
bound to a 0.6.0 hub fetches its package, updates itself and connects with
4, and a 0.5.2 client reads its too-old state.

## What a change owes

A new module, service type, route or CLI verb arrives with its mirrored test
file in the same commit. A new operator-visible behavior adds its cell to
the cli or control matrix. Changing a channel model fails the golden schema
test until `PROTOCOL` moves or the change is shown additive
([protocol.md](protocol.md), "Versioning"). A new `{code}` anywhere adds its
word to the page's table, which the completeness assertion enforces. The pipeline gains a case only when
the behavior needs a real machine to exist.
