---
title: Dashboard
---

# Dashboard

The **Dashboard** is the page the panel opens after sign-in. It shows the box's traffic, its exit nodes, its DNS queries and the devices connected to it, as live readings.

![The Dashboard with its tiles and cards](/guide/en/dashboard.webp)

## Header

A red notice under the title appears when a proxy switch is on and every enabled exit node is unreachable. With **Let traffic out directly when no exit node answers** on, the notice is yellow instead.

## Tiles

| Tile            | Value                                         | Line under it                          |
| --------------- | --------------------------------------------- | -------------------------------------- |
| **Download**    | the uplink's receive rate                     | bytes received today                   |
| **Upload**      | the uplink's send rate                        | bytes sent today                       |
| **DNS queries** | queries in the last 2000 lines of the DNS log | **in the recent log**                  |
| **Proxy exits** | exit nodes with traffic in the last 2 minutes | the nodes measured, as **probed**      |
| **AI tokens**   | tokens the AI gateway served today            | **served today**                       |
| **Devices**     | managed machines connected now                | **agents reporting**                   |
| **CPU**         | processor load                                | a bar, yellow from 70 %, red from 90 % |
| **Memory**      | memory in use                                 | a bar, in the same colors              |
| **Uptime**      | time since the box booted                     | the uplink's address                   |

The uplink is the first interface in the WAN role, or in server and side gateway mode the interface of the default route.

## Live traffic

**Live traffic** charts the uplink's rate over the **last 2 min**, with **down** and **up** as two areas.

| Scope       | What the chart counts                     |
| ----------- | ----------------------------------------- |
| **All**     | every byte on the uplink                  |
| **Proxied** | the bytes sent to an exit node            |
| **Direct**  | the uplink's bytes minus the proxied ones |

## Traffic history

**Traffic history** shows the uplink's **received** and **sent** bytes as stacked bars, by **Day**, **Week**, **Month** or **Year**.

## Active exits

**Active exits** lists each exit node with traffic in the last two minutes, busiest first, with its latency and its bytes. A red dot marks a node whose last measurement failed. With no exit in use, the card reads **No exit is carrying traffic**.

## DNS queries

**DNS queries** lists the names the served networks look up, **newest first**. Each row shows the time, the name, the device's address and the tag of the resolver that answered:

| Tag      | Answered by                                                                                             |
| -------- | ------------------------------------------------------------------------------------------------------- |
| `cached` | dnsmasq's cache                                                                                         |
| `config` | dnsmasq's own records, such as `hub.neutrino.internal`                                                  |
| `direct` | the uplink's resolvers, or the direct resolvers of the [Proxy](./proxy.md) page when the fallback is on |
| `xray`   | xray, through the direct or the remote resolver                                                         |

A box in server mode serves no network, and the card reads **No DNS queries yet**.

## AI usage

**AI usage** shows the gateway's requests and tokens by **Day**, **Week**, **Month** or **Year**, for **All keys** or one key. [AI](./ai.md) covers the gateway and its keys.
