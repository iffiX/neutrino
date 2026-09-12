---
title: Containers
---

# Containers

Containers run on a managed machine as systemd units through podman, from declarations written on the **Containers** page. Each host port a container publishes becomes an entry in the client windows. The page enables the module on a machine, then shows that machine's **Declared containers**, **Running now** and **Registry mirrors**.

## Enable a device

1. In the panel, open **Containers** under **Agent**.
1. Under **Enabled devices**, tick the machine and select **Apply devices**. A consent dialog names what is installed; confirm it.

![The Containers page with a declared container running](/guide/en/containers.webp)

The module runs containers through Quadlet, the podman feature that turns a container declaration into a systemd unit; it needs podman 4.4 or newer. Debian 12 packages 4.3, so the hub rejects a Debian 12 machine as unable to run the module. Debian 13, Ubuntu 24.04, Fedora 41 and the RHEL 9 family qualify.

## Declare a container

1. Under **Declared containers**, add a container.
1. Fill the **Image tag**, the **Ports** it publishes on the host, and the **Volumes** it keeps data in; the command is the image's own unless you set one.
1. Select **Apply containers**. The container's first start pulls the image, and the pull can take a while.

Each container becomes a systemd unit on the default network. **Start with the box** is on by default. With it off, the container stays declared and starts only from **Start** under **Running now**.

::: warning
An edited container is recreated on apply, and files outside its volumes are lost.
:::

## Running now

**Running now** lists the containers on the machine with their state. Each row has **Journal**, the container's log, and a shell inside the container.

## Registry mirrors

**Registry mirrors** are tried in order before `docker.io`. **Apply mirrors** takes effect on the next pull, and nothing restarts.

## Where it is published

[The Services page](./services.md) lists a published host port under **Ports**, described as published by that container's image. Each client window shows it in the **Ports** panel with a **Connect** button.
