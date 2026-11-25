---
description: "Neutrino Hub answers the common questions about installing, reaching home from outside, apps, the AI gateway and sharing, grouped by topic."
---

# Frequently asked questions

The questions are grouped by topic, and each answer links to a page with the details.

## Differences from other tools

### How is it different from Claude's built-in remote access and agent aggregation tools

Claude's built-in remote access covers Claude alone. Neutrino Hub installs Claude Code, Codex and OpenCode, and harnesses such as CloudCLI and Codeg, on your own computer. One AI gateway holds the keys, and your phone opens them all. Claude's built-in remote access is a feature from Anthropic, and Neutrino Hub neither installs nor manages it.

### How is it different from 1Panel and BT Panel

1Panel and BT Panel manage websites and databases on Linux servers. Neutrino Hub manages the software you work with on your Windows, macOS or Linux computers. It also provides 6 access methods: NetBird, EasyTier, SSH relay, Direct, SakuraFrp and OpenFrp. For the full comparison, see [Comparison with other tools](/en/compare).

## AI tools

### How to use the AI gateway, and what it needs

Add an API key or a subscription account to the hub, and the AI tools on every computer can use it. The local Ollama models on your computers work too. [AI gateway](/en/hub/ai_gateway) has the steps.

### How soon do new AI tools arrive

Ask for a tool in [GitHub Issues](https://github.com/iffiX/neutrino/issues). A new tool usually lands in 3 to 5 days.

## Preparation

### What if downloads are slow in mainland China

Install the China edition, with the command on [Install the hub](/en/hub/install). Each app has several download sources, and the hub picks the fastest.

### Do you need to buy a server or a domain

You do not need to buy a server or a domain, because the hub installs on a computer you already have. On the same LAN as the hub, you need nothing else. Away from that LAN, turn on an access method, and some of them are free; see [Choose an access method](/en/access/ways_in).

### Does the computer have to stay on

The computer with the hub must stay on, and while it is off, phones and share links cannot connect. You can wake other systems on the same LAN from the panel; see [Agents](/en/hub/agents).

### Which phone systems are supported

The phone app supports Android 8.0 or later and iOS 16 or later. On an iPhone, you sign and install the app yourself; for the steps, see [iOS app](/en/access/ios).

### What do visitors need to install

Visitors install no software: they open the share link in a browser and use the app. See [App share](/en/share/web_share).

## Security and open source

### Is it secure, and is sign-up required

Neutrino Hub has no sign-up. You generate join links and share links in the panel, and only people who hold a link get access. Every connection goes through one hub port, and the content between devices and the hub is encrypted. For details, see [Security model](/en/share/security).

### Can Neutrino Hub see my data

Neutrino Hub runs no public server, and devices and visitors connect only to your own hub. The share site share.neutrinohub.net serves only static pages. For the outside addresses the hub connects to, see [Data and outbound connections](/en/hub/what_it_holds).

### Does it cost money, and what is the license

Neutrino Hub is open source and free. The hub, the agent and the desktop client use the MIT license, and the Android and iOS apps use the AGPL-3.0 license. Each provider sets the cost of its third-party routes.
