# Operating the gateway

How to verify the box is doing what you think, and what to check when it is not.
The configuration reference is [config.md](config.md).

## Verifying a fresh install

Run these from a machine plugged into the LAN port. Each one checks a different
part of the chain, so the first failure tells you where to look.

```bash
# 1. Did DHCP work? You should get 192.168.100.x with .1 as gateway and DNS.
ip addr show; ip route; resolvectl status | grep -A2 'DNS Servers'

# 2. Does the proxy path work? This should show a proxy node's address,
#    not your local ISP address.
curl -s https://ifconfig.me; echo

# 3. Does the direct path work? This should show your local WAN address —
#    the path remote desktop and anything else that must look local uses.
curl -s --proxy socks5h://192.168.100.1:1080 https://ifconfig.me; echo

# 4. Is GeoIP split routing working? With it on, a Chinese destination
#    should leave directly while a foreign one goes through the proxy.
curl -s --resolve '' https://www.baidu.com -o /dev/null -w '%{http_code}\n'

# 5. Does DNS resolve, and does it leak? The dig should answer; the tcpdump
#    should stay silent while it does.
sudo tcpdump -ni enp2s0 port 53 &     # run on the gateway
dig @192.168.100.1 google.com +short  # run on the LAN machine
```

Step 5 is the important one. If `tcpdump` prints anything while the `dig`
answers, LAN queries are escaping to the WAN in plaintext and the dnsmasq
upstream is wrong — check that the generated `dnsmasq_neutrino.conf` has `no-resolv`
and exactly one `server=127.0.0.1#5353` line.

On the gateway itself:

```bash
systemctl status neutrino_hub_router neutrino_hub_xray neutrino_hub_dnsmasq neutrino_hub_web
sudo nft list table inet neutrino          # the ruleset that is actually loaded
ip rule show | grep 0x1                    # the TPROXY policy rule must exist
ip route show table 100                    # must hold "local default dev lo"
xray api statsquery --server=127.0.0.1:10085 | head   # counters are flowing
```

## When the LAN has no internet

Work outward from the box:

1. **Is the WAN up?** `ip -br addr show enp2s0` should show an address. If it
   does not, the upstream network never leased one — see "moving the box"
   below.
2. **Is forwarding on?** `sysctl net.ipv4.ip_forward` must be 1. The
   `neutrino_router` service sets it; if it is 0, that unit failed.
3. **Is the ruleset loaded?** `nft list table inet neutrino`. If the table is
   missing, the same unit failed — `journalctl -u neutrino_router` says why.
4. **Is xray running?** If xray is down, the forward chain still passes LAN
   traffic straight out the WAN, so the internet works but nothing is proxied.
   That degradation is deliberate. `journalctl -u xray` will show a config or
   node error.
5. **Are any nodes reachable?** In the panel's Nodes tab, every node showing
   dead means the upstream network is blocking them, not that the box is broken.

## When traffic is not being proxied

The usual cause is that TPROXY is not diverting. Check in this order:

```bash
sudo nft list chain inet neutrino prerouting   # is the tproxy rule there?
ip rule show | grep 0x1                        # is the fwmark rule there?
ip route show table 100                        # is the local default there?
sudo ss -tlnp | grep 12345                     # is xray listening?
```

The policy route must exist *before* xray starts, or diverted packets have
nowhere to go. If you applied a ruleset by hand and skipped the `ip rule`, LAN
connections hang rather than fail — which looks like a dead node but is not.

## The anti-loop rule

xray's own outbound connections must not be re-diverted into xray. Two
independent guards prevent that:

- Traffic from the `xray` user returns early from the output chain.
- xray stamps every egress socket with firewall mark 255, which also returns
  early.

If you ever see xray connecting to itself in `ss -tnp`, or the box saturating a
core with no traffic passing, one of those two is missing — most likely because
the ruleset was rendered before the `xray` user existed.

## Moving the box to a different network

The WAN is a NetworkManager DHCP client, so replugging into a new upstream
usually just works. Two cases need a hand:

- **Networks that register a device by MAC** (campus, some hotels): set
  `wan_cloned_mac` in the Network tab to the MAC that is already registered.
- **Captive portals**: the gateway's own traffic goes direct by default, so open
  a browser on the box and click through. Do this *before* turning on "route
  this gateway's own traffic through the proxy", since a portal cannot be
  reached through a proxy that cannot reach the internet yet.

## Getting back in from outside

NetBird advertises `192.168.100.0/24` over its `wt0` interface, so once you are
on the overlay you reach the panel, SSH and the shares at their LAN
addresses. Approve the advertised route once in the NetBird console.

If NetBird itself cannot reach its control plane from where the box lives, turn
on **route this gateway's own traffic through the proxy** in the Proxy tab.
That sends the daemon out through your nodes. It is the reason that switch
exists.

## Wake-on-LAN

The panel can only broadcast the packet; whether a machine wakes is up to the
machine. On the target, once:

```bash
sudo ethtool -s <interface> wol g     # arm the NIC
sudo ethtool <interface> | grep Wake  # confirm: "Wake-on: g"
```

Most distributions reset this on reboot, so persist it with a NetworkManager
setting or a systemd unit on the target. Firmware must also allow it — the
setting is usually called "Wake on LAN" or "Power on by PCIe" in the BIOS.

## Name resolution after a reset

In router mode the hub writes `/etc/resolv.conf`, and before the first write
it copies the file it found to `/var/lib/neutrino/hub/resolv.conf.original`.
`nhub reset all` links the file to the stub of `systemd-resolved` when that
unit is enabled, puts the copy back when there is one, and otherwise writes
the network's resolvers the last apply used, one `nameserver` line each. The
reset prints which of the three it did.

## Logs

| What | Where |
| --- | --- |
| Routing state | `journalctl -u neutrino_hub_router` |
| Proxy | `journalctl -u neutrino_hub_xray` |
| DNS queries | `journalctl -u neutrino_hub_dnsmasq` (also the panel's Dashboard) |
| Control panel | `journalctl -u neutrino_hub_web` |
| An update of the hub itself | `journalctl -u neutrino_hub_update`, and `/var/lib/neutrino/hub/hub_update/update.log` |
| The hub's own agent following the hub | `journalctl -u neutrino_hub_local_agent`, and `/var/lib/neutrino/hub/hub_update/local_agent.log` |
| Device agents | `journalctl -u neutrino_agent` on the device itself |

## A hub on macOS or Windows

The hub there is one service in `server` mode, and the checks above that read
nftables, `ip rule` or dnsmasq are Linux's.

| | macOS | Windows |
| --- | --- | --- |
| The service | the LaunchDaemon `com.neutrino.hub`: `sudo launchctl print system/com.neutrino.hub` | `neutrino_hub`: `sc query neutrino_hub` |
| Start and stop | `sudo nhub start`, `sudo nhub stop` | `nhub start`, `nhub stop` in an administrator PowerShell |
| The panel | the `Neutrino Hub` entry in Launchpad, or `nhub open` | the `Neutrino Hub` entry in the Start menu, or `nhub open` |
| Logs | `/Library/Logs/Neutrino/hub/<name>.log` | `C:\ProgramData\Neutrino\hub\log\<name>.log` |
| The firewall | `/usr/libexec/ApplicationFirewall/socketfilterfw --listapps`, `sudo pfctl -a com.apple/neutrino_hub -sr` and `-sT` for the exposed segments' tables | `Get-NetFirewallRule -Name 'neutrino_hub_*'`, each hub port's rule with a `Get-NetFirewallAddressFilter` naming the exposed segments |

`nhub open` opens the panel in the default browser on every system, and
the setup wizard while the box is not set up. `nhub start` and `nhub stop`
drive the one service, and with it every daemon it supervises. Each supervised daemon writes a log file named after it,
`netbird.log` for NetBird, and `nhub` and the panel read the tail of that
file where Linux runs `journalctl -u`. An update
records its turns in `state.json` under the state root's `hub_update/`, as on
Linux.

## Checking the panel's HTTPS

The HTTPS port, `https_listen_port` (443 by default), serves the panel's
certificate whether `is_https_enabled` is on or off. The certificate chains to
the hub's own authority and names the address it was reached at:

```bash
sudo openssl s_client -connect 127.0.0.1:443 \
    -CAfile /etc/neutrino/hub/web/panel_tls/authority.pem </dev/null 2>/dev/null \
    | grep -E 'subject=|Verify return code'
sudo openssl x509 -in /var/lib/neutrino/hub/panel_tls_certificate.pem -noout -ext subjectAltName -dates
```

`Verify return code: 0 (ok)` is the chain holding. A browser that still warns
has not installed the authority, or was given a new one by
**Regenerate certificate**, or was told to proceed past a warning and has not
restarted since; Settings downloads the current one, and with HTTPS on the HTTP
port still serves it at `/api/hub/setting/https/authority`. While HTTPS is on,
`curl -sI http://127.0.0.1:8080/` answers `301` with the HTTPS address in
`location`. An HTTPS port that refuses connections has no certificate to
serve, or its port is the HTTP port, and `journalctl -u neutrino_hub_web`
names why, usually `vault_locked` or `port_already_in_use`.

## Updating the hub from the panel

Settings has an Update panel; `sudo nhub update` does the same from a
terminal, and `sudo nhub update --package <file>` installs a package file
somebody brought. That file keeps its release name, `neutrino-hub_<version>_<arch>.deb`
for a deb, since the version is read off the name; any other name is rejected
with `package_name_mismatch`, and a path with no file with `package_missing`. Either way the panel process only stages: it downloads the
package into `/var/lib/neutrino/hub/hub_update/`, checks it against the release's
`SHA256SUMS`, keeps the running version's own package beside it, and starts
the transient unit `neutrino_hub_update` with `update.sh` from that directory.
The unit runs the package manager and reads `nhub --version`: a version other
than the target fails the update at once, and a box still on the version it
started from is left as it is. With the target in place it holds a gate of up
to 180 seconds:
`neutrino_hub_web` and whichever of `neutrino_hub_router` and
`neutrino_hub_dnsmasq` were running must be active, `GET /api/hub/display`
must answer, on `https://127.0.0.1:<https_listen_port>` while
`is_https_enabled` is on at that moment and on
`http://127.0.0.1:<listen_port>` otherwise, or else on the other one, HTTPS
trusting `/etc/neutrino/hub/web/panel_tls/authority.pem`, and
`nhub --version` must print the target.
A gate that fails installs the previous package and holds the gate again.

When `/proc/meminfo` gives less than 300 MB of `MemAvailable` as the unit
starts, it stops `neutrino_hub_web` and `neutrino_hub_cliproxyapi`, where
running, before the package manager runs, and starts them again once it has
finished, whether the install succeeded or not. The unit installs no agent.
The machine's own agent follows the version the unit ends on, as after every
install of the hub's package ("The hub's own agent follows its hub" below).

`state.json` in that directory records where it stands: `installing`,
`installed`, `rolling_back`, `rolled_back` or `failed`, with `reason` naming
the first failure, `steps` the lines the Settings page shows, and `output` the
tail of `update.log`. The panel reads it
back once it is up again. A box left on neither version, which only a
rollback that failed too can leave, is put back by hand:

```bash
sudo apt-get install -y --reinstall --allow-downgrades /var/lib/neutrino/hub/hub_update/neutrino-hub_<version>_amd64.deb
```

A board that resets during the unpack, with nothing in the journal, is
being reset by hardware, not by a crash: Armbian arms the SoC's watchdog
through systemd (`RuntimeWatchdogSec=` in
`/etc/systemd/system.conf.d/10-watchdog.conf`), and PID 1 alone feeds it.
The unpack takes the box's memory. dpkg-deb decodes xz with one thread per
processor and each thread holds a block of the archive, so four threads
take over 200 MB, and the page cache the unpack fills takes the rest. A box
with under 1 GB and no swap then drops the pages every other process runs
on, PID 1's among them; the page faults PID 1 takes on its way to feed the
watchdog wait behind the card's write queue, and a few in a row cost more
than 30 seconds. Measured on an S905X box with 787 MB and an SD card
writing at 10 MB/s, 2026-09-23: the same package reset the board four times
out of four under the unit and once out of four by hand over SSH, and a
loop that runs every half second went 26 seconds without running during a
hand install. The unit therefore runs with `MemoryHigh=384M`, which keeps
its page cache inside its own cgroup, and `DPKG_DEB_THREADS_MAX=1`, which
holds dpkg-deb under 100 MB; with both, six unit installs on that board
took 285 to 337 seconds each and the loop never waited more than 21
seconds, in most runs under 10. `--force-unsafe-io` was measured too and
left out: under the bound it saved no time, and it kept the card's writes
for the moment the panel restarts, which is the heaviest moment of the
install. The package manager runs under `ionice -c 2 -n 7 nice -n 10`. A
watchdog of 60 seconds gives such a board room for that restart; by hand on
such a board, put `DPKG_DEB_THREADS_MAX=1` in front of the `apt-get` line
above.

## What an upgrade restarts

An install of the hub's package over a hub somebody set up restarts the
transport and the panel on the package's new programs. The panel's update
and its rollback run the package manager, and with it the same scripts.

| Package | Its install over a hub somebody set up |
| --- | --- |
| `.deb`, `.rpm`, Arch | The script runs `nhub apply`. It then restarts `neutrino_hub_router` where it is enabled, `neutrino_hub_web` while it runs, and `neutrino_hub_transport` while it runs, in that order. |
| macOS `.pkg` | The preinstall stops `com.neutrino.hub` before the installer writes the files, and every daemon it supervises ends with it, the transport among them. The postinstall starts it again. |
| Windows `.msi` | The installer stops `neutrino_hub` before it replaces the files and starts it after them. The daemons it supervises run in its job and end with it. |

| Rule | Reason |
| --- | --- |
| On Linux the script restarts the transport's unit after `nhub apply`, whether or not `nhub apply` restarted it. | A running process keeps the program it started from, and `nhub apply` restarts the transport only when `transport.json` changes. The restart runs the unit `nhub apply` wrote. |
| The transport restarts last. | The restart ends every session, and each peer dials again at once ([../design/transport.md](../design/transport.md), "The redial"). The new panel already runs and admits each peer. A peer that dials while no panel runs reads `control_unavailable` and dials again 5 seconds later. |
| On macOS and Windows no script names the transport. | The transport runs there as a child of the one service, and the install stops and starts that service. |

## The hub's own agent follows its hub

The agent on the hub's own machine is brought to the version of the hub's
package by every way that package arrives: the panel's update, `install.sh`,
`install.ps1`, `apt`, `dnf`, `pacman`, the macOS `.pkg` and the Windows
`.msi`. Each of them ends with the panel started on the new version. The
Linux packages' scripts restart `neutrino_hub_web` on a box somebody set up,
and the `.pkg` and the `.msi` start the one service. At each start the panel
reads `nagent --version`. When the machine has an agent whose version is not
the version of the machine's own package in
`/var/lib/neutrino/hub/agent_cache/`, the panel writes `local_agent.sh`, or
`local_agent.ps1` on Windows, into `/var/lib/neutrino/hub/hub_update/` and
starts it apart from itself, the way the hub's update starts `update.sh`:

| System | The script runs as |
| --- | --- |
| Linux | the transient unit `neutrino_hub_local_agent` |
| macOS | the job `neutrino_hub_local_agent` given to `launchctl submit`, which removes itself when it ends |
| Windows | a PowerShell with no window, whose process id the panel writes to `local_agent.pid` beside it |

A script of that name still running is left to run, and no second one
starts. The script takes these turns and writes each one, with the package
manager's output, to `local_agent.log` beside it:

1. It waits, at most 30 minutes, while the hub's own update runs:
   `neutrino_hub_update` on Linux and macOS, and the update's PowerShell on
   Windows. It looks every second.
1. It ends when `nhub --version` names a version other than the one it was
   written for, or when `nagent --version` names the package's version.
1. It installs the package with the command the hub's update installs with,
   which waits up to 300 seconds for the lock of the install that started the
   panel: apt and dnf by their own wait, pacman by a wait on its lock file,
   macOS while `installer` runs, and Windows while the Windows Installer
   runs and once more after `msiexec`'s busy answer.

A machine with no agent gets none. A hub that is not set up serves the setup
wizard and starts no panel, and `nhub setup` installs its agent
([../design/architecture.md](../design/architecture.md), "`nhub setup`
configures and starts, and installs nothing"). The Arch package carries no
agent package, so a hub there starts no script. An agent of 0.5 is replaced
by the agent of 0.6, which reads `hub_key_missing` until it joins again with
a new link from the hub's own row on the Agents page
([../design/transport.md](../design/transport.md), "A peer of 0.5").

| Rule | Reason |
| --- | --- |
| The panel's start starts the script, and no package script does. | Every install path ends with the panel started on the new version, the panel's update among them, so one check there serves every package format on every system. |
| The script runs apart from the panel and installs once the package manager lets go. | The package manager holds its lock while the hub package's scripts run, which is when the panel starts, and an install in the panel's own process ends when the panel stops. |
| The script waits for the hub's own update to end and installs only while the hub is still the version it was written for. | The update's gate can put the previous version back, and the agent follows the version the update ends on. |
| Nothing else holds the script back, and each wait looks every second. | The agent reaches the hub's version within seconds of the panel's start. The agent's own update installs nothing once the agent is at its version. |

## Trying a change on an installed box

A package install puts the hub under `/opt/neutrino/hub/python/lib/python3.13/site-packages/neutrino_hub/`
and the agent under `/opt/neutrino/agent/python/lib/python3.13/site-packages/neutrino_agent/`.
A `.py` copied over one of those files is not what runs until its compiled
copy is gone: the carried interpreter loads `__pycache__/<name>.cpython-313.pyc`
without checking the source (the packaged files are unchecked-hash pycs), so
a pushed file whose change is missing at runtime has a stale `.pyc` beside it.

```bash
SP=/opt/neutrino/hub/python/lib/python3.13/site-packages/neutrino_hub
sudo cp module.py $SP/web/routers/agent/module.py
sudo rm -f $SP/web/routers/agent/__pycache__/module.cpython-313.pyc
sudo systemctl restart neutrino_hub_web
```

The built panel under `neutrino_hub/data/frontend/` is served from disk, so a
copied build shows on the next page load with no restart. Restarting
`neutrino_hub_web` leaves every session to `neutrino_hub_transport`, but every
question and frame waits on the panel's process for that moment: an install
in progress on a device fails with `hub_unreachable` or
`control_unavailable` and the agent retries on its own, so restart between
installs, not during one.

## Running a package through the VM lab

`packaging/lab/run_lab.py` takes a hub package from nothing to a tested hub
on two fresh VMs: `setup_vms.sh` builds a hub with three ports and a client on
the wire it serves, the suite under `packaging/integration/` and the package
go into the hub, and `run_mode_matrix.sh --client` walks every mode there.
`--lifecycle` builds the pair again and runs `run_on_box.sh` on it as well.
The exit status is the number of phases that failed.

The lab's images, disks and SSH key live in the directory `NEUTRINO_VM_LAB`
names, which qemu's own user must be able to reach, so not one under `/home`.
The libvirt group is needed to drive it:

```bash
export NEUTRINO_VM_LAB=/var/lib/neutrino_vm_lab
sg libvirt -c "python3 packaging/lab/run_lab.py dist/neutrino-hub_<version>_amd64.deb"
```

The package keeps its release name, because `nhub update --package` reads the
version off it. `--distro` and `--version` pick the cloud image, `debian 12`
by default. One run takes about ten minutes.
