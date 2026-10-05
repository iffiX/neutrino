---
title: Containers
---

# Containers

The **Containers** module runs the containers you declare on a managed Linux machine as systemd units through podman. Each host port a container publishes becomes an entry in the clients. From podman 4.4 a declaration becomes a Quadlet `.container` file. On an older podman, such as the 4.3 that Debian 12 packages, the agent writes the `.service` unit itself, and the declaration means the same.

Before you start, select **Install** and then **Configure** on the **Containers** tab of the [Modules](../modules.md) page. The **Running now**, **Registry mirrors** and **Declared containers** sections open under the tab.

![The Containers tab with its declared containers](/guide/en/containers.webp)

## Declare a container

1. Under **Declared containers**, select **Add container**.
1. Fill **Name**.
1. Fill **Image tag**, or select **Pick a tag** to choose from the tags the registry lists.
1. Under **Ports**, map each host port to a container port, for example `8080:80`.
1. Under **Volumes**, map each host folder that keeps data to a path in the container, for example `/srv/share:/data`.
1. Optional: fill **Environment** with `KEY=value` lines, and **Command (optional)** when the image's own command is not the one you want.
1. Optional: turn off **Start with the box** to keep the container declared but stopped until you start it.
1. Select **Apply containers**. A container's first start pulls its image, which can take a while.

Each container becomes a systemd unit on podman's default network. A base image needs a command that keeps running.

::: warning
Applying recreates every edited container, and files outside its volumes are lost.
:::

## Running now

**Running now** lists every container on the machine with its state. Each row has **Start**, **Stop**, **Restart**, **Journal** and **Shell**. **Journal** shows the container's log, and **Shell** opens a shell inside the container in a window on the page.

## Registry mirrors

Mirrors are tried in order before `docker.io`. Select **Add mirror**, fill the address, then select **Apply mirrors**. The change takes effect on the next pull, and nothing restarts.

## Containers already on the machine

The first **Configure** takes the containers already on the machine as declarations, with their images, ports, volumes and environment, and takes the registry mirrors too. From then on, the declarations on this tab are the only truth for that machine.

## Where it is published

Each host port a container publishes is a row under **Ports** on the [Services](../../hub/services.md) page, described as published by that container's image. In the [Desktop client](../../client/desktop.md), it is an entry in the **Ports** panel with **Connect**. A port published with `/udp`, such as `5353:5353/udp`, is an entry of its own, and its address reads `host:port/udp`.
