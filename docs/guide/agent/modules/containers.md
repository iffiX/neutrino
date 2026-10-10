---
title: Containers
---

# Containers

On a managed Linux machine, the **Containers** module runs the containers you declare as systemd units through podman. It is how a managed machine becomes a Docker host: podman runs Docker images from Docker Hub and other registries. Each host port a container publishes becomes an entry on the clients' **Ports** page. From podman 4.4 a declaration becomes a Quadlet `.container` file; on an older podman the agent writes the `.service` unit itself.

To prepare the tab, select **Install** and then **Configure** on the **Containers** tab of the [Modules](../modules.md) page.

![The Containers tab with its declared containers](/guide/en/containers.webp)

## Declare a container

1. Under **Declared containers**, select **Add container**.
1. Fill **Name** and **Image tag**.
1. Under **Ports**, add each port the clients open.
1. Under **Volumes**, add each folder whose files outlast the container.
1. Optional: fill **Environment** and **Command (optional)**.
1. Optional: turn off **Start with the box**.
1. Select **Apply containers**.

## Name and image tag

**Name** names both the container and its systemd unit. It holds lowercase letters, digits, `-` and `_`, and starts with a letter or a digit. It has at most 64 characters and is unique on the machine.

**Image tag** is the image to run, such as `redis:7`, with no spaces. An image named without a registry is pulled from `docker.io`. After you type the image, **Pick a tag** lists the tags the registry holds for it, and selecting one replaces the part after the colon. When the registry lists none, type the tag yourself, such as `:latest`.

## Ports

::: tip
Every host port declared on a container appears on the hub's **Services** page by itself, under **Ports** and titled with the container's name. **Connect** on a client's **Ports** page forwards it, and a `/udp` port is a UDP entry.
:::

Each line maps a port on the machine to a port in the container, as `host_port:container_port`, such as `8080:80`. Add `/udp` for a UDP port, such as `5353:5353/udp`; a line without it is TCP. Podman publishes the host port on every address of the machine.

Each host port becomes a row under **Ports** on the [Services](../../hub/services.md) page, titled with the container's name. **Connect** on a client's **Ports** page opens a port on the client's own `127.0.0.1`, relayed to the host port through the hub. The desktop client takes the same port number when it is free on that computer, and otherwise one from 20000 up. A UDP line is an entry of its own.

The row reads **serving** while the container runs and **not serving** while it is stopped. The agent connects a client to the port only while the container runs. A container started by hand at a shell, with a published port, gets a row as well.

## Volumes

Each line maps a source on the machine to an absolute path in the container, as `host_path:container_path`, such as `/srv/share:/data`. The source is an absolute folder on the machine, or the name of a podman volume, written like a container name. Files the container writes under that path stay on the machine; every other file it writes is lost when the container is recreated.

A folder of a [ZFS storage](zfs.md) dataset works as a source, such as `/tank/media:/media`.

## Environment and command

**Environment** holds one `KEY=value` line per variable. The key starts with a letter or `_` and holds letters, digits and `_`.

**Command (optional)** is one line that replaces the image's own command, such as `python3 -m http.server 8000`. Left empty, the container runs the image's command. A base image such as `debian` exits at once without a command that keeps running.

## Start with the box

With **Start with the box** on, the container starts when the machine boots and after each apply that changes it. With it off, the machine does not start it at boot, and a new container stays stopped until you select **Start** under **Running now**.

## What Apply does

**Apply containers** sends every declaration to the machine. The agent checks the fields first; when one is wrong, the apply is rejected with the field's name, and nothing on the machine changes. Otherwise the agent works through the declarations:

- A new or edited container gets its unit file written, and is restarted when it starts with the box or is running. Its first start pulls the image.
- A container whose declaration did not change keeps running untouched.
- A container removed from the list has its unit stopped and its unit file deleted. Its image and its podman volumes stay on the machine.

::: warning
Applying recreates every edited container, and files outside its volumes are lost.
:::

## Running now and mirrors

**Running now** lists every container on the machine, each with **Start**, **Stop**, **Restart**, **Journal** and **Shell**. **Shell** opens a shell inside the container in a window on the page.

Under **Registry mirrors**, select **Add mirror**, fill the address, then select **Apply mirrors**. Mirrors are tried in order before `docker.io`, from the next pull on.

The first **Configure** takes the containers and mirrors already on the machine as declarations.
