---
title: Upgrade and reset
---

# Upgrade and reset

The hub, the agent and the client carry one version number and are released
together. Upgrading means replacing all three, in one order, and a reset takes
the box back to the day before its first setup.

Six things to settle first:

- There are no migrations. `config/` may change shape between versions, and
  nothing translates an old one.
- Upgrade order is the hub, then the agents, then the clients. A client ahead
  of the hub unbinds itself.
- `sudo nhub reset all` is not a mode switch. It throws away every key and
  token the box collected.
- A reset takes no address off anything, so the session that asked for it is
  not dropped.
- `/etc/neutrino/agent` survives a hub reset, because it belongs to the agent
  package.
- Nothing here upgrades 0.1.0 in place. Take a backup, reset, and set the box
  up again.

## One version

- The three packages are released together and carry the same number.
- A version that does not match is asked to upgrade, never negotiated with.
- A client that is ahead refuses with "this client ({client_version}) is newer
  than the hub ({hub_version}); update the hub first", and unbinds itself with
  "{cause}; rejoin by pasting a fresh link from the hub".
- A mismatched agent reads "This agent is a different version from the hub."
  with "Reinstall it with the Reinstall agent action below.", or, with no SSH
  credential stored, "Re-enroll it with a fresh link. The SSH installer needs
  Linux."

Open **Settings** and read About.

Expect: Panel version, This machine, Kernel, Uptime, Geodata and Carried
software, each carried binary with a source link.

![The Settings page's About section with the panel version and carried software](/guide/en/settings_about.webp)

Open **Clients** and read the Version column.

Expect: one row per client, its version beside its status and its last seen.

![The Clients page with laptop and office-pc, their platforms and versions](/guide/en/clients_table.webp)

## Upgrade order

**1.** On the hub box:

```bash
sudo apt install ./neutrino-hub_0.2.0_amd64.deb
```

Expect: the panel restarts on the new version, and Settings, About shows it.

**2.** For each agent, open the device drawer in the panel and press "Reinstall
agent".

Expect: the install output streams, and the drawer's version warning clears.

Where no SSH credential is stored for that machine, mint a fresh link with "Add
by link" and run it there:

```bash
sudo nagent connect 'neutrino://enroll/PLACEHOLDER_LINK'
```

**3.** For each client:

```bash
sudo apt install ./neutrino-client_0.2.0_amd64.deb
```

Expect: the client window reconnects by itself. On Windows, run the new msi
instead.

::: warning
A client upgraded ahead of its hub unbinds itself, and its window carries the
reason rather than the services.

Upgrade the hub first. Where a client has already unbound, paste it a fresh
link from the Clients page once the hub is on the new version.
:::

## Reset the panel password

On the hub box:

```bash
sudo nhub reset password
```

Expect: a prompt for the new password, then every session is signed out.

Without a terminal to type into:

```bash
printf '%s' "$NEW_PASSWORD" | sudo nhub reset password --stdin
```

Where the sign-in page reads "Locked after repeated failures.":

```bash
sudo nhub unlock
```

Expect: the login page answers again, and every fail2ban SSH ban on the box is
cleared with it.

::: tip
The panel password and the vault passphrase are different secrets. This resets
the first; the second is `sudo nhub vault rekey`, in
[Backup and restore](./backup-restore.md).
:::

## Reset the box

```bash
sudo nhub reset all
```

Expect: the network is handed back, `config/` returns to the committed
examples, every key and token this box collected is gone, the services stop and
the panel restarts.

- The network is handed back before `config/` is replaced, and no address is
  taken off any interface.
- The panel restarts, so no session outlives the change.
- `/etc/neutrino/agent` is kept. It belongs to the agent package, not to the
  hub.

::: danger A reset takes every credential
A reset takes **every** credential the box holds: SSH keys, AI tokens and the
vault. Download a backup before you run it.
:::

Then set the box up again:

```bash
sudo nhub setup
```

## Uninstall

| Package           | Remove                                                                      | Purge                       |
| ----------------- | --------------------------------------------------------------------------- | --------------------------- |
| `neutrino-client` | the residents stop, the install prefix goes, a person's configuration stays | the personal state goes too |
| `neutrino-agent`  | the service stops and its files go                                          | no separate purge           |
| `neutrino-hub`    | the units stop and its files go                                             | no separate purge           |

Undo the hub's side in this order before removing the package:

1. Delete each client on the Clients page: "Its gateway key is revoked and its
   program loses this hub; it needs a new link to come back."
2. Forget each device in its drawer: "The device and its saved credentials are
   deleted from this box."
3. Run `sudo nhub reset all`, which hands the network back and stops the
   services.
4. Remove the package.

A module removed from a device stops its service and takes its packages: "What
it wrote outside the packages stays on the machine."

::: tip
On a client, `remove` keeps a person's configuration and only `purge` takes it.
:::

That is the whole path: three packages on one version, or a box back to the day
it was installed.
