# Integration on AWS

The platforms the pipeline VM on xenode cannot carry, driven on rented
machines: a Windows Server building the installer and joining a Linux hub as
a device, and a Mac doing the same for the pkg. Nothing here runs in CI; every
script bills by the hour while it runs, and `down.sh` is the last word.

## What is here

The root holds what every platform shares; each platform's own scripts sit in
its directory, the ones that run on the rented machine beside the ones that
drive it from here.

| File | Runs where | What it does |
| --- | --- | --- |
| `up.sh` | here | A Debian 12 hub and a Windows Server 2025 device in one security group, keyed to pairs generated into `state/`. |
| `status.sh` | here | Everything tagged for this harness that is still billing. |
| `down.sh` | here | Terminates it all, releases any host, deletes the group and the keys, then prints `status.sh`. |
| `linux/push_hub.sh` | here | Installs the hub deb, sets it up as a `server`, mints an enrollment link. |
| `linux/hub_install.sh` | the hub | What `push_hub.sh` runs there. |
| `windows/push.sh` | here | Toolchain, the tracked tree, `build_msi.py` for both architectures, the installers fetched into `dist/`. |
| `windows/user_data.ps1` | Windows, first boot | OpenSSH keyed to the harness. |
| `windows/toolchain.ps1` | Windows | Python, the .NET SDK, WiX at the release workflow's pin. |
| `windows/build.ps1` | Windows | The build. |
| `windows/test.sh` | here | Mints a link this minute, installs the msi, joins the hub, checks both ends: the agent's own status and the hub's device list. |
| `windows/test.ps1` | Windows | What `test.sh` runs there: remove a previous install, install, leave any earlier binding, join, heartbeat. |
| `macos/` | | The same pair of scripts for the pkg, on a dedicated host. |

`state/` holds the keys, the ids, the addresses, the panel password and the
link. It is gitignored and belongs to one run. There are two keys because
EC2 refuses an ED25519 pair on a Windows AMI, where the pair is what decrypts
the Administrator password; the hub takes the ED25519 one and Windows the
RSA one, and SSH is offered both.

## A run

```bash
cd packaging/integration_aws
./up.sh                 # ~6 minutes; Windows pulls OpenSSH from Windows Update
linux/push_hub.sh       # the deb from dist/, or a path
windows/push.sh         # ~10 minutes the first time, the toolchain is most of it
windows/test.sh
./down.sh
```

`AWS_PROFILE` defaults to `claude-1day` and the region to `us-east-1`. Both
are overridable in the environment, as are `HUB_TYPE`, `WIN_TYPE` and
`ZONE`.

## What it costs

On-demand in N. Virginia, September 2026. The Windows figure includes the
licence.

| Machine | Type | Per hour | An evening |
| --- | --- | --- | --- |
| Hub | `t3.medium` | $0.0416 | under a dollar |
| Windows | `t3.xlarge` | about $0.25 | about two dollars |
| Mac | `mac-m4.metal` on a dedicated host | about $1.23 | **$29.52, because a host is billed for 24 hours however briefly it is used** |

The Mac is the whole budget. It is allocated last, once the Windows walk has
passed, and released by `down.sh` like everything else; releasing early
saves nothing, so a Mac session should do everything it came for.

## Reaching the boxes by hand

`ssh -i state/id_aws admin@$(cat state/hub_ip)` for the hub and
`ssh -i state/id_aws_rsa Administrator@$(cat state/win_ip)` for Windows,
which lands in PowerShell. The security group admits only the address
`up.sh` was run from; RDP and the panel port are open to it as well, for the
parts a script cannot look at.
