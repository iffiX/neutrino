---
title: Overlay with EasyTier
---

# Overlay with EasyTier

EasyTier is peer to peer, with no management plane of its own. The hub mints a
network, other machines join it with one command, and nothing in between keeps
accounts or policies.

Five things to know before the first click:

- One overlay runs at a time. Choosing EasyTier stops NetBird, and choosing
  NetBird stops EasyTier.
- There is no console. If you want accounts, policies and a web console, read
  [Overlay with NetBird](./overlay-netbird.md).
- The secret is never shown. It is masked on screen and real in what the Copy
  buttons put on the clipboard.
- EasyTier cannot ship in the Windows client: its Windows build statically
  imports Npcap's `packet.dll`, which may not be redistributed.
- Whether this box answers on the overlay is set under Network, Exposure, not
  on this page.

The engine runs on interface `easytier`, with peer port `11010` on TCP and UDP.

## What EasyTier gives

- A network is a name and a secret that this hub mints. The panel says it
  plainly: "A network is a name and a secret. Every machine carrying both is on
  it, and the secret is also the key its traffic is encrypted under."
- The secret is sealed under the vault's data key on this box.
- The panel never asks the engine for its own `node` read, because that read
  prints the secret in the clear.
- What it does not give: no console, no accounts, no policies. A name and a
  secret are the whole of the network.

The Overlay page draws the members in a lane labelled "EASYTIER NETWORK".

## Choose and Generate

Open **Overlay**, pick EasyTier, and press "Apply engine".

Expect: the engine installs if it is not installed, and an EasyTier section
appears below the chooser. Until it is installed the page reads "The engine is
not installed. Applying the engine above installs it."

![The Overlay page's engine chooser, with None, NetBird and EasyTier](/guide/en/overlay_chooser.webp)

In "This gateway on the network", press "Generate".

Expect: the Network name field fills with a minted name, and the Network secret
field fills masked.

Set "This box's address", for example `10.0.0.1/24`, then press "Apply
network".

Expect: "Restarts the engine on this network.", then the badge turns
"connected", or "no peers yet" while this box is alone.

![The EasyTier panel connected, with this gateway's overlay address](/guide/en/overlay_easytier_running.webp)

::: warning
A different secret is a different network. Every other machine stays on the old
one until its secret is changed too, and the two networks cannot see each
other.

Change the secret on the hub last, after every machine has been given the new
one, or change it here and then re-run the join command on each machine.
:::

## Bootstrap peers and exported networks

Under "Bootstrap peers", add the address of a machine already on the network,
then press "Apply peers".

Expect: "Restarts the engine and dials them." With none listed, the section
reads "Nothing to reach yet, so this box waits to be reached."

The panel names the schemes it takes: "There is no server to find. A machine
starting up reaches one that is already on the network: tcp://, udp://, ws://,
wss:// or quic:// for an address, http://, https://, txt:// or srv:// for one
that answers with addresses."

Under "Exported networks", add each subnet the peers should reach through this
box, such as `10.20.0.0/24`, then press "Apply networks".

Expect: "Restarts the engine and announces them.", and the machines on the
overlay reach those addresses through this box.

## Commands for another machine

In "Commands for another machine", press "Copy with the secret" on the join
line.

Expect: the clipboard carries the whole command with the real secret in it,
while the screen still shows the secret masked.

Run it on the second machine:

```bash
easytier-core -d --network-name PLACEHOLDER_NETWORK \
  --network-secret PLACEHOLDER_SECRET -p tcp://198.51.100.10:11010
```

Expect: within seconds that machine appears in the hub's Peers table.

![The commands panel with the join line and the rendezvous line, secret masked](/guide/en/overlay_easytier_commands.webp)

The second command is for a rendezvous of your own, on a machine with a public
address. The panel describes it as one that "carries no traffic of anybody
else's network and answers nobody without this secret".

```bash
easytier-core --private-mode true --network-name PLACEHOLDER_NETWORK \
  --network-secret PLACEHOLDER_SECRET \
  --relay-network-whitelist PLACEHOLDER_NETWORK \
  -l tcp://0.0.0.0:11010 -l udp://0.0.0.0:11010
```

Expect: it listens on `11010` and relays this network's traffic only.

Only the network name and the secret change between machines. When the hub has
no reachable address yet, the join line prints `<this gateway>` where the
address belongs.

## Peer table

Read "Peers".

Expect: one row per machine on the network, refreshed by itself every few
seconds. With nobody else on it, the table reads "No machine has joined yet."

![The EasyTier peer table with two machines on the network](/guide/en/overlay_easytier_peers.webp)

## Where the secret lives

The secret sits in the vault, sealed under its data key. The panel shows twelve
dots in its place, and the Copy buttons fetch the real value at the moment you
press them.

::: danger The secret is the key
The secret is also the **encryption key** for the network's traffic. Anybody
holding the name and the secret is on the network.
:::

That is the whole path: the hub owns a network, and one command puts another
machine on it.
