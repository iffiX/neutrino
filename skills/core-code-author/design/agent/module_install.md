# Installing a device module

A module's install source is where its software comes from and which
component puts it on a machine; the manifest names it in the key
`installer`. Each platform entry of a module's manifest has one install
source, and the source sets the presence check, what `running` means and
what an uninstall removes. How a module runs once it is there is
[module_template.md](module_template.md), and each module's own page is
under `modules/`.

## The four sources

| Source | `installer` | Where the bytes come from | What puts them on the machine | Modules |
| --- | --- | --- | --- | --- |
| The agent's package | `agent` | the agent's own package | the agent's install | Terminal, Remote desktop |
| The system's sources | `platform`, or `builtin` on a platform entry | the system's package repositories; for `builtin`, the system itself | the system's package manager, run by the agent; for `builtin`, nothing | File share, ZFS storage, Containers on Linux |
| The hub's cache | `hub` | the publisher's release, fetched by the hub and pinned by `sha256` | the agent, from the `package` stream | Gitea, VS Code, code-server, CloudCLI, Codeg, Containers on Windows and macOS |
| A container registry | `container` | the registry each image reference names, pinned by digest | the Containers module's Podman | every module whose software is container images |

## What every source answers

| | The agent's package | The system's sources | The hub's cache | A container registry |
| --- | --- | --- | --- | --- |
| The manifest's platform entry names | nothing: the manifest has no platform | `packages`, `pre_install` where a step comes first, `verify`, `uninstall` | `url`, `sha256` and `package_kind`, or `components`; `verify`, `uninstall` | `images` |
| Present when | always | `verify` exits 0; for `builtin`, the runner's own check passes | `verify` exits 0 | every pinned image is in the Containers module's Podman, as the agent reads it there |
| `running` means | the module's own rule ([modules/terminal.md](modules/terminal.md), [modules/remote_desktop.md](modules/remote_desktop.md)) | the module's unit is active | the module's service or instances run | every container of the module runs |
| An uninstall removes | nothing: the presses are refused `module_not_optional` | the named packages and the configuration the hub wrote, keeping the data | the unpack, the service definitions and the forwarder's records, and for an `msi` or `pkg` what the module's own page names, keeping the data | the module's containers, units, network and volumes, and its images no other container uses |
| A failed install reports | `reinstall_failed`, from the agent's own install | `install_failed {detail}` with the package manager's output | `module_fetch_failed` or `module_fetch_too_large` from the cache, then `install_failed {detail}`, or the module's own code for a failed `package` stream, such as `code_server_download_failed` | `image_pull_failed {image, detail}` |
| A `cn` hub gets the bytes from | the mainland agent package | the system's own mirrors | `cn_url` where the entry has one | the docker.io mirrors the Containers module holds, on every hub; an image on another registry comes from that registry |
| A new version comes with | a new agent package | the system's update | a new `url` and `sha256` in the manifest | a new `digest` in the manifest |

## One presence check

| Rule | Reason |
| --- | --- |
| The source's presence check is the one test that the software is there: the manifest's `verify` for the system's sources and the hub's cache, the pinned images for a container registry. | Two checks that disagree give a module that is present and never `running`. |
| `is_active` and `details` are read whenever the presence check passes, and a runner adds no check of its own in front of them. | A runner check stricter than `verify` read Containers as `stopped` with an empty list on a machine whose Docker CE kept `podman-docker` off. |
| A runner's own check answers only for a `builtin` entry and for a module the hub does not name in the machine's state, which the agent still observes and reports, such as a Samba a person installed by hand. | Neither comes with a `verify` to run. |

## Carried by the agent

Terminal and Remote desktop are in the agent's package on every system.
Their manifests name the installer `agent`, with no platform and no recipe, and
the state names them with no `install`. They are never in the Modules
page's picker, always a tab, and the four presses on them are refused
`module_not_optional` ([agent.md](../agent.md), "The kinds of module").

## From the system's sources

| Rule | Reason |
| --- | --- |
| A `platform` entry names `packages`, with `pre_install` where the system needs a step first, and names no download. | The system's package manager fetches, checks and updates its own packages. |
| The agent installs and removes the named packages with the system's package manager, one operation at a time, in `modules/shared/system_package.py`. | One package manager holds a machine-wide lock. |
| An entry names the packages the module runs and leaves out a package that adds a convenience. | `podman-docker` adds a `docker` command and conflicts with Docker CE over `/usr/bin/docker`, so naming it failed the install on a machine with Docker. |
| A module whose unit a distribution ships disabled enables and starts it at the install and at every apply while its `want` is `running`, and its **Stop** disables it; Containers' `podman.socket` is that unit ([modules/containers.md](modules/containers.md)). | The software starts with the machine from its install on, on every distribution, and a stopped module stays stopped after a restart. |
| A `builtin` platform entry names software the system carries, such as the SMB server of Windows and macOS: it names no `packages`, `verify` or `uninstall`, and the runner checks for the software itself. | The system installs and removes it, and the module drives it. |
| An uninstall removes the named packages and keeps the data: pools, share directories and declared containers' volumes stay. | The data is the person's, and the packages are the module's. |

## From the hub's cache

The hub's cache and the agent install a module of this source in steps,
each with one owner:

1. The hub's cache fetches each archive the entry names into the module
   cache, from `cn_url` on a `cn` hub where the entry has one.
1. The cache checks the bytes against the pinned `sha256` and keeps nothing
   that differs. It refuses a file larger than 2 GiB, and after it places a
   new file it deletes the files it held for the same module, component and
   platform.
1. The agent opens `package {module, component}` for each component, or
   `package {module}` for a module with one archive, and the hub streams the
   cached file down with its digest in the close
   ([protocol.md](../protocol.md), "The stream layer"), writing `hub:
   sending <title>, <sent> / <total> MB to <device>` into the module's
   output as it goes.
1. The agent unpacks each archive under `agent/<module>/<directory>/` in
   the state root, `<directory>` being the component's `directory`; an
   archive whose members all sit under one top directory is unpacked
   without it, so the component's files sit directly under its directory.
   A module with one archive unpacks it where its own page says. The
   unpack is sealed: owned by the agent's own account, root or SYSTEM,
   readable and executable by every account, writable by none, and on no
   `PATH`.
1. The agent runs the manifest's `verify` command; its success is
   `installed`.

Four component kinds are never unpacked. The agent keeps the file as the
publisher's bytes under `agent/<module>/<directory>/` in the state root, and
the module takes it from there; the `verify` of a module installed from an
`msi` or a `pkg` names the program where that installer puts it:

| `package_kind` | The file | What the module does with it |
| --- | --- | --- |
| `msi` | a Windows Installer package | installs it with `installers.install_msi` |
| `pkg` | a macOS installer package | installs it with `installers.install_pkg` |
| `tar_zst` | a zstd-compressed tar, such as Podman's machine image for WSL | passes its path to the module's program |
| `raw_zst` | a zstd-compressed disk image, such as Podman's machine image for applehv | passes its path to the module's program |

The cache checks the head of each before it keeps it: `msi` and `pkg` by the
magic bytes it already checks for the agent's own packages, and the two zstd
kinds by `28 b5 2f fd`.

A runtime a module needs, Node.js among them, is one of its components,
pinned in its own manifest. A module of this source reads no other module's
directory and depends on no other module being installed, so two modules
that need the same runtime carry it twice.

## From a container registry

A module of this source is one or more container images, which the
Containers module runs as hub containers. The hub composes them into the
Containers module's state, and Containers renders them as it renders a
declared container ([modules/containers.md](modules/containers.md), "Hub
containers").

| Rule | Reason |
| --- | --- |
| A `container` entry names `images`, each `{name, reference, digest}`: `name` the part, `reference` the image without a tag, such as `docker.io/library/mongo`, and `digest` the publisher's manifest digest, `sha256:...`. | A digest pins the same bytes on every registry and mirror, and a tag moves. |
| The manifest has one `container` entry for each platform Containers runs on, all naming the same images, each built for amd64 and arm64. | Podman pulls the variant of the Linux it runs on: the machine's own on Linux, the Podman machine's on Windows and macOS. |
| The Containers module's Podman pulls each image as `reference@digest`, through the docker.io mirrors Containers holds for an image on docker.io and from the image's own registry otherwise; the hub caches no image. | An image is often several GB, and the mirrors already serve the machine. |
| The module's containers are named `neutrino_<module>` or `neutrino_<module>_<part>`, its named volumes `neutrino_<module>_<volume>`, and the one network its containers share `neutrino_<module>`. | One prefix keeps every hub container apart from a person's containers, and the containers of one module reach each other by name on their network. |
| Each hub container has the label `neutrino.module=<module>`, and the agent and the hub read a container's module from the label alone. | Module names contain `_`, so a name cannot be split into module and part. |
| The module's data is in its named volumes, and it binds no host folder. | An uninstall removes everything the module wrote. |
| The module depends on Containers alone: an install or a **Start** of it sets Containers' `want` to `running` first, which installs Containers where it is absent, and Containers' **Uninstall** is refused `module_in_use {modules}` while a container module is installed. | A container module runs on Containers' Podman, and two container modules share nothing but it. |
| Containers' **Stop** stops the hub containers with the declared ones, and each container module then reads `stopped`. | The containers stop with the engine that runs them. |
| A pull that fails ends the install `image_pull_failed {image, detail}`. | The image is the whole install. |
| An uninstall stops and removes the module's containers, their units, its network and its named volumes, and the images no other container uses. A `container` entry names no `uninstall`, since this source fixes what an uninstall removes. | A container module is removed whole, and a person's container on the same image keeps it. |

This is the one source whose modules depend on another module; the rule
that a module depends on no other holds for the other three.

## One source per platform

`data/manifests/<module>.json` in the hub is the one record of where a
module's software comes from and how a machine checks for it. The hub
resolves the entry for a machine's platform and sends the recipe inside the
state, so the agent is handed conclusions and holds no manifest logic
([agent.md](../agent.md), "One socket, everything on it").

| Key | Holds |
| --- | --- |
| `name`, `title`, `installer`, `source`, `version`, `license`, `corresponding_source`, `description` | the module's identity: its manifest name, the title every surface shows, `installer` its install source (`agent`, `platform`, `hub` or `container`), `source` its publisher, the pinned version, the licence, the source code the licence asks for, and a one-line description |
| `platforms.<os>-<arch>` | one entry per platform the module runs on; a platform with no entry cannot run the module, and the Modules page greys it out ([protocol.md](../protocol.md), "The modules section, one entry per module") |
| `kind`, `installer`, `version`, `source`, `license`, `corresponding_source` | on a platform entry: the entry's own identity, in place of the manifest's for that platform alone; an entry's `installer` is `builtin`, `hub` or `container`, and `platform` is named on the manifest alone, so an entry with no `installer` of its own takes it |
| `url`, `sha256`, `package_kind` | on a `hub` entry: the publisher's file, its digest and how it unpacks; the digest is the publisher's, so a mirror serving the same file is covered by the same pin, and the `digest` GitHub's API gives a release asset, or an OCI registry's blob digest of the same bytes, counts as the publisher's |
| `components` | on a `hub` entry, in place of one `url`: a list of `{name, url, sha256, package_kind, directory}`, with `cn_url` optional on each, one per file the module takes; a manifest with one file lists none |
| `cn_url` | the mirror's address of the same file, which a `cn` hub fetches from when the entry has one; a file no mirror carries has none, and the `cn` hub fetches `url` itself |
| `images` | on a `container` entry: a list of `{name, reference, digest}`, one per image the module runs |
| `verify` | the command whose success means the software is installed, run after the install and at every observation; on Windows `cmd.exe` runs it, and it is the program's quoted path with `--version`, such as `"%ProgramData%\Neutrino\agent\state\vscode\code.exe" --version`, which fails when the file is missing |
| `uninstall` | on a `platform` or `hub` entry, `{packages, post_uninstall, is_data_kept}`: what an uninstall removes beyond the module's own directory; every shipped manifest keeps the data |

What an entry names follows its source, the entry's own or the manifest's.
An `agent` manifest names no platform, no `url` and no recipe. A `platform`
entry names `packages` and never a download. A `hub` entry names a
download, as one `url` or as `components`, and never `packages` for a
program run as an account. A `container` entry names `images` and no `url`,
`packages` or `verify`. A `hub` or `container` entry resolves a `version`,
a `license` and a `corresponding_source`, its own or the manifest's, and an
entry of the other sources resolves none of the three. The loader refuses
a manifest outside these shapes, so a wrong file fails the suite.

`branch_identity(manifest, entry)` in `modules/devices/manifests.py` is the
one place an entry's identity is resolved. The catalog's row
(`catalog.resolve_module`), the Modules page's list (`list_modules`), the
cache's file title (`artifact_title`) and the state's recipe, whose `kind`
is the resolved entry's (`desired_state._recipes`), all read it.
Containers shows one module with two sources: its Linux entries name no
identity of their own and keep the manifest's `platform` installer and
`system_package` kind, and its Windows and macOS entries name `installer`
`hub`, `kind` `podman_machine` and their own pinned Podman release
([modules/containers.md](modules/containers.md)).
