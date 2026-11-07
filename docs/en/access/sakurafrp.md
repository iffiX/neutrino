# SakuraFrp

SakuraFrp is a third-party tunnel service. The hub runs frpc, which connects to a SakuraFrp node, and the node forwards a public port to the hub's connection port. Content between the devices and the hub is encrypted, so the node cannot read it.

<Facts systems="Linux,Windows,macOS" editions="国际版,国内版" since="0.6.0" />

| Free account quota | Value                                              |
| ------------------ | -------------------------------------------------- |
| Tunnels            | 2, of which the hub uses 1                         |
| Bandwidth          | 10 Mibps                                           |
| Traffic            | 5 GiB per month                                    |
| Reading date       | 2026-10-30; the SakuraFrp website is authoritative |

## Register an account

1. Open [SakuraFrp](https://www.natfrp.com/) and register an account.

1. Complete the identity verification on the website, which costs 1 yuan.

1. Copy your **访问密钥** (Access key) from the website.

## Save the access key

1. In the panel's left sidebar, select **Access**, turn on the **SakuraFrp** card's switch, then select **Apply access**. The **Status** section appears and shows **Not signed in**.

   ![Status section showing Not signed in](/guide/en/access_sakurafrp_01_status.webp)

1. In the **Account** section, paste the key into **Access key**, then select **Save access key**. The hub checks the key with SakuraFrp, and after the check passes, the status changes to **Enabled, not connected**.

   ![Access key box marked in red](/guide/en/access_sakurafrp_02_key.webp "Paste the key")
   ![Key filled in, Save access key button marked in red](/guide/en/access_sakurafrp_03_save.webp "Select Save access key")

## Create a tunnel

1. Note the connection port, which is in the **Ports** section of the panel's **Network** page and is 8443 by default.

1. After the key is saved, the panel shows the **Tunnels** section. If the list is empty, select **Open the SakuraFrp console**.

1. In the tunnel list on the SakuraFrp website, select **创建隧道** (Create tunnel) and choose a node first. The node must have forced access authentication turned off. The picture shows 日本 1 (Japan 1); pick a node close to where you usually are.

   ![Node list with Japan 1 marked in red](/guide/zh/access_sakurafrp_12_node.webp)

1. For the tunnel type, choose **TCP 隧道** (TCP tunnel). Enter a name such as `neutrino` in **隧道名** (Tunnel name), and the connection port in **本地端口** (Local port). Leave **本地 IP** (Local IP) and **访问密码** (Access password) empty, then select **创建** (Create).

   ![Completed tunnel form with the local port and the create button marked in red](/guide/zh/access_sakurafrp_14_form.webp)

1. Back in the panel, select **Refresh** in the **Tunnels** section. The list shows only usable tunnels, and each row shows the tunnel name, the node, **Region** and **Latency**.

   ![Tunnels section in the panel with the neutrino row marked in red](/guide/zh/access_sakurafrp_20_tunnels.webp)

1. Select the tunnel, then select **Apply tunnel**.

   ![neutrino selected, Apply tunnel button marked in red](/guide/zh/access_sakurafrp_21_apply.webp)

1. Wait for the status to show **Connected**; the result appears within a minute.

   ![Status showing Connected, with the client address masked](/guide/zh/access_sakurafrp_22_connected.webp)

Each status means:

| Status                         | Meaning                                                                         |
| ------------------------------ | ------------------------------------------------------------------------------- |
| **Not signed in**              | The hub has no saved access key                                                 |
| **Vault locked**               | The hub cannot read the key                                                     |
| **Enabled, not connected**     | The key is saved, and no tunnel is selected yet                                 |
| **Connecting**                 | The first check has not finished, and the result appears within a minute        |
| **Connected**                  | Outside networks can connect to this hub                                        |
| **Local port in use**          | Another program uses the local port the hub reserves for frpc                   |
| **Tunnel config unavailable**  | The tunnel was deleted, the key expired, or SakuraFrp returned no configuration |
| **Tunnel refused by the node** | Another tunnel uses the public port, or the tunnel was turned off at SakuraFrp  |
| **Public port closed**         | The tunnel runs, but outside networks cannot connect to it                      |
| **Node login failed**          | The node rejects this account                                                   |
| **Node unreachable**           | The hub cannot connect to the node, or the connection dropped                   |

## Verify the connection

Joined devices receive this address automatically, so you do not join them again. Turn off Wi-Fi on the phone and open the client over mobile data. The tunnel works when the hub row shows **Connected · SakuraFrp**.

![The hub row shows Connected and SakuraFrp](/guide/en/access_sakurafrp_09_client_connected.webp)

## Maintenance

- **Changing the tunnel or turning off the card:** clients connected through this tunnel disconnect. If another access method is on, the clients reconnect automatically.
- **Changing the connection port:** after you change it on the **Network** page, change the local port in the SakuraFrp console, then select **Refresh** and **Apply tunnel**.
- **Pausing:** turn off the card's **Enable** switch. The hub keeps the account and the tunnel.
- **Stopping use of this account:** select **Forget access key**.
