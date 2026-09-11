---
title: Network modes
---

# Network modes

A mode decides how much of the machine's network the hub takes over. The
wizard offers four; the panel's Network page offers three, because one-arm
router is stored as router.

Read this before you pick one:

- One-arm router is a wizard answer only. It decides which questions you are
  asked, and the Network page shows the result as Router.
- Server and side gateway change no address on the machine. Only Router does.
- Changing shape after setup means `sudo nhub reset all`, which throws away
  every key and token the box has collected. It is not a mode switch.
- The router layer does not build on NetworkManager.
- A trunk cannot be a radio. 802.1Q tags do not ride on Wi-Fi.

If all you want is one application sent through an exit node, server mode is
enough and the page you want is [Proxy](./proxy.md).

## The four shapes

| Shape          | Takes over                                            | Ports   | Offered by                                     |
| -------------- | ----------------------------------------------------- | ------- | ---------------------------------------------- |
| Server         | nothing                                               | 1       | the wizard and the Network page                |
| Side gateway   | nothing addressed; it forwards for hosts that name it | 1       | the wizard and the Network page                |
| Router         | the interface roles and the addresses on them         | 2       | the wizard and the Network page                |
| One-arm router | as router, on one wired trunk                         | 1 wired | the wizard only; the panel stores it as Router |

A machine with too few ports is not offered the mode at all. Interface roles
are `wan`, `lan`, `split` and `disabled`, a VLAN tag runs from 1 to 4094, and a
prefix length from 1 to 32.

![The Network page's mode panel, with Server, Side gateway and Router](/guide/en/network_modes.webp)

## Server keeps the network

Server "Routes nothing; answers where it is reached." Every address the machine
has stays as it is, and it stays from wherever it came: DHCP, a static file, or
whatever set it before Neutrino arrived. Only Router owns addressing.

The wizard says it once, on the ports screen: "No port is given a job. Every one
of them keeps the address it has and answers to begin with; the panel's Network
page narrows that afterwards."

## Side gateway

Side gateway "Forwards for hosts that name it as their gateway." It takes over
no address either. The hub sits on the network it was already on, and routes
for the hosts that point at it.

Set the default gateway of each host you want routed to this box's address. On
that host, `ip route` then names the hub.

Expect: that host's traffic leaves through the hub, and the hub's Dashboard
counts it.

The box's own way out stays the address in "That network's own router".

## Router and one-arm

Router owns the interface roles and the addresses on them, and needs two ports.
One-arm router does the same job on a single wired trunk: untagged traffic goes
out, tagged VLAN traffic comes in.

- The default served network is `192.168.8.0/24`, with the box at
  `192.168.8.1`. It is deliberately not `192.168.0.x` or `192.168.1.x`, which
  the router upstream is most likely already using.
- The DHCP pool runs from host `.100` to `.200`, leaving the low addresses for
  hosts you pin by hand.
- The default one-arm VLAN tag is `3`. The uplink needs no tag; it is the
  untagged traffic on the same wire.
- A trunk's untagged main is named `<trunk>.main` on the panel and in
  `config/`. It is not a kernel device.
- The wizard sets the primary uplink and the primary served network only: "Only
  the primary way out and the primary served network are set here. The panel's
  Network page adds more."

Open Network, pick Router under Mode, and press "Apply mode".

Expect: "Rewrites the interface roles and reloads the firewall.", then the
interface list redraws with `wan` and `lan` roles on it.

::: danger The switch has to pass tags
A one-arm trunk only works if the switch it plugs into **passes VLAN tags**. On
a plain switch this looks configured and carries nothing.
:::

::: warning
Changing the served subnet invalidates every device's DHCP lease and every SSH
host key pinned to an old address.

Renew the leases by restarting the router service, and remove and re-add any
device whose SSH details were stored.
:::

## Exposure and panel port

Exposure is "The networks on which this box accepts connections to its own
services: the panel, SSH, DNS, the shares."

Open Network, tick the networks under Exposure, and press "Apply exposure".

Expect: "Applied to the firewall." Applying reloads the firewall input chain
and nothing else.

![The Exposure panel, with the LAN and the overlay ticked](/guide/en/network_exposure.webp)

The panel port is "The TCP port this panel listens on, on every exposed
interface.", and it is `8080` until you change it.

Open Network, set a new port under Panel port, and press "Apply panel port".

Expect: "Moves to {origin}." first, then the browser follows the panel to the
new address. If it cannot, the page reads "No answer at {origin}. Open it again
once the panel is reachable from here."

## Changing shape

The mode you answered in the wizard is undone by a reset, not by an edit.

```bash
sudo nhub reset all
```

Expect: the network is handed back first, then `config/` returns to the
committed examples, every key and token the box collected is gone, and the
services stop. `/etc/neutrino/agent` is kept, because it belongs to the agent
package.

Then set the box up again:

```bash
sudo nhub setup
```

::: tip
A reset takes no address off anything, so the SSH session that asked for it
survives the command.
:::

That is the whole path: the box is in the shape you chose, answering on the
networks you ticked.
