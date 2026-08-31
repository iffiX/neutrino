# Repository tree

How the repository is arranged, and why each top-level directory is the kind
of thing it is. The rest of this standard governs what goes *inside* a
package; this page governs the tree itself.

## The tree

```
modules/          What the gateway does. One package per feature module.
  router/           Interface roles, uplink planning, nftables, dnsmasq, Wi-Fi
  xray/             Proxy nodes, the xray config, stats and probes
  devices/          LAN devices: scan, SSH, Wake-on-LAN, remote desktop, agents
  samba/            The file share
  gitea/            The git server
  netbird/          Remote access: the way back into the box from anywhere
system/           How the box's own OS is driven: systemd control, a pty
                  shell, vnstat history. Wrappers around system software —
                  think ansible roles — with no feature logic of their own.
services/         The systemd unit files the installer copies into place.
web/              The control panel: backend/ (FastAPI) and frontend/
                  (React + TypeScript). Sits ON TOP of the modules.
utils/            Generic helpers with no domain: subprocess, config file IO.
scripts/          The only executables: install/, render_all/, web/.
config/           The single source of truth, one directory per module.
                  Secrets are gitignored with committed *.example.json.
packages/         Vendor installer bundles (.deb and friends) dropped in for
                  offline installs — data fetched from vendors, never code.
services/... docs/ tests/  (see below)
```

## The rules that shaped it

**A module is a domain, and the tree does not rank them.** `modules/router`
and `modules/samba` sit side by side even though the gateway is dead without
one and merely quieter without the other. Core-versus-optional is a *product*
classification and it changes — netbird moved from optional to core in one
conversation — so it lives in one constant
(`system/constants.py: SYSTEM_CORE_UNITS`) and in the sidebar's grouping,
where reclassifying is a one-line edit instead of a file move.

**Every module has the same shape.** `config.py` parses and validates its
slice of `config/` (pure), `renderer.py` turns it into the artifact the
software consumes (pure), `ops.py` makes it true on the box (effects:
writing, validating with the real tool, reloading), `constants.py` holds the
module-prefixed constants, `provisioner.py` installs the software itself
where the Ubuntu archive cannot. Knowing one module is knowing all of them.

**Every module declares what machines it runs on.** The gateway is meant to
land on whatever box is around — an x86 mini PC, a Raspberry Pi — so each
`constants.py` carries `<PREFIX>_SUPPORTED_ARCHITECTURES`: `("*",)` when the
installer underneath (apt, a vendor script) picks the machine's build
itself, or the explicit list when the module downloads a binary and must
pick correctly. `system/machine.py` normalizes what the kernel reports and
refuses an unsupported install *before* the wrong binary lands.

**Modules may read each other, nothing reads the panel.** `modules/router`'s
dnsmasq renderer points at `modules/xray`'s DNS inbound — modules cooperate.
But only `web/` and `neutrino_hub/cli/` import across the whole tree; no module
imports `web/`, so every module works headless under `nhub apply`.

**`neutrino_hub/system/` wraps invocations, modules own meaning.** `system/systemd_ctl.py`
knows how to ask systemd about a unit; *which* units exist and which refuse
to stop is configuration it is handed. If a file in `neutrino_hub/system/` starts knowing
about shares or uplinks, it is in the wrong directory.

**`web/` is the panel over the modules, not a module.** One backend router
per module page, one shared `PanelRuntime` that owns the render-and-apply
pipeline, and a frontend whose API types mirror the backend models
field-for-field.

**No templates directory.** Artifacts — the nft ruleset, dnsmasq and hostapd
configs, smb.conf, the xray JSON — are rendered by plain Python that carries
its explanatory comments into the output and is unit-tested by asserting on
that output. A template language would move that logic somewhere tests cannot
reach and add a dependency for string concatenation. The only true templates
are the systemd unit files, which are static and live in `services/`.

## Three trees, one spine

A module's name is the same in all three places:

```
modules/samba/            the code
config/samba/             its configuration (the source of truth)
tests/modules/samba/      its tests
```

`tests/` mirrors the source tree exactly (`tests/system/`, `tests/web/`,
`tests/modules/<name>/`), with the shared builders and stubs in
`tests/conftest.py`. `config/` stays flat — it is user-facing, and the person
editing it should not need to know how the code is arranged.

## Directories that are data, not code

- `services/` — unit files. Named for what it holds: the services the
  installer registers with systemd.
- `packages/` — vendor installers (ToDesk, AnyDesk, …) placed here so a
  gateway can provision LAN devices offline; gitignored except for the
  manifest naming what belongs in each.
- `config/` — the box's state. Backing this up *is* backing up the gateway.

## Where a new thing goes

| The new thing is… | It goes in… |
| --- | --- |
| A feature the gateway offers (a VPN, a DNS blocker, a media server) | `neutrino_hub/modules/<name>/`, in the standard shape |
| A new way to drive the OS (a mount helper, a journal reader) | `neutrino_hub/system/` |
| A page or API for an existing module | `neutrino_hub/web/routers/`, `hub/frontend/src/pages/` |
| A helper with no domain at all | `neutrino_hub/utils/` — and only if two packages already need it |
| An entry point | `neutrino_hub/cli/<name>.py` — libraries never grow a `main()` |
