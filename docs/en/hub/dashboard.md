# Dashboard

**Dashboard** is the first page you see after you sign in to the panel, and it shows traffic, systems and AI usage.

Select **Dashboard** in the sidebar to return to it at any time. It shows data only, with no settings. The numbers refresh automatically while the dot at the top right shows **streaming**. While the dot shows **connecting** or **Live stats offline**, the numbers pause.

![The Dashboard page with Dashboard marked in the sidebar](/guide/en/hub_dashboard_01_page.webp)

## Stat tiles

The top of the page has a row of stat tiles, each showing one metric. If one tile cannot read its data, only that tile shows an error, and the others display normally.

![The Dashboard page with a row of stat tiles at the top](/guide/en/hub_dashboard_02_tiles.webp)

| Tile                     | What it shows                                                                                    |
| ------------------------ | ------------------------------------------------------------------------------------------------ |
| **Download**, **Upload** | This computer's current speed, with today's total under it                                       |
| **Proxy exits**          | The number of exits with recent traffic, with the number of tested exits under it                |
| **AI tokens**            | The number of tokens the AI gateway handled today                                                |
| **Agents**               | The number of systems reporting. Select the tile to open the **Agents** page and see each system |
| **CPU**, **Memory**      | Usage. The tile turns yellow at 70% and red at 90%                                               |
| **Uptime**               | The uplink interface's address under it, or **no WAN address** when the interface has no address |
| **DNS queries**          | Appears only in router and side gateway modes on Linux                                           |

The uplink interface is the network interface this computer uses to access the internet. In router mode, it is the first WAN port. In other modes, it is the interface of the default route.

## Live traffic

The **Live traffic** chart shows **down** and **up** traffic on the uplink interface for the **last 2 min**. To see only part of the traffic, switch between **All**, **Proxied** and **Direct** at the top right.

![The Live traffic chart on the Dashboard page with All marked](/guide/en/hub_dashboard_03_live.webp)

**Active exits**, beside the chart, lists the exits used in the last two minutes and their traffic. When no exit has been used, it shows **No active exits yet**.

## Traffic history

The **Traffic history** chart shows **received** and **sent** traffic on the uplink interface. You can switch between **Day**, **Week**, **Month** and **Year** at the top right. Right after the install, the chart shows **No history yet**.

![The Traffic history chart and the range buttons at its top right](/guide/en/hub_dashboard_04_history.webp)

In router and side gateway modes, a **DNS queries** card also appears. It lists the domain names looked up by the networks this computer serves, **newest first**.

## AI usage

**AI usage** shows the AI gateway's requests, tokens and recent speed. At the top left, you can switch between **Day**, **Week**, **Month** and **Year**. Beside those buttons, select **All keys** or one key to view it alone.

![The AI usage area of the Dashboard page with no requests yet](/guide/en/hub_dashboard_05_ai.webp)

Under them are the **Token activity** and **Request health** grid charts. Before the AI gateway serves any request, both show **No requests yet**. To set up the gateway, see [AI gateway](/en/hub/ai_gateway).

## Notice at the top of the page

If traffic must go through an exit and every exit fails to connect, a notice appears under the title. A red notice means that both the traffic and LAN name lookups fail. A yellow notice means that the traffic uses this computer's own connection instead. To configure this behavior, see [Proxy](/en/hub/proxy).
