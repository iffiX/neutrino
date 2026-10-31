# Repository tree

How the repository is arranged, and why each directory is the kind of thing it
is. The rest of this standard governs what goes *inside* a package; this page
governs the tree itself.

## Three packages and two apps, one repository

The repository ships three Python distributions and two mobile apps, and the
split is the first thing to know about the tree: `hub/` is the appliance, on
Linux in any mode and on macOS and Windows in `server` mode,
`agent/` is what runs as root on the Linux, Windows and macOS machines the
appliance manages, `client/desktop/` is what runs in a person's own session on
Linux, Windows or macOS, and `client/android/` and `client/ios/` are what
runs on that person's phone. They share no code. `transport/` is the one Go
module all five carry: the hub, the agent and the desktop client as the
binary `neutrino_transport`, the phones as a library built from it. The agent
is pure standard library, because it installs on a machine somebody else
administers and a dependency is a thing that can be missing there; the Go
programs it carries are binaries beside it.

The two apps are licensed AGPL-3.0, each by the `LICENSE` in its own
directory, and the rest of the repository is MIT. Both apps are AGPL because
the RustDesk core is compiled into them.

```
hub/                 The `neutrino_hub` distribution: the appliance.
agent/               The `neutrino_agent` distribution: the device agent.
client/
  desktop/           The `neutrino_client` distribution: the tray and window.
  android/           The Android app, a Gradle project in Kotlin.
  ios/               The iOS app, in Swift, its Xcode project generated
                     by XcodeGen.
transport/           The Go module of the channel: knock/, handshake/,
                     session/, relay/, control/ the local channel, gate/
                     the guest path of a Web share,
                     cmd/neutrino_transport/ the binary, mobile/ the
                     library the phones embed, tests/ what crosses
                     packages. Style: ../coding_style/go.md.
share_page/          The page a Web share link opens: plain HTML and
                     JavaScript, no build step, hosted as static files.
packaging/           Building every package, and driving a built one on a
                     live box or a rented one.
docs/                guide/, the VitePress documentation site. Generated site
                     output is ignored.
tmp-docs/            The working copy's own notes, memory.md among them, and
                     drafts; gitignored.
skills/              core-code-author/, this standard: design/ the design
                     pages, design/hub_components/ the hub's AI gateway,
                     network and proxy, design/agent/ the agent's AI tools
                     setting, module_template.md the flow every device
                     module shares, module_install.md the install methods,
                     artifacts, sources and versions of a module's
                     software, and modules/ one page per device module;
                     doc-author/, how every .md is written.
images/              Source artwork: icons/ the one icon source the packaging
                     builds copy from, original/ the raw artwork, web/ and
                     screenshots/ the README's images, guide/ the site's.
licenses/            The upstream licences of the software the packages carry.
.github/workflows/   Continuous integration, the release build, and the
                     documentation site.
```

## Inside `hub/`

```
hub/
  neutrino_hub/      One top-level import name, so nothing it installs into
                     site-packages can collide with anything else.
    modules/<name>/    One feature module each. See the shape below.
    system/            How this box's own OS is driven: systemd, a pty shell,
                       the package manager, listening sockets, and
                       windows_net.py, the network Windows reports through
                       iphlpapi.
    web/               The FastAPI panel over the modules: routers/, auth,
                       models, the shared PanelRuntime, the websockets.
    cli/               Every entry point behind `nhub`, one file per
                       subcommand.
    platforms/         What differs between Linux, macOS and Windows:
                       base.py, linux.py, darwin.py, windows.py behind one
                       contract, detect.py, and win32.py and
                       windows_service.py copied from the agent.
    utils/             Generic helpers with no domain: config file IO,
                       subprocess.
    exceptions.py      The package's one exception table; no kind is
                       declared anywhere else.
    edition.py         The edition table: the one way code outside the
                       proxy reaches it.
    data/              What ships inside the wheel: services/ the unit
                       templates, examples/ the committed *.example.json,
                       manifests/ the device software catalog, one file
                       per module, cloudcli.json, code_server.json and
                       codeg.json among them, source_sets.json the one
                       list of sources per software ecosystem, frontend/ the
                       built panel, resources/ the icons the build copies in
                       from images/icons/.
  frontend/          React and TypeScript source. `npm run build` writes into
                     neutrino_hub/data/frontend/, which is not committed.
  packaging/         The .deb, .rpm and Arch builders, and the interpreter
                     tree each package carries.
  tests/             Mirrors neutrino_hub/ exactly.
```

`config/` is absent from this list on purpose: it is created at install time
and gitignored, because the real files hold node passwords, the panel's
password hash and device keys. What each file may contain is documented by the
`*.example.json` beside it in `data/examples/`, which is committed. Details:
[../misc/config.md](../misc/config.md).

## Inside `agent/`

```
agent/
  neutrino_agent/    The agent: the channel to the hub, desired-state sync,
                     the modules it hosts, the streams the panel drives. No
                     window; it listens on 127.0.0.1, and for the machine's
                     containers on the Podman bridges on Linux and on WSL's
                     vEthernet adapter on Windows.
    core/            The session to the hub through the transport,
                     enrollment, the desired state store and engine,
                     metrics, self-update.
    transport/       The agent's side of the local channel to its
                     transport child.
    control/         The root-only local socket `nagent` talks to, and the
                     named pipe that stands for it on Windows.
    streams/         Shell and file streams multiplexed over the channel;
                     windows_shell.py runs PowerShell on a pseudo console.
    modules/         What a machine can host: samba/, gitea/, podman/,
                     vscode/, cloudcli/, code_server/, codeg/, siyuan/,
                     hermes_webui/, ayakaleaf/, terminal/ and remote_desktop/, with remote_desktop/rdp/ reading
                     who is at the screen and writing RustDesk's files;
                     shared/ what every runner shares: the package and
                     unpack machinery, the account service layer, the
                     forwarder, the instances runner, icacls on Windows.
    ai_tools/        The machine's AI tools: cc-switch run as each account the
                     hub names, the client's steps, the records per tool.
    platforms/       The OS layer: linux.py, windows.py and darwin.py behind
                     one contract, with win32.py the one Win32 binding,
                     windows_service.py the service control manager's side,
                     windows_net.py the network iphlpapi reports,
                     windows_accounts.py the local accounts through netapi32
                     and the impersonation of one, windows_batch_logon.py
                     the batch logon right the agent grants an account
                     while a task runs as it, windows_processes.py the
                     process table with command lines and trees,
                     linux_relay.py the Podman bridges and the relays'
                     rules in ufw and firewalld, windows_relay.py WSL's
                     vEthernet adapter and the relays' rules in Windows
                     Firewall, and powershell_host.py the one resident
                     PowerShell host.
    exceptions.py    The package's one exception table; the channel kinds
                     are the copy the client keeps too.
    data/            Ships inside the package: systemd/ its unit, windows/
                     powershell_host.ps1 the PowerShell host's functions.
  sshserver/         The SSH server the agent carries, a Go module of its
                     own: server/, session/, forward/,
                     cmd/neutrino_ssh_server/ the binary. It is Go, so the
                     agent's package stays standard library.
  packaging/         Its .deb, .rpm and Arch builders and the payload every
                     package stages, the .msi and .pkg included.
  tests/
```

## Inside `client/desktop/`

```
client/desktop/
  neutrino_client/   The client: one resident per person with a tray and a
                     window; never root.
    core/            The sessions to the hubs through the transport,
                     enrollment, the state document.
    transport/       The client's side of the local channel to its
                     transport child.
    control/         The local socket the window and `nclient` talk to, the
                     page it serves, its routes.
    gui/             The window and the tray, one file per toolkit:
                     WebKitGTK, WebView2, WKWebView; tray_linux, tray_windows,
                     tray_macos.
    services/        One file per service kind: the apps' entries, file,
                     ai, rdp, ssh and its configuration; the cc-switch
                     driver and the worker that runs them.
    platforms/       The OS layer: linux.py, windows.py, darwin.py and the
                     Win32 helpers.
    bundled.py       Where the carried tools (cc-switch, the RustDesk
                     viewer) are found.
    edition.py       The edition the client was built as, `EDITION`,
                     which chooses where its Source links open.
    netbird/         NetBird's driver and constants.
    data/            Ships inside the package: desktop/ its .desktop entry,
                     polkit/ the policy for the mount helper.
  frontend/          The window's page: plain HTML, CSS and JavaScript, no
                     framework and no node toolchain.
  packaging/         The .deb, .rpm and Arch builders, the payload every
                     package stages, the .msi and .pkg included, and the
                     icon containers.
  tests/
```

## Inside `client/android/` and `client/ios/`

Each app is one person's session on a phone: it joins a hub by the client
link and shows the services the hub publishes, and the Android app runs one
overlay network at a time. Neither shares code with the desktop client. Both speak the channel of
[docs/guide/protocol/channel.md](../../../docs/guide/protocol/channel.md), and
their tests read `hub/tests/web/channel_schema.json`, the golden the hub's
tests pin, so one commit changes the channel for all three clients.

```
client/android/      Gradle project, Kotlin and Jetpack Compose, minSdk 26
                     (Android 8), applicationId `io.github.iffix.neutrino`.
                     Style: ../coding_style/kotlin.md. NetBird's
                     Kotlin is in the main source set, in every edition.
client/ios/          Swift and SwiftUI, iOS 16, bundle id
                     `io.github.iffix.neutrino`. project.yml, the XcodeGen
                     spec, is the committed project; the .xcodeproj is
                     generated from it and ignored. Two targets: Neutrino/
                     the app, NeutrinoTests/ its unit tests. Style:
                     ../coding_style/swift.md.
  Neutrino.xcconfig  The app target's settings beside project.yml: it
                     includes cores/rustdesk/RustDesk.xcconfig when that
                     file is there.
  rustdesk_core/     The RustDesk core's C header and its module map, the
                     one way Swift reaches the core.
  cores/             The RustDesk core build_core_rustdesk_ios.py puts
                     there, and the xcconfig that links it into a device
                     build. Ignored.
```

The iOS project is written as `project.yml` and generated by `xcodegen
generate` before every build. A `.pbxproj` is machine-written, with generated
ids that conflict in merges and cannot be read in a review. The app is
built on GitHub's macOS runner, where XcodeGen runs as one step before
`xcodebuild`.

## Inside `packaging/`

`packaging/` holds one script per thing a release builds, and the machinery
that checks a built package. Every script runs the same way on a machine that
can build its target and in the release workflow, which only sets up the host
and calls it.

```
packaging/
  shared/            Library modules, no main(): constants.py the names of
                     package files and machines, the Nuitka, WiX, pkg, makepkg
                     and RustDesk builders, the container runner, the cores
                     cache.
  build/             One build_<target>.py per target: build_hub.py,
                     build_agent.py and build_client_desktop.py in containers;
                     build_hub_windows.py, build_hub_macos.py,
                     build_agent_windows.py, build_agent_macos.py,
                     build_client_windows.py, build_client_macos.py,
                     build_client_android.py and build_client_ios.py
                     natively; build_core_<core>.py for each core the phones
                     carry; build_sources.py, build_checksums.py and
                     build_docs.py.
  ci/                What only the workflows run: check.py installs a
                     built package where it runs and checks it works;
                     publish_cn.py publishes a release and the mainland
                     tree to CNB, the second release site; count_tests.py writes the test counts the
                     docs build serves for the README's badge.
  install/           install.sh for macOS and Linux and install.ps1 for
                     Windows: the one-command installers a release
                     publishes.
  lab/               The VM lab: run_lab.py builds a hub VM and a client VM
                     with setup_vms.sh and runs the integration suite in the
                     hub; vm_exec.py drives a VM through its guest agent;
                     windows/ the Windows client walk.
  integration/       The suite that runs on the box: pytest files,
                     run_on_box.sh and run_mode_matrix.sh.
  screenshots/       The guide's screenshot tool and its shot list.
  integration_aws/   The same idea as the lab for the platforms it cannot
                     carry.
```

`integration/` is the part that cannot run anywhere else: checks that drive a
**built package on a live box**, deliberately outside `hub/tests` because
pytest must stay runnable on a workstation with no root and no interfaces to
break. The lab keeps its images, disks and key under the directory
`NEUTRINO_VM_LAB` names. `integration_aws/` rents a Windows Server and a Mac
by the hour, builds their installers there, and joins each to a rented Linux
hub as a device. Its `state/` is one run's key and addresses, gitignored, and
its `down.sh` is what stops the bill.

## The rules that shaped it

**A module is a domain, and the tree does not rank them.**
`modules/router` and `modules/samba` sit side by side even though the gateway
is dead without one and merely quieter without the other. Core-versus-optional
is a *product* classification and it changes, so it lives in one constant
(`system/constants.py: SYSTEM_CORE_UNITS`) and in the sidebar's grouping, where
reclassifying is a one-line edit instead of a file move.

**Every module has the same shape.** `config.py` parses and validates its slice
of `config/` (pure), `renderer.py` turns it into the artifact the software
consumes (pure), `ops.py` makes it true on the box (effects: writing,
validating with the real tool, reloading), `constants.py` holds the
module-prefixed constants, `provisioner.py` installs the software itself where
the distribution's archive cannot. Knowing one module is knowing all of them.
A module has only the files it uses: `modules/hub_update` has no renderer,
because the hub's own update renders nothing from `config/`.

**`modules/router` is bigger than that shape, and organised by engine.** It
drives several pieces of software rather than one, so instead of a single
`renderer.py` and `ops.py` it has a pair per engine: `nft_renderer.py`,
`dnsmasq_renderer.py`, `hostapd_renderer.py`, `supplicant_renderer.py` and
`dhcp_renderer.py` are pure and turn `config/` into a file; `links.py`,
`supplicant.py`, `dhcp_client.py`, `wifi.py` and `resolver.py` touch the
machine. `routes.py` is the applier that calls them in order, `interfaces.py`
and `connections.py` are the two files under `config/router/`, `modes.py` turns
a mode into interface roles, `uplink_plan.py` decides which uplink carries
traffic, `link_status.py` reads what the kernel says, `credentials.py` reads
what another manager knew, and `stack.py` stops whatever was driving the
machine before. Which engines and why: [network.md](hub_components/network.md).

**Every module declares what machines it runs on.** The appliance is meant to
land on whatever box is around — an x86 mini PC, a Raspberry Pi — so each
`constants.py` carries `<PREFIX>_SUPPORTED_ARCHITECTURES`: `("*",)` when the
installer underneath (apt, a vendor script) picks the machine's build itself,
or the explicit list when the module downloads a binary and must pick
correctly. `system/machine.py` normalises what the kernel reports and refuses
an unsupported install *before* the wrong binary lands.

**Modules may read each other, nothing reads the panel.** The dnsmasq renderer
in `modules/router` points at `modules/xray`'s DNS inbound — modules cooperate.
But only `web/` and `cli/` import across the whole tree; no module imports
`web/`, so every module works headless under `nhub apply`.

**`system/` wraps invocations, modules own meaning.** `system/systemd_ctl.py`
knows how to ask systemd about a unit; *which* units exist and which refuse to
stop is configuration it is handed. If a file in `system/` starts knowing about
shares or uplinks, it is in the wrong directory.

**`web/` is the panel over the modules, not a module.** One backend router per
module page, one shared `PanelRuntime` that owns the render-and-apply pipeline,
and a frontend whose API types mirror the backend models field for field.

**No templates directory.** Artifacts — the nft ruleset, dnsmasq and hostapd
configs, smb.conf, the xray JSON — are rendered by plain Python that carries
its explanatory comments into the output and is unit-tested by asserting on
that output. A template language would move that logic somewhere tests cannot
reach and add a dependency for string concatenation. The only true templates
are the systemd unit files, which are static and live in `data/services/`.

## Three trees, one spine

A module's name is the same in all three places:

```
hub/neutrino_hub/modules/samba/        the code
config/samba/                          its configuration (the source of truth)
hub/tests/modules/samba/               its tests
```

`hub/tests/` mirrors the source tree exactly (`tests/system/`, `tests/web/`,
`tests/cli/`, `tests/modules/<name>/`), with the shared builders and stubs in
`tests/conftest.py`. `config/` stays flat — it is user-facing, and the person
editing it should not need to know how the code is arranged.

## Where a new thing goes

| The new thing is… | It goes in… |
| --- | --- |
| A feature the appliance offers (a VPN, a DNS blocker, a media server) | `hub/neutrino_hub/modules/<name>/`, in the standard shape |
| A new way to drive the OS (a mount helper, a journal reader) | `hub/neutrino_hub/system/` |
| Something the hub does differently on Linux, macOS and Windows | `hub/neutrino_hub/platforms/` |
| A page or API for an existing module | `hub/neutrino_hub/web/routers/`, `hub/frontend/src/pages/` |
| A helper with no domain at all | `hub/neutrino_hub/utils/` — and only if two packages already need it |
| An entry point | `hub/neutrino_hub/cli/<name>.py` — libraries never grow a `main()` |
| Something the wheel must carry (a unit, an example, an icon) | `hub/neutrino_hub/data/<kind>/` |
| A check that needs root, a real interface or a package installed | `packaging/integration/` |
| Anything the managed machines run | `agent/neutrino_agent/`, or `agent/sshserver/` for the SSH server's Go |
| Anything of the channel's wire, the knock, the handshake, the sessions and the relay | `transport/`, in Go |
| Anything a person's computer runs | `client/desktop/neutrino_client/` |
| Anything a Web share's visitor's browser runs | `share_page/`, in plain JavaScript ([web_share.md](web_share.md)) |
| A screen, a service kind or a platform piece of the Android app | `client/android/`, in Kotlin |
| A page or a platform piece of the iOS app | `client/ios/`, in Swift |
| A script that builds a core the phones compile in | `packaging/build/build_core_<core>.py` |
| A script that builds or checks a release target | `packaging/build/build_<target>.py`, `packaging/ci/check.py` |
| A feature the mainland edition leaves out | its own files, every path listed in `PACKAGING_CN_LEFT_OUT_PATHS`, reached from outside only through the package's `edition.py` ([architecture.md](architecture.md)) |
