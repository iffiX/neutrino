# Repository tree

How the repository is arranged, and why each directory is the kind of thing it
is. The rest of this standard governs what goes *inside* a package; this page
governs the tree itself.

## Three packages, one repository

The repository ships three distributions, and the split is the first thing to
know about the tree: `hub/` is the appliance, `agent/` is what runs as root on
the Linux machines the appliance manages, `client/` is what runs in a person's
own session on Linux, Windows or macOS. They share no code. The agent is pure
standard library, because it installs on a machine somebody else administers
and a dependency is a thing that can be missing there.

```
hub/                 The `neutrino_hub` distribution: the appliance.
agent/               The `neutrino_agent` distribution: the device agent.
client/              The `neutrino_client` distribution: the tray and window.
packaging/           Building every package, and driving a built one on a
                     live box or a rented one.
docs/                memory.md, the working copy's own notes (gitignored), and
                     guide/, the VitePress documentation site. Generated site
                     output is ignored.
skills/              core-code-author/, this standard; doc-author/, how every
                     .md is written.
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
                       the package manager, vnstat, listening sockets.
    web/               The FastAPI panel over the modules: routers/, auth,
                       models, the shared PanelRuntime, the websockets.
    cli/               Every entry point behind `nhub`, one file per
                       subcommand.
    utils/             Generic helpers with no domain: config file IO,
                       subprocess.
    exceptions.py      The package's one exception table; no kind is
                       declared anywhere else.
    data/              What ships inside the wheel: services/ the unit
                       templates, examples/ the committed *.example.json,
                       manifests/ the device software catalog, frontend/ the
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
                     window; it listens on nothing.
    core/            The one WebSocket to the hub, enrollment, the desired
                     state store and engine, metrics, self-update.
    control/         The root-only local socket `nagent` talks to.
    streams/         Shell and file streams multiplexed over the channel.
    modules/         What a machine can host: samba/, gitea/, podman/, zfs/,
                     the RustDesk host, and the installers they share.
    rdp/             Sharing this machine's desktop at the seat password the
                     hub set.
    platforms/       The OS layer; linux.py is the only implementation.
    exceptions.py    The package's one exception table; the channel kinds
                     are the copy the client keeps too.
    data/            Ships inside the package: systemd/ its unit.
  packaging/         Its .deb and .rpm builders and the payload both stage.
  tests/
```

## Inside `client/`

```
client/
  neutrino_client/   The client: one resident per person with a tray and a
                     window; never root.
    core/            The one WebSocket to the hub, enrollment, session.
    control/         The local socket the window and `nclient` talk to, the
                     page it serves, its routes.
    gui/             The window and the tray, one file per toolkit:
                     WebKitGTK, WebView2, WKWebView; tray_linux, tray_windows,
                     tray_macos.
    services/        One file per service kind: web, port, file, ai, rdp;
                     the cc-switch driver and the worker that runs them.
    platforms/       The OS layer: linux.py, windows.py, darwin.py and the
                     Win32 helpers.
    bundled.py       Where the carried tools (cc-switch, the RustDesk
                     viewer) are found.
    data/            Ships inside the package: desktop/ its .desktop entry,
                     polkit/ the policy for the mount helper.
  frontend/          The window's page: plain HTML, CSS and JavaScript, no
                     framework and no node toolchain.
  packaging/         The .deb, .rpm, .msi and .pkg builders, the payload
                     every one of them stages, and the icon containers.
  tests/
```

## Inside `packaging/`

`build_release.py` builds every artifact of a release, including the source
archive. `integration/` is the part that cannot run anywhere else: scripts that drive a **built package on a
live box**, deliberately outside `hub/tests` because pytest must stay runnable
on a workstation with no root and no interfaces to break. `integration_aws/`
is the same idea for the platforms the pipeline VM cannot carry: it rents a
Windows Server and a Mac by the hour, builds their installers there, and
joins each to a rented Linux hub as a device. Its `state/` is one run's key
and addresses, gitignored, and its `down.sh` is what stops the bill.

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
A module that needs none of a file simply does not have it: `modules/zfs` is
`constants.py`, `ops.py` and `provisioner.py`, because a pool is not rendered
from `config/`.

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
machine before. Which engines and why: [network.md](modules/network.md).

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
| A page or API for an existing module | `hub/neutrino_hub/web/routers/`, `hub/frontend/src/pages/` |
| A helper with no domain at all | `hub/neutrino_hub/utils/` — and only if two packages already need it |
| An entry point | `hub/neutrino_hub/cli/<name>.py` — libraries never grow a `main()` |
| Something the wheel must carry (a unit, an example, an icon) | `hub/neutrino_hub/data/<kind>/` |
| A check that needs root, a real interface or a package installed | `packaging/integration/` |
| Anything the managed machines run | `agent/neutrino_agent/` |
