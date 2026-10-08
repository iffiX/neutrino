---
title: SSH Relay
---

# Reach the hub through your own server

With the SSH Relay running, clients and agents outside your network connect to a public port on a server you rent or own. That server forwards each connection to the hub's agent port, 8443. The hub opens the forward itself, as a reverse SSH forward, and signs in to the server with an SSH key or a password. The connection stays encrypted from the client to the hub, so the server forwards bytes it cannot read.

At the end, the relay's **Status** reads **Connected**, and every client holds the relay's address.

Before you start, you need:

- A server with a public address that runs OpenSSH, where you have root to edit the SSH configuration.
- An SSH key pair for the hub, such as one made with `ssh-keygen -t ed25519 -N '' -f relay_key`, or a password for the account. A key is the safer choice, because the server can then limit it to the one listener.
- Your provider's terms on forwarding traffic. Some providers limit or forbid it, so read them before you open the port.

## Set up the server

These steps run on the server, as root. The example account is `relay` and the example public port is `8443`. If you pick another public port, use it in every step; the hub's own agent port stays 8443.

1. Create the account the hub signs in as:

   ```bash
   useradd --create-home --shell /usr/sbin/nologin relay
   ```

1. With a key, add the hub's public key to the account's `authorized_keys`, behind the options that limit it to one listener. Replace `<public-key>` with the line from `relay_key.pub`:

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

1. Open TCP port `8443` in your provider's console and in any firewall on the server. The hub must also reach the server's SSH port, 22 by default.

On Fedora, RHEL and Arch the SSH service is `sshd`, so the restart is `systemctl restart sshd`.

## Connect the hub

1. On the **Credentials** page, under **SSH keys**, select **Add key** and paste the private key `relay_key`. With a password, add it under **Logins** instead.
1. On the **Access** page, turn on **Enable** on the **SSH Relay** card.
1. Select **Apply access**. The **SSH Relay** section appears under the cards, its status **Not configured**.
1. Under **Settings**, fill **Server**, **SSH port**, **Account** and **Public port**.
1. Under **Credential**, choose **SSH key** and pick the key, or **Password** and pick the login.
1. Select **Apply SSH Relay**.

**Status** reads **Connecting**, then **Connected** within a minute. **Address for clients** shows `https://<server>:<public-port>`, built from the **Server** and **Public port** you entered. Every new client link, every joined client's next state from the hub, and every agent's address list hold it as the last address. **Host key** shows the server's key as SSH recorded it on the first connection.

## Read the status

Five seconds after the forward starts, and every minute after that, the hub dials the public address itself. It reads **Connected** only when it finds its own certificate there. Under the status, the section shows the last line SSH wrote, or why the check failed.

| Status                    | Cause                                                                                         | Fix                                                                                                    |
| ------------------------- | --------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| **Connecting**            | The forward started and the first check has not finished.                                     | Read the status again after a minute.                                                                  |
| **Not configured**        | **Server**, **Account** or the key or login is empty, or the key or login is gone.            | Fill in the settings and select **Apply SSH Relay**.                                                   |
| **Vault locked**          | The box has no working copy of the vault's data key, so the hub cannot open the key or login. | Restore the working copy of the data key.                                                              |
| **Authentication failed** | The server rejected the key or the password.                                                  | Check the key's line in the account's `authorized_keys`, or the password and `PasswordAuthentication`. |
| **Forward refused**       | The server refused the listener, or another program holds the port.                           | Check that `permitlisten` names the **Public port**, and free the port on the server.                  |
| **Public port closed**    | The forward runs, and the public address returns no answer or another certificate.            | Check `GatewayPorts clientspecified`, the provider's firewall and the server's firewall.               |
| **Host key changed**      | The server presents a key other than the one recorded.                                        | If you replaced or reinstalled the server, select **Forget host key**.                                 |
| **Server unreachable**    | SSH could not reach the server, or the connection dropped.                                    | Check **Server** and **SSH port**, and that the server is up.                                          |

## Move to another server

Applying a different **Server** or **SSH port** deletes the recorded host key, and the next connection records the new server's key. After a reinstall at the same address, set up the server again, then select **Forget host key** beside **Host key** and confirm with **Forget**. The hub connects again at once.

Applying new settings disconnects the clients connected through the SSH Relay, and each one connects again on its own.
