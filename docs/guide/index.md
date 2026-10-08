---
layout: home
title: Neutrino
markdownStyles: false
hero:
  name: Neutrino
  text: The services on one computer, on your phone and laptop anywhere
  tagline: Your computer at home. Scan once, use it from anywhere.
  image:
    src: /guide/en/app_terminal.webp
    alt: A terminal on the computer at home, open in the Android app
  actions:
    - theme: brand
      text: First step
      link: /quick-start
    - theme: alt
      text: Overview
      link: /overview
first_time:
  - title: First step
    details: Install Neutrino, join your phone and laptop, and reach the computer from outside.
    link: /quick-start
  - title: AI session
    details: Pick up a Claude Code session from the computer on your phone.
    link: /quick-start/cloudcli
  - title: Editor
    details: Open the computer's projects in VS Code, in a browser on any device.
    link: /quick-start/vscode
  - title: Terminal
    details: Start a shell on the laptop and keep using it from the phone.
    link: /quick-start/terminal
  - title: Remote desktop
    details: See and use the computer's screen from the phone or the laptop.
    link: /quick-start/remote_desktop
  - title: Files
    details: Mount a folder of the computer on the laptop, and open it on the phone.
    link: /quick-start/files
going_further:
  - title: Choose a way in
    details: Direct, SSH Relay, NetBird or EasyTier, and what each one needs.
    link: /scenarios/choose_a_way_in
  - title: One laptop, every machine
    details: Add agents to your other machines and use them all from one client.
    link: /scenarios/one_laptop_every_machine
  - title: Your own VPS
    details: Reach home through a public port on a server you rent.
    link: /scenarios/vps_relay
  - title: Router or side gateway
    details: Let a Linux hub forward traffic for the devices at home.
    link: /scenarios/router_or_gateway
  - title: Devices without an agent
    details: Reach a printer or a NAS at home over NetBird or EasyTier.
    link: /scenarios/netbird_lan_routes
reference:
  - title: Hub
    details: Every page of the panel, from the dashboard to the settings.
    link: /hub/dashboard
  - title: Managed machines
    details: Terminals, files and each module an agent installs.
    link: /agent/terminals
  - title: Clients
    details: The desktop client and the Android app, page by page.
    link: /client/desktop
  - title: Commands
    details: Every subcommand of nhub, nagent and nclient.
    link: /commands/nhub
  - title: Reference
    details: Supported platforms, troubleshooting, the channel and the glossary.
    link: /reference/platforms
---

<div class="home-lead">

Neutrino installs on the computer at home, and your phone and laptop join it with a scanned code or a pasted link. They reach it over the home network, and from outside over a way in you choose. On either device you open the computer's terminal, AI sessions, editor, desktop and files.

</div>

<HomeGroups title="First time" :items="$frontmatter.first_time" />

<HomeGroups title="Going further" :items="$frontmatter.going_further" />

<HomeGroups title="Reference" :items="$frontmatter.reference" />
