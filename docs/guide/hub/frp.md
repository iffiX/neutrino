---
title: SakuraFrp and OpenFrp
---

# SakuraFrp and OpenFrp

SakuraFrp (natfrp.com) and OpenFrp (openfrp.net) are third-party services that run frp nodes on public addresses. A TCP tunnel at either one gives the hub's connection port a public port on a node. frpc, the frp client in every hub package, connects to the node and passes each connection on that public port to the hub.

A tunnel suits a home with no public IPv4 or IPv6 address and no VPS of your own. [Choose a way in](../scenarios/choose_a_way_in.md) compares it with the other ways in.

TLS runs from the client to the hub, and the client checks the hub's certificate fingerprint, as on every other way in. The node passes on the encrypted connection. The bandwidth the vendor gives your account limits the speed of every connection through the node.

## Prepare an account

At SakuraFrp or OpenFrp:

1. Register an account.
1. Complete the vendor's real-name verification. SakuraFrp charges 1 yuan for it.

A free SakuraFrp account has 10 Mibps of bandwidth and 5 GiB of traffic a month, and a daily sign-in on SakuraFrp's site adds traffic. You make that sign-in yourself. For OpenFrp's free plan, see OpenFrp's site.

## Create a tunnel at the vendor

The hub lists only the TCP tunnels whose local port is the hub's connection port, so the local port marks a tunnel as the hub's. frpc itself connects to a port of the hub's own on `127.0.0.1`: 18443 for SakuraFrp and 18444 for OpenFrp. That port serves the same channel as the connection port.

The list also leaves out these tunnels:

- At OpenFrp, a tunnel with auto TLS on. Its node ends TLS with its own certificate, which every client rejects.
- At SakuraFrp, a tunnel on a node with forced access authentication, where each visitor first authenticates in a browser.

Read the hub's **Connection port** under **Ports** on the [Network](./network.md#ports) page, 8443 by default, then:

1. In the vendor's console, create a tunnel of type TCP.
1. Set its local port to the hub's connection port.
1. At OpenFrp, turn auto TLS off.
1. Pick a node and save the tunnel.

The local IP can stay as the console fills it in, because frpc on the hub connects to the hub's loopback port.

## Sign the hub in

Before you sign in, turn on the **SakuraFrp** or **OpenFrp** card on the [Access](./overlay.md) page and select **Apply access**. Then select the card itself. Its section opens under the cards with **Status** and **Account**, and **Tunnels** after you sign in.

### SakuraFrp

1. Copy your access key from the SakuraFrp management panel.
1. Under **Account**, paste it into **Access key**.
1. Select **Save access key**.

The hub checks the key with SakuraFrp and stores it only when SakuraFrp accepts it. **Status** then reads **Enabled, not connected**.

### OpenFrp

1. Under **Account**, select **Log in**. OpenFrp's login page opens in a new browser tab.
1. In that tab, sign in to OpenFrp and confirm the login within 5 minutes.

Until you confirm, the panel reads **Confirm the login on the OpenFrp page.**, and the hub polls OpenFrp for your confirmation every 5 seconds. **Open the login page again** opens the tab again after you close it. When the login goes through, **Log out** takes the place of **Log in**.

An OpenFrp login lasts at most 30 days. After it expires, the section reads **The login has expired. The tunnel keeps running; log in again to pick another.**

The hub keeps the access key and the OpenFrp login in `config/overlay/`, sealed under the vault's data key, so a configuration backup holds them.

## Pick a tunnel

**Tunnels** lists the account's tunnels the hub can use, one row each. A row shows the node's name, its region and the latency from the hub to the node. The region reads **Mainland China**, **Hong Kong, Macao, Taiwan** or **Outside China** at OpenFrp, and **Mainland China** or **Outside mainland China** at SakuraFrp. A latency cell stays empty when no connection to the node finished within 3 seconds.

1. Under **Tunnels**, select a row.
1. Select **Apply tunnel**.

The hub fetches the tunnel's configuration from the vendor and writes frpc's file on the hub, which holds the account's token. **Status** reads **Connecting**, then **Connected** within a minute. **Node** names the tunnel's node, and **Address for clients** shows the node's host name and the tunnel's public port as an `https://` address.

The hub reads the list when the section opens and when you select **Refresh**. An empty list reads **No TCP tunnel has local port 8443. Create one at SakuraFrp.**, with your connection port and vendor in it and a button that opens the vendor's console. Create the tunnel there, then select **Refresh**.

The hub calls the vendor when you act on the **Access** page, and when frpc's file for the picked tunnel is missing. Turning the card off deletes that file, and a backup leaves it out. Turning the card on again, or restoring a backup, therefore fetches the configuration again.

## Read the status

The hub checks the public address 5 seconds after frpc starts and every minute after that. **Status** reads **Connected** only when the hub finds its own certificate at that address. Under the status, the section shows the last line frpc wrote, or the reason the check failed.

| Status                         | Meaning                                                                                                |
| ------------------------------ | ------------------------------------------------------------------------------------------------------ |
| **Off**                        | The card is off.                                                                                       |
| **Not signed in**              | No access key or OpenFrp login is stored.                                                              |
| **Vault locked**               | The hub cannot open the stored key or login.                                                           |
| **Enabled, not connected**     | The hub is signed in, and no tunnel is picked.                                                         |
| **Local port in use**          | Another program holds the hub's loopback port for this vendor: 18443 for SakuraFrp, 18444 for OpenFrp. |
| **Tunnel config unavailable**  | The hub has no frpc file for the picked tunnel, and the vendor returned no configuration for it.       |
| **Connecting**                 | frpc runs, and the first check is still running.                                                       |
| **Connected**                  | The public address returns the hub's certificate.                                                      |
| **Tunnel refused by the node** | The node rejected the tunnel, as for a public port in use or a tunnel turned off at the vendor.        |
| **Public port closed**         | frpc runs, and the public address returns nothing or another certificate.                              |
| **Node login failed**          | The node rejected the account's token.                                                                 |
| **Node unreachable**           | frpc exited without reaching the node, or the connection to it dropped.                                |

On Linux, frpc runs as the unit `neutrino_hub_sakurafrp` or `neutrino_hub_openfrp`, and on macOS and Windows inside the hub's service. A stopped frpc starts again after 10 seconds on Linux. What to do for each status is on [Troubleshooting](../reference/troubleshooting.md#access).

## What clients see

While a tunnel is picked, every new client link holds the tunnel's address, whatever the status. Every joined client and agent gets it with its next state from the hub, with no new link. The hub's own addresses come first, then SakuraFrp's, then OpenFrp's, and the SSH relay's last.

A client's hub row reads **Connected · SakuraFrp** or **Connected · OpenFrp** while its connection runs through the tunnel. A client ranks the LAN, Direct, NetBird and EasyTier above the tunnels and the SSH relay. When any of those four reaches the hub, the row names that way instead.

To see the tunnel in use, turn off a phone's Wi-Fi while its virtual network line is not connected, then read its hub row.

Turning the card off, or applying another tunnel, disconnects the clients connected through the tunnel. The apply bar warns before it. Each client connects again on its own through another way in, and a client with none stays disconnected.

## After the connection port changes

frpc keeps passing connections to the hub's loopback port, so the tunnel keeps working after you change **Connection port** on the **Network** page. The hub's list shows only tunnels whose local port is the connection port, so the apply bar on **Network** warns to change the local port at the vendor. With a new port of 9443, the **Status** panel reads **The connection port is 9443. At SakuraFrp, change this tunnel's local port to 9443, then apply the tunnel again.**

1. In the vendor's console, set the tunnel's local port to the new connection port.
1. Under **Tunnels**, select **Refresh**.
1. Select the tunnel's row, then **Apply tunnel**.

## Stop using a tunnel

To stop the tunnel and keep the account, turn the card off and select **Apply access**. The card keeps its account and its tunnel while off.

To take the account off the hub, select **Forget access key** for SakuraFrp or **Log out** for OpenFrp, then confirm. Either one stops frpc and removes the tunnel's address from every client and agent.

## OpenFrp's notice

OpenFrp's terms ask a third-party program to name the interface it uses and to say who supports it. The OpenFrp section's **Account** panel shows both lines at all times:

> Uses the OpenFrp OPENAPI
>
> This project is developed by its community. OpenFrp offers technical support for node problems only.
