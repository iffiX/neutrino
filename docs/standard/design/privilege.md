# Privilege

The panel runs as root, and what is narrowed is what root may reach for rather
than who it runs as. This page says why, and what may not be changed without
re-doing the reasoning.

## Why root, and not a service account

The panel writes nftables rules, drives systemd, edits a dozen files under
`/etc`, installs packages, and sweeps the LAN with raw sockets. Measured across
the tree: 43 `systemctl` calls, 46 writes under `/etc`, 14 package-manager
invocations, 4 user and ownership changes, 3 `nft`, 3 `ip route`/`ip rule`.

Every one of those is what somebody bought the appliance to do. There is no
subset that leaves a useful panel behind.

## Why not run unprivileged and sudo each command

This looks like least privilege and is not. Three reasons, in order of how much
they cost:

**A sudo password would have to be stored.** The panel is a boot-time service —
routing and the proxy have to come back on their own after a reboot — so the
password cannot be typed. It lives on disk, readable by the panel. Anything
that compromises the panel then reads it and becomes root. Compared with
running as root, the isolation gained is zero and there is now a credential to
steal.

**A NOPASSWD sudoers entry is root by another name.** `sudo systemctl` alone is
enough: link a unit file, start it, and you are root. The 46 writes under
`/etc` would need something like `sudo tee`, which is arbitrary file write. An
entry broad enough to cover the real call sites reduces to
`ALL=(ALL) NOPASSWD: ALL`.

**It would not stop the attacks it appears to stop.** The path traversal fixed
in `neutrino_hub/web/routers/settings.py` unpacked an archive as root. Under
sudo-per-command, the unpack still runs with whatever privilege it needs, so
the traversal still lands.

## What is narrowed

In `services/neutrino_hub_web.service`. Each was tested under the exact property
set before being added.

| Setting | Stops |
| --- | --- |
| `NoNewPrivileges=yes` | Any step up from root's own privileges, including setuid binaries |
| `RestrictSUIDSGID=yes` | Creating setuid or setgid files as a foothold |
| `RestrictAddressFamilies=` | Every socket family except the five actually used |
| `RestrictRealtime=yes` | Realtime scheduling, a denial-of-service lever |
| `LockPersonality=yes` | Switching execution domain to dodge seccomp |
| `ProtectClock=yes` | Moving the system clock |
| `SystemCallArchitectures=native` | Reaching syscalls through a foreign ABI |

The five address families, and what needs each: `AF_NETLINK` for `nft` and
`ip`, `AF_PACKET` for the `arp-scan` sweep, `AF_UNIX` to reach systemd and
podman, `AF_INET`/`AF_INET6` for the panel itself and SSH to devices.

## What is deliberately absent

Not oversights. Each breaks something the panel does, and the unit file carries
the same list so nobody adds one back without reading this.

| Setting | What it would break |
| --- | --- |
| `ProtectSystem` | Installing binaries into `/usr/local/bin`; writing a dozen files under `/etc` |
| `ProtectHome` | `config/` still lives in the checkout under a home directory |
| `ProtectKernelTunables` | Setting `net.ipv4.ip_forward` |
| `ProtectKernelModules` | Loading the ZFS module on demand |
| `RestrictNamespaces`, `ProtectControlGroups`, `PrivateDevices` | podman and ZFS |

`ProtectSystem=strict` with an explicit `ReadWritePaths` is the one worth
having — it would have contained that path traversal — and it needs package
installation moved out of this process first. That is the next step whenever
privilege comes up again, not another sudo scheme.

## Stepping down uses runuser, never sudo

The panel is already root, so reaching a service account is a step down.
`sudo` refuses to run at all under `NoNewPrivileges`:

```text
sudo: The "no new privileges" flag is set, which prevents sudo from running as root.
```

Use `runuser -u <account> -- <command>`, as `modules/gitea/ops.py` does. A
`sudo` appearing anywhere in the hub's own code is a bug; `sudo` in
`modules/devices/` is different — that runs on a managed device, not here.

## The panel never stores this machine's sudo password

It does not need one: it is root already. The sudo passwords the panel does
hold belong to **managed devices**, are entered per device, and are used only
over SSH to those devices. Never add a prompt for the local one — it would be
a credential with nothing to spend it on and somewhere to leak from.

## Where privilege is allowed to live

Root-requiring calls stay in `neutrino_hub/system/` and in each module's `ops` or `apply`
layer, behind named operations. Renderers never touch the system
([design/architecture.md](design/architecture.md)). Keeping that seam is what
makes a privileged helper possible later; spreading `systemctl` calls through
routers is what would make it impossible.
