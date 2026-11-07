# Installing a device module

A module's install is the `{method, params}` its manifest names for a
machine's platform. The method fixes where the software comes from, what puts
it on the machine, the one check that it is there, and what an uninstall
removes. How the module runs once it is there is
[module_template.md](module_template.md), and each module's own page is
under `modules/`.

## The manifest

`data/manifests/<module>.json` in the hub is the one record of where a
module's software comes from and how a machine checks for it. Its top level
is the module's identity, the same on every platform:

| Key | Holds |
| --- | --- |
| `name` | the module's name, as the state and the routes spell it |
| `title` | the name every surface shows |
| `description` | one line on what the module does |
| `publisher` | who publishes the software, such as `coder/code-server` or `Microsoft` |
| `is_data_forward_only` | true when the software migrates its data forward and never back, as Gitea does: the module then installs no version older than the newest it has run on the machine; absent is false, and every listed version installs, older ones too ("Module versions") |
| `uninstall_data` | `{is_deleted, text}`: what an uninstall does to the module's data, the line the uninstall dialog shows ([../ui_behavior.md](../ui_behavior.md), "The machine page"); `is_deleted` is true when the data goes with the module, and `text` is the line in each language of the panel, keyed `en` and `zh-CN` |
| `memory_mib` | optional, and only on a module whose entries name the `container` method: the memory in MiB its containers run in without swapping from their first start, a whole number above 0; on Windows and macOS the hub sums it over the container modules of a machine against the Podman machine's memory ([modules/containers.md](modules/containers.md), "Memory for the container modules") |
| `web_share` | `{guest_login}`, present for every module with a page and absent for a module without one: `guest_login` is how an App share's visitor is signed in, `app` for the app's own login page, `guest_account` for one account of the app per share, which the forwarder signs every visitor of that share in as, and `run_account` for the account the app runs as, which the visitor is signed in as, the way the owner's clients are ([module_template.md](module_template.md), "The run") |
| `platforms` | one entry per platform the module runs on |

A platform entry is `{runner, min_version, install, requires}`:

| Key | Holds |
| --- | --- |
| `runner` | the agent runner that makes the machine match the module's `want` ([module_template.md](module_template.md), "How a module runs") |
| `min_version` | optional: the lowest system version the entry runs on, a dotted number the loader checks |
| `install` | `{method, params}`: the install method, and the parameters whose shape the method fixes |
| `requires` | optional: the modules the entry runs on, by name and with no version ("Dependencies") |

| Rule | Reason |
| --- | --- |
| A platform key is `<os>-<family>-<arch>`, `<os>-<family>`, `<os>-<arch>` or `<os>`, tried in that order, and the first key the manifest names wins. | A `system` entry differs by distribution family, a download by architecture, and a `builtin` entry by system alone. |
| `resolve_platform_entry(manifest, platform)` in `modules/devices/manifests.py` is the one function that picks a machine's entry. The catalog's row, the machine page's tabs, the cache and the state's recipe all read it. | Two resolvers can disagree about which entry a machine has. |
| A machine whose platform has no entry, or whose system version is below the entry's `min_version`, cannot run the module. The machine page's catalog greys it out, and a press on it is refused `no_platform_build {module}` ([protocol.md](../protocol.md), "The modules section, one entry per module"). | A machine that reports no system version is not ruled out, since its floor is unknown. |
| A machine where a module the entry requires resolves no entry cannot run the module either, and the press is refused `no_platform_build {module}` naming the required module. | Hermes WebUI and Ayakaleaf name one `linux` entry, and Containers has none for a Linux whose agent reports no family, such as Alpine. |
| A manifest names no licence and no source address, and the loader refuses `license` and `corresponding_source`. No row, catalog entry or credit names one for a module. | A module only installs the publisher's software from the publisher's sources, and no package of Neutrino's carries it. The **About** card credits only what Neutrino's own packages carry ([../ui_text.md](../ui_text.md), "Software the owner installs"). |
| The loader refuses a manifest whose keys or `params` fall outside the shapes on this page, so a wrong file fails the suite. | The hub acts on a manifest as root on every managed machine. |
| Every manifest of a module a person can uninstall names `uninstall_data`, with a line in both languages; a module whose entries name the method `agent` names none. The loader refuses a manifest without it, and one whose `is_deleted` disagrees with its entries: true beside a `system` or `builtin` entry or a `hub` entry whose `is_data_kept` is true, false beside a `container` entry or a `hub` entry whose `is_data_kept` is false. | Every module's uninstall shows one dialog, and the line in it is the one place a person reads what happens to their data before it happens. |
| A line names the data by what the person keeps in it, and where it stays when it stays. `{data_dir}` in a line is the module's per-account data directory on the machine's system ([module_template.md](module_template.md), "Disk layout"), which the hub writes in before it sends the row. | A path is the answer to "where are my notes now"; the hub knows the machine's system, and one line serves all three. |
| Every module with a page names `web_share`, so an App share can offer every `web` entry; a module without a page names none. | A person shares the app they use, and the share dialog says what a visitor holds in it ([../ui_behavior.md](../ui_behavior.md), "The Clients page"). |
| code-server, VS Code, Codeg, CloudCLI, Hermes WebUI and SiYuan name `{guest_login: run_account}`. | Each has one user, the account it runs as, and signs every browser in as that user, a visitor's as the owner's; the visitor can do whatever the app lets that account do until the share ends. |
| Ayakaleaf names `{guest_login: guest_account}` ([modules/ayakaleaf.md](modules/ayakaleaf.md), "The guest account"). | The app has accounts of its own and shares a project with an account, so a visitor works in what the owner shares with that account and sees nothing else. |
| Gitea names `{guest_login: app}`, and a declared app's `web` entry and a container's, declared or started by hand, are offered as they are, with `guest_login` `app`, and have no manifest. | Gitea has accounts and a login page of its own, and the hub holds no login of the others, so the visitor meets the app's own login page, the guard the person already set. |
| The loader refuses a `web_share` of another shape, and a `guest_login` outside the three. | A manifest decides what a visitor holds, so a wrong one fails the suite. |
| The loader refuses a `memory_mib` that is no whole number above 0, and one named by a manifest with no `container` entry. | The sum counts container modules alone, since their containers share the one Podman machine on Windows and macOS. |

`cc_switch.json` describes a tool and no module: it names `is_module: false`,
its version at the top level, and `artifacts` alone in each platform entry,
with no runner and no method. The catalog leaves it out, and the agent takes
it from the hub's cache for the machine's AI tools ([ai_tools.md](ai_tools.md)).
It names no licence and no source address either: the client's package
carries cc-switch, and the client's **About** card credits it from the
client's own pin.

## Install methods

| `method` | `params` | Where the bytes come from | What puts them on the machine | Modules |
| --- | --- | --- | --- | --- |
| `agent` | `{}` | the agent's own package | the agent's install | Terminal, Remote desktop, the SSH server |
| `builtin` | `{}` | the system itself | nothing; the runner checks that the software is there | the file share on Windows and macOS |
| `system` | `{version: "system", packages, pre_install, verify, uninstall: {packages, post_uninstall}}` | the system's package repositories | the system's package manager, run by the agent | the file share and Containers on Linux |
| `hub` | `{version, releases, artifacts, packages, verify, uninstall: {post_uninstall, is_data_kept}}` | the publisher's release, fetched into the hub's cache | the agent, from the `package` stream | Gitea, VS Code, code-server, CloudCLI, Codeg, SiYuan, Codex, Claude Code, Containers on Windows and macOS |
| `container` | `{version, releases, artifacts, source_sets}`, `releases` and `source_sets` optional | the registries each image's `sources` name | the Containers module's Podman | Hermes WebUI ([modules/hermes_webui.md](modules/hermes_webui.md)), Ayakaleaf ([modules/ayakaleaf.md](modules/ayakaleaf.md)) |

`pre_install` is optional, for a system that needs a step before its package
manager installs, such as a repository to add. A `hub` entry's `packages` is
optional too: the system packages the program needs beside its artifacts,
such as Gitea's `git` on Linux. The system's package manager installs them
before the artifacts, and an uninstall keeps them.

| | `agent` | `builtin` | `system` | `hub` | `container` |
| --- | --- | --- | --- | --- | --- |
| Present when | always | the runner's own check passes and the module's uninstalled mark does not stand | `verify` exits 0 | `verify` exits 0 | every image's digest is in the Containers module's Podman, as the agent reads it there |
| `running` means | the module's own rule ([modules/terminal.md](modules/terminal.md), [modules/remote_desktop.md](modules/remote_desktop.md)) | the system's server runs the module's configuration | the module's unit is active | the module's service or instances run; for a command line program, its copy is there and each enabled account's `PATH` put first | every container of the module runs |
| An uninstall removes | nothing: the four presses are refused `module_not_optional` | what the module's own page names, and writes the uninstalled mark; the system keeps its server | the named packages and the configuration the hub wrote, keeping the data | the module's files, its service definitions and the forwarder's records, keeping the data; for a command line program, its copy, its launcher, its record, and each account's line, `env.sh` and Windows entry ("What an uninstall removes") | the module's containers, their units, its network and its named volumes, and the images no other container uses |
| A failed install reports | `reinstall_failed`, from the agent's own install | nothing, since nothing is installed | `install_failed {detail}` with the package manager's output | `download_failed {file, sources}` or `module_fetch_too_large` from the cache, then `install_failed {detail}` or the module's own code | `download_failed {file, sources}` when no source serves an image |
| The version | the agent's | the system's | the system's, locked | the tested one or the machine's choice | the tested tag or the machine's choice; the tested one, locked, where the entry names no `releases` |

Terminal, Remote desktop and the SSH server are in the agent's package on every system.
Their platform entries name the method `agent`, they are never in the Modules
page's picker, always a tab, and the four presses on them are refused
`module_not_optional` ([agent.md](../agent.md), "The kinds of module").

### The source chip and the kind chip

A module's tab shows two chips beside its state
([../ui_behavior.md](../ui_behavior.md), "The machine page"), whose words are
in [../ui_text.md](../ui_text.md), "The machine page's words".

| Rule | Reason |
| --- | --- |
| The source chip names who installs, updates and removes the module's software on the machine: Built-in (自带), the agent, which carries it; System (系统), the system, through its package manager or as part of itself; Upstream (外部源), the module's installer, from the publisher's release at the version the hub sets; Container (容器), the Containers module's Podman, which pulls the images. | Who manages the software decides what an update and an uninstall do to it, and who first pressed **Install** changes neither. |
| `agent` reads Built-in, `builtin` and `system` read System, `hub` reads Upstream, and `container` reads Container. A command line program reads Upstream, as every `hub` module does. The hub derives the word and the module row carries it as `source`. | The method of the machine's entry is what the hub knows of who places the software. A command line program always runs the module's copy ([../agent.md](../agent.md), "Parallel, never take over"). |
| A Samba or a Podman that was on a Linux machine before its module reads System, as the one the module installed does. | The system's package manager updates and removes a package whoever installed it. |
| The kind chip reads Service (服务) for a module with **Start** and **Stop**, and Program (普通程序) for one with neither. Codex and Claude Code read Program; every other module reads Service, the carried ones too, though their tab holds no **Start**, since the agent runs them. The module row carries the kind as `kind`. | A person reads from the kind whether the software runs by itself until stopped, or only when a person runs it, as a command line program does. |
| A module whose manifest says `is_data_forward_only` shows a third chip after the kind chip, Upgrade only (只能升级). The module row carries the flag as `is_data_forward_only`. | A person reads before opening the version dialog that the module goes to no older version. |

## Artifacts

An artifact is one file a `hub` or `container` entry installs:
`{name, kind, digest, sources}`, with `file` where its sources name it,
`directory` where its kind needs one, and `member`, the folder a `dmg` holds
the program in. An artifact whose sources are an
ecosystem's names `source_set`, the set's name, in place of `sources`
("Source sets").

Each kind belongs to one of seven classes, by how the agent places the
software it holds. Where each class lands on each system is
[module_template.md](module_template.md), "Disk layout".

| Class | Kinds | What the agent does with it | Used today by |
| --- | --- | --- | --- |
| archive (压缩包) | `tar_gz`, `zip` | unpacks it into the module's directory and seals it | VS Code, code-server, Codeg's server, SiYuan on Linux, Codex, Claude Code, the Node.js of CloudCLI and Codeg, and Gitea's MinGit on Windows |
| installer (安装包) | `msi`, `pkg` | keeps it in the module's directory and has the system's installer install it | Containers: Podman and WSL on Windows, Podman on macOS |
| disk image (磁盘映像) | `dmg`, `nsis` | copies the program out of it into the module's directory and seals it; nothing in it runs | SiYuan on macOS and Windows |
| machine image (虚拟机映像) | `tar_zst`, `raw_zst` | keeps it in the module's directory, and Podman builds its machine from it | Containers on Windows and macOS |
| container image (容器镜像) | `image` | has the Containers module's Podman pull it from a registry | Hermes WebUI, Ayakaleaf |
| single program (单个程序文件) | `binary` | keeps the publisher's bytes as one program and makes it executable | Gitea |
| npm package (npm 包) | `npm` | installs it with npm, run as the account | CloudCLI |

| Rule | Reason |
| --- | --- |
| A machine image and a container image are two classes. | A machine image is one file that comes down the `package` stream from the hub's cache into the module's directory, and Podman builds a machine from it; a container image Podman pulls itself from a registry into its own store, and the hub caches none. |
| A new class is added only when a new way of placing software on a machine appears, and a new kind joins the class whose way it shares. | A class fixes where its software lands, so a kind placed the way another is lands where that one does. |

| `kind` | The file | What happens to it on the machine |
| --- | --- | --- |
| `tar_gz`, `zip` | an archive | unpacked under `agent/<module>/<directory>/` in the state root and sealed |
| `binary` | one program, as Gitea publishes it | kept as the publisher's bytes where [module_template.md](module_template.md), "Disk layout", puts a single program, and made executable |
| `msi` | a Windows Installer package | kept under `agent/<module>/<directory>/`, then installed with `installers.install_msi` |
| `pkg` | a macOS installer package | kept under `agent/<module>/<directory>/`, then installed with `installers.install_pkg` |
| `tar_zst` | a zstd-compressed tar, such as Podman's machine image for WSL | kept under `agent/<module>/<directory>/`, its path given to the module's program |
| `raw_zst` | a zstd-compressed disk image, such as Podman's machine image for applehv | kept under `agent/<module>/<directory>/`, its path given to the module's program |
| `dmg` | a macOS disk image, such as SiYuan's desktop build | attached with `hdiutil attach -nobrowse -readonly` at a temporary mount point; the folder `member` names is copied with `ditto` to `agent/<module>/<directory>/` and sealed, and the image is detached |
| `nsis` | a Windows installer made with NSIS that holds a 7z archive stored whole, such as SiYuan's | the 7z archive found inside the installer by its signature and read by the agent's own reader with Python's `lzma`, its files unpacked under `agent/<module>/<directory>/` and sealed; nothing in the installer runs |
| `image` | a container image, its `sources` image references with no tag | pulled by the Containers module's Podman |
| `npm` | an npm package, named by `package`, its `source_set` the `npm` set | installed by npm run as the account, where [module_template.md](module_template.md), "Disk layout", puts an npm package |

| Rule | Reason |
| --- | --- |
| A digest is `sha256:<hex>`, and the digest of an artifact from the `npm` set, an `npm` artifact or an npm package's tarball of kind `tar_gz`, is npm's `integrity` as the registry gives it, `sha512-<base64>`. The hub's cache checks a tarball's integrity itself, and names the file by the hex of the digest's bytes. | The digest pins the bytes on every source; npm publishes no sha256 of a tarball, and every npm registry serves a published tarball under the integrity the publisher's upload fixed. |
| The digest is the publisher's: the sha256 file it publishes, the `digest` GitHub's API gives a release asset, Microsoft's `sha256hash`, an OCI manifest digest, or npm's `integrity`. A mirror serves bytes and names no digest. | A mirror that names its own digest can serve anything. |
| The cache checks the head of each file before it keeps it: `msi` and `pkg` by the magic bytes it checks for the agent's own packages, `binary` by the ELF, Mach-O or PE header, the two zstd kinds by `28 b5 2f fd`, `nsis` by the PE header, and `dmg` by `koly` at the start of its last 512 bytes. | A source that answers with an error page passes no head check. |
| An archive whose members all sit under one top directory is unpacked without it, so its files sit directly under `<directory>`. | A path in `verify` and in a service definition stays the same for every version. |
| The unpack is owned by the agent's own account, root or SYSTEM, readable and executable by every account, writable by none, and on no `PATH`. A command line program's launcher folder, `bin/` beside its unpack, is the one folder named on a `PATH`: at the front of each enabled account's `PATH` and of Neutrino's own sessions' ([module_template.md](module_template.md), "The launcher and the account's `PATH`"). | Every account runs the program, and none can change it. A person runs a command line program by its name. |
| Each member of a `zip` keeps the permission bits its entry names, less the setuid, setgid and sticky bits, as a tarball's members do; the seal then takes every write bit away. | VS Code's CLI for macOS comes as a zip whose `code` is 0755. Unpacked without its bits it read `-r--r--r--`, and VS Code did not start. |
| The recipe the state holds for a `hub` entry drops each artifact's `sources`, and the `source_set` of an archive the hub's cache fetches, since the bytes come down the `package` stream. A `container` or an `npm` artifact keeps its `sources` or its `source_set`, since the machine fetches it, and the state's `source_sets` section holds each set a recipe names. | The agent fetches only what the hub cannot send. |

A runtime a module needs, Node.js among them, is one of its artifacts,
pinned in its own manifest. Two modules that need the same runtime each hold
it. A program a person also runs from a shell by its name, such as Codex or
Claude Code, is a module of its own, a command line program, and a module
whose own packages carry a copy of it, as the Agent SDK in CloudCLI's and
Codeg's npm packages carries Claude Code, runs that copy.

## Sources

| Rule | Reason |
| --- | --- |
| Every address that serves the same bytes is in the one `sources` list of its download, or in the one source set of its ecosystem, which the download names ("Source sets"). No key names a country's or an edition's address. | The digest makes every source equal, so the fastest one serves. |
| A source names a file as `{file}`, the artifact's `file` with `{version}` filled in. | One template lists the same file on the publisher and on every mirror. |
| `{release}` names each release site the hub's build stamped, at the release the hub came from ([../../agent_work_rule/release.md](../../agent_work_rule/release.md), "Release sites"). A checkout has no stamp, so `{release}` names no source there. | The project's own release has one address per site, and the hub learns them only from its build. |
| A `hub` artifact names `source_set` in place of `sources` when its file is a package of an ecosystem with a set: the hub's cache reads the artifact's `file` under each of the set's sources, the first source first. Claude Code's and Codex's tarballs name the `npm` set ([modules/claude_code.md](modules/claude_code.md), [modules/codex.md](modules/codex.md)). | Every npm registry serves a published tarball at the same path, so the set's one list of registries, mirrors in mainland China among them, serves the module too. |
| No Claude Code artifact names `{release}`, and no release of Neutrino's carries Claude Code's files. | Claude Code is Anthropic's proprietary software, and its module's installer fetches it only from the npm registries, which serve the package Anthropic publishes. |
| The Containers module's docker.io mirrors stay the person's ordered list, which Podman applies under any `docker.io` source. | They are the person's configuration, and Podman already tries them in order. |

| Download | Fetched by | Its sources |
| --- | --- | --- |
| a `hub` artifact | the hub's cache | the publisher's address first, then each mirror that serves the same file, such as the USTC mirror of code-server and npmmirror's copy of Node.js; `{release}` last, where the project's release holds the file |
| Codeg's archives | the hub's cache | Codeg's GitHub release, the one address that serves them |
| Claude Code's and Codex's tarballs | the hub's cache | the `npm` set: registry.npmjs.org, npmmirror and Tencent's mirror ([modules/claude_code.md](modules/claude_code.md), [modules/codex.md](modules/codex.md)) |
| SiYuan's desktop builds | the hub's cache | SiYuan's GitHub release, then the publisher's own `https://release.liuyun.io/siyuan/{file}` ([modules/siyuan.md](modules/siyuan.md)) |
| Gitea's MinGit on Windows | the hub's cache | Git for Windows' GitHub release, then npmmirror's copy ([modules/gitea.md](modules/gitea.md)) |
| VS Code's CLI | the hub's cache | Microsoft's address alone, a list of one |
| Podman, its machine image and WSL | the hub's cache | each publisher's GitHub release |
| cc-switch | the hub's cache | its publisher's GitHub release, then `{release}` |
| another platform's agent package | the hub's agent cache | `{release}` ([../agent.md](../agent.md), "The agent's packages come from the hub") |
| a container image | the agent, for Podman to pull | each image reference the artifact names, the publisher's registry first |
| CloudCLI's npm package | the agent, for npm to install | the `npm` set |
| the packages a container's own tools fetch | the agent, into the container's environment | each set the module lists: Hermes WebUI's `pypi` |
| the TeX packages Ayakaleaf's first start adds | the agent, for `tlmgr` in the app's container | the `ctan` set, its first ranked source on `tlmgr`'s command line ([modules/ayakaleaf.md](modules/ayakaleaf.md), "The first start") |
| better-sqlite3's prebuilt binary | the agent, for prebuild-install to fetch | its GitHub releases, then npmmirror's copy ([modules/cloudcli.md](modules/cloudcli.md)) |
| a module's version list | the hub, once a day, and every hour while a module holds no list | the publisher's API ("Module versions") |
| the hub's own update | the hub | the release sites ([../architecture.md](../architecture.md), "The hub updates itself outside its own process") |
| a package an install script installs | the install script | the release sites ([../../agent_work_rule/release.md](../../agent_work_rule/release.md), "Install scripts") |

Codeg installs the coding agents it runs with `--registry
https://registry.npmjs.org` fixed in its own command line, and npm reads that
before any setting. It is the one download whose source the hub does not
choose ([modules/codeg.md](modules/codeg.md)).

## Source sets

A source set is the one list of addresses that serve one software
ecosystem's packages, such as PyPI's, for the whole system.
`hub/neutrino_hub/data/source_sets.json` defines each set once, by its name:

```json
{
  "pypi": {
    "probe": "/numpy/",
    "sources": ["https://pypi.org/simple", "https://pypi.tuna.tsinghua.edu.cn/simple", "https://mirrors.aliyun.com/pypi/simple", "https://mirrors.cloud.tencent.com/pypi/simple"],
    "variables": ["PIP_INDEX_URL", "UV_DEFAULT_INDEX", "UV_INDEX_URL"]
  },
  "npm": {
    "probe": "/npm/-/npm-10.9.2.tgz",
    "latency_probes": ["/wrappy", "/once", "/inherits"],
    "sources": ["https://registry.npmjs.org", "https://registry.npmmirror.com", "https://mirrors.cloud.tencent.com/npm"],
    "variables": ["npm_config_registry", "YARN_NPM_REGISTRY_SERVER", "BUN_CONFIG_REGISTRY"]
  },
  "huggingface": {
    "probe": "/openai-community/gpt2/resolve/607a30d783dfa663caf39e06633721c8d4cfcd7e/tokenizer.json", "_probe_scan": "scan: allow",
    "sources": ["https://huggingface.co", "https://hf-mirror.com"],
    "variables": ["HF_ENDPOINT"]
  },
  "ctan": {
    "probe": "/systems/texlive/tlnet/tlpkg/texlive.tlpdb.xz",
    "sources": ["https://mirror.ctan.org", "https://mirrors.mit.edu/CTAN", "https://mirrors.tuna.tsinghua.edu.cn/CTAN", "https://mirrors.ustc.edu.cn/CTAN", "https://mirrors.aliyun.com/CTAN", "https://mirrors.cloud.tencent.com/CTAN", "https://mirrors.sjtug.sjtu.edu.cn/ctan", "https://mirror.nju.edu.cn/CTAN"],
    "variables": []
  }
}
```

| Key | Holds |
| --- | --- |
| `probe` | the path of the file a probe reads under each source ("The file a probe reads") |
| `latency_probes` | optional: the paths of the small documents whose mean time to the first byte is a source's latency ("Choosing a source"); without it the latency is the probe's own first byte |
| `sources` | the addresses, the publisher's first |
| `variables` | the environment variables the ecosystem's tools read the address from: pip and uv for `pypi`; npm, pnpm and Yarn 1 (`npm_config_registry`), Yarn 2 and later, and Bun for `npm`; the Hugging Face libraries for `huggingface`; none for `ctan`, since `tlmgr` reads its repository from its command line |

| Rule | Reason |
| --- | --- |
| Each ecosystem has one set, and every download from it names the set: an artifact by `source_set`, a `container` entry by `source_sets`. | Two lists for one ecosystem drift apart, and a mirror added to one reaches half the modules. |
| An artifact that names a set probes as its kind says: CloudCLI's npm artifact names `npm` and probes its own package's document, and Claude Code's and Codex's tarballs, of kind `tar_gz`, probe the tarball itself as any `hub` artifact does. | The package being installed is the document or the file that has to be there. |
| A `container` entry lists the sets its containers use in `source_sets`, and the hub copies the list into each hub container of the module. | The tools inside a container fetch from the network at their start, and the container's environment is where they read the address. |
| Before the agent writes a hub container's environment file, it probes each set the container lists and writes every variable of the set, with the first ranked source, into the container's environment. | Which source is fastest depends on the machine's own network. |
| An environment value `{<set>}`, such as `{pypi}`, is the first ranked source of that set, for a variable the set does not list. The set is one the module lists. | A tool that reads a variable of its own gets the same choice. |
| An apply whose one change to a container's environment file is a set's value keeps the file as it is. | The value is in the container's environment, so a new value restarts the container, and a source ranked first today is no reason to restart a running page. |
| The hub sends the sets the machine's recipes name in the state's `source_sets` section, and the agent probes them; nothing remembers a past result. | Only the machine measures its own network, and a network changes. |
| The loader rejects a `source_set`, a `source_sets` item or a placeholder that names a set the file does not define, and a placeholder that names a set its module does not list. | A wrong name fails the suite, and the agent resolves only the sets the state sends. |
| A set exists for an ecosystem a module fetches from. Go's module proxy, crates.io, conda channels and Ollama's library have none. | A set no module names is a list nobody keeps true. |
| A set with no `variables` is ranked when a module's hook asks for it, and the hook gives the first ranked source to its tool on the tool's command line: Ayakaleaf's `tlmgr --repository`. | A tool that reads no variable for its address takes it where it reads it. |
| The `ctan` set's first source is CTAN's own redirector, then the MIT mirror and the mirrors at Tsinghua, USTC, Aliyun, Tencent, SJTU and Nanjing. Its sources can hold snapshots of TeX Live a day apart, and `tlmgr` checks every package it installs against the signed package database of the one source it reads. | In the lab the eight sources served two `texlive.tlpdb.sha512` a day apart, so no digest names the same bytes on every source, and the signature makes each source safe alone. |

better-sqlite3's prebuilt binary host serves that one package alone, so it
stays in CloudCLI's artifact as `hosts`, and `hosts_probe` names the path a
probe reads under each setting's hosts ([modules/cloudcli.md](modules/cloudcli.md)).

## Choosing a source

One method chooses among the sources of every download:

| Rule | Reason |
| --- | --- |
| Every source is probed at once, and a probe waits at most 5 seconds for an answer. | 5 seconds bounds the wait on a source that never answers. |
| A probe reads 100 KB to 1 MiB of a real file. It asks for the file's first 1 MiB with a Range request, and the read stops 5 seconds after its first byte, the speed taken over what arrived. | A smaller read times the first packets: over CTAN's eight sources 144 B gave 5 and 6 different winners in two runs of 10, and 1 MiB gave 3, the two fastest of a 16 MiB read among them. The time limit bounds a slow line: eight sources sharing 200 KB/s end in 6 seconds, and 1 MiB from each takes 42. |
| A probe checks no digest, except an npm registry's. | The download, the pull or the tool checks the bytes it takes, and a probe's file is often another file. |
| Each source that answered gets two measures: its speed, from the probe's first byte to its last, and its latency, the time from the request to the probe's first byte. For a set that names `latency_probes`, the `npm` set, the latency is the mean time to the first byte of one request for each of those small documents, made one after another. | A large download waits on speed, and an install of many small files, such as npm's about 2000 fetches, waits on every answer. One small request answers by luck where a few seldom do. |
| Each measure is scored against the best source's: the speed score is the source's speed over the best speed, and the latency score the best latency over the source's latency. The total is half the one and half the other, and the source with the highest total ranks first; the download, the pull or the tool starts on it. The same rule ranks every list: a set's sources, npm registries, an image's registries, an npm setting's hosts and a `hub` artifact's sources. | iffi's design. In R168 one CloudCLI upgrade took 13.9 minutes on Tencent's npm mirror, which won on one document's speed and answers every request slowly; in R65 the same install took 1870 s there against 95 s on registry.npmjs.org. |
| While a download has at least 30 seconds left at its speed now, the fetcher measures the other sources every 30 seconds. Each measure is a 1 MiB Range request at the current offset, to every source that has not failed. | A short download ends before a change pays back; 1 MiB per source every 30 seconds costs a few percent of the transfer. |
| A source takes over when its total is at least 1.5 times the current source's, the totals scored over each measured source's speed and first byte and over the current source's speed in the last 10 seconds and the latency of its last probe or measure. The download resumes there by a Range request at the current offset, and the next measure comes 30 seconds later. | A short probe measures low against a running transfer, and a smaller gap changes source on noise. |
| An install that a tool runs, npm, pip in a container or `tlmgr`, keeps the source it started on until it ends; the next ranked source is tried only by a new install after one fails. | Each of its thousands of requests goes to the source it was told, and a change in the middle would leave half the files from each. |
| A source fails when it sends no byte for 20 seconds, answers with an error, or serves a file whose digest differs; the download resumes on the next ranked source by a Range request. A source that did not answer the probe in time has not failed, and the next measure asks it again. | The bytes are the same on every source, and a source slow to answer once can be the fastest later. |
| A source that answers a Range request with the whole file serves a download from its start alone, and is never moved to while a download runs. | It cannot resume at an offset. |
| The digest is checked when the last byte arrives. A mismatch drops that source and fetches the file again from the next one. | A source serving other bytes is wrong for this file alone. |
| When every source fails, the download fails `download_failed {file, sources}`, each source as `{source, reason, detail}`, `reason` being `unreachable`, `timeout`, `stalled`, `digest_mismatch`, `http_<status>` or `pull_failed`, and `detail` the tool's own last line where one exists. | A person reading the failure sees each address and why it failed. |
| Nothing remembers a past result: each download probes again. | A network changes, and a stored ranking outlives the network it measured. |
| Every ranking the agent makes writes one line to the agent's log: what it ranked, each source with its speed, its latency and its total, or with its failure's reason, and the source chosen, such as `source set pypi: https://pypi.org/simple 2.1 MB/s latency 180 ms total 1.00, https://mirrors.aliyun.com/pypi/simple timeout; chose https://pypi.org/simple`. | A slow install then shows in the log which source it used and what the others measured. |

What is probed differs by what the source serves:

| Source | The probe | What follows |
| --- | --- | --- |
| a file | a Range request for its first 1 MiB | the download, with the measures and the moves |
| a container image | a Range request for the first 1 MiB of its largest layer, which the registry's manifest for the image's digest and the manifest of its first Linux image name | Podman pulls `<source>@<digest>` from the first ranked; a pull that fails goes on to the next source. A source whose probe got no answer is pulled from after the ranked ones, in the artifact's order, and only a pull's own failure is listed in `download_failed` |
| an npm registry | a GET of the package's whole document, whose integrity it checks, then one GET of each of the `npm` set's `latency_probes` | npm runs with the first ranked as `--registry`; an install that fails runs again with the next |
| a source set a container lists | a Range request for the first 1 MiB of the set's `probe` file under each source | every variable of the set names the first ranked in the container's environment; the container's tools read it, and nothing moves later |
| a host an npm setting names | a Range request for the first 1 MiB of the setting's `hosts_probe` file under each host | the setting names the first ranked host; an install that fails on a native module runs again with the next |
| a version list or `latest.json` | a GET, which for a feed's version list waits up to 30 seconds for data at each wait | the fastest valid answer is read |

An image's probe can fail where its pull works, and Podman checks the
digest of every pull. On Windows the agent's probe verifies against the
roots the system has fetched so far, and a probe of docker.io failed
`CERTIFICATE_VERIFY_FAILED` while Podman in the machine pulled the image.

The hub's fetcher is `utils/source_fetch.py`, and it does all of this. The
agent's is `modules/shared/source_fetch.py`, standard library only: it
probes and ranks, since the agent downloads no file itself and hands the
chosen source to Podman, to npm or to a container's environment.
`install.sh` and `install.ps1` hold a small one each: they probe, rank the
sites that answered by the same total, the speed score and the latency
score half each, the latency being the probe's time to its first byte,
start on the first, and move on a stall, with no measures while a file
downloads. Their probe has 5 seconds for the answer and the bytes together.

## The file a probe reads

Each list names its probe file once, in the data file that holds the list.

| List | The file | Its size | Why the path holds |
| --- | --- | --- | --- |
| `pypi` | `/numpy/` | 1.3 to 2.4 MB | An index page is the one kind of file all four sources serve under `/simple`: pypi.org keeps the packages on another host. This page grows with each release. |
| `npm` | `/npm/-/npm-10.9.2.tgz` | 2.7 MB | A published version's tarball does not change. |
| `npm`'s `latency_probes` | `/wrappy`, `/once`, `/inherits` | 7 to 16 KB each | Each is the document of a small package that changes seldom, and every npm registry serves it at that path. |
| `huggingface` | `/openai-community/gpt2/resolve/607a30d783dfa663caf39e06633721c8d4cfcd7e/tokenizer.json` | 1.4 MB | A file at a commit does not change. | <!-- scan: allow -->
| `ctan` | `/systems/texlive/tlnet/tlpkg/texlive.tlpdb.xz` | 2.8 MB | The bytes change each day and the path does not: `tlmgr` reads this package database from the repository first. |
| better-sqlite3's hosts | `/v12.6.2/better-sqlite3-v12.6.2-node-v127-linux-x64.tar.gz` | 1.1 MB | A release's file does not change. |
| an image's registries | its largest layer, by its digest | the layer's | The digest names the bytes, and the layer goes only with the image. |
| CloudCLI's registries | the package's document | 220 to 296 KB | The install needs this document, and the probe checks its integrity. |
| a `hub` artifact | the artifact | the artifact's | The download takes this file. |
| Claude Code's and Codex's tarballs on the `npm` set | the tarball, `@anthropic-ai/claude-code-<platform>/-/claude-code-<platform>-{version}.tgz` and `@openai/codex/-/codex-{version}-<platform>.tgz` | 127 MiB and 164 MiB for linux-x64 | A published version's tarball does not change, and the download takes this file. |

| Rule | Reason |
| --- | --- |
| A source that no longer serves the file fails its probe, and is tried after the ranked sources. A file gone from every source leaves the list in its own order, the publisher's first, and the install goes on. An npm registry is the exception: when none names the integrity, the install fails `download_failed`. | A probe orders the sources, and the digest of what they serve decides the rest. |
| A hub test pins each name, the sets' in `test_source_sets.py` and the hosts' in `test_manifests.py`. No test reads the file upstream. | A name changes only together with its test, and a suite that needs the network fails for reasons of its own. |
| An image's probe reads a layer, and a registry that serves the manifest and no layer is left unranked. | From one host, `ghcr.m.daocloud.io` served every manifest and answered 503 for every layer, and `ghcr.nju.edu.cn` won 7 of 10 rankings on a 1.6 KB manifest while it reads a layer at a tenth of `ghcr.io`'s speed. |
| A list of one image source is not probed. | One source has no order to find. |
| A registry's token goes to the address asked and to no address it redirects to. | A registry redirects a layer to a storage host, a party the token is not for. |

## From the hub's cache

The hub's cache and the agent install a `hub` entry in steps, each with one
owner:

1. The cache fetches each artifact of the version the state names into the
   module cache, with the method of "Choosing a source", and writes
   `hub: fetching <file> from <host>` into the module's output.
1. The cache checks the digest and the head, keeps nothing that differs, and
   refuses a file larger than 2 GiB with `module_fetch_too_large`.
1. The agent opens `package {module, artifact, digest}` for each artifact,
   and the hub streams the cached file with that digest down
   ([transport.md](../transport.md), "The stream layer"), writing `hub:
   sending <title>, <sent> / <total> MB to <device>` into the module's output
   as it goes, `<device>` the machine's name in the panel.
1. The agent installs each artifact as its kind says, each in one step
   `artifact {name}`, and the system packages the entry names before them in
   one step `packages` ([../agent.md](../agent.md), "The steps").
1. The agent runs the entry's `verify` command; its success is `installed`.

| Rule | Reason |
| --- | --- |
| The cache names each file by its digest, and keeps every file of a version some machine names, with cc-switch's pinned files. It deletes the other files after it places a new one. | Two machines can run two versions of one module at once. |
| A machine names a module's version while its `modules.json` names the module with a `want` other than a settled `absent`: its chosen `version`, or the tested one while that is empty. | A machine that chose nothing follows the tested version. |
| On Windows `cmd.exe` runs `verify`, which is the program's quoted path with `--version`, such as `"%ProgramData%\Neutrino\agent\state\vscode\code.exe" --version`. | It fails when the file is missing. |
| On Linux, where SELinux is enforcing or permissive, the agent labels each module's unpack `bin_t` with `chcon -R -t bin_t` right after the unpack and at every apply of the module; the unpack of an artifact that names no directory is the module's directory. Where SELinux is disabled or absent, nothing is labelled. | The unpack under `/var/lib/neutrino/agent` is labelled `var_lib_t`, which systemd does not run: on Rocky 9 code-server, Codeg and VS Code exited 203/EXEC. A relabel of the whole system puts `var_lib_t` back, and the next apply undoes it. |
| The `verify` of a module installed from an `msi` or a `pkg` names the program where that installer puts it. | The system's installer chooses the place. |
| Containers on Windows and macOS uninstalls Podman only where the module installed it. Its install writes the mark `package_mark` in the module's directory before it hands Podman's msi or pkg to the system's installer, when Podman's program was not on the computer, and runs no installer on a Podman with no such mark. With no such mark the Podman is the person's: its uninstall leaves Podman installed, and the module reads `absent` through the uninstalled mark `uninstalled/podman`, whatever `verify` finds, until the next install's `verify` ([modules/containers.md](modules/containers.md), "A person's Podman and the module's"). | A Podman on the computer before the module is the person's, as a Samba is ("From the system's packages"). |

## From the system's packages

| Rule | Reason |
| --- | --- |
| A `system` entry names `packages`, with `pre_install` where the system needs a step first, and no download. | The system's package manager fetches, checks and updates its own packages. |
| The agent installs and removes the named packages with the system's package manager under the step lock `package_manager`, through one helper in `modules/shared/system_package.py` that waits up to 300 seconds for the system's own lock ([../agent.md](../agent.md), "The system's own lock"). | One package manager holds a machine-wide lock, and the system's own updaters take it without asking the agent; apt and dnf 5 fail at once on a held lock. |
| An entry names the packages the module runs and leaves out a package that adds a convenience. | `podman-docker` adds a `docker` command and conflicts with Docker CE over `/usr/bin/docker`, so naming it failed the install on a machine with Docker. |
| A unit a distribution installs disabled is enabled and started at the install and at every apply while the module's `want` is `running`, and the module's **Stop** disables it. Containers' `podman.socket` is that unit ([modules/containers.md](modules/containers.md)). | The software starts with the machine from its install on, on every distribution, and a stopped module stays stopped after a restart. |
| An uninstall removes the named packages and keeps the data: share directories and declared containers' volumes stay. The file share on Linux removes them only from a Samba the module installed: its install step records that it installed the package itself when the presence check found no Samba before it, and runs no package manager when it finds a Samba with no such record. With no such record the Samba is the person's, its uninstall removes no package, and the module reads `absent` through the uninstalled mark `uninstalled/samba`, whatever `verify` finds, until the next install's `verify` ([modules/file_share.md](modules/file_share.md), "A person's Samba and the module's, on Linux"). Containers on Linux removes `podman` only where the module installed it, the same way: its install writes the mark `package_mark` in the module's directory before the package manager runs, when Podman's program was not on the machine, and on a Podman with no such mark it installs no `podman` and its uninstall removes none, through `uninstalled/podman` ([modules/containers.md](modules/containers.md), "A person's Podman on Linux"). | The data is the person's, and the packages are the module's. A Samba or a Podman on the machine before the module is the person's, and its packages with it. |
| The version of a `system` entry is the system's, and no other can be installed. | The system's package manager updates its own packages. |

A `builtin` entry names software the system holds, such as the SMB server of
Windows and macOS. It names no `packages`, `verify` or `uninstall`, and the
runner checks for the software itself: the system installs and removes it,
and the module drives it. An uninstall leaves that software where it is, so the
agent keeps a root-only mark, `uninstalled/<module>` under the state root, from
the uninstall until the next install's `verify`. While the mark stands the
module reads `absent`, whether the state names it or not and across a restart
of the agent. A state that names no module, as after a join or a leave, deletes
every mark.

## From container images

A `container` module is one or more container images, which the Containers
module runs as hub containers. The hub composes them into the Containers
module's state, and Containers renders them as it renders a declared
container ([modules/containers.md](modules/containers.md), "Hub
containers").

| Rule | Reason |
| --- | --- |
| Each `image` artifact names `sources`, image references with no tag such as `docker.io/library/mongo`, and `digest`, the publisher's digest of the index that covers amd64 and arm64. | A digest pins the same bytes on every registry and mirror, and a tag moves. |
| The manifest has one `container` entry for each platform Containers runs on: `linux`, `windows-amd64`, `darwin-arm64` and `darwin-amd64`, all naming the same images, each built for amd64 and arm64. | Podman pulls the variant of the Linux it runs on: the machine's own on Linux, the Podman machine's on Windows and macOS. |
| The agent chooses a source for each image and has the Containers module's Podman pull `<source>@<digest>`; the hub caches no image. | An image is often several GB, and the machine reaches the registries itself. |
| A hub container names its image as `{digest, sources}`, and the agent renders the reference it finds in Podman's store with that digest. | An image pulled from a mirror is stored under the mirror's name. |
| Every entry of the module names `requires: ["podman"]` ("Dependencies"). The module's task waits for Containers in its first step, `wait_module {module: podman}`, and asks Containers for a configure task once its images are pulled, in its step `render` ([../agent.md](../agent.md), "A step that brings up another module"). | A container module runs on Containers' Podman, and two container modules share nothing but it. |
| Containers' **Stop** stops the hub containers with the declared ones, and each container module then reads `stopped`. | The containers stop with the engine that runs them. |
| The agent keeps the recipe of each container module that a state names with the `want` `installed`, `stopped` or `running`, root-only in `container_recipes/<module>.json` under the state root, and deletes it once the module's uninstall took. While no state names the module, as after the machine left its hub, the agent makes the module's runner from the kept recipe, at its start as well, and reads the module against it as it reads a module the state names ([../agent.md](../agent.md), "Leaving a hub, and joining again"). | The images are the module's presence, and only its recipe names them. In the lab a Debian 12 machine that joined its hub again by a new link had Ayakaleaf read `absent` while its three containers ran. |
| The module's data is in its named volumes, and it binds no host folder. | An uninstall removes everything the module wrote. |
| An uninstall stops and removes the module's containers, their units, its network and its named volumes, and the images no other container uses. A `container` entry names no `uninstall`. | A container module is removed whole, and a person's container on the same image keeps it. |
| A container module whose page needs a forwarder, or whose software needs a step after its first start, keeps `config.py`, `constants.py` and `hooks.py` under `modules/<module>/`, and the `container` runner calls them. | Hermes WebUI's login and its gateway keys are its own; the pull, the containers and the uninstall are the runner's for every container module. |

A container module that uses the AI gateway has a gateway key of its own
([modules/containers.md](modules/containers.md), "Reaching the machine").
The tools inside its containers fetch from the source sets its entry lists
("Source sets").

## One presence check

| Rule | Reason |
| --- | --- |
| The method's presence check is the one test that the software is there: `verify` for `system` and `hub`, every image's digest for `container`. On Windows and macOS, while Containers' machine does not answer the read, the digests are read from the list Containers saved at its last read ([modules/containers.md](modules/containers.md), "The keeper"). | Two checks that disagree give a module that is present and never `running`. A stopped machine lists no images. |
| A `verify` that names its program by an absolute path, as every `hub` entry's does, runs again only once that file changes its size, its time or its inode. A pass stands until then, and a failure runs again at the next read. | The agent reads every module at each report, every 5 seconds: on the lab Mac `gitea --version` and `code --version` each ran 12 times a minute as root. |
| `is_active` and `details` are read whenever the presence check passes, and a runner adds no check of its own in front of them. | A runner check stricter than `verify` read Containers as `stopped` with an empty list on a machine whose Docker CE kept `podman-docker` off. |
| A runner's own check answers only for a `builtin` entry and for a module the hub does not name in the machine's state, which the agent still observes and reports, such as a Samba a person installed by hand. A container module the state does not name is read against the recipe the agent kept ("From container images"). | Neither comes with a `verify` to run. |
| A `builtin` module reads absent while its uninstalled mark stands, whatever the runner's own check finds. | The system keeps its own software, so the runner's check stays true after an uninstall, and the row read `failed` `uninstall_unconfirmed` with no press that cleared it. |

## What an uninstall removes

An uninstall removes what its method's column of "Install methods" names,
and no folder but one of Neutrino's own.

| Rule | Reason |
| --- | --- |
| An uninstall removes only directories whose name shows they are Neutrino's: the module's directory under the state root, `agent/<module>/`, and the module's folder in an account's own Neutrino tree, `~/.local/share/neutrino/agent/<module>/` on Linux, `~/Library/Application Support/Neutrino/agent/<module>/` on macOS and `%LOCALAPPDATA%\Neutrino\agent\<module>\` on Windows ([module_template.md](module_template.md), "Disk layout"). A shared directory, `~/.local/bin`, `~/.local`, `~/.config`, an account's home or `/usr/local/bin`, is never removed, whoever made it, and only the module's own files in it go, such as a unit file, a launcher or a line. On Linux, writing a command line program's env file makes `~/.local/share` and `~/.local` for an account that had neither, and both stay after an uninstall, as every shared directory does; on macOS the env file sits in `~/Library/Application Support/Neutrino/agent/` and makes no `~/.local`. | A shared directory may hold the person's files, and one the module made may have been taken into use since. |
| A command line program's uninstall removes, for each account it enabled, its line from each startup file, and once no command line program names the account `env.sh`, `env.fish` and the Neutrino folders that hold nothing else; on Windows it removes the account's entry in the user `PATH` ([../agent.md](../agent.md), "The account's startup files"). | Each startup file is byte for byte what it was, and the person's copy stays as it is. |

## Module versions

A module's version follows its publisher's releases, apart from Neutrino's
own. `params.version` is the tested version: the one the manifest's
artifacts pin, and the one a machine installs while it chose no other or no
version list can be read.

| Rule | Reason |
| --- | --- |
| `params.releases` is how the hub lists the publisher's versions: a list of feeds, each `{kind, sources}` and the keys of its kind. The hub reads them once a day with the method of "Choosing a source", and keeps what it read in `module_releases.json` under its state root ([../files.md](../files.md)). | A daily read follows the publisher, and a read that fails leaves the last list and the tested version. |
| A feed's read waits up to 30 seconds for data at each wait, where a probe and every other fetch wait 5. | A feed can be a large document: GitHub's release list of Gitea is about 15 MB, and GitHub at times sends nothing for more than 5 seconds. In R170 a new hub's first read of it timed out at 5 seconds, while the same read with a 30 second wait took 6.7, 3.2, 2.2 and 47.6 seconds in four tries. |
| While a module whose entries name a feed holds no version list, the next read comes an hour after the last, and the reads stay hourly until every such module holds one; then they are daily again. A module whose list is held keeps it through a read that fails. | A new hub that misses one read holds no list, and would offer the tested version alone for a day. |
| The first feed lists the versions: the tags its template matches, each read as a dotted number, newest first. A tag that is no dotted number, such as a nightly build's, is not listed. | One feed decides what a version is. |
| A version's artifacts are the tested ones with `{version}` filled in, and each takes its digest from the feed whose release holds its file. An artifact whose `file` and `sources` hold no `{version}` keeps its own digest for every version, as WSL's msi, Node.js and Gitea's MinGit do. | A runtime pinned once serves every version of the program. |
| A version is listed for a platform only when every artifact of that platform's entry is found in it. | Podman publishes no 6.x package for an Intel Mac, so that entry lists 5.x alone. |
| A version newer than the tested one reads untested. | Neutrino has run the tested version and no newer one. |
| `config/devices/<id>/modules.json` holds each machine's chosen `version` per module, and empty follows the tested one. | The choice is per machine, as `want` is. |
| A `system` entry has one version, the system's, locked. An `agent` module follows the agent, and a `builtin` one the system. | Their software comes from outside the hub's cache. |
| A `container` entry that names no `releases` has one version, its tested one, locked as a `system` entry's is. | Hermes WebUI's two images run as one tested pair, and its publishers state no pairs ([modules/hermes_webui.md](modules/hermes_webui.md)). |
| Containers on a person's Podman on Windows and macOS has one version, the one `podman --version` prints, locked as a `system` entry's is ([modules/containers.md](modules/containers.md), "A person's Podman and the module's"). | The module installs no other version over a person's Podman. |
| A `container` version is a tag, which the `oci` feed resolves to the image's digest. | A digest pins the bytes, and the person chooses a tag. |
| In a `container` entry that names `releases`, the image whose `sources` name the `oci` feed's repository takes each version's digest from the feed, and every other image keeps its own digest for every version. | Ayakaleaf's MongoDB and Redis stay the same beside every version of its app, as WSL's msi and Node.js stay beside every version of their programs ([modules/ayakaleaf.md](modules/ayakaleaf.md)). |
| A module whose manifest says `is_data_forward_only` installs no version older than the newest it has run on the machine. The version dialog shows each such version greyed out, and **Follow the tested version** too while the tested version is older ([../ui_behavior.md](../ui_behavior.md), "The machine page"); `version/set` refuses one 409 `version_older_than_run {module, version, newest_run}` ([../protocol.md](../protocol.md), "`/api/agent/module`"). | Such software migrates its data at its first start on a newer version, and an older version cannot read the data then. In the lab Gitea 1.27.3 to 1.27.2 failed, and 28.0.0 back to the tested 1.27.3 failed, while 1.27.3 to 28.0.0 worked. |
| The newest run is the newest version at which the agent ran the module's `configure` step under `running`. The agent notes the recipe's version before the step runs, keeps it root-only in `newest_run/<module>` under the state root, and reports it on every row of the module as `newest_run`. A note stays whatever the start does after it. | The data moves forward at the new version's first start, before that start can fail, so a failed upgrade has moved it already. |
| An uninstall that keeps the data keeps the note, and one that removes the data removes it: a `hub` entry's `uninstall.is_data_kept` decides, and a `container` entry removes it. | The note describes the data, so the two go together. |
| The hub takes the newer of the row's `newest_run` and, on a row reading `running`, its installed version. | A version that runs has run, and an agent of an earlier build noted none. |
| No state the hub sends names a recipe older than the newest run of a module whose manifest says `is_data_forward_only`. Where the version the machine chose, or the tested one while it chose none, is older than the newest run, the state names the newest run's version in its place: the listed version's recipe, or the tested recipe when the newest run is the tested version. This holds for every state: a machine joined again by a new link after **Forget** that follows the tested version, a machine whose chosen version is older, and a state built from `modules.json` before any press. `modules.json` keeps the machine's choice. | Data the newest run moved forward breaks under an older version, whatever made the state name one. In the lab Gitea 28.0.0 back to 1.27.3 failed. |
| Where the newest run's version is not listed for the machine's platform, as before the feeds' first read on a hub set up again, the hub holds the module: its entry carries `is_taken_over`, so the machine installs, switches, starts and stops nothing of it, and a `container` module's containers are left out of Containers' `hub_containers`, so they stop and keep their volumes. The state that can name the newest run's recipe ends the hold. | The hub has no recipe of that version to send, and every recipe it has is older. Containers run on an older image they find in the store would run an older version on the data. |
| The hub reads the newest run from the machine's last report, and offers an agent its first state on a connection after that connection's first report. | A state composed before the report would not know the newest run. |
| A module without the flag installs any listed version, older ones too. | Its software reads the data every version wrote, or holds none. |

| Module | `is_data_forward_only` | Why |
| --- | --- | --- |
| Gitea | true | It migrates its database at its first start on a new version ([modules/gitea.md](modules/gitea.md)). |
| Ayakaleaf | true | The app runs its migrations at its first start on a new version, and its publisher supports no downgrade ([modules/ayakaleaf.md](modules/ayakaleaf.md)). |
| Codeg | true | Its server runs sea-orm-migration at its start, which refuses a database holding a migration the binary does not know, so an older Codeg does not start on data a newer one migrated. |
| CloudCLI | true | Its server migrates its database at each start: it merges `session_names` into `sessions` and drops `workspace_original_paths`, so an older version finds the tables it reads gone. |
| SiYuan | absent | Its kernel logs a downgrade at its start and goes on. |
| Hermes WebUI | absent | Its one version is locked. |

| Feed `kind` | Its keys | The versions | A version's digest |
| --- | --- | --- | --- |
| `github` | `repository`, `tag` such as `v{version}` | the repository's releases, drafts and prereleases left out | each asset's `digest` |
| `vscode_update` | `platform`, Microsoft's platform name such as `cli-alpine-x64` | Microsoft's list of stable releases | `sha256hash` for that version and platform |
| `oci` | `repository`, `tag` such as `{version}` | the registry's tags | the manifest digest the registry gives the tag |
| `npm` | `package` | the registry's versions of the package | `dist.integrity`, read from `registry.npmjs.org`: an `npm` artifact's from the version itself, and a `tar_gz` artifact's from the version whose `dist.tarball` path is the artifact's `file`, such as `0.166.0-linux-x64` for Codex's linux-x64 tarball at 0.166.0 ([modules/codex.md](modules/codex.md)) |

A feed's `sources` are the publisher's API addresses, such as
`https://api.github.com`.

| Rule | Reason |
| --- | --- |
| An `npm` feed asks for the package's short document, with `Accept: application/vnd.npm.install-v1+json`, which still holds each version's `dist`. | On 2026-11-04 the whole document of `@openai/codex` was 18.5 MB and its short document 5.4 MB, each naming 5,702 versions. |

Installing another version of a `hub` module replaces its files as one step:

| Rule | Reason |
| --- | --- |
| The agent keeps the version it installed in the module's record, and a recipe naming another version starts the switch. | The recipe holds the version the machine is to run. |
| Each artifact's new files are placed beside the old ones under `<directory>.new`; then the module's services stop, `<directory>` is renamed `<directory>.old` and `<directory>.new` takes its place, `verify` runs and the services start. The `.old` files go once the services run. | The paths in `verify` and in every service definition stay the same. |
| A failure before the rename leaves the old version as it was and removes the new files. | Nothing of the running version has changed yet. |
| A failure after the rename puts the old files back, starts the old version, and reports the module `failed` with `version_switch_failed {version, detail}`, `detail` being the failed step's output. The module's record keeps the old version, and the agent tries the switch again only when the module's entry changes, as after any failure. | The machine keeps a working module, and the report says which version failed and why. |
| An `msi` or a `pkg` is switched by uninstalling the old package and installing the chosen one, keeping the data. A person's Podman is neither uninstalled nor installed over, and stays at its own version. | Windows Installer and macOS's installer own their packages' files, and the person's Podman is the person's. |

## Dependencies

A module depends on another when its platform entry names it in
`requires`. The container modules are the modules that require one, and
each requires Containers alone.

| Rule | Reason |
| --- | --- |
| `requires` names modules alone, each once, never the module itself, and no version. | The required module's own entry decides its version on each machine. |
| Every `container` entry names `podman`. Every other module requires nothing: it reads only its own directory, and installs with no other module present. | A module that needs a runtime holds it, so two modules that need the same runtime each hold it. |
| Every name in `requires` is a module of the catalog. On each platform the agent reports, the Linux of no family among them, a module whose entry resolves while a module it requires resolves none reads unsupported ("The manifest"), and on the Debian, RHEL and Arch families, Windows and macOS every required module resolves. The names of every manifest form no cycle. The manifest tests check all three. | A press installs each required module first, and a cycle would make two tasks wait for each other. |
| **Install** or **Start** of a module first writes `want: running` on each module it requires whose `want` is another, which installs a required module that is absent. | The required module's install stays its own task, and **Install** again retries both. |
| The module's task waits for each module it requires in its first steps, `wait_module {module}` ([../agent.md](../agent.md), "A step that brings up another module"). | The required module runs before the module's first step that needs it. |
| **Uninstall** of a module is refused `module_in_use {modules}` while another module whose `want` is not `absent` requires it on the machine. | The modules that require it could no longer run. |
| A required module's **Stop** leaves each module that requires it reading `stopped`: Containers' **Stop** stops the hub containers with the declared ones ("From container images"). The hub writes no `want` of the modules that require it. | The state that starts the required module again plans their start. |
