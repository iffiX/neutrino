---
title: Containers
---

# Containers

On a managed Linux machine, the **Containers** module runs the containers you declare as systemd units through podman. Each host port a container publishes becomes an entry on the clients' **Ports** page. From podman 4.4 a declaration becomes a Quadlet `.container` file; on an older podman the agent writes the `.service` unit itself.

To prepare the tab, select **Install** and then **Configure** on the **Containers** tab of the [Modules](../modules.md) page.

![The Containers tab with its declared containers](/guide/en/containers.webp)

## Declare a container

1. Under **Declared containers**, select **Add container**.
1. Fill **Name**.
1. Fill **Image tag**, or select **Pick a tag** to choose from the registry's tags.
1. Under **Ports**, map each host port to a container port, for example `8080:80`.
1. Under **Volumes**, map each host folder that keeps data to a path in the container, for example `/srv/share:/data`.
1. Optional: fill **Environment** with `KEY=value` lines, and **Command (optional)** to replace the image's command.
1. Optional: turn off **Start with the box** to keep the container stopped until you start it.
1. Select **Apply containers**. The first start pulls the image.

::: warning
Applying recreates every edited container, and files outside its volumes are lost.
:::

## Running now and mirrors

**Running now** lists every container on the machine, each with **Start**, **Stop**, **Restart**, **Journal** and **Shell**. **Shell** opens a shell inside the container in a window on the page.

Under **Registry mirrors**, select **Add mirror**, fill the address, then select **Apply mirrors**. Mirrors are tried in order before `docker.io`, from the next pull on.

The first **Configure** takes the containers and mirrors already on the machine as declarations. Each published host port is a row under **Ports** on the [Services](../../hub/services.md) page. A port published with `/udp`, such as `5353:5353/udp`, is an entry of its own.
