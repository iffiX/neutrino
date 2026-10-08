---
title: SSH Relay
---

# SSH Relay

The SSH Relay opens a public port on a server you rent or own. The server forwards each connection on that port to the hub's port 8443. Clients and agents outside your network then reach the hub at that server's address.

This page describes the relay's settings and status. The steps that set up the server are in [Reach the hub through your own VPS](../scenarios/vps_relay.md).

## Settings

After you turn on the **SSH Relay** card and select **Apply access** on the **Access** page, the **SSH Relay** section appears under the cards.

| Field           | What it holds                                                                     |
| --------------- | --------------------------------------------------------------------------------- |
| **Server**      | the server's host name or address                                                 |
| **SSH port**    | the server's SSH port, 22 by default                                              |
| **Account**     | the account the hub signs in as                                                   |
| **Public port** | the port on the server that clients connect to                                    |
| **Credential**  | **SSH key** or **Password**, picked from the [Credentials](./credentials.md) page |

**Apply SSH Relay** saves the settings and connects. **Address for clients** then shows `https://<server>:<public-port>`, built from **Server** and **Public port**. New client links, joined clients and agents receive it as the hub's last address. **Host key** shows the server's key as SSH recorded it on the first connection.

## Read the status

The hub checks the public address five seconds after the forward starts and every minute after that. **Status** reads **Connected** only when the hub finds its own certificate at that address. Under the status, the section shows the last line SSH wrote, or the reason the check failed.

| Status                    | Meaning                                                                          |
| ------------------------- | -------------------------------------------------------------------------------- |
| **Connecting**            | The forward started and the first check is still running.                        |
| **Connected**             | The public address returns the hub's certificate.                                |
| **Not configured**        | **Server**, **Account**, or the key or login is empty or deleted.                |
| **Vault locked**          | The hub cannot open the stored key or login.                                     |
| **Authentication failed** | The server rejected the key or the password.                                     |
| **Forward refused**       | The server refused the listener, or another program holds the port.              |
| **Public port closed**    | The forward runs, and the public address returns nothing or another certificate. |
| **Host key changed**      | The server presents a key other than the one recorded.                           |
| **Server unreachable**    | SSH cannot reach the server, or the connection dropped.                          |

What to do for each status is on [Troubleshooting](../reference/troubleshooting.md#access).

## Move to another server

Applying a different **Server** or **SSH port** deletes the recorded host key, and the next connection records the new server's key. After a reinstall at the same address, set up the server again, then select **Forget host key** beside **Host key** and confirm with **Forget**.

Applying new settings disconnects the clients connected through the SSH Relay, and each one connects again on its own.
