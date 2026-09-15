---
title: Containers
---

# Containers

Containers run on a managed machine as systemd units through podman, from declarations written under the **Containers** tab of [the Modules page](./modules.md). Each host port a container publishes becomes an entry in the client windows. The tab's **Declared containers**, **Running now** and **Registry mirrors** sections open after **Configure**, and the first **Configure** takes the containers already on the machine as declarations, together with its registry mirrors.

From podman 4.4 a declaration becomes a Quadlet `.container` file that podman turns into a systemd unit. On an older podman, the 4.3 that Debian 12 packages for example, the agent writes the `.service` unit itself and the declaration means the same thing.

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
