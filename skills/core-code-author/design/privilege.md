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

## Installing software happens outside the sandbox

The narrowing above has a cost that only shows up on an install, and it is not
the one it looks like. Under `NoNewPrivileges` systemd installs the seccomp
filters the other directives need, and the effective capability set loses
`CAP_SETUID`. Measured on Debian 12: `NoNewPrivileges` **plus any one** of the
others is enough, and without `NoNewPrivileges` systemd applies no filter at
all — which is why taking it out appears to fix this and is the one thing that
must not be done.

apt is what finds it. It drops to the `_apt` account to fetch, cannot, and
every download dies:

```text
E: seteuid 42 failed - seteuid (1: Operation not permitted)
E: Method http has died unexpectedly!
```

Measured as netbird, podman and zfs all failing to install from the panel
while the same installs from a shell succeeded. A vendor's installer piped to
`sh` hits the same wall one level further down, where no flag of ours reaches
its package manager at all.

So an install is handed to systemd rather than run here: `system/sandbox.py`
wraps the command in a transient unit, which has its own properties and none
of this one's. The panel keeps every directive, apt keeps its own sandbox, and
what changed is where the install runs.

**Anything that installs software goes through it.** The package controller
does for every family — dnf and pacman do not drop privileges the way apt
does, but one rule beats three — and so does any vendor script that runs a
package manager of its own. A working copy started from a shell is not inside
a unit and gets the command unchanged.

## Stepping down uses runuser, never sudo

The panel is already root, so reaching a service account is a step down.
`sudo` refuses to run at all under `NoNewPrivileges`:

```text
sudo: The "no new privileges" flag is set, which prevents sudo from running as root.
```

Use `runuser -u <account> -- <command>`, as `modules/gitea/ops.py` does. A
`sudo` appearing anywhere in the hub's own code is a bug; `sudo` in
`modules/devices/` is different — that runs on a managed device, not here.

## On macOS and Windows

The hub runs as the root LaunchDaemon `com.neutrino.hub` on macOS and as the
SYSTEM service `neutrino_hub` on Windows, as the agent does. Everything above
about the unit is Linux's:

- No unit narrows the process and no sandbox exists, so `system/sandbox.py`
  runs its command directly.
- Nothing steps down. `runuser` is Linux's, and the hub runs nothing as
  another account there.
- xray runs as a child of the supervising service
  ([architecture.md](architecture.md)), with no `xray` account and no
  capabilities.
- The elevation check is `is_elevated()` of the hub's platform layer: euid 0
  on Linux and macOS, `IsUserAnAdmin` on Windows. No code calls
  `os.geteuid` itself.
- The launchd jobs of the hub and the agent carry `LANG=en_US.UTF-8`.
  launchd starts a job with no locale, under which Python decodes a
  command's output as ASCII and the first curly quote in it is an error.
- A secret file is protected by the ACL or the mode of its directory
  ([files.md](files.md), "One Neutrino tree on macOS and Windows").

`sudo` stays out of the hub's code there too.

## The application entry elevates once

The `Neutrino Hub` entry ([install_and_dev.md](install_and_dev.md), "The
application entry opens the panel") runs one elevated step, which starts the
hub's service when it is stopped and hands back the address to open, the
setup token included while the box is not set up, and does nothing else;
UAC, macOS's administrator prompt and `pkexec` are what ask. The browser opens as the
person who clicked, never as root, and everything the page then does goes
through the service's own authentication.

## The panel never stores this machine's sudo password

It does not need one: it is root already. The sudo passwords the panel does
hold belong to **managed devices**, are entered per device, and are used only
over SSH to those devices. Never add a prompt for the local one — it would be
a credential with nothing to spend it on and somewhere to leak from.

## A password on a managed machine's command line

The agent's file share sets an account's password on the machine it
manages. On Windows the password reaches PowerShell on standard input and
never a command line. On macOS `sysadminctl` and `dscl -passwd` take a
password only as an argument, so while `dscl -passwd` runs the share
account's password is in the process list, where any local account can read
it. The account can do nothing but reach the shares: it has no shell and no
home, and the fence limits who reaches the server.

## VS Code runs as the account it serves

The agent's VS Code module starts each server as the account it names,
never as root, so a browser that holds the token gets that account's files
and nothing more. Its token file belongs to that account, mode 0600 on Linux
and macOS, and on Windows is readable by the account, SYSTEM and the
administrators alone.

On Windows the account's password is needed to start it: the hub unseals the
login it keeps in its vault and sends it inside the device's desired state,
as it sends Gitea's secrets. The agent keeps its copy of that state in its
data directory, which only SYSTEM and the administrators can open, and
passes the password to PowerShell on standard input to register the task.
Windows keeps the password with the task from then on.

CloudCLI runs the same way, as the account it serves and never as root
([agent.md](agent.md), "CloudCLI").

The machine's AI tools go further: cc-switch and every read, write and
removal in the account's home run as the account, because an account can
point a file of its home at a file only root reads
([agent.md](agent.md), "The machine's AI tools"). The one file the agent
hands cc-switch, `payload` under the account's `neutrino/agent/ai_tools/`,
is written and removed as the account too. On Windows the login an
account was switched with stays in the agent's state, which SYSTEM and the
administrators alone open, until the account is switched back. `nagent
answer`, which that account's task runs, is the one `nagent` verb an
account runs, and it starts only the program it is given, with the
account's own rights.

## The relay's ssh runs as root and opens no session

The relay's `ssh` is a root process: the unit `neutrino_hub_relay.service` on
Linux, and a child of the root or SYSTEM service on macOS and Windows. It
reads a key file that only root reads, under the state root
([files.md](files.md)), and it dials one server the person named.

| Rule | Reason |
| --- | --- |
| The start line is rendered from `config/overlay/relay.json`, and a `host` or `account` that is empty, holds whitespace or starts with `-`, or an `account` that holds `@`, is refused before it is stored. | Either value reaches a root command line, where a leading `-` is read as an option. |
| The line carries `-N`, `-T`, `BatchMode=yes` and `IdentitiesOnly=yes`. | The process opens no session, allocates no terminal, asks no question, and offers the one key it was given. |
| The key file holds the key without its passphrase, mode 0600, and is deleted when the relay stops. | `BatchMode` cannot type a passphrase, and the vault keeps the sealed copy. |

On the server, the key is limited by the `authorized_keys` options the
person sets, `restrict,port-forwarding,permitlisten=` the public port, so the
key opens that one listener and nothing else
([network.md](modules/network.md), "The VPS is the person's").

## Where privilege is allowed to live

Root-requiring calls stay in `neutrino_hub/system/` and in each module's `ops` or `apply`
layer, behind named operations. Renderers never touch the system
([design/architecture.md](architecture.md)). Keeping that seam is what
makes a privileged helper possible later; spreading `systemctl` calls through
routers is what would make it impossible.
