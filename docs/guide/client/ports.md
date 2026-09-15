---
title: Ports
---

# Ports

The **Ports** panel in a hub's group relays a port that hub publishes to this computer's loopback address, where any program on the machine reaches it.

## Where the entries come from

An entry in a **Ports** panel is a port the hub of its group published. It is a host port a container publishes on a managed machine, or a TCP port declared by hand on the hub's **Services** page. The line under the entry says which, and each hub publishes into its own group.

## Connect

1. In the **Ports** panel, select **Connect** on the entry.

The row reads `127.0.0.1:` followed by the local port, and the button reads **Disconnect**. The local port is the entry's own port when that port is free. When the port is taken, by a program of yours or by a relay to another hub, the client binds any free port instead.

![The Ports panel forwarding a port](/guide/en/client_port_forwarding.webp)

From a terminal, `nclient service port forward <ref>` opens the same relay and `--local-port <port>` chooses the local port. The hub goes in `--hub`, optional with one hub joined, and `<ref>` is the entry's number under that hub in `nclient service list`, or its id.

## Disconnect

**Disconnect** closes the relay, as does `nclient service port unforward <ref>`. Leaving a hub closes every relay it published. While a relay is open, every program on the computer can reach it, because the relay listens on the loopback address of the whole machine.
