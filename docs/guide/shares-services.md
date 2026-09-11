---
title: Shares and services
---

# Shares and services

Samba, Gitea, Podman and ZFS run under the agent, on the machine that owns the
disk or the GPU. The hub publishes what they serve to every client, and the
Services page declares anything the hub does not host itself.

Six things to settle first:

- The hub hosts nothing. Every module runs under an agent, the hub box included
  when its own agent is the one you pick.
- The Services page has four groups. Remote desktops reach the client, but have
  no group on that page.
- Only Web, Port and File can be declared by hand. AI entries come from the
  gateway, and a desktop is declared by the machine sharing it.
- A machine that is offline cannot be changed. The apply is refused, not
  queued.
- Podman needs 4.4 or newer for Quadlet. Debian 12 ships 4.3.1.
- ZFS on a distribution with no prebuilt module compiles one, and compiles it
  again after every kernel upgrade.

## What an agent hosts

| Module | What it needs                  | Where it runs                        |
| ------ | ------------------------------ | ------------------------------------ |
| Samba  | the disk holding the share     | the machine with that disk           |
| Gitea  | somewhere to keep repositories | any managed machine                  |
| Podman | 4.4 or newer, for Quadlet      | the machine that runs the containers |
| ZFS    | the disks themselves           | the machine they are plugged into    |

Every module page is the same frame: "Enabled devices" with a machine picker
and one apply bar, then that machine's own panels below. The picker says what
it does: "Machines running the agent. Picking one installs {module} on it;
clearing one removes it."

Open a module page, tick a machine under "Enabled devices", and press "Apply
devices".

Expect: a consent dialog headed "Applying {name} changes what these machines
run", then the module installs and that machine's panels appear below.

With no agent anywhere, the page reads "No machines run the agent" and "Install
the agent on a machine from the Devices page." With an agent but no machine
picked, it reads "{module} is on no machine yet" and "Pick a machine above and
apply."

The consent dialog words what the install will do: a third-party repository
will be added, a kernel module will be compiled, packages will be installed on
these machines, packages will be removed. Removing a module says what stays:
"The service stops and its packages go. What it wrote outside the packages
stays on the machine."

::: tip
The hub box has an agent of its own, installed during setup. Picking it here
hosts a module on the hub's hardware, as a device, not as the hub.
:::

## Samba

Open **Samba**, tick `home-hub`, and press "Apply devices".

Under "Users", press "Add user", name it `alex`, give it a password, then press
"Apply users".

Expect: "Creates accounts, sets staged passwords, revokes removed ones." A
staged row reads "created on apply" until then.

Replacing a password is removing the user and adding it again. The panel says
so on the section: "Adding stages name and password together; replacing a
password is removing the user and adding it again."

Under "Shares", press "Add share", name it `media`, give it a directory, then
press "Apply shares".

Expect: "Saves shares and reloads the server.", and the share row carries a
copy button for its address. Read-only is "Whether writing is refused for
everyone, whoever they are."

![The Samba page with the media share, the alex user and the current sessions](/guide/en/samba_share.webp)

"Now serving" lists who is connected right now. Samba answers on port 445.

## Gitea

Open **Gitea**, tick a machine, and press "Apply devices".

Set the root URL, or leave it empty to derive it from the machine's address,
then press "Apply access".

Expect: "Rewrites app.ini and restarts Gitea." The root URL is "Written into
clone addresses."

Press "Create administrator".

Expect: the first administrator exists. Where the service is not up yet the
button reads "Create the first administrator. Start the service first."

![The Gitea page with the access settings and the administrator section](/guide/en/gitea.webp)

The panel keeps only "What must agree with the hub. Repositories, accounts and
everything else are managed in Gitea itself."

## Containers

Open **Containers**, tick a machine, and press "Apply devices".

Press "Add container", give it an image, a tag, ports and volumes, then press
"Apply containers".

Expect: "First starts pull the image, which can take a while." Each declared
container becomes a systemd unit on the default network, and "Running now"
fills in.

![The Containers page with two declared containers and what is running](/guide/en/containers.webp)

::: warning Editing recreates the container
Editing a container recreates it, and files outside its volumes are lost.

Put anything worth keeping in a volume before you press "Apply containers".
:::

Registry mirrors are "Tried in order before docker.io.", and applying them
"Takes effect on the next pull; nothing restarts."

A container's published port becomes a Ports entry in every client window.

## ZFS

Open **ZFS**, tick a machine, and press "Apply devices". Until then the page
reads "Enable the zfs module for this machine above."

Press "Create pool", pick the disks, and pick a layout.

Expect: the four layouts, each with what it costs: single is "No redundancy",
mirror is "Full copies", raidz1 "Survives 1 disk", raidz2 "Survives 2 disks".

Press "Create dataset", and leave the mountpoint blank to take the default:
"Blank keeps the default /pool/name."

![The ZFS page with a pool, its vdevs and two datasets](/guide/en/zfs.webp)

::: danger Adding a disk overwrites it
A disk that still carries traces of an earlier pool is **overwritten** when you
add it anyway. A vdev whose layout does not match the pool's existing ones
leaves the pool only as safe as its **weakest** vdev.
:::

## Services page

Open **Services**.

Expect: four groups, Web, Ports, AI and Files, with a badge reading "{healthy}
of {total} healthy". Rows published by the modules are already listed, each
saying where it came from.

![The Services page with the four groups and their published rows](/guide/en/services_list.webp)

Press "Declare service" for something the hub does not host.

Expect: the "New declared service" form, with Name, Kind, Host, Port and the
kind's own fields. Web adds Scheme and Path; File adds Shares.

![The declare service form with the kind, host and port fields](/guide/en/services_add.webp)

A loopback or hub-held host is served to each machine as the address it reaches
the hub on, so `127.0.0.1`, `0.0.0.0`, `::1` and `localhost` all mean the hub
itself. A File kind left without a port gets 445.

For a File kind, press "Scan host".

Expect: the host's exports fill the Shares list, each published as its own row.
A host exporting nothing reads "The host exports nothing to declare."

Press "Declare".

Expect: the row joins its group, and reaches every client on their next frame.

Deleting one says what goes with it: "The declaration is removed, every row it
published with it; the machine it points at is untouched."

## What the client sees

| Panel           | What is set on the hub              | The client's button                 |
| --------------- | ----------------------------------- | ----------------------------------- |
| Web             | a link                              | "Open"                              |
| Ports           | a port                              | "Connect", then "Disconnect"        |
| AI              | providers and accounts              | "Config", then "Apply"              |
| Files           | a share                             | "Config", then "Mount" or "Unmount" |
| Remote desktops | nothing; the machine shares its own | "Connect"                           |

The client draws all five panels, whether or not each carries entries. An empty
one says so: "no share is published". A row the hub cannot reach is greyed and
reads "not reachable now".

![The connected client window with the five service panels](/guide/en/client_connected.webp)

That is the whole path: the modules on the machine that owns the disk, and
every one of them a row on the laptop.
