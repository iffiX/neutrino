---
title: Troubleshooting
---

# Troubleshooting

Eight symptoms, each with the check that confirms it and the fix that ends it.
Read the section whose first line matches what you are looking at.

Five things that are not faults:

- The panel is HTTP. `https://` never connects.
- An offline machine is refused, not queued. Nothing is waiting to happen when
  it comes back.
- The agent's stop waits out its backoff before it takes effect. That is a
  known bug, not a hung machine.
- Two hubs behind one hostname evict each other, because the session cookie is
  scoped to a host and not a port.
- Core units cannot be stopped from the panel. A gateway with `dnsmasq` down is
  broken, not reconfigured.

Nothing on this page edits `/etc` by hand. `config/` is the source of truth,
and `sudo nhub apply` is how it becomes true.

## Panel unreachable

The browser gets nothing at `http://<hub>:8080`.

```bash
# 1. Is the unit up? Expect active (running).
systemctl status neutrino_hub_web

# 2. Is it on the port you think? Expect 8080 unless it was moved.
ss -lntp | grep neutrino

# 3. Does this network answer at all? Expect the exposure list to name it.
sudo nhub apply --only router --dry-run
```

The port is set on the Network page under Panel port. The networks the box
answers on are set under Exposure. The panel speaks HTTP, so an `https://`
address never connects.

::: warning Two hubs, one hostname
Two hubs behind one hostname evict each other. The session cookie is scoped to
a host and not a port, so signing into the second signs you out of the first.

Give each hub its own hostname, or work with one at a time.
:::

## Locked out

The sign-in page reads "Locked after repeated failures."

```bash
# 1. Open login again, and clear every fail2ban SSH ban with it.
sudo nhub unlock
```

With the password forgotten as well:

```bash
# 2. Set a new panel password. Every session is signed out.
sudo nhub reset password
```

The vault passphrase is a different secret, and neither command touches it.
[Backup and restore](./backup-restore.md) covers that one.

## Device offline

The drawer refuses with "The machine is not answering, so nothing was started
on it."

```bash
# 1. On the machine: is the agent up? Expect active (running).
systemctl status neutrino_agent

# 2. What is it bound to? Expect this hub's address.
sudo nagent status

# 3. Ask the hub for this machine's state now, rather than waiting.
sudo nagent sync
```

| What it reads                                                  | Fix                                                           |
| -------------------------------------------------------------- | ------------------------------------------------------------- |
| "That agent speaks an older channel than this hub; update it." | reinstall the agent from the drawer                           |
| "That agent is a later release than this hub; update the hub." | upgrade the hub first                                         |
| "The hub did not present the certificate this machine pins."   | the hub was reset or reinstalled; re-enroll with a fresh link |
| nothing bound                                                  | `sudo nagent connect '<link>'` with a fresh link              |

::: tip
A stop issued during one of the agent's turns waits out the backoff before it
lands. The machine is not hung; the flag is cleared a moment too late.
:::

## Client will not connect

Read the refusal in the client window, then take the row.

| Refusal                                                                   | Fix                                                            |
| ------------------------------------------------------------------------- | -------------------------------------------------------------- |
| "the hub cannot be reached"                                               | the hub's agent-channel port, 8443, is not answering from here |
| "the hub refused this link; it may have expired, so generate a fresh one" | links last five minutes; mint a new one                        |
| "that is not an enrollment link; copy the whole line from the hub"        | the paste was truncated                                        |
| "that link carries no hub address and token"                              | the same, from the other end of the line                       |
| "that link is for a device agent, not for a client"                       | mint it on the Clients page, not on Devices                    |
| "what answers is not the hub this link pins"                              | the hub was reset or reinstalled                               |
| "the hub has switched this client off"                                    | Clients page, then Enable                                      |
| "this client (…) is newer than the hub (…); update the hub first"         | upgrade the hub                                                |
| "the window needs WebKitGTK" or "the window needs {runtime}"              | install it, then start the client again                        |

## Share will not mount

| Refusal                                               | Fix                                                                           |
| ----------------------------------------------------- | ----------------------------------------------------------------------------- |
| "give a folder under your home, like ~/nas/share"     | the path is outside home                                                      |
| "give an unused drive letter, like N:"                | Windows takes a letter, not a path                                            |
| "that folder is not empty"                            | pick an empty one                                                             |
| "mounting was not authorized on this machine"         | the polkit prompt was dismissed                                               |
| "the mount tooling is missing on this machine"        | install the cifs tooling                                                      |
| "the saved login is gone; enter it again with Config" | press Config and retype the share login                                       |
| the row is greyed, reading "not reachable now"        | the machine serving the share is off, or Exposure does not carry this network |

The client's one escalation is the polkit mount helper. It is never root for
anything else.

## AI tool ignores the gateway

```bash
# 1. Where do this person's tools point? Expect the hub's endpoint.
nclient service ai show

# 2. Does the gateway answer? Expect a model list, not a refusal.
curl -s http://<hub>:8317/v1/models -H 'Authorization: Bearer PLACEHOLDER_CLIENT_KEY'
```

| Symptom                                                | Fix                                                               |
| ------------------------------------------------------ | ----------------------------------------------------------------- |
| "the hub has not granted you a key yet"                | AI, Access, Generate key, or rejoin the client                    |
| "The gateway is not answering, so it cannot be asked." | `systemctl status neutrino_hub_cliproxyapi`                       |
| the tools still use their own configuration            | the Config dialog only stages; press Apply                        |
| one machine reaches nothing while others do            | the gateway port was changed, and that machine's endpoint was not |

## Overlay peer missing

| Engine   | What you see                             | Fix                                                            |
| -------- | ---------------------------------------- | -------------------------------------------------------------- |
| NetBird  | the badge reads "management unreachable" | Proxy, then send this box's own traffic through the proxy      |
| NetBird  | Peers is empty                           | log in on the other device with the NetBird app                |
| NetBird  | the route is announced but unreachable   | the subnet needs an Access Control Policy in the console       |
| EasyTier | "No machine has joined yet."             | the other machine's network name and secret must match exactly |
| EasyTier | joined, but nothing routes               | add the subnet under Exported networks and apply               |
| either   | the box answers nowhere on the overlay   | Network, then Exposure                                         |

A different secret is a different network. The engine reports nothing wrong;
the peer list simply stays empty.

## Logs

| What                           | Where                                   |
| ------------------------------ | --------------------------------------- |
| The setup run                  | `/var/log/neutrino/setup.log`           |
| The hub's own logs             | `/var/log/neutrino/`                    |
| One unit                       | `journalctl -u neutrino_hub_web -n 200` |
| The agent on a machine         | `journalctl -u neutrino_agent -n 200`   |
| The AI gateway, from the panel | the AI page's Journal panel             |
| What a render would produce    | `sudo nhub apply --dry-run`             |

The hub's units are `neutrino_hub_web`, `neutrino_hub_router`,
`neutrino_hub_xray`, `neutrino_hub_dnsmasq`, `neutrino_hub_cliproxyapi`, and
`neutrino_hub_netbird` or `neutrino_hub_easytier` where an overlay runs. The
per-interface ones are templates, such as `neutrino_hub_dhcpcd@<iface>`.
Configuration lives under `/etc/neutrino`, state under `/var/lib/neutrino`.

::: tip
`sudo nhub apply --dry-run` renders every module and writes nothing, so it is
safe to run while you are still working out what is wrong.
:::

That is the whole path through the eight.
