---
title: Containers
---

# Containers

The **Containers** module runs the containers you declare for one managed machine, from Docker images on Docker Hub and other registries. On Linux the machine's own Podman runs them as systemd units. On Windows and macOS they run inside a Podman machine, a Linux virtual machine that belongs to one account on the computer.

Each host port a container publishes becomes an entry that clients open on their **Web** or **Ports** page.

![The Containers tab with its declared containers](/guide/en/containers.webp)

## What each system needs

| System  | Requirements                                                                                                               | Podman                                                                          |
| ------- | -------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| Linux   | any system the agent installs on                                                                                           | the distribution's own package, 3.4 or newer, run the same way on every version |
| Windows | x86-64, Windows 10 version 2004 (build 19041) or newer, or Windows 11; virtualisation turned on in the computer's firmware | Podman 6 on WSL 2, both installed by the module                                 |
| macOS   | macOS 13 or newer                                                                                                          | Podman 6 on Apple silicon, Podman 5.8 on Intel, installed by the module         |

On an older system, the module picker greys **Containers** out. On Windows, the first install turns on WSL's two Windows features when they are off, and Windows then needs one restart.

## Install the module

Before you start, the machine's agent must be online. On Windows, the account that runs the containers must have its login under **Logins** on the [Credentials](../../hub/credentials.md) page.

1. On the [Modules](../modules.md) page, pick the machine and select the **Containers** tab.
1. Select **Install**.
1. If the tab shows **Windows needs a restart to finish turning on WSL; the install goes on after it.**, select **Restart now**, then **Restart** in the confirmation. Every program open on the computer closes, and the install resumes after the restart.
1. Select **Configure**.
1. On Windows or macOS, fill **Run settings**, as the next section describes.
1. On Windows or macOS, select **Apply run settings**.

On Windows and macOS, **Running now**, **Registry mirrors** and **Declared containers** read **Choose an account under Run settings first.** until the Run settings are applied.

The first **Configure** takes the containers and mirrors already on the machine as declarations, so the first apply changes nothing. After a reinstall on Windows or macOS, it also takes the account of the Podman machine the agent finds.

## Run settings

On Windows and macOS, **Run settings** choose whose Podman machine runs the containers, and how large it is. A Linux machine has no such section.

| Field                             | What it sets                                                                                         |
| --------------------------------- | ---------------------------------------------------------------------------------------------------- |
| **Account**                       | the account on the computer whose Podman machine runs the containers                                 |
| **Windows login for** the account | on Windows, the login that starts the Podman machine at boot                                         |
| **CPUs**                          | the processors the Podman machine uses                                                               |
| **Memory (GiB)**                  | the memory the Podman machine uses                                                                   |
| **Disk limit (GiB)**              | the size of the Podman machine's disk, which only grows; the hint under the field gives its size now |

A 0 keeps Podman's default: half the computer's processors, 2 GiB of memory and, on macOS, a 100 GiB disk. On Windows, **Disk limit (GiB)** starts at 100 and takes 1 or more. The first apply creates the account's default Podman machine, which takes about a minute. When the account already has one, the agent uses it, and `podman ps` run as that account lists the same containers.

The computer starts the Podman machine at boot, before anyone signs in, and the container ports answer about 30 seconds later. After you choose another account, the declared containers run in that account's Podman machine. The old account's machine stops, and its images and named volumes stay in that account's profile.

::: warning
On Windows, **CPUs** and **Memory (GiB)** are written to the account's `.wslconfig` file, and every WSL system of that account uses them. A change of CPUs, memory or disk restarts all those WSL systems, and the apply that creates the Podman machine stops them too. The file's other lines stay as they are.
:::

On macOS, a change restarts the Podman machine alone, and its containers stop for a moment.

## Declare a container

1. Under **Declared containers**, select **Add container**.
1. Fill **Name** and **Image tag**.
1. Under **Ports**, add each port the clients open.
1. Optional: under **Services**, choose how each port is published.
1. Under **Volumes**, add each folder whose files outlast the container.
1. Optional: fill **Environment** and **Command (optional)**.
1. Optional: turn off **Start with the box**.
1. Select **Apply containers**.

Each list takes one line at a time: type the line, then select **Add**.

## Name and image tag

**Name** names both the container and its systemd unit. It holds lowercase letters, digits, `-` and `_`, and starts with a letter or a digit. It has at most 64 characters and is unique on the machine.

**Image tag** is the image to run, such as `redis:7`, with no spaces. An image named without a registry comes from `docker.io`. After you type the image, **Pick a tag** lists the 25 tags Docker Hub updated last for it. Selecting one replaces the part after the colon. An image outside Docker Hub lists none, so type its tag yourself, such as `:latest`.

## Ports

Each line maps a port on the machine to a port in the container, as `host_port:container_port`, such as `8080:80`. Add `/udp` for a UDP port, such as `5353:5353/udp`; a line without it is TCP.

| System  | Where the host port answers                                    |
| ------- | -------------------------------------------------------------- |
| Linux   | every address of the machine                                   |
| Windows | the computer's own `127.0.0.1` alone, on TCP alone             |
| macOS   | the computer's own `127.0.0.1`, through Podman's own forwarder |

The agent connects every client to the port on the machine itself, so a client reaches it on every system. Another machine on the LAN reaches a Windows container's port only through a client. On Windows, an apply rejects a UDP port, because WSL forwards TCP alone.

Each host port becomes an entry on the hub's [Services](../../hub/services.md) page, titled with the container's name. The entry reads **serving** while the container runs and **not serving** while it is stopped. A container started by hand at a shell, with a published port, gets an entry as well.

## The Services row

Under **Services**, each host port of the container has a row that offers **Auto**, **Web** or **Port**.

| Choice                                  | What the machine publishes               | Where clients show it                                                                     |
| --------------------------------------- | ---------------------------------------- | ----------------------------------------------------------------------------------------- |
| **Auto**, the default                   | the port as its **Ports** line writes it | on the **Web** page when the agent detects http or https, otherwise on the **Ports** page |
| **Web**, with **http** or **https**     | the port on TCP                          | on the **Web** page, on computers and phones                                              |
| **Port**, with **TCP**, **UDP** or both | the port on each checked protocol        | on the **Ports** page of the desktop client, one entry per protocol                       |

With **Auto**, the agent checks each published TCP port once after every start of the container. A service that sends first, such as SSH or a database, is TCP. A service that answers an HTTP request is http, and one that answers it over TLS is https. A port that is not open yet is checked again a few seconds later. The row reads **Auto: http detected**, for example, and **Auto: detected after the container starts** until the check.

Checking **UDP** under **Port** publishes the port on UDP as well, the same as a `/udp` line under **Ports**. The **Ports** page is in the desktop client alone, so a port entry appears on computers.

## Volumes

Each line maps a source on the machine to an absolute path in the container, as `host_path:container_path`. The source is a folder, in the system's own form, or the name of a Podman volume, written like a container name.

| System  | Example                | Folders a container can use                                     |
| ------- | ---------------------- | --------------------------------------------------------------- |
| Linux   | `/srv/share:/data`     | any absolute folder of the machine                              |
| Windows | `C:\data:/data`        | a folder on a fixed drive of the computer, such as `C:` or `D:` |
| macOS   | `/Users/me/data:/data` | a folder under `/Users`, `/private` or `/var/folders`           |

On Windows and macOS, an apply rejects any other folder, such as a network share.

**Browse…** beside **Add** opens the machine's folders. Open a folder and select **Choose this folder**, and the line starts with that folder and a colon. Type the path in the container after the colon, then select **Add**.

Files the container writes under that path stay on the machine; every other file it writes is lost when the container is recreated. On Windows and macOS a named volume is on the Podman machine's disk.

## Environment and command

**Environment** holds one `KEY=value` line per variable. The key starts with a letter or `_` and holds letters, digits and `_`.

**Command (optional)** is one line that replaces the image's own command, such as `python3 -m http.server 8000`. Left empty, the container runs the image's command. A base image such as `debian` exits at once without a command that keeps running.

## Start with the box

With **Start with the box** on, the container starts when the machine boots and after each apply that changes it. With it off, the machine leaves it stopped at boot, and a new container stays stopped until you select **Start** under **Running now**.

## What Apply does

**Apply containers** sends every declaration to the machine. The agent checks the fields first. When one is wrong, the agent rejects the whole apply with the field's name, and nothing on the machine changes. Otherwise the agent works through the declarations:

- A new or edited container gets its unit file written, and restarts when it starts with the box or is running. Its first start pulls the image.
- A container whose declaration did not change keeps running untouched.
- A container removed from the list has its unit stopped and its unit file deleted. Its image and its Podman volumes stay on the machine.

::: warning
Applying recreates every edited container, and files outside its volumes are lost.
:::

When the tab shows a code, its cause and fix are under [Containers](../../reference/troubleshooting.md#containers) on the troubleshooting page.

## Running now and mirrors

**Running now** lists every container on the machine with its image and its status, and ends each row with where the container comes from: **hub** for one a module of the hub runs, **declared** for one you declared, and **manual** for one started by hand. A running container has **Journal**, **Shell**, **Restart** and **Stop**, and a stopped one has **Journal** and **Start**. A container a module runs shows the module's name and has **Journal** alone.

**Hub containers** lists the containers the hub's modules run on the machine, with their images, ports and volumes. Each one is changed in its module's tab.

**Shell** opens a terminal inside the container, in a window on the page, on every system. It runs bash when the image has it, and sh otherwise. **Close**, or `exit` typed in it, ends the shell and every program it started in the container.

Under **Registry mirrors**, select **Add mirror**, fill the address, then select **Apply mirrors**. Podman tries the mirrors in order before `docker.io`, from the next pull on.

## Uninstall

**Uninstall** on the tab stops every declared container and removes Podman. While a module that runs on Containers is installed, uninstall that module first. The containers' data stays on the computer, and the hub keeps the declarations.

| System  | Removed                                                            | Kept                                                                                                                                                  |
| ------- | ------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| Linux   | the declared containers' units, the mirror file, Podman's packages | images, volumes, and containers started by hand                                                                                                       |
| Windows | the declared containers, Podman                                    | the Podman machine with its disk, images, named volumes and containers started by hand; WSL, its two Windows features, and the account's `.wslconfig` |
| macOS   | the declared containers, Podman                                    | the Podman machine with its disk, images, named volumes and containers started by hand                                                                |

On Windows and macOS, the Podman machine stops and stays in the account's profile, and nothing starts it at boot. After a new install, the agent finds that machine again, and the next apply brings back the declared containers with their volumes.
