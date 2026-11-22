# The Ollama module

The `ollama` module runs Ollama, the server its publisher builds (MIT), one
instance per machine, on Linux, macOS and Windows. It runs language models
on the machine and serves them on Ollama's HTTP API at `127.0.0.1:11434`.
One applier per system sits behind one runner in
`agent/neutrino_agent/modules/ollama/`, and the layout, the environment, the
published `port` entry and the model list are the same on every system.

| | Linux | macOS | Windows |
| --- | --- | --- | --- |
| Program | `ollama/bin/ollama` under the module's directory, its libraries in `ollama/lib/ollama/` beside it, where Ollama looks for them | `ollama/ollama` under the module's directory, its libraries beside it | `ollama\ollama.exe` under the module's directory, its libraries in `ollama\lib\ollama\` |
| Data: the models, Ollama's key | `ollama_data/` under the state root, owned by the account, mode 700 | `ollama_data/` under the state root, owned by the account, mode 700 | `ollama_data\` under the state root, SYSTEM and the administrators alone as the root is |
| Runs as | the system account `neutrino_ollama` the module makes with `useradd --system`, the comment `neutrino ollama`, no login shell and the data directory as its home, in the groups `render` and `video` where the machine has them | the hidden account `neutrino_ollama`, made with `sysadminctl` the way Gitea makes its account, with the full name `Neutrino Ollama`, the shell `/usr/bin/false` and the data directory as its home | SYSTEM |
| Service | `neutrino_ollama.service`, disabled at **Stop** and enabled at **Start** | the LaunchDaemon `com.neutrino.ollama` with `UserName`, its output in `/Library/Logs/Neutrino/agent/ollama.log`, disabled with `launchctl disable` at **Stop** and enabled at **Start** | the scheduled task `neutrino_ollama` run as SYSTEM, started at boot and again a minute after it stops, with no time limit; disabled at **Stop** and enabled at **Start**; its output in `ollama_data\ollama.log` |
| Listens on | `127.0.0.1:11434` alone | the same | the same |

In every list of modules Ollama comes after Gitea, and the catalog lists it
under `code`, after OpenCode ([../../ui_behavior.md](../../ui_behavior.md),
"The machine page").

**The environment is the module's.** The service starts `ollama serve` with
`OLLAMA_HOST=127.0.0.1:11434`, `OLLAMA_MODELS` the `models` folder of the
data directory and `OLLAMA_NO_CLOUD=1`, and on Linux and macOS `HOME` the
data directory, where Ollama keeps its own key in `.ollama`. Beside these it
carries the variables of the hub's settings ("The settings are the hub's").

| Rule | Reason |
| --- | --- |
| The server listens on `127.0.0.1` at 11434 alone, and the module opens no port in any firewall. | Ollama's API has no login: anything that reaches the port can chat, pull and delete models. 11434 is the port every tool and `ollama launch` use with no setting. |
| `OLLAMA_NO_CLOUD=1` turns off Ollama's cloud models. | The hub's AI gateway already serves cloud models; this module is for the models on the machine. |
| The models are in the module's own data directory, never in an account's home. | One server serves every account, and the models are the module's data. |
| On Windows the server runs as a scheduled task of SYSTEM's, through the agent's PowerShell host, as `cmd.exe` running a script under the module's directory that sets the environment, with its output appended to the log. A **Stop** ends the task and every process of the module's program it started. | `ollama.exe` is no Windows service program, and the service control manager ends a program that does not answer it. A task of SYSTEM's needs no password, and Task Scheduler sets no environment of its own. |
| A `configure` that runs the server waits until `GET /api/version` answers on `127.0.0.1:11434`, at most 60 seconds, and otherwise fails `apply_failed {detail}`, the detail naming the port and the last line of the server's output. | In the lab a restart answered in 0.11 seconds; a server that does not answer in a minute has failed. |

**The settings are the hub's.** The module's configuration is
`{keep_alive, gpus}`. The hub keeps it in
`config/devices/<id>/ollama.json` and sends it as the module's `config` in
the state ([../../protocol.md](../../protocol.md), "The modules section, one
entry per module"), and the service starts with its variables:

| Setting | Values | Variables |
| --- | --- | --- |
| `keep_alive`, how long a model a request loaded stays in memory after its last request | `5m`, `30m`, `1h`, `4h`, or `-1` for never; `30m` while the file names none | `OLLAMA_KEEP_ALIVE` |
| `gpus`, the GPUs the server uses | absent for every GPU; otherwise the machine's GPUs in the order its last report lists them (`machine.metrics.gpus`), each `{vendor, is_used}` | `CUDA_VISIBLE_DEVICES` for the NVIDIA cards, with `CUDA_DEVICE_ORDER=PCI_BUS_ID`; `ROCR_VISIBLE_DEVICES` for the AMD cards; `GGML_VK_VISIBLE_DEVICES` for every card that is neither NVIDIA's nor Apple's, which Vulkan serves. Each names the places, counted from 0 among the cards of its group, of the cards used, `-1` when none of its group is, and is set only while a card of its group is not used |

| Rule | Reason |
| --- | --- |
| A changed setting changes the unit, the LaunchDaemon or the task, and the `configure` restarts the server that runs. Models in memory leave it, and the kept ones are loaded again ("The model list is the hub's, through a forward of its own"). | Ollama reads its environment once, at its start. |
| `keep_alive` is `30m` by default, not Ollama's own 5 minutes. | A model of several gigabytes takes longer to load again than a pause in a conversation lasts; half an hour keeps it through a session of work. |
| A GPU's place in its group is its order in the report: `nvidia-smi`'s for NVIDIA cards, the PCI bus order that `CUDA_DEVICE_ORDER=PCI_BUS_ID` gives CUDA, and the order of `/sys/class/drm` for AMD cards on Linux. | The report is the one list of the machine's GPUs the hub has, and the person ticks the cards it shows. |
| `gpus` lists every reported card with its tick, not the ticked ones alone. | Vulkan counts the cards of every vendor in one list, and the agent places a card in it only from the whole list. |
| A card the stored list does not name, such as one added after the settings were saved, is not used while a list is stored, and the panel draws it unticked. | The variables name the cards to use, and the panel draws what the server does. |
| macOS takes `keep_alive` alone: the agent sets no GPU variable there, and the panel draws no GPU. | A Mac's GPU is Apple's one GPU, which Ollama reaches through Metal. |

**The archives come from the publisher's GitHub release.**
`data/manifests/ollama.json` names one artifact, `ollama`, at one tested
version, the newest stable release on the day: `ollama-linux-amd64.tar.zst`
and `ollama-linux-arm64.tar.zst` of kind `tar_zst`,
`ollama-windows-amd64.zip` of kind `zip`, and `ollama-darwin.tgz` of kind
`tar_gz` for both Mac architectures, each with the digest GitHub's API
gives the asset. Its versions come from a `github` feed on
`ollama/ollama`. Its sources are the GitHub release, then SourceForge's
`ollama.mirror` project, which holds the same files under `v{version}/`;
no mirror in mainland China serves them, and the hub's cache takes
whichever of the two its probe finds faster. The hub's cache fetches each archive and
sends it down `package {module: ollama, artifact, digest}`.

| Rule | Reason |
| --- | --- |
| The Linux entries name `packages: ["zstd"]`, as Gitea's name `git`, and the module unpacks its `tar_zst` artifact itself: the system's `zstd -dc` writes the tar to Python's `tarfile`, which unpacks it under `ollama/` in the module's directory with the checks and the seal of every archive ([../module_install.md](../module_install.md), "Artifacts"). | The agent's Python has no zstd, and Ollama publishes its Linux builds as `.tar.zst` alone. The kind keeps its name, and the system's `zstd` reads the file. |
| A version switch on Linux unpacks the new archive in a staging directory and replaces `ollama/` in one rename while the server is stopped, as an install does; the old files are gone once the rename took. | The engine stages archive kinds alone, and a `tar_zst` artifact is the module's to place. |
| The macOS entry names `min_version` 14. | Ollama's floor is macOS 14, above the agent's 13 ([../../min_support.md](../../min_support.md)). |
| No entry names the ROCm archive. | An AMD GPU runs on the main archive through Vulkan, and the ROCm archive adds 1 GB to every Linux install. |
| Each archive passes through the hub's cache under its 2 GiB limit: 1.55 GB on Linux amd64, 1.60 GB on arm64, 1.62 GB on Windows and 186 MB on macOS for 0.40.16. | The cache refuses a larger file `module_fetch_too_large`. |

**A person's own Ollama never runs beside the module's**
([../../agent.md](../../agent.md), "Parallel, never take over"). Ollama is a
server that holds one port and the GPU, so two copies cannot run on one
machine.

A person's unit on Linux is adopted. A person's app on Windows and macOS is
taken over while the module is installed, the way the remote desktop module
takes a person's RustDesk over ([remote_desktop.md](remote_desktop.md), "The
desktop is the hub's order"): only the module's own server runs.

| | Linux: a person's unit | Windows and macOS: the publisher's app |
| --- | --- | --- |
| What is found | the unit `ollama.service`, whose file is `/etc/systemd/system/ollama.service`, where the publisher's `install.sh` puts it, or `/usr/lib/systemd/system/ollama.service` or `/lib/systemd/system/ollama.service`, where a distribution's package puts it | the app the publisher's installer adds: `AppData\Local\Programs\Ollama\` in any profile, `/Applications/Ollama.app` on a Mac. It counts as nothing installed |
| Before a press | the row reads `installed`, `is_active` by the unit, and `details.found` is `unit` | the row reads as the module alone makes it |
| **Install** | its plan holds no artifact | installs the module's own server, as on a machine with no app |
| **Start** and **Stop** | the person's first **Start** adopts it: **Start** enables and starts `ollama.service`, **Stop** stops and disables it, and the first **Start** keeps whether the unit was enabled and active as `found_unit` in the module's record | the module's own server's |
| A `configure` | writes the drop-in `ollama.service.d/neutrino.conf` beside the unit's file under `/etc/systemd/system`, holding the settings' variables alone, and reloads systemd when it changed; under `running` a changed drop-in restarts the unit that runs. It writes nothing else of the person's: no unit, no other variable, no account | takes every account's app over first: keeps aside its start at login, records whether the app ran, and ends the app and the server it started |
| Each report | nothing more | while the module's program is installed, ends every process of the app, one a person opened by hand among them |
| **Uninstall** | deletes the drop-in, and its folder when nothing of the person's is in it, reloads systemd and restarts the unit if it runs, then puts the unit back as the first **Start** found it from `found_unit`; it removes nothing of the person's, and the module reads `absent` through the uninstalled mark `uninstalled/ollama` until the next **Install**, whose plan holds no artifact and whose `verify` deletes the mark | after its own server is gone, puts each kept start at login back, and opens the app again for each account whose app ran when it was taken over and that is logged on now |
| The settings | the drop-in's | the module's own server's |
| Its version | the hub locks it: `details.has_package_mark` is false ([../module_install.md](../module_install.md), "Module versions") | the module's own |
| The model list | managed the same way as the module's own | the module's server's models; the app's stay in the person's own folder, which the module's server does not read |

| | Windows | macOS |
| --- | --- | --- |
| The app's processes | every process whose program is in `AppData\Local\Programs\Ollama\` of a profile: `ollama app.exe`, the `ollama.exe` it starts and its runners | every process whose program is in `/Applications/Ollama.app` |
| Its start at login | the shortcut `Ollama.lnk` in the profile's Startup folder, `AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup`, which the app copies there at its first start | the login item the app registers with `SMAppService` from its bundle's `Contents/Library/LaunchAgents/com.ollama.ollama.plist`, the job `com.ollama.ollama` in each account's `gui` domain |
| Kept aside | the shortcut moved to `ollama/kept/<profile>/Ollama.lnk` under the state root, its Startup folder refused when it is a junction | the job disabled with `launchctl disable gui/<uid>/com.ollama.ollama`, whether it was disabled before kept |
| Given back | the shortcut moved back while no file of that name stands there | `launchctl enable` for a job that was not disabled before |
| Opened again | `schtasks` runs the app once as the account, interactive only, then deletes the task | `launchctl asuser <uid> open` of the app, for the account at the console |

| Rule | Reason |
| --- | --- |
| Every `verify` and every read of the program's version runs with `OLLAMA_MODELS` naming the module's `models` folder ([../module_install.md](../module_install.md), "One presence check"). | Ollama's `--version` stops with `$HOME is not defined` while neither names a folder, and the agent's LaunchDaemon on macOS has no `HOME`: on the lab Mac the first install ended `install_unconfirmed`. |
| The Linux entries' `verify` is the module's program with `--version`, else a test that the person's unit file is in one of its three places. | The method's presence check is the one test that Ollama is there, whoever installed it ([../module_install.md](../module_install.md), "One presence check"), and a test of a file runs no program of the person's as root. |
| The hub takes no Ollama over at a report. | A person's Ollama has no configuration to import, and the row's own state is enough to publish its port and list its models. |
| A person's unit takes the settings through a drop-in of the module's own name, which holds nothing but their variables. | systemd reads every file of the unit's `.d` folder after the unit's own, so the person's unit file stays as the person wrote it, and the module's own file is all an **Uninstall** takes away. |
| On Windows and macOS only the module's server runs while the module is installed, and the app's files, its models among them, are never changed or deleted. | The app starts its own server on 11434 at the person's login, and the module's server is the one the hub's settings, models and gateway reach. |
| The app is ended again at each report, not only at the take-over. | A person can open the app by hand, and its server would take the port the moment the module's server restarts. |

**What a report reads.** `details` is `{is_running, port, version, found,
has_package_mark}`: `is_running` whether `GET /api/version` answers on
`127.0.0.1:11434` within a second, `port` 11434, `version` the version the
server answers, else the module's program's `--version`, read once per
program file, `found` empty for the module's own copy and `unit` for a
person's on Linux, and `has_package_mark` false for a person's. No report
carries a model.

**The port is the `api` entry of the Ollama app.** The hub publishes the app
`ollama_<device id>`, titled `Ollama`, with one TCP `port` entry named
`api` at 11434 ([../../protocol.md](../../protocol.md), "Apps"), while the
machine's row reads `installed`, `stopped` or `running` and its details
name the port. The entry is healthy while `details.is_running` is true. A
client forwards it at its local port, as it forwards Gitea's `ssh` entry;
Ollama accepts a request whose `Host` is `127.0.0.1` at any port, so a
tool on the client reaches the API at `http://127.0.0.1:<local port>`.
Ollama has no page, so the app has no `web` entry and no App share.

**The model list is the hub's, through a forward of its own.** The hub's
Python asks its own transport for a forward on the hub's loopback,
`forward_start {binding_id, listen, protocol, open}` with `listen`
`127.0.0.1:0` and `open` `{kind: connect, port: 11434, protocol: tcp}`
([../../transport.md](../../transport.md), "The hub's local channel"), and
calls Ollama's own API through it with a plain HTTP client: `GET /api/tags`
and `GET /api/ps` to list, `POST /api/pull` streamed to pull, `DELETE
/api/delete` to remove, and `POST /api/generate` with `keep_alive` -1 to
load and 0 to unload. The agent publishes the port and carries nothing else
for the models: no verb and no field of the report.

| Rule | Reason |
| --- | --- |
| The hub keeps one forward per machine whose Ollama row reports `is_running`, starts it at the report that first says so and stops it at the report that says no more, at the machine's leave and when the module is uninstalled. A new control connection to the transport finds no forward, and the hub starts them again. | A forward lasts while the control connection that started it is open, and the transport keeps only what is live. |
| A pull is a background task of the hub's, one at a time per machine, in the order the person pressed **Pull**; a further **Pull** waits behind the running one. Closing the page or leaving it does not stop it, and the page shows its progress when it comes back. **Cancel** ends a running pull by closing its connection, and takes a waiting one off the queue. | A model is gigabytes, and a pull outlives the page that asked for it. Ollama keeps the layers a cut pull fetched, so a pull of the same name later goes on from them. |
| The pull's progress is the sum of each layer's `completed` and `total` that `/api/pull` streams, and its speed the bytes of the last 5 seconds. The panel reads the view every 2 seconds while a pull runs or waits ([../../ui_behavior.md](../../ui_behavior.md), "The machine page"). | The hub holds the progress, so a page that comes back draws it at once. |
| A pull that fails stays a row with its code, `ollama_pull_failed {name, detail}` and Ollama's own words, until the person dismisses it with **Cancel**. | The person reads why the model is not there. |
| A name is any name Ollama takes: a library name such as `qwen2.5:7b`, `hf.co/<owner>/<repository>:<quantization>` or `modelscope.cn/<owner>/<repository>:<quantization>`. The hub refuses `ollama_model_name_invalid {name}` for a name that is empty, longer than 200 characters, or holds a character other than a letter, a digit, `.`, `_`, `-`, `:` and `/`. | ModelScope serves Ollama's registry protocol for its GGUF repositories, the way in mainland China. The hub keeps no catalog of models of its own. |
| A call that does not reach Ollama answers `ollama_unreachable {detail}`. | The machine's row says whether the module runs; this code says the call itself failed. |
| **Load** loads a model with `keep_alive` -1, which keeps it in memory until **Unload**, and the hub adds its name to `kept_models` in the machine's `ollama.json`. **Unload** and **Remove** take the name off. A request that names no `keep_alive`, as every request through the AI gateway, leaves a loaded model's time as it is, so a kept model stays and a model a request loaded leaves memory after the idle unload time. | Ollama sets a loaded model's time from a request that names one and keeps it otherwise. |
| The hub loads every kept model the machine's `/api/ps` does not list: at once when its forward to the machine starts, and every 10 seconds for a machine that holds a kept model. A kept model is back within 10 seconds of a restart of the server, whoever restarted it, and at the machine's first report after a reboot, plus the time it takes to load. | A settings change, a person, a crash and a reboot each restart the server with nothing in memory, and `/api/ps` is where the hub sees it. One call through the forward every 10 seconds costs nothing beside a load. |
| A load runs on a thread of its own, at most one per model. The press does not wait for it: the view marks the model `is_loading` until it ends. One that fails is tried again 5 minutes later, or at the next **Load**. A load that ends after its name was taken off unloads the model. | A large model takes minutes to load on a CPU, and one that does not fit in memory fails the same way each time. |
| `kept_models` is the hub's alone: the module's `config` never carries it, and changing it pushes nothing to the machine. | A model the person keeps changes nothing the server starts with. |

**Every machine's Ollama feeds the hub's AI gateway.** While the machine is
online and its Ollama runs with at least one model, the hub adds an
OpenAI-compatible provider to the gateway at the forward above, under
`/v1`, serving the names `/api/tags` returns with no machine name in front
([../../hub_components/ai.md](../../hub_components/ai.md), "Every machine's
Ollama"). Every program that goes through the gateway can then use them,
the AI tools of a client and of a managed machine among them, and the same
name on two machines rotates between both. The provider goes while the
machine is offline and when its Ollama stops, is uninstalled or holds no
model. The AI page lists it as a read-only row that links to this tab's
**Models** panel. The agent carries nothing more for it.

**Uninstall takes what the module added and keeps the models**: the unit,
the LaunchDaemon or the task, its script and the program go; the data
directory stays, so an install afterwards serves the same models. The
account `neutrino_ollama` stays on Linux and macOS: it owns the data
directory, and the next install runs as it again. An `account` step that
finds the data directory owned by another uid, as after the account was
removed by hand and made again, gives it to the account by open descriptor,
following no link, as Gitea's handover does
([gitea.md](gitea.md), "The data belongs to the server's account"); on
macOS it gives `models` and `.ollama` alone, since the data directory is the
account's home. Every other read and write in the data directory runs as
the account ([../../agent.md](../../agent.md), "Acting for an account"). The
module's journal is the unit's journal on Linux and the end of its output
file on macOS and Windows, then the agent's lines that name it
([../../agent.md](../../agent.md), "Which modules each system runs").
