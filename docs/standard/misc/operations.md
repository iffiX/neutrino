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
on the overlay you reach the panel, SSH, Gitea, and the shares at their LAN
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

## Logs

| What | Where |
| --- | --- |
| Routing state | `journalctl -u neutrino_router` |
| Proxy | `journalctl -u xray`, `/var/log/neutrino/xray_error.log` |
| DNS queries | `/var/log/neutrino/dnsmasq.log` (also the panel's Dashboard) |
| Control panel | `journalctl -u neutrino_web` |
| Device agents | `journalctl -u neutrino_agent` on the device itself |
