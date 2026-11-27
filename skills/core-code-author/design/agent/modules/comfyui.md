# The ComfyUI module

The `comfyui` module runs ComfyUI (GPL-3.0), Comfy Org's program that
generates images, video and sound from node workflows of diffusion models,
one instance per machine, on Linux, Windows and macOS on Apple silicon. Its
page and its API answer on `127.0.0.1` alone, behind the agent's forwarder.
One applier per system sits behind one runner in
`agent/neutrino_agent/modules/comfyui/`, and the layout, the Python
environment, the shared folders and the published `web` entry are the same
on every system. Its kind chip reads System service and its source chip
Upstream ([../module_install.md](../module_install.md), "The source chip
and the kind chip"). Its `accounts` reads `one`: it serves the machine's
default account ([../accounts.md](../accounts.md), "Which modules serve
which accounts").

| | Linux | macOS | Windows |
| --- | --- | --- | --- |
| Program | `comfyui/` under the state root, root's and sealed: `python/`, python-build-standalone's CPython; `uv/`, Astral's uv; `source/`, ComfyUI's source at the tested tag; `mcp/`, comfy-mcp's environment | the same | the same, with the Visual C++ runtime's DLLs in `python\` beside `python.exe` |
| Data | `comfyui_data/` under the state root, the account's, mode 700 with the default account's entries of "The shared folders": `venv/`, `uv_cache/`, `tmp/`, `pycache/` and `data/`, the shared folders ("The shared folders") | the same, the data directory being the account's home | `comfyui_data\` under the state root, LOCAL SERVICE's to change by inheritance beside SYSTEM and the administrators |
| Runs as | the system account `neutrino_comfyui` the module makes with `useradd --system`, the comment `neutrino comfyui`, no login shell and the data directory as its home, in the groups `render` and `video` where the machine has them | the hidden account `neutrino_comfyui`, made with `sysadminctl` as Ollama's is, with the full name `Neutrino ComfyUI`, the shell `/usr/bin/false` and the data directory as its home | LOCAL SERVICE |
| Service | `neutrino_comfyui.service` with `User=neutrino_comfyui` and `UMask=0027`, disabled at **Stop** and enabled at **Start** | the LaunchDaemon `com.neutrino.comfyui` with `UserName`, `GroupName` and `Umask` 23, its output in `/Library/Logs/Neutrino/agent/comfyui.log`, disabled with `launchctl disable` at **Stop** and enabled at **Start** | the scheduled task `neutrino_comfyui` run as LOCAL SERVICE, started at boot and again a minute after it stops, with no time limit, its output in `comfyui_data\comfyui.log`; disabled at **Stop** and enabled at **Start** |
| Listens on | `127.0.0.1` alone: ComfyUI at a port the agent takes from 15000 up, and its forwarder at a port the agent takes from 8188 up | the same | the same |

In every list of modules ComfyUI comes after Ollama, and the catalog lists
it under `other`, after AstrBot ([../../ui_behavior.md](../../ui_behavior.md),
"The machine page").

## The service

The service starts `venv/bin/python source/main.py --listen 127.0.0.1
--port <port> --base-directory <data directory>/data --enable-manager`,
`venv\Scripts\python.exe` on Windows, with `--cpu` under the CPU build
("The PyTorch build"). Its environment is written from scratch:

| Variable | Value |
| --- | --- |
| `HOME` | the data directory, on Linux and macOS |
| `TMPDIR`; `TEMP` and `TMP` on Windows | `tmp/` in the data directory |
| `PYTHONPYCACHEPREFIX` | `pycache/` in the data directory |
| `UV_CACHE_DIR` | `uv_cache/` in the data directory |
| `UV_PYTHON_DOWNLOADS` | `never` |
| `UV_NO_CONFIG` | `1` |
| `UV_STACK_SIZE` | `16777216`, on Windows |
| `PIP_INDEX_URL`, `UV_DEFAULT_INDEX`, `UV_INDEX_URL` | the first ranked source of the `pypi` set ([../module_install.md](../module_install.md), "Source sets") |

| Rule | Reason |
| --- | --- |
| `--base-directory` names `data/` in the data directory, and ComfyUI writes nothing into the module's directory. | The flag moves `models/`, `custom_nodes/`, `input/`, `output/`, `temp/` and `user/` together. In the lab ComfyUI 0.46.0 wrote nothing into the sealed source, and `user/` held `comfyui.db`, the Manager's `config.ini` and `comfyui_<port>.log`. |
| `PYTHONPYCACHEPREFIX` puts the bytecode of the source and the venv in `pycache/`. | The source is sealed, so Python cannot write its bytecode beside it. In the lab a start took 6.7 seconds with no bytecode and 4.3 seconds with this prefix. |
| On Windows the service runs as LOCAL SERVICE, never as SYSTEM, and the task names it by its SID, S-1-5-19, which the agent's PowerShell host turns into the account's name in the system's language. A move to SYSTEM waits for a person's report that LOCAL SERVICE cannot use a GPU (iffi, 2026-11-26). | A custom node is code the service runs, and LOCAL SERVICE holds no right over the machine. In the lab LOCAL SERVICE read the module's directory, wrote its data and ran ComfyUI on the CPU. No GPU of the lab could show whether LOCAL SERVICE reaches one. |
| On Windows the module's directory grants the Users group read and execute, inherited, as Codeg's and CloudCLI's do. | LOCAL SERVICE's token holds the Users group. In the lab an `icacls /reset` that dropped the entry left LOCAL SERVICE with "Access is denied". |
| `UMask=0027` on Linux and `Umask` 23 on macOS. | ComfyUI's own files are the service's and its group's alone, and the shared folders give the default account its access by their own entries ("The shared folders"). |
| A `configure` that runs the server waits until `GET /system_stats` answers on ComfyUI's port, at most 300 seconds, and otherwise fails `apply_failed {detail}`, the detail naming the port and the last line of the server's output. | In the lab a first start reached the page in 13 to 17 seconds on Linux and in 113 seconds on Windows with Microsoft Defender on; a later start took 4 to 7 seconds on Linux and 24 on Windows. |
| An apply whose one change to the service's environment is the `pypi` set's first ranked source keeps the unit, the LaunchDaemon and the task as they are. | A new value restarts ComfyUI, and the Manager reads the whole Comfy Registry again at each start, 3.4 minutes in the lab ("Custom nodes"). |
| The module adds no Microsoft Defender exclusion. | An exclusion stops the scan of the folders where a custom node writes code that runs. In the lab the first start on Windows took 40 seconds with exclusions and 113 without, and the PyPI part of the install 265 seconds against 958. |
| ComfyUI's own port answers every program on the machine, any local account's among them. Through ComfyUI's API a program runs a workflow, uploads a file, and installs a custom node through the Manager, whose code then runs as the service's account. The module opens no port in any firewall and filters no account, as Ollama's port is left ([ollama.md](ollama.md)). | ComfyUI has no login, and a loopback port has no filter by account: in the lab an account the module did not serve got HTTP 200 from `/system_stats` on Windows. No module fences the machine ([../../agent.md](../../agent.md), "Parallel, never take over"). |

## The Python environment

ComfyUI runs in a virtual environment of the module's own Python, which the
service's account makes with the module's uv from a lock that names every
package and every file's hash ([../module_install.md](../module_install.md),
"A Python environment"). `data/manifests/comfyui.json` names one tested
version of each artifact:

| Artifact | Kind | Tested version | Where it lands | Its digest |
| --- | --- | --- | --- | --- |
| `python` | `tar_gz` | CPython 3.13.18 of python-build-standalone's release 20261110, the `install_only_stripped` build | `comfyui/python/` | GitHub's `digest` of the asset, which the release's `SHA256SUMS` repeats |
| `uv` | `tar_gz`; `zip` on Windows | uv 0.13.9 | `comfyui/uv/` | GitHub's `digest` of the asset, which the release's `sha256.sum` repeats |
| `source` | `tar_gz` | ComfyUI 0.46.0 | `comfyui/source/` | `git-tree:<hex>`, the tree of the tag's commit ([../module_install.md](../module_install.md), "Artifacts") |
| `vc_runtime` | `zip`, on Windows alone | the PyPI wheel `msvc-runtime` 14.51.36231 | `comfyui\python\` | PyPI's sha256 of the wheel |
| `mcp` | `uv_lock` | comfy-mcp 0.11.0 and comfy-cli 1.28.0 | `comfyui/mcp/`, root's and sealed ("comfy-mcp") | the lock's sha256 |
| `venv` | `uv_lock` | ComfyUI's packages, ComfyUI-Manager 4.2.2 and the PyTorch build the settings name | `comfyui_data/venv/`, the service account's | the lock's sha256 |

| Rule | Reason |
| --- | --- |
| The module's Python is python-build-standalone's `install_only_stripped` build. | Unpacked it is 111 MB on Linux against 262 MB for the full build, and in the lab it ran ssl, sqlite3, ctypes and venv. |
| The venv is made with the module's uv as the service's account, `uv venv --python <module's python> <data directory>/venv`, with no seed. pip comes from the lock with its hash. | `--seed` fetches pip from the default index at no pinned version and with no hash. ComfyUI-Manager runs pip and uv from the venv. |
| The venv's lock installs in two parts: the packages its `# from` lines name under the `pytorch` set from that set's first ranked source, then the rest from the `pypi` set's, each with `uv pip install --require-hashes --no-deps --index-url <source>`; then `uv pip check`. `uv pip sync` never runs. | In the lab uv refused a file whose hash differed, printing both hashes, and a line with no hash. `sync` removes every package the lock does not name, pip and the packages of custom nodes among them. |
| The agent keeps the digest of the lock it installed in the module's record. A recipe that names another lock stops ComfyUI, removes `venv/`, makes it again and installs the new lock into it (iffi, 2026-11-26). | A new PyTorch build or a new tested version is a new lock. A lock installed over another leaves the packages only the old one named, another torch's among them. |
| After a new venv's lock and its `uv pip check`, each custom node's `requirements.txt` in `custom_nodes/` is installed again into the venv as the service's account, with `uv pip install -r` from the `pypi` set's first ranked source, as the Manager installs a node's packages. A node whose packages fail is logged, and the step goes on. | The new venv holds the lock's packages alone, and a custom node imports its own at ComfyUI's start. One node's broken requirements stop no other node and no ComfyUI. |
| The venv's `python` names the module's `python/`. A new Python of the same minor version keeps the venv, and a new minor version makes it again. | A venv runs the base Python at the path it was made with. |
| On Windows the agent runs uv as LOCAL SERVICE in a one-shot scheduled task, with `UV_STACK_SIZE=16777216` and its output to a file in the data directory. | In the lab uv crashed with `0xC0000409` as LOCAL SERVICE with the default stack, and again through PowerShell's own redirect of its output; with the variable and its output in files it finished every time. |
| Every uv command the agent runs as the service's account runs under umask 077. | In the lab uv made `venv/` with mode 755 under the agent's umask, which let the default account read it through its entry on `comfyui_data/`. |
| On macOS every command the agent runs as the account starts in the data directory. | In the lab uv started from a folder the account cannot enter failed with "Current directory does not exist". |
| On Windows the files of `vc_runtime`'s `msvc_runtime-<version>.data/data/` are copied beside `python.exe` before the seal, each that the Python does not carry itself. | torch failed with `WinError 126` on `c10.dll` in the lab: the Python carries `vcruntime140.dll` and `vcruntime140_1.dll` alone, and torch also needs `msvcp140.dll` and its kin. The wheel is a third party's repackaging of Microsoft's files under PyPI's hash, and it changes nothing of the system; Microsoft's `vc_redist.x64.exe` installs for the whole system and publishes no hash. |
| ComfyUI's source is GitHub's archive of the tag, `https://codeload.github.com/Comfy-Org/ComfyUI/tar.gz/refs/tags/v{version}`, checked against the tree hash of the tag's commit. | ComfyUI publishes no digest of its source: the tag is lightweight and unsigned, the release holds the Windows portable 7z alone, and PyPI's `comfyui` is a placeholder. The tree hash is the publisher's own git object id, and it holds whatever compression GitHub serves. In the lab a script of 40 lines of the standard library computed the tree `2bd4ec8b…` of 0.46.0 in 0.4 seconds. |
| The hub's cache holds no wheel: the machine's uv fetches each file of a lock from the ranked source. | torch's AMD build alone is 6.2 GB, past the cache's 2 GiB a file, and an environment is about a hundred files. |
| `verify` runs the module's own Python, `python/bin/python3 --version`, `python\python.exe --version` on Windows, and never the venv's. | The venv is the service account's, and a custom node can change it, torch included. Root runs no program another account can change ([../module_install.md](../module_install.md), "One presence check"). |

### The locks

| Rule | Reason |
| --- | --- |
| One lock is compiled ahead per PyTorch build and platform, with `uv pip compile --generate-hashes --python-version 3.13 --python-platform <triple> --torch-backend <build> --emit-index-annotation --exclude-newer <date>`, from ComfyUI's `requirements.txt`, its `manager_requirements.txt`, `torchaudio` and `pip`. | A lock takes at most 3 seconds on any machine. `--exclude-newer` fixes it to the files published by that date, and `--emit-index-annotation` writes the `# from` line that splits it. |
| The Mac lock is compiled with `MACOSX_DEPLOYMENT_TARGET=14.0` against PyPI alone. | torch from 2.12 publishes `macosx_14_0` wheels alone, and `--torch-backend cpu` chose torch 2.11.0 on macOS. |
| A lock is in the requirements format, every file of each version with its hash, and sits beside the manifest as `data/manifests/comfyui/<version>/<build>_<platform>.txt`. | The requirements format names hashes and no address, so any source of a set serves it. `pylock.toml` names one absolute address per wheel, which a mirror needs rewritten. |
| comfy-mcp's lock holds 73 packages, its environment 344 MB on Linux, installed as root with wheels alone and sealed. | comfy-mcp runs as the default account, and a sealed environment is one the account cannot change ([../module_install.md](../module_install.md), "A Python environment"). |

### The PyTorch build

The settings' `torch_build` names which PyTorch the venv's lock holds:

| `torch_build` | For | Index under the `pytorch` set | torch | Platforms | Download |
| --- | --- | --- | --- | --- | --- |
| `nvidia` | NVIDIA GPUs | `/cu132` | 2.15.0+cu132 | Linux amd64 and arm64, Windows | 3.9 to 4.0 GB on Linux, 3.0 GB on Windows |
| `amd` | AMD GPUs on Linux | `/rocm7.2` | 2.14.1+rocm7.2 | Linux amd64 | 7.5 GB |
| `intel` | Intel Arc GPUs | `/xpu` | 2.15.0+xpu | Linux amd64, Windows | 3.4 GB on Linux, 2.3 GB on Windows |
| `cpu` | every machine | `/cpu` | 2.15.0+cpu | Linux amd64 and arm64, Windows | 1.0 to 1.1 GB |
| none, on a Mac | Apple silicon | PyPI alone | 2.15.0 | macOS 14 or later, arm64 | 0.9 GB |

| Rule | Reason |
| --- | --- |
| At **Install** the hub writes `torch_build` into `comfyui.json` from the machine's last report, under the same hold of `CONFIG_WRITE_LOCK` as the `want`: `nvidia` while a card is NVIDIA's, else `amd` on Linux while a card is AMD's, else `intel` while a card is Intel's and its name holds `Arc`, else `cpu`. A Mac's file names none. The tab's **Settings** changes it ([../../ui_behavior.md](../../ui_behavior.md), "The machine page"). | `config/` is the one source of truth. A build read from each report installs another torch, gigabytes of it, at the first report that misses a card. An Intel card with no `Arc` in its name is the graphics of a processor, which the `xpu` build does not serve (the main session, 2026-11-26). |
| NVIDIA's build is cu132. | torch 2.15.0 has no cu130 build, which stops at 2.14.1, and cu132 gives the same torch as the CPU and Intel builds. |
| An AMD GPU on Windows takes the CPU build. | AMD's Windows index serves no sha256 and no upload date, so no lock pins its files, and under uv's first index rule 11 common packages, numpy and pillow among them, came from AMD's copies in the lab. |
| No entry names an Intel Mac or Windows on arm64, and no build serves Ascend, Cambricon or Iluvatar GPUs. | PyTorch publishes no x86 macOS wheel from 2.5 on. The other GPUs are out of the module's scope (iffi, 2026-11-22). |
| The macOS entry names `min_version` 14. | torch from 2.12 publishes `macosx_14_0` wheels alone, above the agent's 13 ([../../min_support.md](../../min_support.md)). |
| The lab runs the CPU build alone. Every GPU build is locked, and installs on a person's machine; a person's report shows whether it runs. | No GPU of the lab can run a test, and the module is complete once each build locks (iffi, 2026-11-22). |

## The shared folders

`data/` is one workspace for everyone who uses ComfyUI on the machine.
ComfyUI has no login, and the module runs no `--multi-user`, which splits
`user/` alone and leaves the outputs, the inputs, the queue and the history
shared. The service's account owns every folder, and the default account
reaches what the table names:

| Folder | The default account | The service's account |
| --- | --- | --- |
| `data/models/`, `data/input/`, `data/output/` | reads and writes | reads and writes |
| `data/user/`, `data/custom_nodes/` | reads | reads and writes |
| `data/temp/`, `venv/`, `uv_cache/`, `tmp/`, `pycache/` | nothing | reads and writes |

| Rule | Reason |
| --- | --- |
| The default account writes `models/`, `input/` and `output/`. | comfy-mcp's `download_model` writes into the account's workspace, whose `models` is the shared folder ("comfy-mcp"). In the lab an account's comfy-mcp downloaded a 1.54 GB checkpoint there in 74 to 92 seconds, and the service listed and loaded it with no restart. A person deletes and sorts outputs. |
| `user/` and `custom_nodes/` are read-only to the default account. | `user/` holds the Manager's `config.ini` with its security level, the settings and `comfyui.db`, and a journal file an account owns there blocks the service's writes. A custom node is code the service runs, so an account that writes `custom_nodes/` runs its own code as the service past the Manager's security level. comfy-mcp's `get_logs` reads `user/`. |
| `temp/`, `venv/`, `uv_cache/`, `tmp/` and `pycache/` are the service's alone. | An account that writes the venv can replace a locked package the service then runs. comfy-mcp runs from its own sealed environment. |
| No account but the default reaches any of them. | The module serves the default account alone ([../accounts.md](../accounts.md), "Which modules serve which accounts"). |
| While the machine has no default account, no account reaches the folders, and no tool names comfy-mcp. | The module serves no account until the machine has its default ([../accounts.md](../accounts.md), "A machine with no default"). |

Each system gives the default account its access by an entry for that one
account:

| | Linux | macOS | Windows |
| --- | --- | --- | --- |
| The way in | an access entry `u:<account>:--x` on `comfyui_data/` and `u:<account>:r-x` on `data/` | an access entry allowing `search` on `comfyui_data/` and `list,search` on `data/` | `<account>:(S,X,RA)` on `comfyui_data\`, inherited by nothing, and read and execute on `data\` |
| The write folders | the access entries `u:<account>:rwx` and `u:neutrino_comfyui:rwx`, each also a default entry, and the mask `rwx` with its default | an inherited entry for each of the two accounts allowing `list`, `add_file`, `search`, `delete`, `add_subdirectory`, `delete_child`, `readattr`, `writeattr`, `readextattr`, `writeextattr` and `readsecurity` | `<account>:(OI)(CI)M` |
| The read folders | `u:<account>:r-x`, also a default entry | an inherited entry allowing `list`, `search`, `readattr`, `readextattr` and `readsecurity` | `<account>:(OI)(CI)RX` |

| Rule | Reason |
| --- | --- |
| The default account's access is an entry for that one account on every system, and the module adds the account to no group. | An entry takes effect at once in every process of the account, where a group added on Linux reaches the processes of a new login alone. It changes nothing of the person's account ([../../agent.md](../../agent.md), "Parallel, never take over"). |
| On Windows the default account passes through `comfyui_data\` and reads its attributes by its own entry there, and loses the entry where it loses the others. | PowerShell's `Remove-Item`, `Move-Item` and `Get-Item` read the attributes of every folder above a file. In the lab, with no entry on `comfyui_data\`, PowerShell refused the default account's own files in `models\` with `Access is denied`, while `del`, `ren` and .NET's `File.Delete` worked. The Users group holds the same right on `agent\` and `state\`. |
| A file written into a write folder takes the folder's entries: on Linux the default entries stand in for the umask, on macOS and Windows the inherited entries are on every new file. | In the lab comfy-cli's downloads came out readable and writable by both accounts on all three systems, and a plain write under umask 077 still gave the group read and write on Linux. |
| Every `configure`, which runs at each **Start** and at each apply of the module's state, writes the entries again on every file and folder under `models/`, `input/`, `output/`, `user/` and `custom_nodes/`. | A file moved in from a home keeps the home's permissions: in the lab such a file stayed the account's alone on Linux and macOS and kept its profile's access list on Windows, and the service could not read it. A file made with mode 600 and renamed in, as `mkstemp` makes one, gave the service nothing on Linux. |
| The walk opens each folder by descriptor and follows no link on Linux and macOS, and opens each by handle with no reparse point followed on Windows. A link or a junction keeps its own entries. | The default account can put a link in a folder it writes, and the agent writes the entries as root or SYSTEM ([../module_template.md](../module_template.md), "What `modules/shared/` holds", `handle_walk.py`). |

## comfy-mcp

comfy-mcp (AGPL-3.0-or-later, or Comfy Org's commercial licence) is Comfy
Org's MCP server: a coding agent searches, downloads and runs models and
workflows through it. It calls comfy-cli (GPL-3.0) for each of its tools.
Both are in the module's `mcp/` environment, root's and sealed.

| Rule | Reason |
| --- | --- |
| The default account's Claude Code, Codex and OpenCode each name one MCP server, `comfyui`, while ComfyUI is installed and that tool's module is installed on the machine. The server is the program `mcp/bin/comfy-mcp`, `mcp\Scripts\comfy-mcp.exe` on Windows, with the environment below. No other account's tools name it. | The default account alone writes the shared models, which `download_model` needs. Each file is written as the account ([../../agent.md](../../agent.md), "Acting for an account"). |
| The models a tool drives comfy-mcp with follow the default account's AI switch, as every tool of the account does ([../ai_tools.md](../ai_tools.md)). comfy-mcp itself calls no model and holds no gateway key. | Comfy Org's own agent runs on Comfy's cloud alone and is paid in Comfy credits, and the hub's gateway serves the person's own models. |
| The environment is `COMFY_BIN`, `mcp/bin/comfy`; `COMFY_LOCAL_URL`, `http://127.0.0.1:<ComfyUI's port>`; `COMFY_PROJECT`, the account's workspace; `DO_NOT_TRACK=1`; and on a Mac with no usable `git`, as Gitea reads one ([gitea.md](gitea.md)), `GIT_PYTHON_REFRESH=quiet` with `GIT_PYTHON_GIT_EXECUTABLE` naming a path that does not exist. | comfy-cli reaches a ComfyUI it did not start at `COMFY_LOCAL_URL`. `COMFYUI_URL` names a ComfyUI on another machine, and with it `download_model` refuses. comfy-cli carries PostHog and Mixpanel, which send its usage unless `DO_NOT_TRACK` is set. GitPython stops at import on macOS's `/usr/bin/git` placeholder, and `quiet` alone did not stop it in the lab. |
| The server's `COMFY_LOCAL_URL` follows the port the module's record keeps for ComfyUI. Each `configure` reads each tool's file as the account and writes the `comfyui` entry again where it is missing or differs, a changed port among them; an entry that is already right is left, and nothing else of the file changes. | The agent takes ComfyUI's port ("The service"). The AI tools' switch back puts a tool's file back as it was before its first switch, which can predate the entry ([../ai_tools.md](../ai_tools.md)). |
| After the last cc-switch run of an AI tools switch and of its switch back, the agent takes out of Claude Code's, Codex's and OpenCode's files, as the account, a `comfyui` entry whose program file is not there. | cc-switch takes the account's MCP servers into its own store at its first run and writes them into every tool's file at each run. In the lab, after ComfyUI's uninstall, the switch back left the entry in Codex's `config.toml` in cc-switch's own shape and in Claude Code's `~/.claude.json`, a file no switch keeps. |
| Neither the service nor comfy-mcp is given `HF_ENDPOINT`, and the module names no `huggingface` set (the main session, 2026-11-26). | The module downloads no model itself: a model comes from the address a person, a workflow or a tool names. |
| The workspace is `comfyui/workspace/` in the default account's own Neutrino tree ([../module_template.md](../module_template.md), "Disk layout"), made as the account. `main.py`, `nodes.py`, `comfy/`, `comfy_extras/` and `comfy_api/` in it link to the sealed source, and `models/`, `input/`, `output/`, `user/` and `custom_nodes/` to the shared folders. On Windows the folders are junctions and the two files copies, written again when the source changes. | comfy-cli takes a folder for ComfyUI when it finds 4 of those 5 names, and comfy-mcp starts every comfy-cli call in `COMFY_PROJECT`, so `download_model` writes into the shared `models`. A standard account cannot make a link to a file on Windows. comfy-cli keeps its download records in the workspace's `.comfy-downloads`, mode 700. |

Each tool keeps the server in its own list of MCP servers:

| Tool | The file | The entry |
| --- | --- | --- |
| Claude Code | `~/.claude.json` | `mcpServers.comfyui`, `{type: stdio, command, args: [], env}` |
| Codex | `~/.codex/config.toml` | `[mcp_servers.comfyui]` with `command`, `args` and `env` |
| OpenCode | `~/.config/opencode/opencode.json` | `mcp.comfyui`, `{type: local, command: [<program>], environment, enabled: true}` |

The tools against the service, from the lab on Linux and Windows:

| Tool | Against the module's ComfyUI |
| --- | --- |
| `which`, `server_info`, `system_stats`, `search_models`, `nodes`, `search_templates`, `validate_workflow`, `run_workflow`, `job`, `free_memory` | work |
| `download_model` | writes into the shared `models/`; a 1.54 GB checkpoint in 74 to 92 seconds |
| `upload_file` | the service writes the file into `input/` |
| `fetch_outputs` | copies the outputs into the account's own folder |
| `get_logs` | reads `user/comfyui_<port>.log` |
| `install_node` | refused before it acts: comfy-cli finds no ComfyUI-Manager in the workspace, and nothing is installed |
| `launch_comfyui` | refused `port_in_use` while the service runs; while it is stopped, refused for the log it cannot open in `user/`, and nothing starts |
| `stop_comfyui` | refused `no_background_server`, and the service runs on |
| `generate_image` | runs its own graph, `image_z_image_turbo`, and refuses `checkpoint=` |

`update_comfyui`, `switch_comfyui_version` and `restart_comfyui` were not
run in the lab.

## Custom nodes

| Rule | Reason |
| --- | --- |
| A custom node goes in through ComfyUI-Manager in the page, which runs as the service: its files land in `custom_nodes/`, and its packages in the venv through the venv's uv, at no pinned version and with no hash. | The Manager is the one writer of `custom_nodes/` ("The shared folders"). In the lab it installed ComfyUI-GGUF 1.1.10 from cdn.comfy.org in 5 to 10 seconds on Linux and in 45 on Windows, with gguf, sentencepiece and protobuf from the `pypi` set's first source. |
| The Manager keeps its own defaults, `use_uv = True`, `security_level = normal` and `network_mode = public`, and the module writes nothing of its `config.ini`. | The page's own settings change them, and `user/` is the service's to write. |
| At each start the Manager reads the whole Comfy Registry from api.comfy.org, and a node's install fails with "is not a CNR node" until the read ends. | The registry comes 30 entries a request: 3.4 minutes in the lab. |
| A custom node's packages can replace a locked package in the venv, torch among them. | The Manager installs a node's requirements into the same venv, and a node names no hash. |

## Idle unload

A model ComfyUI loaded stays in memory after the job that loaded it. The
setting `idle_unload` takes it out after a time with no job: `5m`, `30m`,
`1h`, `4h`, or `-1` for never, `30m` while `comfyui.json` names none.

| Rule | Reason |
| --- | --- |
| Every 60 seconds while ComfyUI runs and `idle_unload` is not `-1`, the agent reads `GET /queue` and `GET /history?max_items=1` on ComfyUI's port. When `queue_running` and `queue_pending` are empty and the newest entry of the history ended at least `idle_unload` ago, it sends `POST /free` with `{"unload_models": true, "free_memory": true}`, once for that entry. A history with no entry, as after a restart, sends nothing. | In the lab memory fell from 4.8 GB to 2.2 GB two seconds after `/free`. A `/free` sent while a job ran waited for it, and the job's image came out whole. The hub holds no forward to ComfyUI, and the agent reaches its port on loopback. |
| The unload is no restart. | A restart brings memory to about 600 MB, but the Manager reads the registry again for 3.3 minutes. |
| `idle_unload` is `30m` by default, as Ollama's `keep_alive` is ([ollama.md](ollama.md)). | The next image after an unload pays the model's load again: 34 seconds against 32 for a cold load in the lab. Half an hour keeps a model through a pause in a session of work. |
| A changed `idle_unload` restarts nothing. | The agent reads it; ComfyUI does not. |

## The settings are the hub's

The hub keeps `{torch_build, idle_unload}` in
`config/devices/<id>/comfyui.json`, beside the forwarder's token secret,
sealed under the vault's data key, which the hub generates the first time
the module is installed. The state's `config` is `{secret, cookie_name,
local_name, torch_build, idle_unload, account, password, tools}`: `account`
the machine's default account, empty while it has none, `password` its
login on Windows alone, and `tools` the modules among `claude_code`, `codex`
and `opencode` whose `want` is not `absent` ([../../protocol.md](../../protocol.md),
"The modules section, one entry per module").

| Rule | Reason |
| --- | --- |
| A changed `torch_build` names another lock in the recipe, and the module installs it with ComfyUI stopped ("The Python environment"). | Each build is its own lock. |
| The module's version is locked to the tested one: its entries name no `releases` ([../module_install.md](../module_install.md), "Module versions"). | A lock exists for the tested version alone, and a version with no lock installs with no hash. A new tested version reaches the machines in a hub release. |

## The page

The page is the `web` entry of the app `comfyui_<device id>`, titled
`ComfyUI`, the entry's id `comfyui_<device id>_web`, with
`is_token_required: true` and `description_code` `comfyui_module`. The
entry exists while the module reads `running`. The manifest names
`web_share: {guest_login: run_account}` ([../module_install.md](../module_install.md),
"The manifest").

ComfyUI has no login of its own, so the forwarder's own login cookie admits
the browser:

| A request | The forwarder |
| --- | --- |
| holds `?tkn=<token>` that verifies | sets the forwarder's login cookie, named by `cookie_name`, and redirects to the same path without the token |
| holds `?tkn=<token>` that does not verify, has expired or was spent | 401 |
| holds the login cookie with a good signature and expiry | passed on unchanged, `Host` and `Origin` as the browser sent them, WebSockets included |
| holds neither | 401 |

| Rule | Reason |
| --- | --- |
| The login cookie is `base64url(expiry \|\| HMAC-SHA256(key, expiry))` with the key derived from the module's secret, HttpOnly and SameSite=Lax, and lasts seven days, the shape of Codeg's ([codeg.md](codeg.md)). | The cookie is the page's one login, its files, its API and its WebSocket included. |
| The cookie's name is the entry's `cookie_name`, `neutrino_` and the first 12 hex characters of the SHA-256 of the entry's id ([../module_template.md](../module_template.md), "The run"). | Two machines' ComfyUI pages at two local ports of one client keep both logins only under two names. |
| ComfyUI's own port is in no entry, and no `connect` stream serves it. | Every request from a client reaches ComfyUI through the forwarder's check. |
| A visitor of an App share works in the whole workspace, as the owner's clients do, and can install custom nodes through the Manager. | ComfyUI has one workspace and no account of its own. |

**What a report reads.** `details` is `{is_running, port, version}`:
`is_running` whether `GET /system_stats` answers on ComfyUI's port within a
second, `port` the forwarder's, and `version` the tested version the
module's record keeps. No report carries a model.

## Uninstall

**Uninstall** takes the unit, the LaunchDaemon or the task, the module's
directory, the forwarder's record, the `comfyui` entry of each tool and the
default account's workspace. It keeps `data/`, with the models, the inputs,
the outputs, the custom nodes and `user/`, and removes `venv/`,
`uv_cache/`, `tmp/` and `pycache/`, and on Windows `step.log`, the file
uv's output went to; `comfyui.log` stays with `data/`. The manifest's
`uninstall_data` names `is_deleted: false`.

| Rule | Reason |
| --- | --- |
| The account `neutrino_comfyui` stays on Linux and macOS, as Ollama's does ([ollama.md](ollama.md)). | It owns `data/`, and the next install runs as it again. |
| The venv and the caches go at the uninstall. | They are the module's software, several gigabytes of it, and the next install makes them again from its lock. |
| An `account` step that finds the data directory owned by another uid gives it to the account by open descriptor, following no link, as Ollama's does. | An account removed by hand and made again has another uid. |

The module's journal is the unit's journal on Linux and the end of its
output file on macOS and Windows, then the agent's lines that name it
([../../agent.md](../../agent.md), "Which modules each system runs").
