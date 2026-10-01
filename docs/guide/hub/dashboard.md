---
title: Dashboard
---

# Dashboard

The **Dashboard** is the panel's first page after sign-in: live readings of the box's traffic, its exits, its DNS and the devices reporting to it. The live chart and the tiles read one stream the hub sends every second, and each card reports its own error when its source fails.

![The Dashboard with its tiles and cards](/guide/en/dashboard.webp)

## Header

The dot beside the title states the live stream: **streaming**, **connecting**, or **stats socket offline**. A red notice under the title appears when a proxy switch is on and every enabled exit node is unreachable. With **Let traffic out directly when no exit node answers** on, the notice is yellow and says that proxied traffic leaves through the WAN instead.

## Tiles

| Tile            | Value                                                                           | Line under it                                  |
| --------------- | ------------------------------------------------------------------------------- | ---------------------------------------------- |
| **Download**    | the uplink's receive rate now                                                   | the bytes received today, from vnstat          |
| **Upload**      | the uplink's send rate now                                                      | the bytes sent today                           |
| **DNS queries** | the queries among the last 2000 lines of dnsmasq's journal                      | **in the recent log**                          |
| **Proxy exits** | the exit nodes that moved traffic in the last two minutes                       | how many nodes the hub measures, as **probed** |
| **AI tokens**   | the tokens the AI gateway served today; a dash when the gateway reports nothing | **served today**                               |
| **Devices**     | the managed machines connected to the hub now                                   | **agents reporting**                           |
| **CPU**         | the box's processor load                                                        | a bar, yellow from 70 % and red from 90 %      |
| **Memory**      | the box's memory in use                                                         | a bar, with the same colours                   |
| **Uptime**      | the time since the box booted                                                   | the uplink's address, or **no WAN address**    |

The uplink is the first interface in the WAN role. In server and side gateway mode, it is the interface the default route uses.

## Live traffic

**Live traffic** charts the uplink's rate over the **last 2 min**, with **down** and **up** as two areas and their current values in the legend.

| Scope       | What the chart counts                     |
| ----------- | ----------------------------------------- |
| **All**     | every byte on the uplink                  |
| **Proxied** | the bytes xray handed to an exit node     |
| **Direct**  | the uplink's bytes minus the proxied ones |

Direct includes traffic that never enters xray, such as an overlay engine's own packets. Before two readings arrive, the card reads **Waiting for the first stats frames**.

## Traffic history

**Traffic history** shows the uplink's **received** and **sent** bytes from vnstat as stacked bars, by **Day**, **Week**, **Month** or **Year**; **Month** is the first one shown. A new box reads **No history yet** until vnstat has a day of samples.

## Active exits

**Active exits** lists each exit node that moved bytes in the last two minutes, busiest first. A row shows the node's name, its last measured latency, and its bytes in that window as **/ 2 min**. A red dot marks a node whose last measurement failed. With no exit carrying traffic, the card reads **No exit is carrying traffic**: the served networks are idle, or every request matches a direct rule.

## DNS queries

**DNS queries** lists the names the served networks resolve, **newest first**, and the badge counts the rows held as **held**. Each row shows the time, the name, the asking device's address, and the resolver that answered:

| Tag      | Answered by                                                |
| -------- | ---------------------------------------------------------- |
| `cached` | dnsmasq's cache                                            |
| `config` | dnsmasq's own records, such as `hub.neutrino.internal`     |
| `direct` | the direct resolver of the [Proxy](./proxy.md) page        |
| `xray`   | xray, which picks the direct or the remote resolver itself |

A row still waiting for its answer shows **pending**. A server-mode box serves no network, so the card reads **No DNS queries yet**.

## AI usage

**AI usage** shows the gateway's requests and tokens by **Day**, **Week**, **Month** or **Year**, for **All keys** or one key. Its tiles are **Requests**, **Tokens**, **RPM**, **TPM**, **Cache rate** and **Daily average**, followed by **Token activity** and **Request health** grids. [AI](./ai.md) covers the gateway and its keys.
