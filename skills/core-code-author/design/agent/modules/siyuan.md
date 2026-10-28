# The SiYuan module

The `siyuan` module runs the kernel of SiYuan, tested at 3.8.8 (AGPL-3.0),
a note-taking program whose kernel serves its own web page, once per enabled
account on Linux (amd64 and arm64), macOS (arm64 and amd64) and Windows
(x64). It is a program run as a person's account
([module_template.md](../module_template.md)):
`agent/neutrino_agent/modules/siyuan/` holds `config.py`, `constants.py` and
`hooks.py`, and `modules/shared/` does the rest. Its configuration is
`{instances: [{account, secret, access_code, gateway_key, password}],
gateway_url, models}`, and the agent takes each instance's port, the
forwarder's, itself from 6810 up ([../../protocol.md](../../protocol.md), "The account layer in the
state").

## The kernel comes from the desktop build

No release asset holds the kernel alone: each desktop build carries it
inside, beside the files its page is made of. `data/manifests/siyuan.json`
names one artifact per platform, the desktop build at the module's version,
unpacked under `siyuan/app/` in the state root, which every account reads
and runs, none writes, and no `PATH` names ([module_install.md](../module_install.md), "Artifacts"):

| Platform | File | `kind` | The kernel |
| --- | --- | --- | --- |
| `linux-amd64` | `siyuan-{version}-linux.tar.gz` | `tar_gz` | `app/resources/kernel/SiYuan-Kernel` |
| `linux-arm64` | `siyuan-{version}-linux-arm64.tar.gz` | `tar_gz` | the same |
| `darwin-arm64` | `siyuan-{version}-mac-arm64.dmg` | `dmg`, `member` `SiYuan.app/Contents/Resources` | `app/kernel/SiYuan-Kernel` |
| `darwin-amd64` | `siyuan-{version}-mac.dmg` | the same | the same |
| `windows-amd64` | `siyuan-{version}-win.exe` | `nsis` | `app\resources\kernel\SiYuan-Kernel.exe` |

| Rule | Reason |
| --- | --- |
| The versions come from the `github` feed on `siyuan-note/siyuan`, tag `v{version}`, and each file's digest from the asset's `digest` in GitHub's API. Prereleases are left out. | The publisher releases a prerelease almost every day, `v3.8.9-alpha.N` and `-beta.N`, beside each stable release. |
| Each file's sources are the GitHub release, then the publisher's own `https://release.liuyun.io/siyuan/{file}`. | The publisher's mirror, which its download page links, serves every desktop file with the same SHA-256 and answers Range requests. It holds no `SHA256SUMS.txt`, so the digest is GitHub's ([module_install.md](../module_install.md), "Sources"). |
| The unpack is the whole build, 741 MB on Linux and 841 MB on Windows, and the kernel's working directory is its `resources`: the page's files, the guide and pandoc. | 280 MB of the Linux build are Electron, which the kernel never opens; the publisher's layout unpacks every version by one rule. |
| The Linux kernel is a static-pie ELF, so the Linux entries name no `min_version`. | It needs no glibc of the machine. |
| The Windows file is the publisher's NSIS installer, whose 7z archive the agent reads itself ([../module_install.md](../module_install.md), "Artifacts"), so the entry names no `min_version`. | The installer stores `app-64.7z` whole, one folder per file of LZMA2 behind BCJ, a filter for x86 code. The agent's reader unpacked 3.8.8's 1,433 files in 11.6 seconds with 25 MB of memory, each byte equal to 7-Zip's unpack. The system's `tar.exe` read the archive on build 26100, bsdtar 3.8.9 with liblzma; no older build was in the lab, and the agent runs from Windows 10 1809 up. |
| The four copies of one guide video the installer carries outside its 7z archive are left out. | The installer's own script writes them beside the archive's files, and the kernel ran without them in the lab. |
| On macOS the agent attaches the dmg read-only, copies `SiYuan.app/Contents/Resources` into the unpack and detaches it. | The kernel there is `Contents/Resources/kernel/SiYuan-Kernel`, a Mach-O signed with the publisher's Developer ID, beside the same resources as on Linux. In the lab, on macOS 15 on Intel, the image attached in 2.7 seconds, the copy took 2.4 seconds and carried no quarantine attribute, and the kernel ran as the account under a LaunchDaemon, answering 3.4 seconds after its first start. |

On Linux the unpack is labelled `bin_t` where SELinux enforces, as every
module's unpack is ([module_install.md](../module_install.md), "From the
hub's cache"): on Rocky 9 the unit failed 203/EXEC until it was.

## The workspace is the account's

The per-account data directory, `<data>`, is
`~/.local/share/neutrino/agent/siyuan/` on Linux, `~/Library/Application
Support/Neutrino/agent/siyuan/` on macOS and
`%LOCALAPPDATA%\Neutrino\agent\siyuan\` on Windows, made as the account. The
workspace is `<data>/workspace`: the notes in `data/`, the settings in
`conf/`, the indexes and the log in `temp/`. The kernel's own files,
`workspace.json`, `cookie.key`, `port.json` and `announcement.json`, are in
`<data>/.config/siyuan`.

| Rule | Reason |
| --- | --- |
| The workspace is in Neutrino's own directory, never the person's `~/SiYuan`. | The kernel holds a `.lock` in its workspace, one kernel per workspace, so a desktop SiYuan of the same account cannot open a workspace an instance runs on. |
| The kernel runs with `--home-dir=<data>`. | Its own files go to `~/.config/siyuan` without it, which a desktop SiYuan of the same account shares. |
| The service runs under `umask 077`, and the hook makes `<data>/workspace` as the account, mode 700 with the directories above it, before the first start. | The kernel writes `cookie.key` with mode 0644, and with `UMask=0077` it was 0600. The kernel writes `conf.json` and `workspace.json` with mode 0644 under any umask, and `conf.json` holds the access code as plain text, so the 0700 directories above them keep other accounts out. A kernel whose `--workspace` names no directory takes `SiYuan` under `--home-dir` in its place. |
| An uninstall keeps `<data>` and every file in it, as `is_data_kept` says, and its line in the uninstall dialog names it ([../../ui_text.md](../../ui_text.md), "The uninstall dialog's words"). | The workspace is the person's notes, and the module removes no file of the account's ([module_template.md](../module_template.md), "The run"). |

## The service

The account service layer runs each instance as its account
([module_template.md](../module_template.md), "The run"); on Linux the
template unit's command line reads the workspace, the home directory and the
port from the instance's environment as `${NEUTRINO_SIYUAN_WORKSPACE}`,
`${NEUTRINO_SIYUAN_DATA}` and `${NEUTRINO_SIYUAN_PORT}`:

```text
<kernel> serve --wd=<resources> --workspace=<data>/workspace --home-dir=<data> --port=<kernel port>
```

`<resources>` is `app/resources` under the module's directory on Linux and
Windows and `app` on macOS. `<kernel port>` is a free loopback port the agent
picks at the instance's first start and keeps in the instance's record; the instance's port is the
forwarder's. The kernel reads one variable, `SIYUAN_ACCESS_AUTH_CODE`, the
instance's access code, from the service's environment, which the layer
writes root-only as it writes Codeg's token. The entry's `verify` is the
kernel with `--version`, which prints `SiYuan-Kernel version <version>` and
writes no file. In the lab a kernel was ready 0.64 seconds after
its start on Linux and in under a second on Windows, held 120 to 132 MB on
Linux and 76 MB on Windows, and stopped in 0.58 seconds with exit 0.

| Rule | Reason |
| --- | --- |
| Every instance has an access code, which the hub generates the first time the account is enabled and seals in `config/devices/<id>/siyuan.json`. | Without a code the kernel admits every request whose peer, `Host` and `Origin` are local, a `*.localhost` name among them, so any program of any account on the machine reads the notes. |
| The code is in the environment, never on the command line, though `serve` takes `--accessAuthCode`. | Every account on the machine reads a process's command line. |
| The kernel also listens on `127.0.0.1:6806` whenever its own port is another and 6806 is free, and no flag turns that off. That port asks for the same code, and the `connect` stream does not serve it. | It is the kernel's fixed port for the publisher's browser extensions, a proxy to itself, so the first instance on a machine holds it. |
| The kernel admits a local request to `/api/system/exit` with no login, so any account on the machine can end an instance; the account service starts it again, as it starts any instance that exits. | In the lab a local request to it ended a kernel that had a code. |

After a start the kernel opens one connection of its own, to the publisher's
host `siyuan-sync.b3logfile.com`; in the lab it was the kernel's one outbound
connection in the 90 seconds after a restart.

## The forwarder renames SiYuan's cookie

The forwarder listens on `127.0.0.1` at the instance's port, where the
agent's end of a `connect` stream reaches it, and passes what it admits to
the kernel's port:

| A request | The forwarder |
| --- | --- |
| holds `?tkn=<token>` that verifies | sends `POST /api/system/loginAuth` to the kernel with the JSON body `{"authCode": <code>, "rememberMe": true}`, the browser's `Host` and no `Origin`; sets the cookie the kernel returns, `siyuan`, on the browser under the instance's `cookie_name`, and redirects to `/` |
| holds `?tkn=<token>` that does not verify, has expired or was spent | 401 |
| holds the cookie `cookie_name` | passed on with that cookie renamed `siyuan` and any `siyuan` cookie of the browser's dropped, `Host` and `Origin` as the browser sent them, the page's three WebSockets included; a `siyuan` cookie the kernel sets in its response is renamed `cookie_name` |
| asks for `/api/system/loginAuth`, whatever else it holds | 401; the browser's login never reaches the kernel |
| holds neither | 401 |

| Rule | Reason |
| --- | --- |
| The forwarder renames the cookie both ways, `siyuan` toward the kernel and `cookie_name` toward the browser ([module_template.md](../module_template.md), "The run"). | The kernel names its cookie `siyuan` and no setting renames it. On macOS and iOS every app is at `127.0.0.1`, where two instances' cookies of one name sign each other out, each kernel signing with its own key. |
| The login the browser holds is SiYuan's own cookie, HttpOnly and SameSite=Lax, for 30 days, and never the kernel's API token. | The kernel admits its API token header on HTTP requests and never on its WebSockets, `/ws?...&type=main`, `filetree` and `protyle`, which the page opens at once. |
| The login is the forwarder's own request, with the code as JSON and no `Origin`. | The kernel returns `{"code": 0}` and the cookie to it, and returns "invalid request origin" to a request whose `Origin` differs from its `Host`. After a few wrong codes the kernel's login shows a captcha, and the forwarder only ever sends the instance's code. |
| The token is the one every program run as an account takes ([module_template.md](../module_template.md), "The run"). | The hub generates it from the instance's secret on every `service` ask, and the forwarder checks it on the device and spends it once. |

The page worked at the app's local name and at `127.0.0.1`, its login,
its interface and its three WebSockets, and it made no request to any other
host. The kernel needs no address of its own.

## The gateway

Each instance calls the hub's AI gateway with a key of its own, written into
the account's SiYuan settings. The hub generates the key when the account is
enabled, seals it in `siyuan.json`, registers it under the device, the module
and the account, and voids it when the account is disabled or removed and at
the module's uninstall ([../../hub_components/ai.md](../../hub_components/ai.md),
"A key per device as well as per client"). `gateway_url` is
`http://127.0.0.1:8317` on a managed machine, the agent's AI gateway forward,
which is open while the module is installed ([../../agent.md](../../agent.md),
"The AI gateway forward"), and the gateway's `listen_port` in place of 8317 on
the hub's own machine. `models` are the names the gateway serves.

The hook writes into the workspace's `conf/conf.json`, as the account:

| Key | Value |
| --- | --- |
| `ai.providers`, the provider whose `id` is the module's | `{id, enabled: true, apiKey, baseURL, protocol: "openai", requestTimeout: 120, models}`: the instance's `gateway_key`, `gateway_url` with `/v1` after it, and one `{id, enabled: true, name}` per name in `models` |
| `ai.agent.modelId`, `ai.editing.modelId` | the provider's first model's id, written only while the setting names no model the file holds |
| `system.downloadInstallPkg` | `false` |

| Rule | Reason |
| --- | --- |
| The hook writes the file after the instance's first start, and again whenever the key, `gateway_url` or `models` differ from what the instance's record holds, with the instance stopped and started again after. | The kernel makes `conf.json` at its first start, reads it at each start and writes it back from what it holds. `SIYUAN_OPENAI_API_BASE_URL`, `_KEY` and `_MODEL` fill one provider at the first start alone. |
| The provider's id and each model's id have the form of SiYuan's own ids, `20000101000000-` and seven hex characters, from the SHA-256 of `neutrino` for the provider and of `neutrino/<name>` for a model. | A fixed id finds the module's provider again among the person's own, and the kernel gives its AI entries ids of that form. |
| The key is written as it is, and the kernel encrypts it with a key built into SiYuan when it next saves the file, within seconds of its start. The hub's keys are 32 characters of base64url. | The kernel decrypts every stored key that reads as hex: keys of 32, 48 and 64 hex characters stopped the kernel at every start while the file held them, with `crypto/cipher: input not full blocks`, and a key that reads as no hex is taken as written. |
| The key is in the person's file, not only in the service's environment as Hermes WebUI's is. | SiYuan reads its providers from `conf.json` alone. |
| `system.downloadInstallPkg` is false. | The kernel downloads each new desktop installer in the background by default, and the module's version moves in the hub. |

A disabled account's `conf.json` keeps its voided key, which the gateway no
longer accepts, and the next enable writes a new one.

In the lab a new workspace pointed at a stand-in gateway answered
`POST /api/ai/chatGPT`, and the stand-in logged the kernel's key and model.

## The entry, the details and the refusals are code-server's

Each instance a running module serves is published as one app,
`siyuan_<device id>_<account>`, titled `SiYuan (<account>)`, whose one entry,
`web`, has `is_token_required: true` and `description_code` `siyuan_module`.
`details` is `{version, instances: [{account, port, is_running, code}]}`, and
an apply refuses `account_invalid`, `account_duplicate` and `secret_missing`,
each naming the `account`, `account_unknown {account}` for an account the
machine does not have, and on Windows `credential_missing {account}` and
`credential_invalid {account}` as Codeg's does
([../../protocol.md](../../protocol.md), "The modules section, one entry per
module").

Another version is installed from the module's tab, and a new tested version
in `siyuan.json` reaches every machine that chose none at the next apply
([module_install.md](../module_install.md), "Module versions").
