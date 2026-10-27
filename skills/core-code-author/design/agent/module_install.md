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
| `license` | the licence the publisher gives the software |
| `corresponding_source` | the address of the source the licence asks for, with `{version}` where the version goes |
| `is_data_forward_only` | true when the software migrates its data forward and never back, as Gitea does; absent is false ("Module versions") |
| `uninstall_data` | `{is_deleted, text}`: what an uninstall does to the module's data, the line the uninstall dialog shows ([../ui_behavior.md](../ui_behavior.md), "The machine page"); `is_deleted` is true when the data goes with the module, and `text` is the line in each language of the panel, keyed `en` and `zh-CN` |
| `web_share` | `{guest_login}`, present for a module whose page a Web share can offer and absent for every other: `guest_login` is how the share's visitor is signed in, `app` for the app's own login page and `guest_account` for one account of the app per share, which the forwarder signs every visitor of that share in as ([module_template.md](module_template.md), "The run") |
| `platforms` | one entry per platform the module runs on |

A platform entry is `{runner, min_version, install}`:

| Key | Holds |
| --- | --- |
| `runner` | the agent runner that makes the machine match the module's `want` ([module_template.md](module_template.md), "How a module runs") |
| `min_version` | optional: the lowest system version the entry runs on, a dotted number the loader checks |
| `install` | `{method, params}`: the install method, and the parameters whose shape the method fixes |

| Rule | Reason |
| --- | --- |
| A platform key is `<os>-<family>-<arch>`, `<os>-<family>`, `<os>-<arch>` or `<os>`, tried in that order, and the first key the manifest names wins. | A `system` entry differs by distribution family, a download by architecture, and a `builtin` entry by system alone. |
| `resolve_platform_entry(manifest, platform)` in `modules/devices/manifests.py` is the one function that picks a machine's entry. The catalog's row, the machine page's tabs, the cache and the state's recipe all read it. | Two resolvers can disagree about which entry a machine has. |
| A machine whose platform has no entry, or whose system version is below the entry's `min_version`, cannot run the module. The machine page's catalog greys it out, and a press on it is refused `no_platform_build {module}` ([protocol.md](../protocol.md), "The modules section, one entry per module"). | A machine that reports no system version is not ruled out, since its floor is unknown. |
| The catalog shows the licence and the source address for a `hub` or a `container` entry alone. | The other methods install the system's own software or the agent's. |
| The loader refuses a manifest whose keys or `params` fall outside the shapes on this page, so a wrong file fails the suite. | The hub acts on a manifest as root on every managed machine. |
| Every manifest of a module a person can uninstall names `uninstall_data`, with a line in both languages; a module whose entries name the method `agent` names none. The loader refuses a manifest without it, and one whose `is_deleted` disagrees with its entries: true beside a `system` or `builtin` entry or a `hub` entry whose `is_data_kept` is true, false beside a `container` entry or a `hub` entry whose `is_data_kept` is false. | Every module's uninstall shows one dialog, and the line in it is the one place a person reads what happens to their data before it happens. |
| A line names the data by what the person keeps in it, and where it stays when it stays. `{data_dir}` in a line is the module's per-account data directory on the machine's system ([module_template.md](module_template.md), "Disk layout"), which the hub writes in before it sends the row. | A path is the answer to "where are my notes now"; the hub knows the machine's system, and one line serves all three. |
| A module names `web_share` only where its page hands a visitor the app and nothing more. code-server, VS Code, Codeg, CloudCLI, Hermes WebUI and SiYuan name none, and neither does any module without a page. | Each of those six signs its browser in as the machine's account or as the owner, so a share of one hands a visitor the owner's shell, files or notes. |
| Ayakaleaf names `{guest_login: guest_account}` ([modules/ayakaleaf.md](modules/ayakaleaf.md), "The guest account"). | The app has accounts of its own and shares a project with an account, so a visitor works in what the owner shares with that account and sees nothing else. |
| A declared app's `web` entry and a container's, declared or started by hand, are offered as they are, with `guest_login` `app`, and have no manifest. | The hub holds no login of theirs, so the visitor meets the app's own login page, the guard the person already set. |
| The loader refuses a `web_share` of another shape, and a `guest_login` outside the two. | A manifest decides what a visitor holds, so a wrong one fails the suite. |

`cc_switch.json` describes a tool and no module: it names `is_module: false`,
its version at the top level, and `artifacts` alone in each platform entry,
with no runner and no method. The catalog leaves it out, and the agent takes
it from the hub's cache for the machine's AI tools ([ai_tools.md](ai_tools.md)).

## Install methods

| `method` | `params` | Where the bytes come from | What puts them on the machine | Modules |
| --- | --- | --- | --- | --- |
| `agent` | `{}` | the agent's own package | the agent's install | Terminal, Remote desktop, the SSH server |
| `builtin` | `{}` | the system itself | nothing; the runner checks that the software is there | the file share on Windows and macOS |
| `system` | `{version: "system", packages, pre_install, verify, uninstall: {packages, post_uninstall}}` | the system's package repositories | the system's package manager, run by the agent | the file share, ZFS storage and Containers on Linux |
| `hub` | `{version, releases, artifacts, packages, verify, uninstall: {post_uninstall, is_data_kept}}` | the publisher's release, fetched into the hub's cache | the agent, from the `package` stream | Gitea, VS Code, code-server, CloudCLI, Codeg, SiYuan, Containers on Windows and macOS |
| `container` | `{version, releases, artifacts, source_sets}`, `releases` and `source_sets` optional | the registries each image's `sources` name | the Containers module's Podman | Hermes WebUI ([modules/hermes_webui.md](modules/hermes_webui.md)), Ayakaleaf ([modules/ayakaleaf.md](modules/ayakaleaf.md)) |

`pre_install` is optional, for a system that needs a step before its package
manager installs, such as a repository to add. A `hub` entry's `packages` is
optional too: the system packages the program needs beside its artifacts,
such as Gitea's `git` on Linux. The system's package manager installs them
before the artifacts, and an uninstall keeps them.

| | `agent` | `builtin` | `system` | `hub` | `container` |
| --- | --- | --- | --- | --- | --- |
| Present when | always | the runner's own check passes | `verify` exits 0 | `verify` exits 0 | every image's digest is in the Containers module's Podman, as the agent reads it there |
| `running` means | the module's own rule ([modules/terminal.md](modules/terminal.md), [modules/remote_desktop.md](modules/remote_desktop.md)) | the system's server runs the module's configuration | the module's unit is active | the module's service or instances run | every container of the module runs |
| An uninstall removes | nothing: the four presses are refused `module_not_optional` | what the module's own page names; the system keeps its server | the named packages and the configuration the hub wrote, keeping the data | the module's files, its service definitions and the forwarder's records, keeping the data | the module's containers, their units, its network and its named volumes, and the images no other container uses |
| A failed install reports | `reinstall_failed`, from the agent's own install | nothing, since nothing is installed | `install_failed {detail}` with the package manager's output | `download_failed {file, sources}` or `module_fetch_too_large` from the cache, then `install_failed {detail}` or the module's own code | `download_failed {file, sources}` when no source serves an image |
| The version | the agent's | the system's | the system's, locked | the tested one or the machine's choice | the tested tag or the machine's choice; the tested one, locked, where the entry names no `releases` |

Terminal, Remote desktop and the SSH server are in the agent's package on every system.
Their platform entries name the method `agent`, they are never in the Modules
page's picker, always a tab, and the four presses on them are refused
`module_not_optional` ([agent.md](../agent.md), "The kinds of module").

## Artifacts

An artifact is one file a `hub` or `container` entry installs:
`{name, kind, digest, sources}`, with `file` where its sources name it,
`directory` where its kind needs one, and `member`, the folder a `dmg` holds
the program in. An artifact whose sources are an
ecosystem's names `source_set`, the set's name, in place of `sources`
("Source sets").

| `kind` | The file | What happens to it on the machine |
| --- | --- | --- |
| `tar_gz`, `zip` | an archive | unpacked under `agent/<module>/<directory>/` in the state root and sealed |
| `binary` | one program, as Gitea publishes it | kept as the publisher's bytes where the module's own page says, and made executable |
| `msi` | a Windows Installer package | kept under `agent/<module>/<directory>/`, then installed with `installers.install_msi` |
| `pkg` | a macOS installer package | kept under `agent/<module>/<directory>/`, then installed with `installers.install_pkg` |
| `tar_zst` | a zstd-compressed tar, such as Podman's machine image for WSL | kept under `agent/<module>/<directory>/`, its path given to the module's program |
| `raw_zst` | a zstd-compressed disk image, such as Podman's machine image for applehv | kept under `agent/<module>/<directory>/`, its path given to the module's program |
| `dmg` | a macOS disk image, such as SiYuan's desktop build | attached with `hdiutil attach -nobrowse -readonly` at a temporary mount point; the folder `member` names is copied with `ditto` to `agent/<module>/<directory>/` and sealed, and the image is detached |
| `nsis` | a Windows installer made with NSIS that holds a 7z archive, such as SiYuan's | unpacked under `agent/<module>/<directory>/` by the system's `%SystemRoot%\System32\tar.exe`, which reads the 7z archive inside the installer, and sealed; nothing in the installer runs |
| `image` | a container image, its `sources` image references with no tag | pulled by the Containers module's Podman |
| `npm` | an npm package, named by `package`, its `source_set` the `npm` set | installed by npm, as the module's own page says |

| Rule | Reason |
| --- | --- |
| A digest is `sha256:<hex>`, and an `npm` artifact's digest is npm's `integrity` as the registry gives it, `sha512-<base64>`. | The digest pins the bytes on every source; npm checks its own integrity format. |
| The digest is the publisher's: the sha256 file it publishes, the `digest` GitHub's API gives a release asset, Microsoft's `sha256hash`, an OCI manifest digest, or npm's `integrity`. A mirror serves bytes and names no digest. | A mirror that names its own digest can serve anything. |
| The cache checks the head of each file before it keeps it: `msi` and `pkg` by the magic bytes it checks for the agent's own packages, `binary` by the ELF, Mach-O or PE header, the two zstd kinds by `28 b5 2f fd`, `nsis` by the PE header, and `dmg` by `koly` at the start of its last 512 bytes. | A source that answers with an error page passes no head check. |
| An archive whose members all sit under one top directory is unpacked without it, so its files sit directly under `<directory>`. | A path in `verify` and in a service definition stays the same for every version. |
| The unpack is owned by the agent's own account, root or SYSTEM, readable and executable by every account, writable by none, and on no `PATH`. | Every account runs the program, and none can change it. |
| The recipe the state holds for a `hub` entry drops each artifact's `sources`, since the bytes come down the `package` stream. A `container` or an `npm` artifact keeps its `sources` or its `source_set`, since the machine fetches it, and the state's `source_sets` section holds each set a recipe names. | The agent fetches only what the hub cannot send. |

A runtime a module needs, Node.js among them, is one of its artifacts,
pinned in its own manifest. Two modules that need the same runtime each hold
it.

## Sources

| Rule | Reason |
| --- | --- |
| Every address that serves the same bytes is in the one `sources` list of its download, or in the one source set of its ecosystem, which the download names ("Source sets"). No key names a country's or an edition's address. | The digest makes every source equal, so the fastest one serves. |
| A source names a file as `{file}`, the artifact's `file` with `{version}` filled in. | One template lists the same file on the publisher and on every mirror. |
| `{release}` names each release site the hub's build stamped, at the release the hub came from ([../../agent_work_rule/release.md](../../agent_work_rule/release.md), "Release sites"). A checkout has no stamp, so `{release}` names no source there. | The project's own release has one address per site, and the hub learns them only from its build. |
| The Containers module's docker.io mirrors stay the person's ordered list, which Podman applies under any `docker.io` source. | They are the person's configuration, and Podman already tries them in order. |

| Download | Fetched by | Its sources |
| --- | --- | --- |
| a `hub` artifact | the hub's cache | the publisher's address first, then each mirror that serves the same file, such as the USTC mirror of code-server and npmmirror's copy of Node.js; `{release}` last, where the project's release holds the file |
| Codeg's archives | the hub's cache | Codeg's GitHub release, the one address that serves them |
| SiYuan's desktop builds | the hub's cache | SiYuan's GitHub release, then the publisher's own `https://release.liuyun.io/siyuan/{file}` ([modules/siyuan.md](modules/siyuan.md)) |
| VS Code's CLI | the hub's cache | Microsoft's address alone, a list of one |
| Podman, its machine image and WSL | the hub's cache | each publisher's GitHub release |
| cc-switch | the hub's cache | its publisher's GitHub release, then `{release}` |
| another platform's agent package | the hub's agent cache | `{release}` ([../agent.md](../agent.md), "The agent's packages come from the hub") |
| a container image | the agent, for Podman to pull | each image reference the artifact names, the publisher's registry first |
| CloudCLI's npm package | the agent, for npm to install | the `npm` set |
| the packages a container's own tools fetch | the agent, into the container's environment | each set the module lists: Hermes WebUI's `pypi` |
| the TeX packages Ayakaleaf's first start adds | the agent, for `tlmgr` in the app's container | the `ctan` set, its fastest source on `tlmgr`'s command line ([modules/ayakaleaf.md](modules/ayakaleaf.md), "The first start") |
| better-sqlite3's prebuilt binary | the agent, for prebuild-install to fetch | its GitHub releases, then npmmirror's copy ([modules/cloudcli.md](modules/cloudcli.md)) |
| a module's version list | the hub, once a day | the publisher's API ("Module versions") |
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
    "probe": "/pip/",
    "sources": ["https://pypi.org/simple", "https://pypi.tuna.tsinghua.edu.cn/simple", "https://mirrors.aliyun.com/pypi/simple", "https://mirrors.cloud.tencent.com/pypi/simple"],
    "variables": ["PIP_INDEX_URL", "UV_DEFAULT_INDEX", "UV_INDEX_URL"]
  },
  "npm": {
    "probe": "/npm/latest",
    "sources": ["https://registry.npmjs.org", "https://registry.npmmirror.com", "https://mirrors.cloud.tencent.com/npm"],
    "variables": ["npm_config_registry", "YARN_NPM_REGISTRY_SERVER", "BUN_CONFIG_REGISTRY"]
  },
  "huggingface": {
    "probe": "/openai-community/gpt2/resolve/main/config.json",
    "sources": ["https://huggingface.co", "https://hf-mirror.com"],
    "variables": ["HF_ENDPOINT"]
  },
  "ctan": {
    "probe": "/systems/texlive/tlnet/tlpkg/texlive.tlpdb.sha512",
    "sources": ["https://mirror.ctan.org", "https://mirrors.mit.edu/CTAN", "https://mirrors.tuna.tsinghua.edu.cn/CTAN", "https://mirrors.ustc.edu.cn/CTAN", "https://mirrors.aliyun.com/CTAN", "https://mirrors.cloud.tencent.com/CTAN", "https://mirrors.sjtug.sjtu.edu.cn/ctan", "https://mirror.nju.edu.cn/CTAN"],
    "variables": []
  }
}
```

| Key | Holds |
| --- | --- |
| `probe` | the path the probe fetches under each source: a small document every source of the set serves |
| `sources` | the addresses, the publisher's first |
| `variables` | the environment variables the ecosystem's tools read the address from: pip and uv for `pypi`; npm, pnpm and Yarn 1 (`npm_config_registry`), Yarn 2 and later, and Bun for `npm`; the Hugging Face libraries for `huggingface`; none for `ctan`, since `tlmgr` reads its repository from its command line |

| Rule | Reason |
| --- | --- |
| Each ecosystem has one set, and every download from it names the set: an artifact by `source_set`, a `container` entry by `source_sets`. | Two lists for one ecosystem drift apart, and a mirror added to one reaches half the modules. |
| An artifact that names a set probes as its kind says: CloudCLI's npm artifact names `npm` and probes its own package's document. | The package being installed is the document that has to be there. |
| A `container` entry lists the sets its containers use in `source_sets`, and the hub copies the list into each hub container of the module. | The tools inside a container fetch from the network at their start, and the container's environment is where they read the address. |
| Before the agent writes a hub container's environment file, it probes each set the container lists and writes every variable of the set, with the fastest source, into the container's environment. | Which source is fastest depends on the machine's own network. |
| An environment value `{<set>}`, such as `{pypi}`, is the fastest source of that set, for a variable the set does not list. The set is one the module lists. | A tool that reads a variable of its own gets the same choice. |
| An apply whose one change to a container's environment file is a set's value keeps the file as it is. | The value is in the container's environment, so a new value restarts the container, and a source ranked first today is no reason to restart a running page. |
| The hub sends the sets the machine's recipes name in the state's `source_sets` section, and the agent probes them; nothing remembers a past result. | Only the machine measures its own network, and a network changes. |
| The loader rejects a `source_set`, a `source_sets` item or a placeholder that names a set the file does not define, and a placeholder that names a set its module does not list. | A wrong name fails the suite, and the agent resolves only the sets the state sends. |
| A set exists for an ecosystem a module fetches from. Go's module proxy, crates.io, conda channels and Ollama's library have none. | A set no module names is a list nobody keeps true. |
| A set with no `variables` is ranked when a module's hook asks for it, and the hook gives the fastest source to its tool on the tool's command line: Ayakaleaf's `tlmgr --repository`. | A tool that reads no variable for its address takes it where it reads it. |
| The `ctan` set's first source is CTAN's own redirector, then the MIT mirror and the mirrors at Tsinghua, USTC, Aliyun, Tencent, SJTU and Nanjing. Its sources can hold snapshots of TeX Live a day apart, and `tlmgr` checks every package it installs against the signed package database of the one source it reads. | In the lab the eight sources served two `texlive.tlpdb.sha512` a day apart, so no digest names the same bytes on every source, and the signature makes each source safe alone. |

better-sqlite3's prebuilt binary host serves that one package alone, so it
stays in CloudCLI's artifact as `hosts` ([modules/cloudcli.md](modules/cloudcli.md)).

## Choosing a source

One method chooses among the sources of every download:

| Rule | Reason |
| --- | --- |
| Every source is probed at once, and a probe waits at most 5 seconds for an answer. A file's probe asks for its first 1 MiB with a Range request. | A probe that small still measures a speed, and 5 seconds bounds the wait on a source that never answers. |
| The sources that answered are ranked by the probe's speed, measured from its first byte to its last, and the download starts on the fastest. Two speeds within a tenth of each other go to the earlier first byte. | Speed decides a large download, and the first byte decides between two equal ones. |
| While a download has at least 30 seconds left at its speed now, the fetcher measures the other sources every 30 seconds. Each measure is a 1 MiB Range request at the current offset, to every source that has not failed. | A short download ends before a change pays back; 1 MiB per source every 30 seconds costs a few percent of the transfer. |
| A source whose measure is at least 1.5 times the current source's speed over the last 10 seconds takes over. The download resumes there by a Range request at the current offset, and the next measure comes 30 seconds later. | A short probe measures low against a running transfer, and a smaller gap changes source on noise. |
| A source fails when it sends no byte for 20 seconds, answers with an error, or serves a file whose digest differs; the download resumes on the next ranked source by a Range request. A source that did not answer the probe in time has not failed, and the next measure asks it again. | The bytes are the same on every source, and a source slow to answer once can be the fastest later. |
| A source that answers a Range request with the whole file serves a download from its start alone, and is never moved to while a download runs. | It cannot resume at an offset. |
| The digest is checked when the last byte arrives. A mismatch drops that source and fetches the file again from the next one. | A source serving other bytes is wrong for this file alone. |
| When every source fails, the download fails `download_failed {file, sources}`, each source as `{source, reason, detail}`, `reason` being `unreachable`, `timeout`, `stalled`, `digest_mismatch`, `http_<status>` or `pull_failed`, and `detail` the tool's own last line where one exists. | A person reading the failure sees each address and why it failed. |
| Nothing remembers a past result: each download probes again. | A network changes, and a stored ranking outlives the network it measured. |

What is probed differs by what the source serves:

| Source | The probe | What follows |
| --- | --- | --- |
| a file | a Range request for its first 1 MiB | the download, with the measures and the moves |
| a container image | the registry's manifest request for the image's digest | Podman pulls `<source>@<digest>` from the fastest; a pull that fails goes on to the next source. A source whose probe got no answer is pulled from after the ranked ones, in the artifact's order, and only a pull's own failure is listed in `download_failed` |
| an npm registry | a GET of the package's document | npm runs with the fastest as `--registry`; an install that fails runs again with the next |
| a source set a container lists | a GET of the set's `probe` path under each source | every variable of the set names the fastest in the container's environment; the container's tools read it, and nothing moves later |
| a host an npm setting names | a GET of the host's base address | the setting names the fastest host; an install that fails on a native module runs again with the next |
| a version list or `latest.json` | a GET | the fastest valid answer is read |

An image's probe can fail where its pull works, and Podman checks the
digest of every pull. On Windows the agent's probe verifies against the
roots the system has fetched so far, and a probe of docker.io failed
`CERTIFICATE_VERIFY_FAILED` while Podman in the machine pulled the image.

The hub's fetcher is `utils/source_fetch.py`, and it does all of this. The
agent's is `modules/shared/source_fetch.py`, standard library only: it
probes and ranks, since the agent downloads no file itself and hands the
chosen source to Podman, to npm or to a container's environment.
`install.sh` and `install.ps1` hold a small one each: they probe, start on
the fastest, and move on a stall, with no measures while a file downloads.

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
   as it goes.
1. The agent installs each artifact as its kind says, and the system packages
   the entry names before them.
1. The agent runs the entry's `verify` command; its success is `installed`.

| Rule | Reason |
| --- | --- |
| The cache names each file by its digest, and keeps every file of a version some machine names, with cc-switch's pinned files. It deletes the other files after it places a new one. | Two machines can run two versions of one module at once. |
| A machine names a module's version while its `modules.json` names the module with a `want` other than a settled `absent`: its chosen `version`, or the tested one while that is empty. | A machine that chose nothing follows the tested version. |
| On Windows `cmd.exe` runs `verify`, which is the program's quoted path with `--version`, such as `"%ProgramData%\Neutrino\agent\state\vscode\code.exe" --version`. | It fails when the file is missing. |
| On Linux, where SELinux is enforcing or permissive, the agent labels each module's unpack `bin_t` with `chcon -R -t bin_t` right after the unpack and at every apply of the module; the unpack of an artifact that names no directory is the module's directory. Where SELinux is disabled or absent, nothing is labelled. | The unpack under `/var/lib/neutrino/agent` is labelled `var_lib_t`, which systemd does not run: on Rocky 9 code-server, Codeg and VS Code exited 203/EXEC. A relabel of the whole system puts `var_lib_t` back, and the next apply undoes it. |
| The `verify` of a module installed from an `msi` or a `pkg` names the program where that installer puts it. | The system's installer chooses the place. |

## From the system's packages

| Rule | Reason |
| --- | --- |
| A `system` entry names `packages`, with `pre_install` where the system needs a step first, and no download. | The system's package manager fetches, checks and updates its own packages. |
| The agent installs and removes the named packages with the system's package manager, one operation at a time, in `modules/shared/system_package.py`. | One package manager holds a machine-wide lock. |
| An entry names the packages the module runs and leaves out a package that adds a convenience. | `podman-docker` adds a `docker` command and conflicts with Docker CE over `/usr/bin/docker`, so naming it failed the install on a machine with Docker. |
| A unit a distribution installs disabled is enabled and started at the install and at every apply while the module's `want` is `running`, and the module's **Stop** disables it. Containers' `podman.socket` is that unit ([modules/containers.md](modules/containers.md)). | The software starts with the machine from its install on, on every distribution, and a stopped module stays stopped after a restart. |
| An uninstall removes the named packages and keeps the data: pools, share directories and declared containers' volumes stay. | The data is the person's, and the packages are the module's. |
| The version of a `system` entry is the system's, and no other can be installed. | The system's package manager updates its own packages. |

A `builtin` entry names software the system holds, such as the SMB server of
Windows and macOS. It names no `packages`, `verify` or `uninstall`, and the
runner checks for the software itself: the system installs and removes it,
and the module drives it.

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
| The module depends on Containers alone. Its install or **Start** sets Containers' `want` to `running` first, which installs Containers where it is absent. Containers' **Uninstall** is refused `module_in_use {modules}` while a container module is installed. | A container module runs on Containers' Podman, and two container modules share nothing but it. |
| Containers' **Stop** stops the hub containers with the declared ones, and each container module then reads `stopped`. | The containers stop with the engine that runs them. |
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
| The method's presence check is the one test that the software is there: `verify` for `system` and `hub`, every image's digest for `container`. | Two checks that disagree give a module that is present and never `running`. |
| `is_active` and `details` are read whenever the presence check passes, and a runner adds no check of its own in front of them. | A runner check stricter than `verify` read Containers as `stopped` with an empty list on a machine whose Docker CE kept `podman-docker` off. |
| A runner's own check answers only for a `builtin` entry and for a module the hub does not name in the machine's state, which the agent still observes and reports, such as a Samba a person installed by hand. | Neither comes with a `verify` to run. |

## Module versions

A module's version follows its publisher's releases, apart from Neutrino's
own. `params.version` is the tested version: the one the manifest's
artifacts pin, and the one a machine installs while it chose no other or no
version list can be read.

| Rule | Reason |
| --- | --- |
| `params.releases` is how the hub lists the publisher's versions: a list of feeds, each `{kind, sources}` and the keys of its kind. The hub reads them once a day with the method of "Choosing a source", and keeps what it read in `module_releases.json` under its state root ([../files.md](../files.md)). | A daily read follows the publisher, and a read that fails leaves the last list and the tested version. |
| The first feed lists the versions: the tags its template matches, each read as a dotted number, newest first. A tag that is no dotted number, such as a nightly build's, is not listed. | One feed decides what a version is. |
| A version's artifacts are the tested ones with `{version}` filled in, and each takes its digest from the feed whose release holds its file. An artifact whose `file` and `sources` hold no `{version}` keeps its own digest for every version, as WSL's msi and Node.js do. | A runtime pinned once serves every version of the program. |
| A version is listed for a platform only when every artifact of that platform's entry is found in it. | Podman publishes no 6.x package for an Intel Mac, so that entry lists 5.x alone. |
| A version newer than the tested one reads untested. | Neutrino has run the tested version and no newer one. |
| `config/devices/<id>/modules.json` holds each machine's chosen `version` per module, and empty follows the tested one. | The choice is per machine, as `want` is. |
| A `system` entry has one version, the system's, locked. An `agent` module follows the agent, and a `builtin` one the system. | Their software comes from outside the hub's cache. |
| A `container` entry that names no `releases` has one version, its tested one, locked as a `system` entry's is. | Hermes WebUI's two images run as one tested pair, and its publishers state no pairs ([modules/hermes_webui.md](modules/hermes_webui.md)). |
| A `container` version is a tag, which the `oci` feed resolves to the image's digest. | A digest pins the bytes, and the person chooses a tag. |
| In a `container` entry that names `releases`, the image whose `sources` name the `oci` feed's repository takes each version's digest from the feed, and every other image keeps its own digest for every version. | Ayakaleaf's MongoDB and Redis stay the same beside every version of its app, as WSL's msi and Node.js stay beside every version of their programs ([modules/ayakaleaf.md](modules/ayakaleaf.md)). |
| A module whose manifest says `is_data_forward_only` asks before it installs a version older than the one installed ([../ui_behavior.md](../ui_behavior.md), "The machine page"). | Gitea migrates its database forward at its first start, and an older Gitea cannot read it. |

| Feed `kind` | Its keys | The versions | A version's digest |
| --- | --- | --- | --- |
| `github` | `repository`, `tag` such as `v{version}` | the repository's releases, drafts and prereleases left out | each asset's `digest` |
| `vscode_update` | `platform`, Microsoft's platform name such as `cli-alpine-x64` | Microsoft's list of stable releases | `sha256hash` for that version and platform |
| `oci` | `repository`, `tag` such as `{version}` | the registry's tags | the manifest digest the registry gives the tag |
| `npm` | `package` | the registry's versions of the package | `dist.integrity`, read from `registry.npmjs.org` |

A feed's `sources` are the publisher's API addresses, such as
`https://api.github.com`.

Installing another version of a `hub` module replaces its files as one step:

| Rule | Reason |
| --- | --- |
| The agent keeps the version it installed in the module's record, and a recipe naming another version starts the switch. | The recipe holds the version the machine is to run. |
| Each artifact's new files are placed beside the old ones under `<directory>.new`; then the module's services stop, `<directory>` is renamed `<directory>.old` and `<directory>.new` takes its place, `verify` runs and the services start. The `.old` files go once the services run. | The paths in `verify` and in every service definition stay the same. |
| A failure before the rename leaves the old version as it was and removes the new files. | Nothing of the running version has changed yet. |
| A failure after the rename puts the old files back, starts the old version, and reports the module `failed` with `version_switch_failed {version, detail}`, `detail` being the failed step's output. The module's record keeps the old version, and the agent tries the switch again only when the module's entry changes, as after any failure. | The machine keeps a working module, and the report says which version failed and why. |
| An `msi` or a `pkg` is switched by uninstalling the old package and installing the chosen one, keeping the data. | Windows Installer and macOS's installer own their packages' files. |

## Dependencies

| Rule | Reason |
| --- | --- |
| A `container` module depends on Containers alone ("From container images"). | It runs on Containers' Podman. |
| Every other module depends on no other module: it reads only its own directory, and installs with no other module present. | A module installs and uninstalls by itself, so two modules that need the same runtime each hold it. |
