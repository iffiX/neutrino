# The AstrBot module

The `astrbot` module runs AstrBot (AGPL-3.0), AstrBotDevs' platform for chat
bots that answer with large language models, as one container on the
Containers module. A person sets up the bots, their chat platforms, plugins
and personas in AstrBot's own page, and the models come from the hub's AI
gateway. The module's software is a container image, installed by the
`container` method ([module_install.md](../module_install.md), "From
container images").

`agent/neutrino_agent/modules/astrbot/` holds `config.py`, `constants.py`
and `hooks.py`: the settings file written before the first start, the
forwarder's login, the gateway's source and the health read, which the
`container` runner calls. The configuration is `{secret, password,
cookie_name, local_name, model}`: the token secret, the password of
AstrBot's dashboard user, the name of the forwarder's login cookie ("The
page"), the app's local name, which the forwarder checks the `Host` against
([../module_template.md](../module_template.md), "The run"), and the default
model, empty while the gateway serves none ("The gateway"). The hub
generates the secret and the password the first time the module is
installed, and seals both in `config/devices/<id>/astrbot.json`, beside the
module's gateway key. The module runs wherever Containers runs
([containers.md](containers.md)), and its kind chip reads System service
([../module_install.md](../module_install.md), "The source chip and the kind
chip").

## The image

| Image | Tested version | Index digest | Sources |
| --- | --- | --- | --- |
| astrbot | 4.29.4 | `sha256:72f341f0ffcf6621ef820277642c5d63955f7beeac3683433ce09cac96379c78` | `docker.io/soulter/astrbot`, which Podman reaches through the docker.io mirrors the Containers module names, then `m.daocloud.io/docker.io/soulter/astrbot` |

The index covers amd64 and arm64. The manifest's four `container` entries,
`linux`, `windows-amd64`, `darwin-arm64` and `darwin-amd64`, name the one
artifact `astrbot` and `source_sets: ["pypi"]` ("Plugin requirements"), and
its top level names `is_data_forward_only: true`.

| Rule | Reason |
| --- | --- |
| The image's sources are `docker.io/soulter/astrbot`, with the person's docker.io mirrors under it, then `m.daocloud.io/docker.io/soulter/astrbot`. No `ghcr.io` source is listed. | docker.io is the image's one public registry: `ghcr.io/astrbotdevs/astrbot` refuses an anonymous pull, and `ghcr.nju.edu.cn` and `ghcr.m.daocloud.io` hold nothing of it. The publisher's documents name `m.daocloud.io` for mainland China. |
| The module's version is the image's tag without its `v`. The entries' `releases` name one `oci` feed, `{kind: oci, repository: soulter/astrbot, tag: "v{version}", sources: ["https://registry-1.docker.io"]}`. The tested version installs the digest the manifest names, and any other version installs the digest the registry gives its tag ([../module_install.md](../module_install.md), "Module versions"). | The publisher tags each release `vX.Y.Z`, beside `latest`, `-alpha.N`, `-beta.N` and `nightly-<date>-<sha>` tags. Only a dotted number is a version, so the feed lists the releases alone. |
| The manifest names `is_data_forward_only`, so the module installs no version older than the newest it has run on the machine. | AstrBot migrates its data one way at the first start of a new version. In the lab 4.28.2 to 4.29.4 moved settings into SQLite and removed the old keys, and 4.28.2 then started on that data and lost what had moved. |
| A source that serves the manifest and no layer is left unranked, and Podman pulls from it only after the ranked sources ([../module_install.md](../module_install.md), "The file a probe reads"). | From the lab, whose exit is in the US, `m.daocloud.io` served the manifest and answered 503 for every layer. No pull from inside mainland China was tested. |

## The container

The container `neutrino_astrbot` joins the network `neutrino_astrbot` and
has the label `neutrino.module=astrbot`, as every hub container does
([containers.md](containers.md), "Hub containers").

| Container | Image | Command | User | Ports |
| --- | --- | --- | --- | --- |
| `neutrino_astrbot` | astrbot | the image's own, `python main.py` in `/AstrBot` | the image's own, root | AstrBot's 6185, published on `127.0.0.1` at a port the agent picks ("The page"); 6199, published on `127.0.0.1:6199` and in no entry ("Chat platforms") |

| Volume | Holds | Mounted at |
| --- | --- | --- |
| `neutrino_astrbot_data` | data: `cmd_config.json` with every setting; `data_v4.db` with the conversations, personas, web chat, API keys, tasks and statistics; `knowledge_base/`; `mcp_server.json`; `plugins/` and their settings under `config/`; `skills/`; `t2i_templates/`; `attachments/`. Cache: `temp/`, which AstrBot empties every 600 seconds, and `python_user/`, the plugins' requirements ("Plugin requirements") | `/AstrBot/data` |

| Variable | Value |
| --- | --- |
| `PIP_USER` | `1` |
| `PYTHONUSERBASE` | `/AstrBot/data/python_user` |
| `NEUTRINO_GATEWAY_URL`, `NEUTRINO_GATEWAY_KEY` | the gateway's address and the module's key ([containers.md](containers.md), "Reaching the machine") |
| `PIP_INDEX_URL`, `UV_DEFAULT_INDEX`, `UV_INDEX_URL` | the first ranked source of the `pypi` set, as in every container whose module lists the set ([../module_install.md](../module_install.md), "Source sets") |

The container's environment is in its root-only environment file, never in
its unit or on a command line ([containers.md](containers.md), "Linux").

| Rule | Reason |
| --- | --- |
| The hub container names `stop_signal: SIGINT`, so its stop sends SIGINT, and `podman stop` keeps its 10 seconds before SIGKILL ([containers.md](containers.md), "Hub containers"). | AstrBot is the container's first process and handles SIGINT alone. In the lab SIGTERM waited out the 10 seconds and ended in SIGKILL, exit 137; SIGINT ended AstrBot in 1.1 to 1.5 seconds with exit 0 and its databases closed, on Podman 3.4.4 and on the Mac's Podman 5.8.9. |
| The container runs as the image's own user, root, and its unit names no `--user`. | The image names no user, and AstrBot writes its data, its plugins and their requirements as root. The lab ran it so on all three systems. |
| The module reads `running` while the container runs and `GET /` returns 200 at its published port. | The image declares no health check. `GET /` returns 200 with no login, and only once AstrBot's core has started, a reinstall of plugin requirements included. |
| The module's journal is the container's journal. | AstrBot writes its log to standard output; its log file is off by default. |
| An uninstall removes the container, the network, the volume, and the image when no other container uses it. The manifest's `uninstall_data` names `is_deleted: true`, and the dialog shows its line in red ([../../ui_behavior.md](../../ui_behavior.md), "The machine page"). | A container module is removed whole, and its data is in its volume ([../module_install.md](../module_install.md), "From container images"). |
| The manifest's `memory_mib` is 1024 ([containers.md](containers.md), "Memory for the container modules"). | In the lab AstrBot used 286 to 381 MB idle on Linux, 298 on Windows and 289 on the Mac. It peaked at 475 MB while it installed a plugin and at 497 MB in a start that reinstalled a plugin's requirements. |
| The image takes 2.0 GB on the disk of Podman's storage on amd64, a download of 723 MB. The volume holds 0.6 MB after the first start and grows with the plugins: 41 MB of requirements for the lab's one plugin. | The image holds Python, AstrBot's packages and its built page. |

## Plugin requirements

AstrBot installs a plugin's Python requirements when the plugin is
installed, and again at a start for each requirement it does not find. pip
runs inside AstrBot's process with `-i` set to `pypi_index_url` from
`cmd_config.json`, so it reads no index from `PIP_INDEX_URL` or the `UV_`
variables.

| Rule | Reason |
| --- | --- |
| `PIP_USER=1` and `PYTHONUSERBASE=/AstrBot/data/python_user` put every requirement under `python_user/` in the volume. | Without them the requirements land in the container's own layer, which a container made again does not keep. In the lab a start with one plugin then reinstalled its requirements and took 49 seconds in place of 8.8; with them in the volume the next start loaded the plugin in 11 seconds with no install. |
| The agent makes `python_user/lib/python3.12/site-packages` in the volume before the first start, beside the settings file ("The settings file"). | Python puts the user folder on its path only when the folder exists as Python starts. In the lab a start without it installed a plugin's requirements there and still failed the plugin with `ModuleNotFoundError` until the next start. |
| `pypi_index_url` is the first ranked source of the `pypi` set, which the agent writes into the settings file before the first start ([../module_install.md](../module_install.md), "Source sets"). After that the person sets it in AstrBot's own page. | AstrBot's pip reads its index from that key alone, and AstrBot's own default is Aliyun's mirror. The agent writes no file while AstrBot runs ("The settings file"). |

## The settings file

AstrBot keeps every setting in `cmd_config.json` in the volume. At a first
start with no password in the file, AstrBot generates a random password of
24 characters, prints it in its log, and sets a flag that opens its page on a
dialog demanding a new password. The agent writes the file into the empty
volume in the step `settings`, before the container's first start, with the
keys below. AstrBot adds its defaults for every other key at that start.

| Key | Value |
| --- | --- |
| `dashboard.username` | `astrbot` |
| `dashboard.pbkdf2_password` | the module's password as AstrBot hashes it, `pbkdf2_sha256$600000$<salt>$<hex>` |
| `dashboard.password` | the MD5 of the password in hex, the second hash AstrBot keeps beside the first |
| `dashboard.password_storage_upgraded` | `true` |
| `dashboard.password_change_required` | `false` |
| `dashboard.jwt_secret` | 32 random bytes in hex, generated for this file: AstrBot signs its login tokens with it |
| `provider_sources`, `provider`, `agent_runner` | the gateway's source, the default model's provider and the default ("The gateway") |
| `pypi_index_url` | the first ranked source of the `pypi` set ("Plugin requirements") |
| `disable_metrics` | `true` |

| Rule | Reason |
| --- | --- |
| The step `settings` makes the volume when it is missing, and writes the file only into a volume that holds no `cmd_config.json`. A volume that holds one keeps it, apart from the `dashboard` keys after a change of hub ("A machine that joins another hub"). | Once AstrBot has started, the file holds the person's bots, providers and settings, and a volume kept across a version change keeps them. |
| The step runs before `render` in the install's plan, since Containers' configure task starts the container. | AstrBot started on an empty volume generates its own password, sets the change flag and sends its metrics. |
| On Linux the agent writes the file and the folder as root into the volume's folder that `podman volume inspect` names. The file is written whole under a temporary name and renamed into place. On Windows and macOS the root script writes them the same way inside the Podman machine ([containers.md](containers.md), "Reads and writes"). | The lab wrote the file this way on Ubuntu 22.04 with Podman 3.4.4, and the first login returned `change_pwd_hint: false` and `setup_required` read false. A write inside the Podman machine is not proven. |
| The agent never writes `cmd_config.json` while AstrBot runs. A later change goes through AstrBot's own API, signed in as the forwarder signs in ("The page"). | A running AstrBot does not read the file again, and its next save of any setting writes its own copy over it. In the lab a timeout edited in the file read 120 from the API 3 seconds later, and the file itself read 120 again after AstrBot's next save. |
| The password is in the file before the first start, and `ASTRBOT_DASHBOARD_INITIAL_PASSWORD` is not set. | The variable sets the password and keeps the change flag, so the page opens on the dialog. |
| The hub generates a password of at least 8 characters with an upper-case letter, a lower-case letter and a digit. | AstrBot's own rule for a dashboard password. |
| `disable_metrics` is true, and `ASTRBOT_DISABLE_METRICS` is not set. A person who wants AstrBot's metrics turns them on in AstrBot's own settings. | AstrBot sends usage metrics with the host name and an installation id to `tickstats.soulter.top` by default. With the variable set, the setting in AstrBot's page has no effect, and metrics stay off. |

## The gateway

The agent points AstrBot at the hub's AI gateway in the settings file, with
one provider source and, while the configuration names a model, one chat
provider set as the default:

| Key | Value |
| --- | --- |
| `provider_sources` | `[{id: neutrino_gateway, provider: openai, type: openai_chat_completion, provider_type: chat_completion, enable: true, key: ["$NEUTRINO_GATEWAY_KEY"], api_base, timeout: 120, proxy: "", custom_headers: {}}]`, `api_base` being `NEUTRINO_GATEWAY_URL` with `/v1` after it: `http://host.containers.internal:8317/v1` on a managed machine, and the gateway's `listen_port` in place of 8317 on the hub's own machine |
| `provider` | `[{id: "neutrino_gateway/<model>", model: <model>, enable: true, provider_type: chat_completion, provider_source_id: neutrino_gateway}]`, `<model>` the configuration's `model`: the default model ([../../hub_components/ai.md](../../hub_components/ai.md), "The default model") |
| `agent_runner` | `{runner_type: local, config: {model: {provider_id: "neutrino_gateway/<model>"}}}` |

| Rule | Reason |
| --- | --- |
| The source's key is `$NEUTRINO_GATEWAY_KEY`, the variable's name, and never the key. | AstrBot reads a key written `$VAR` or `${VAR}` from its environment when it loads the provider. The hub rewrites the environment at every apply, so a new or voided key reaches AstrBot when the container starts again, and no key is in the volume or in a copy of it. |
| The page's button that lists a source's models fails for this source with a 500, and a person adds a model by typing its name. | AstrBot sends the key's text, `$NEUTRINO_GATEWAY_KEY`, to the gateway unresolved, and the gateway rejects it with 401. iffi accepted this so that the key is never written into the file. |
| While the configuration names no model, the file holds the source alone, with no `provider` and no `agent_runner`. | A provider names a model the gateway serves. |
| The agent's provider is the one the module's record names as the provider the default follows, `neutrino_gateway/<model>`. The record also keeps whether the agent wrote that provider into the file or added it through the API, and the agent deletes only a provider it wrote or added. Every other provider is the person's, one on the `neutrino_gateway` source included, and the agent never changes or deletes it. | AstrBot's page adds providers on any source, so a provider's id does not say who made it. The record does. |
| At each start of the module after its first start, whenever the configuration's `model` differs from the one the record holds, the agent changes AstrBot through its API while AstrBot runs. First it adds `neutrino_gateway/<model>` with `POST /api/v1/provider-sources/neutrino_gateway/providers` and the JSON body `{config: <provider>}`, unless AstrBot holds a provider of that id, which it then uses without adding. Then it sets the `default` profile's `agent_runner.config.model.provider_id` to it with `PUT /api/v1/config-profiles/default`, the body being the `config` that `GET /api/v1/config-profiles/default` returns with that one key changed. Last it deletes its earlier provider with `DELETE /api/v1/providers/<id>`, when it wrote or added that one. The record then keeps the new model and provider. | The default model is the one every AI tool of the hub uses where nobody chose one ([../../hub_components/ai.md](../../hub_components/ai.md), "The default model"). AstrBot reads its chat model from the `default` profile's `agent_runner.config.model.provider_id`, the first provider while the key is empty, and loads a provider added through its API at once. AstrBot keeps no route of its own for the default chat model. |
| The agent sets the default only while `agent_runner.config.model.provider_id` names the agent's provider or is empty. A default the person picks in AstrBot's own page names another provider and stays, and so do AstrBot's other profiles. | A model a person chose stays, and the default model fills only what nobody chose ([../../hub_components/ai.md](../../hub_components/ai.md), "The default model"). A default that names the agent's provider follows the hub's default model. |
| While the configuration names no model, nothing changes, and the record keeps the last model. A call that fails is a line in the agent's log, and the record keeps the earlier model, so the module's next start tries again. | The gateway that serves no model leaves no model to name. A failed call changes nothing AstrBot reads, and the next start compares the record again. |
| Adding a provider through `POST /api/v1/provider-sources/neutrino_gateway/providers` is proven in the lab. Setting the default through `PUT /api/v1/config-profiles/default` and deleting a provider through `DELETE /api/v1/providers/<id>` are read from AstrBot 4.29.4's source and are not proven. | R196 added a provider through the API and AstrBot loaded it at once; it did not set a default through the API or delete a provider. |
| At each start of the module after its first start, when the gateway's address differs from the one the module's record holds, as after a change of `listen_port` on the hub's own machine, the agent writes the source again with `POST /api/v1/provider-sources` and the JSON body `{config: <source>}` while AstrBot runs, and the record keeps the address written. | AstrBot loads a source changed through its API at once. The address on a managed machine never changes. |

The container reaches the gateway at `host.containers.internal` through the
agent's relays ([../../agent.md](../../agent.md), "The listeners a container
reaches"). The gateway accepts the module's key whatever the machine's AI
tools setting says ([containers.md](containers.md), "Reaching the machine").
In the lab AstrBot's web chat answered through the gateway in 0.94 and 7.18
seconds with a small Ollama model.

## The first start

| Rule | Reason |
| --- | --- |
| From the install, after a version change, and after a new password ("A machine that joins another hub"), the module reads `installing` until `GET /` first returns 200 at the published port. The module's task checks every 30 seconds in its step `first_start` meanwhile ([../../agent.md](../../agent.md), "The steps"). | The first start took 8.8 seconds on Ubuntu 22.04, 50 on Windows and 15 on an Intel Mac in the lab, and a version change migrates the data at its first start. The entry appears when the page can serve. |
| A version change makes the container again on the new image and keeps the volume, with the settings, the plugins and their requirements. The step `settings` writes nothing then. | The data is in the volume, and AstrBot migrates it at the new version's first start. In the lab 4.28.2 to 4.29.4 on the same volume started in 10.9 seconds and kept the persona and the provider. |

The pull by digest took 77 seconds on Ubuntu 22.04, 198 on Windows and 81
on the Intel Mac. The first start installs nothing. It fetches
`models.dev/api.json` and AstrBot's text-to-image endpoints from
`api.soulter.top`. The plugin market's list comes from `api.soulter.top`,
with GitHub as AstrBot's own fallback, and plugin archives from
`astrbot-cloud-test-s3.astrbot.app`.

## A machine that joins another hub

A machine that runs AstrBot and joins another hub keeps the module's volume,
with its bots, conversations, plugins and settings. Its container stops
when it leaves the earlier hub, and the new hub imports none of it. The
module reads `stopped` on the new hub, from the recipe the agent kept
([../module_install.md](../module_install.md), "From container images"),
and its **Start** there starts the container again on the same volume
([containers.md](containers.md), "Hub containers"). The new hub generates
the module's secret and its password at that **Start**, as at every first
install.

| Rule | Reason |
| --- | --- |
| The module's record keeps the password written into `cmd_config.json`. When the state names another password, or the record holds none, the step `settings` runs before `start`: it stops the container, writes the `dashboard` keys of "The settings file" again with the new password and a new `jwt_secret`, keeps every other key, and starts the container. The record then keeps the new password. | The volume keeps the dashboard user with the earlier hub's password, and the forwarder signs in with the password the state names. AstrBot is stopped while the file changes, so no running AstrBot writes its copy over it. A new `jwt_secret` ends every login made under the earlier hub. |
| The step takes `containers` shared ([../../agent.md](../../agent.md), "Step locks"). | An apply of Containers takes the lock alone and starts each container that starts with the box, so none starts the container while the file changes. |
| The module reads `installing` until the step ends and `GET /` returns 200. A step that fails ends the task `install_failed {detail}`, and **Start** runs it again. | The entry appears when the forwarder's login works. |
| The rewrite after a change of hub is not proven in the lab. | R196 wrote the file into an empty volume alone. |

## The page

The page is the `web` entry of the app `astrbot_<device id>`, titled
`AstrBot`, the entry's id `astrbot_<device id>_web`, with
`is_token_required: true` and `description_code` `astrbot_module`. The
entry exists while the module reads `running`.

| Rule | Reason |
| --- | --- |
| The agent's forwarder listens on `127.0.0.1` at a port the agent takes from 6185 up at the first apply and keeps in the module's record, where the agent's end of a `connect` stream reaches it, and reports it as `port`. | The page's port is the agent's, as Hermes WebUI's is ([hermes_webui.md](hermes_webui.md), "The page"). |
| AstrBot's 6185 is the hub container's `page_port`: published on `127.0.0.1` at a free loopback port the agent picks from 15000 up at the first apply and keeps in the module's record, in no entry, and served by no `connect` stream ([containers.md](containers.md), "Hub containers"). | Every request from a client reaches AstrBot through the forwarder's check. |
| AstrBot's own login stays set. | A program on the machine that finds the published port still meets AstrBot's login. On macOS every container in the Podman machine reaches the Mac's loopback. |

AstrBot's page keeps its login token in the browser's `localStorage`, under
`token`, and the user's name under `user`. It sends the token as
`Authorization: Bearer` on each call and as `?token=` on WebSockets and
backup downloads, opens only while `localStorage.token` is set, and goes to
its own login page on a 401. The forwarder turns the hub's token into that
login:

| A request | The forwarder |
| --- | --- |
| holds `?tkn=<token>` that verifies | sets the forwarder's login cookie, named by `cookie_name`, and redirects to `/neutrino_login` |
| asks for `/neutrino_login` with that cookie | sends `POST /api/auth/login` to the published port with the JSON body `{username, password}` and no `Origin`, and answers a page that stores the returned `token` in `localStorage['token']` and the user's name in `localStorage['user']` and then sends the browser to `/` |
| holds `?tkn=<token>` that does not verify, has expired or was spent | 401 |
| asks for a refused route, whatever else it holds | 401 |
| holds the login cookie with a good signature and expiry | passed on unchanged, `Host` and `Origin` as the browser sent them, WebSockets included, and AstrBot checks the token the page sends |
| holds neither | 401 |

| Refused route | Reason |
| --- | --- |
| the login: `/api/auth/login`, `/api/v1/auth/login`, `/api/auth/desktop-session` and `/api/v1/auth/desktop-session` | The forwarder alone signs in, and a browser's login never reaches AstrBot. |
| the setup and the account: `/api/auth/setup`, `/api/v1/auth/setup`, `/api/auth/setup-authenticated`, `/api/auth/account/edit` and `/api/v1/auth/account` | A password or a user name changed in the page leaves the module's password wrong, and the page opens no more. |
| the second factor: `/api/auth/totp/setup`, `/api/v1/auth/totp/setup`, `/api/auth/totp/recovery` and `/api/v1/auth/totp/recovery` | A TOTP code on the dashboard user stops the forwarder's login, which sends the password alone. These paths are read from AstrBot 4.29.4's source; the lab did not send them. |
| the self-update: `/api/update/do`, `/api/update/dashboard`, `/api/v1/updates/core` and `/api/v1/updates/dashboard` | The self-update migrates the data and then writes a newer core into the container's own layer. The container made again at the next start runs the module's version on data a newer version moved. |

| Rule | Reason |
| --- | --- |
| The login cookie is the forwarder's own, `base64url(expiry \|\| HMAC-SHA256(key, expiry))` with the key derived from the module's secret, HttpOnly and SameSite=Lax, and lasts seven days, the shape of Codeg's ([codeg.md](codeg.md)). | The page never needs AstrBot's own cookie, `astrbot_dashboard_jwt`. The forwarder's cookie admits every request of the page, its files and scripts included. |
| The cookie's name is the entry's `cookie_name`, `neutrino_` and the first 12 hex characters of the SHA-256 of the entry's id ([../module_template.md](../module_template.md), "The run"). | Two machines' AstrBot pages at two local ports of one client keep both logins only under two names. Their `localStorage` stays apart by itself, since a browser keeps it per origin, the port included. |
| The login is the forwarder's own request to the published port, with the JSON body and no `Origin`. AstrBot's token lasts seven days, as the cookie does. | AstrBot returns its token, an HS256 JWT under `jwt_secret` with seven days' expiry, to a program that sends the password. In the lab Chromium reached the page through such a forwarder in 1.5 to 2.7 seconds and Firefox in 3.4, with no response of 400 or above, and the web chat worked. |
| The token is the one every page behind a forwarder takes, made from the module's secret, verified on the device and spent once ([../module_template.md](../module_template.md), "The run"). | The hub generates a token on each `service` ask, and the device checks it with no call to the hub. |

The module runs one instance per machine, for one person. Its bots,
conversations, plugins and gateway key are the same for everyone who signs
in, so no instance runs per account.

## App shares

| Rule | Reason |
| --- | --- |
| The manifest names `web_share: {guest_login: run_account}`, and a visitor of an App share is signed in as the dashboard user `astrbot`, the way the owner's clients are ([../module_install.md](../module_install.md), "The manifest"). | AstrBot has one dashboard user, and the forwarder signs every browser in as it. The visitor can do what that user can until the share ends, its bots, plugins and conversations among them. |
| The share page keeps AstrBot's token where the app stores it, in the share site's `localStorage`, and it stays there after the tab closes ([../../web_share.md](../../web_share.md), "What the page keeps"). | The token opens nothing alone: every request reaches the forwarder through the share's `connect` streams, and the forwarder's cookie is in the tab's memory alone. An App share of AstrBot is not proven in the lab. |

## Chat platforms

Each bot a person adds in AstrBot's page runs one platform adapter. An
adapter either connects out to its platform, or waits for the platform's
servers to call an HTTPS address on the internet. The hub gives AstrBot no
such address: a client reaches its page through the hub's channel, a
visitor of an App share through the share page, and the forwarder answers
401 to every other request.

| The bot connects out, and works | AstrBot's adapter and mode |
| --- | --- |
| QQ official bot | `qq_official`, WebSocket |
| personal WeChat | `weixin_oc`, Tencent's iLink long polling, signed in with a QR code |
| WeCom AI bot | `wecom_ai_bot` in the `long_connection` mode |
| Feishu and Lark | `lark` in the socket mode |
| DingTalk | `dingtalk`, Stream |
| Telegram | `telegram`, long polling |
| Discord | `discord`, its gateway |
| Slack | `slack` in Socket Mode |
| Misskey, KOOK and Satori | each over a WebSocket the adapter opens |
| Mattermost | `mattermost`, its messages over a WebSocket the adapter opens; its message buttons call back and do not work |

| The platform calls back, and the bot does not work | AstrBot's adapter and mode |
| --- | --- |
| WeChat Official Accounts | `weixin_official_account`, a webhook alone |
| WeCom app and customer service | `wecom`, a webhook alone |
| QQ official bot's webhook mode | `qq_official_webhook` |
| LINE | `line`, always the unified webhook; it also fetches media from `callback_api_base` |
| the webhook modes of Feishu, the WeCom AI bot and Slack | `lark`, `wecom_ai_bot` and `slack` in a webhook mode |

| Rule | Reason |
| --- | --- |
| A bot whose adapter connects out works from any machine that reaches its platform. | The adapter opens the connection, and the platform sends every message over it. |
| A bot whose platform calls back does not work. AstrBot's unified webhook, `/api/platform/webhook/<uuid>` on 6185, receives no call from the platform, and the module publishes none of the adapters' own ports, 6194 to 6198. | A platform's callback is an HTTPS request from its servers to a fixed public address. The forwarder answers it 401, since it holds neither a token nor the login cookie. |
| The module installs no NapCat. A person's own NapCat on the same machine reaches AstrBot's OneBot v11 adapter, `aiocqhttp`, at `127.0.0.1:6199`. | A personal QQ account reaches AstrBot through NapCat alone, which speaks QQ's unofficial protocol, and an account that uses it risks a ban. The adapter listens on 6199 for NapCat to connect in from the moment a person adds such a bot, with no restart. |
| 6199 is published at `127.0.0.1:6199`, that fixed number, and is in the hub container's `local_ports`: in no entry, and served by no `connect` stream ([containers.md](containers.md), "Hub containers"). | NapCat's settings name AstrBot's default, 6199. The adapter's token is empty by default, so the port reaches programs on the machine alone. An entry offers its port to the hub's clients. |
