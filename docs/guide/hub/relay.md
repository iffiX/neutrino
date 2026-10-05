---
title: SSH Relay
---

# Reach the hub through your own server

With the SSH Relay on, clients and agents outside your network connect to a public port on a server you rent or own, and that server forwards each connection to the hub. The hub opens the forward itself over SSH, so the server needs only an SSH account, which the hub signs in to with an SSH key or a password.

The connection stays encrypted from the client to the hub, and the client checks the hub's certificate as it does on the LAN. The server forwards bytes it cannot read.

Before you start, you need:

- A server with a public address that runs OpenSSH, where you can edit the SSH configuration as root.
- An SSH key pair for the hub, such as one made with `ssh-keygen -t ed25519 -N '' -f relay_key`. The private key `relay_key` goes on the **Credentials** page, and the public key `relay_key.pub` goes on the server. Or a password for the account instead: it goes on the **Credentials** page as a login. A key is the safer choice, because the server can then limit it to the one listener.
- Your provider's terms on forwarding traffic. Read them before you open the port: some providers limit or forbid it.

## Set up the server

These steps run on the server, as root. The example account is `relay` and the example public port is `8443`. If you pick another port, use it in every step.

1. Create the account the hub logs in as:

   ```bash
   useradd --create-home --shell /usr/sbin/nologin relay
   ```

1. With a key, put the hub's public key in that account's `authorized_keys`, behind the options that limit it to one listener. Replace `<public-key>` with the line from the public key file:

   ```bash
   mkdir -p /home/relay/.ssh
   echo 'restrict,port-forwarding,permitlisten="8443" <public-key>' >> /home/relay/.ssh/authorized_keys
   chown -R relay:relay /home/relay/.ssh
   chmod 700 /home/relay/.ssh
   chmod 600 /home/relay/.ssh/authorized_keys
   ```

1. With a password instead, give the account one, and let that account alone sign in with a password:

   ```bash
   passwd relay
   printf 'Match User relay\n    PasswordAuthentication yes\n' > /etc/ssh/sshd_config.d/20-neutrino-relay-password.conf
   ```

1. Let forwarded ports listen on the public address, then restart the SSH server. The setting applies to the whole server:

   ```bash
   echo 'GatewayPorts clientspecified' > /etc/ssh/sshd_config.d/10-neutrino-relay.conf
   systemctl restart ssh
   ```

1. Open TCP port `8443` in your provider's console, and in any firewall running on the server. The hub must also reach the server's SSH port, 22 by default.

On Fedora, RHEL and Arch the SSH service is `sshd`, so the restart is `systemctl restart sshd`.

## Connect the hub

1. On the **Credentials** page, under **SSH keys**, select **Add key** and paste the private key. With a password, add it under **Logins** instead.
1. On the **Access** page, turn on the **SSH Relay** card's switch, then select **Apply overlays**. The card's section appears under the cards, its status **Not configured**.
1. Under **Settings**, fill in **Server**, **SSH port**, **Account** and **Public port**. Under **Credential**, choose **SSH key** and pick the key, or **Password** and pick the login.
1. Select **Apply SSH Relay**. This stores the settings and starts the relay.

**Status** reads **Connecting**, then **Connected** within a minute. **Address for clients** shows `https://<server>:<public-port>`, built from the **Server** and **Public port** you entered. Every client link and every agent's address list now has it as the last address. **Host key** shows the server's key as SSH recorded it on the first connection.

## Read the status

The hub dials the public address itself five seconds after the forward starts and every minute after that. Only its own certificate at that address counts as **Connected**. Under the state, the panel shows the last line SSH wrote, or why the check failed.

| Status                    | Cause                                                                                                   | Fix                                                                                                                                      |
| ------------------------- | ------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| **Connecting**            | The forward started and the first check has not run yet.                                                | Wait a minute.                                                                                                                           |
| **Not configured**        | **Server**, **Account** or the key or login is empty, or it is gone from **Credentials**.               | Fill in the settings and select **Apply SSH Relay**.                                                                                     |
| **Vault locked**          | The box has no working copy of the vault's data key, so the hub cannot open the stored key or password. | Restore the working copy, as [the vault](./credentials.md#the-vault) describes.                                                          |
| **Authentication failed** | The server rejected the key or the password.                                                            | Check the public key line in the account's `authorized_keys`, or the password and the server's `PasswordAuthentication` for the account. |
| **Forward refused**       | The server refused the listener, or another program already holds the port.                             | Check that the port in `permitlisten` is the **Public port**, and free the port on the server.                                           |
| **Public port closed**    | The forward runs, and the public address returns no answer or another certificate.                      | Check `GatewayPorts clientspecified` and the provider's firewall.                                                                        |
| **Host key changed**      | The server presents a key other than the one recorded.                                                  | If you replaced or reinstalled the server, select **Forget host key**.                                                                   |
| **Server unreachable**    | SSH could not reach the server, or the connection dropped.                                              | Check **Server** and **SSH port**, and that the server is up.                                                                            |

## Move to another server

Applying a different **Server** or **SSH port** deletes the recorded host key, and the next connection records the new server's key. After a reinstall at the same address, set up the server again, then select **Forget host key** beside **Host key** and confirm with **Forget**. The hub connects again at once.

Clients connected through the SSH Relay disconnect when you apply new settings, and connect again on their own.
