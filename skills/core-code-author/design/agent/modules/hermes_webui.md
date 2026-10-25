# The Hermes WebUI module

The `hermes_webui` module runs Hermes WebUI (MIT), a web page for Hermes
Agent, Nous Research's AI agent (MIT), as two containers on the Containers
module. One container runs the agent's gateway, and the other runs the webui,
which imports the agent's Python code from a volume the two share. The
module's software is container images, installed by the `container` method
([module_install.md](../module_install.md), "From container images").

`agent/neutrino_agent/modules/hermes_webui/` holds `config.py`,
`constants.py` and `hooks.py`: the forwarder's login, the gateway keys and the
health read, which the `container` runner calls. The configuration is
`{port, secret, password}`: the forwarder's port, 8787 unless the person sets
another, the token secret, and the webui's password. The hub generates the
secret and the password the first time the module is installed or its port
is set, and seals both in
`config/devices/<id>/hermes_webui.json`, beside the module's gateway key. The
module runs wherever Containers runs ([containers.md](containers.md)).

## The two images

| Image | Version | Index digest | Sources |
| --- | --- | --- | --- |
| webui | 0.52.492 | `sha256:e507cafa7b112de9abd58348423ded28a8182539e6ebb5f95be603f20aff52e6` | `ghcr.io/nesquena/hermes-webui`, `ghcr.nju.edu.cn/nesquena/hermes-webui`, `ghcr.m.daocloud.io/nesquena/hermes-webui` |
| agent | v2026.9.24 | `sha256:fca358f12efd65bfaaca05884166f15c0e2788375ca30d77061ac1ebc96452b7` | `docker.io/nousresearch/hermes-agent`, which Podman reaches through the docker.io mirrors the Containers module names |

Each index covers amd64 and arm64. The manifest's four `container` entries,
`linux`, `windows-amd64`, `darwin-arm64` and `darwin-amd64`, name the same two
artifacts.

| Rule | Reason |
| --- | --- |
| The two images are one tested pair. The module's version is the webui's, `0.52.492`, and the agent image is pinned beside it by its digest. | The webui imports the agent's code at its first start. The `exp-0.52.555` webui with the agent of its day stopped there with uv's `No solution found when resolving dependencies`. |
| The module's `container` entries name no `releases`, so the tested pair is the one version a machine can install. `GET /api/agent/module/version` returns `is_locked: true`, and `version/set` rejects the module with `version_locked {module}`. | The webui publishes prereleases every day, and neither publisher states which webui runs with which agent. A new pair reaches the machines in a hub release, after it is tested. |

## The containers

Both containers join the network `neutrino_hermes_webui` and have the label
`neutrino.module=hermes_webui`, as every hub container does
([containers.md](containers.md), "Hub containers").

| Container | Image | Command | Ports |
| --- | --- | --- | --- |
| `neutrino_hermes_webui_agent` | agent | `gateway run` | none |
| `neutrino_hermes_webui` | webui | the image's own | the webui's 8787, published on `127.0.0.1` at a port the agent picks ("The page") |

| Volume | Holds | In the agent container | In the webui container |
| --- | --- | --- | --- |
| `neutrino_hermes_webui_home` | data: `config.yaml`, sessions, memory, skills, and the webui's state under `webui/` | `/opt/data` | `/home/hermeswebui/.hermes` |
| `neutrino_hermes_webui_workspace` | data: the files the person works on in the page | none | `/workspace` |
| `neutrino_hermes_webui_agent` | cache: the agent image's `/opt/hermes`, which Podman copies into the volume at its first mount | `/opt/hermes` | `/home/hermeswebui/.hermes/hermes-agent`, read-only |
| `neutrino_hermes_webui_app` | cache: the webui's virtual environment, built at its first start | none | `/app` |

| Variable | Container | Value |
| --- | --- | --- |
| `HERMES_UID`, `HERMES_GID` | agent | `1024` |
| `WANTED_UID`, `WANTED_GID` | webui | `1024` |
| `HERMES_WEBUI_STATE_DIR` | webui | `/home/hermeswebui/.hermes/webui` |
| `HERMES_WEBUI_PASSWORD` | webui | the module's password |
| `NEUTRINO_GATEWAY_URL`, `NEUTRINO_GATEWAY_KEY` | both | the gateway's address and the module's key ("The gateway") |
| `PIP_INDEX_URL`, `UV_DEFAULT_INDEX`, `UV_INDEX_URL` | both | the fastest source of the `pypi` source set ("The first start") |

The webui image sets `HERMES_WEBUI_HOST=0.0.0.0` and `HERMES_WEBUI_PORT=8787`
itself, and the module leaves both as the image sets them.

| Rule | Reason |
| --- | --- |
| Both containers start as root and step down to uid and gid 1024, the number each image's own variables give its user. | Both write `home`, so the volume needs one owner. Each image renames its user to the number it is given and exits on a `--user` of another. |
| The webui's unit names the agent container's unit in `Requires=` and `After=`, through the hub container's `after`. | Podman fills `agent` from the agent image at the volume's first mount. A webui that mounts the empty volume first finds no agent code to install. |
| A version change comes with a hub release whose manifest names a new tested pair, and reaches each machine at its next apply. The agent stops both containers, removes `agent` and `app` and makes them again, and keeps `home` and `workspace`. | Podman copies an image's files into a new volume alone, so a kept `agent` holds the old agent, and `app` holds a virtual environment built against it. |
| The module reads `running` while both containers run and the webui's `/health` returns 200 at its published port. | Neither image declares a health check. `/health` returns 200 with no login, and only after the webui's first start has ended. |
| The module's journal is the two containers' journals, the agent container's first. | Each container's journal is read as Containers reads any container's journal. |
| An uninstall removes both containers, the network and all four volumes, `home` and `workspace` among them. | A container module is removed whole, and its data is in its volumes ([module_install.md](../module_install.md), "From container images"). |

The agent container starts first, and the webui starts after it. The agent
writes the gateway keys while the webui's first start runs, and the module's
entry appears only after both ("The first start").

## The page

The page is one `web` entry, `hermes_webui_<device id>`, titled `Hermes
WebUI`, with `is_token_required: true` and `description_code`
`hermes_webui_module`. The entry exists while the module reads `running`.

| Rule | Reason |
| --- | --- |
| The agent's forwarder listens on `127.0.0.1` at the configured port, where the agent's end of a `connect` stream reaches it. | The configured port is the page's, as a program run as an account has its forwarder at the configured port ([module_template.md](../module_template.md), "The run"). |
| The webui's 8787 is published on `127.0.0.1` at a free loopback port the agent picks at the first apply. The agent keeps it in the module's record, root-only under `platform.agent_data_dir()`, and writes it into the container's Quadlet file or plain unit. | The forwarder holds the configured port, which is 8787 too unless the person sets another. A port picked one time keeps the container's file the same across applies. |
| The published port is in no entry, and the `connect` stream does not serve it. | Every request from a client reaches the webui through the forwarder's check. |
| A configured port another program holds is one line in the agent's log, and the forwarder tries it again every report interval. | The page is there when the other program lets the port go. |
| The webui's own password stays set. | A program on the machine that finds the published port still meets the webui's login. On macOS every container in the Podman machine reaches the Mac's loopback. |

The forwarder turns the hub's token into the webui's own login:

| A request | The forwarder |
| --- | --- |
| holds `?tkn=<token>` that verifies | sends `POST /api/auth/login` to the webui with the JSON body `{"password": <password>}`, sets the `hermes_session` cookie the webui returns on the browser, and redirects to `/` |
| holds `?tkn=<token>` that does not verify, has expired or was spent | 401 |
| holds the `hermes_session` cookie | passed on unchanged, `Host` and `Origin` as the browser sent them, and the webui checks the cookie |
| asks for `/api/auth/login`, whatever else it holds | 401; the browser's login request never reaches the webui |
| holds neither | 401 |

| Rule | Reason |
| --- | --- |
| The forwarder passes `Host` unchanged. | The webui rejects a browser's POST whose `Origin` differs from its `Host` with 403. In the lab a forwarder that rewrote `Host` got 403. |
| The login is the forwarder's own request to the published port, with the password as JSON and no `Origin`. | The webui rejects a form post with 400, and accepts a POST with no `Origin`, as a program sends it. The browser holds the cookie and never the password. |
| The cookie is the webui's, HttpOnly and SameSite=Lax, and lasts 30 days. | The webui checks it on every request, and the forwarder keeps no login state of its own. |
| The token is the one every page behind a forwarder takes, made from the module's secret, verified on the device and spent once ([module_template.md](../module_template.md), "The run"). | The hub generates a token on each `service` ask, and the device checks it with no call to the hub. |

The module runs one instance per machine, for one person. Its sessions,
memory, workspace and gateway key are the same for everyone who signs in, so
no instance runs per account. The webui's share links, `/share/<id>`, open
with no login of the webui's own. The forwarder returns 401 to a request with
neither a token nor the cookie, so a share link opens only in a browser that
signed in through the page, from a client the hub allows this entry.

## The gateway

The agent points Hermes at the hub's AI gateway by writing three keys into
`config.yaml` in `home`:

| Key | Value |
| --- | --- |
| `model.provider` | `custom` |
| `model.base_url` | `NEUTRINO_GATEWAY_URL` with `/v1` after it: `http://host.containers.internal:8317/v1` on a managed machine, and the gateway's `listen_port` in place of 8317 on the hub's own machine |
| `model.key_env` | `NEUTRINO_GATEWAY_KEY` |
| `model.default` | not written: the person picks it from the gateway's models, which the page lists under `custom` |

| Rule | Reason |
| --- | --- |
| The agent writes each key with `podman exec -u hermes -e HERMES_HOME=/opt/data neutrino_hermes_webui_agent hermes config set <key> <value>`. | Hermes reads a custom endpoint from `config.yaml` alone; `OPENAI_BASE_URL` picks no custom endpoint. `hermes config set` keeps every other line of the person's file. |
| The keys are written after the install, when `config.yaml` exists in `home`, and again whenever the base URL differs from the one the module's record holds. | The agent image writes `config.yaml` at its first start, about 5 seconds in. The base URL changes with the gateway's `listen_port` on the hub's own machine. |
| `model.default` is never written. | The model is the person's choice, made in the page from the models the gateway serves. |
| The key is in the containers' environment alone, and `config.yaml` names only its variable. | The hub rewrites the environment at every apply, so a new or voided key reaches Hermes with no edit of the person's file. |
| The webui container is the one that calls the gateway, with the key from its own environment. | The webui runs the agent's code in its own process: in the lab a stand-in gateway saw every chat request come from the webui's address. |

The containers reach the gateway at `host.containers.internal` through the
agent's relays ([../../agent.md](../../agent.md), "The listeners a container
reaches"). The gateway accepts the module's key whatever the machine's AI
tools setting says ([containers.md](containers.md), "Reaching the machine").

## The first start

The webui's first start runs `uv pip install` into `app` for about 100 Python
packages, the agent's dependencies among them. uv reads its index from
`UV_DEFAULT_INDEX`, and an older uv from `UV_INDEX_URL`; pip reads
`PIP_INDEX_URL`.

| Rule | Reason |
| --- | --- |
| The module's `container` entries list one source set, `source_sets: ["pypi"]`. Before the agent writes a container's file, it probes the set and writes each of the set's three variables, with the fastest index, into the container's environment ([module_install.md](../module_install.md), "Source sets"). | The index is the one download of the first start, and which index is fastest depends on the machine's own network. |
| The `pypi` set holds PyPI and its mirrors at Tsinghua, Aliyun and Tencent, the publisher's first. | Each serves the same packages under the same hashes, and every module that fetches Python packages chooses from the same list. |
| From the install, and after a version change, the module reads `installing` until `config.yaml` holds the keys with the current base URL and `/health` first returns 200. The state is applied again every 30 seconds meanwhile. | The first start took 30 seconds on the lab machine with pypi.org, and a slow index takes minutes. The entry appears when the page can serve a chat. |
| The two images take about 3.2 GB, and the two caches about 2.4 GB, on the disk of Podman's storage. | The agent image is 2.8 GB, and `agent` and `app` hold copies of its code and of the packages built for the webui. |
