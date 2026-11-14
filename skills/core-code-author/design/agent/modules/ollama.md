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
data directory, where Ollama keeps its own key in `.ollama`.

| Rule | Reason |
| --- | --- |
| The server listens on `127.0.0.1` at 11434 alone, and the module opens no port in any firewall. | Ollama's API has no login: anything that reaches the port can chat, pull and delete models. 11434 is the port every tool and `ollama launch` use with no setting. |
| `OLLAMA_NO_CLOUD=1` turns off Ollama's cloud models. | The hub's AI gateway already serves cloud models; this module is for the models on the machine. |
| The models are in the module's own data directory, never in an account's home. | One server serves every account, and the models are the module's data. |
| On Windows the server runs as a scheduled task of SYSTEM's, through the agent's PowerShell host, as `cmd.exe` running a script under the module's directory that sets the environment, with its output appended to the log. A **Stop** ends the task and every process of the module's program it started. | `ollama.exe` is no Windows service program, and the service control manager ends a program that does not answer it. A task of SYSTEM's needs no password, and Task Scheduler sets no environment of its own. |
| A `configure` that runs the server waits until `GET /api/version` answers on `127.0.0.1:11434`, at most 60 seconds, and otherwise fails `apply_failed {detail}`, the detail naming the port and the last line of the server's output. | In the lab a restart answered in 0.11 seconds; a server that does not answer in a minute has failed. |

**The archives come from the publisher's GitHub release.**
`data/manifests/ollama.json` names one artifact, `ollama`, at one tested
version, the newest stable release on the day: `ollama-linux-amd64.tar.zst`
and `ollama-linux-arm64.tar.zst` of kind `tar_zst`,
`ollama-windows-amd64.zip` of kind `zip`, and `ollama-darwin.tgz` of kind
`tar_gz` for both Mac architectures, each with the digest GitHub's API
gives the asset. Its versions come from a `github` feed on
`ollama/ollama`, and its one source is the GitHub release; no mirror in
mainland China serves these files. The hub's cache fetches each archive and
sends it down `package {module: ollama, artifact, digest}`.

| Rule | Reason |
| --- | --- |
| The Linux entries name `packages: ["zstd"]`, as Gitea's name `git`, and the module unpacks its `tar_zst` artifact itself: the system's `zstd -dc` writes the tar to Python's `tarfile`, which unpacks it under `ollama/` in the module's directory with the checks and the seal of every archive ([../module_install.md](../module_install.md), "Artifacts"). | The agent's Python has no zstd, and Ollama publishes its Linux builds as `.tar.zst` alone. The kind keeps its name, and the system's `zstd` reads the file. |
| A version switch on Linux unpacks the new archive in a staging directory and replaces `ollama/` in one rename while the server is stopped, as an install does; the old files are gone once the rename took. | The engine stages archive kinds alone, and a `tar_zst` artifact is the module's to place. |
| The macOS entry names `min_version` 14. | Ollama's floor is macOS 14, above the agent's 13 ([../../min_support.md](../../min_support.md)). |
| No entry names the ROCm archive. | An AMD GPU runs on the main archive through Vulkan, and the ROCm archive adds 1 GB to every Linux install. |
| Each archive passes through the hub's cache under its 2 GiB limit: 1.55 GB on Linux amd64, 1.60 GB on arm64, 1.62 GB on Windows and 186 MB on macOS for 0.40.16. | The cache refuses a larger file `module_fetch_too_large`. |

**A person's own Ollama is adopted, never run beside**
([../../agent.md](../../agent.md), "Parallel, never take over"). Ollama is a
server that holds one port and the GPU, so two copies cannot run on one
machine.

| | Linux: a person's unit | Windows and macOS: a person's app |
| --- | --- | --- |
| What is found | the unit `ollama.service`, whose file is `/etc/systemd/system/ollama.service`, where the publisher's `install.sh` puts it, or `/usr/lib/systemd/system/ollama.service` or `/lib/systemd/system/ollama.service`, where a distribution's package puts it | an Ollama the module did not start answering on `127.0.0.1:11434`: the per-user app the publisher's installer adds, which starts at the person's login |
| Before a press | the row reads `installed`, `is_active` by the unit, and `details.found` is `unit` | the row reads `installed` while the port answers, `is_active` true, and `details.found` is `app`; with the port silent nothing is found |
| Its port | published while the row reads `installed`, `stopped` or `running` | published while the row reads `installed` |
| **Start** and **Stop** | the person's first **Start** adopts it: **Start** enables and starts `ollama.service`, **Stop** stops and disables it, and the first **Start** keeps whether the unit was enabled and active as `found_unit` in the module's record | none: the tab draws no **Install**, **Start**, **Stop** or **Uninstall**, and **Configure** opens the model list |
| A `configure` | writes nothing of the person's: no unit, no environment, no account | none runs |
| **Uninstall** | removes nothing of it, puts the unit back as the first **Start** found it from `found_unit`, and the module reads `absent` through the uninstalled mark `uninstalled/ollama` until the next **Install**, whose plan holds no artifact and whose `verify` deletes the mark | none |
| Its version | the hub locks it: `details.has_package_mark` is false ([../module_install.md](../module_install.md), "Module versions") | the same |
| The model list | managed the same way as the module's own | the same |

| Rule | Reason |
| --- | --- |
| The Linux entries' `verify` is the module's program with `--version`, else a test that the person's unit file is in one of its three places. | The method's presence check is the one test that Ollama is there, whoever installed it ([../module_install.md](../module_install.md), "One presence check"), and a test of a file runs no program of the person's as root. |
| An **Install** on Windows or macOS refuses `ollama_found {path}` while the publisher's app is on the machine, at `%LOCALAPPDATA%\Programs\Ollama\ollama.exe` of any profile or at `/Applications/Ollama.app`. | The app starts its own server at the person's login, and a second server would fight it for the port. |
| The hub takes no Ollama over at a report. | A person's Ollama has no configuration to import, and the row's own state is enough to publish its port and list its models. |

**What a report reads.** `details` is `{is_running, port, version, found,
has_package_mark}`: `is_running` whether `GET /api/version` answers on
`127.0.0.1:11434` within a second, `port` 11434, `version` the version the
server answers, else the module's program's `--version`, read once per
program file, `found` empty for the module's own copy and `unit` or `app`
for a person's, and `has_package_mark` false for a person's. No report
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
/api/delete` to remove, and `POST /api/generate` with `keep_alive` 0 to
unload. The agent publishes the port and carries nothing else for the
models: no verb and no field of the report.

| Rule | Reason |
| --- | --- |
| The hub keeps one forward per machine whose Ollama row reports `is_running`, starts it at the report that first says so and stops it at the report that says no more, at the machine's leave and when the module is uninstalled. A new control connection to the transport finds no forward, and the hub starts them again. | A forward lasts while the control connection that started it is open, and the transport keeps only what is live. |
| A pull is a background task of the hub's, one at a time per machine, in the order the person pressed **Pull**; a further **Pull** waits behind the running one. Closing the page or leaving it does not stop it, and the page shows its progress when it comes back. **Cancel** ends a running pull by closing its connection, and takes a waiting one off the queue. | A model is gigabytes, and a pull outlives the page that asked for it. Ollama keeps the layers a cut pull fetched, so a pull of the same name later goes on from them. |
| The pull's progress is the sum of each layer's `completed` and `total` that `/api/pull` streams, and its speed the bytes of the last 5 seconds. The panel reads the view every 2 seconds while a pull runs or waits ([../../ui_behavior.md](../../ui_behavior.md), "The machine page"). | The hub holds the progress, so a page that comes back draws it at once. |
| A pull that fails stays a row with its code, `ollama_pull_failed {name, detail}` and Ollama's own words, until the person dismisses it with **Cancel**. | The person reads why the model is not there. |
| A name is any name Ollama takes: a library name such as `qwen2.5:7b`, `hf.co/<owner>/<repository>:<quantization>` or `modelscope.cn/<owner>/<repository>:<quantization>`. The hub refuses `ollama_model_name_invalid {name}` for a name that is empty, longer than 200 characters, or holds a character other than a letter, a digit, `.`, `_`, `-`, `:` and `/`. | ModelScope serves Ollama's registry protocol for its GGUF repositories, the way in mainland China. The hub keeps no catalog of models of its own. |
| A call that does not reach Ollama answers `ollama_unreachable {detail}`. | The machine's row says whether the module runs; this code says the call itself failed. |

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
