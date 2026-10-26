# The Codeg module

The `codeg` module runs Codeg's `codeg-server`, tested at 0.35.1 (Apache-2.0), a web
page for AI coding sessions beside CloudCLI, once per enabled account on Linux
(amd64 and arm64), macOS (arm64 and amd64) and Windows (x64; the publisher
builds no Windows arm64 server). It is a program run as a person's account
([module_template.md](../module_template.md)): `agent/neutrino_agent/modules/codeg/` holds
`config.py`, `constants.py` and `hooks.py`, and `modules/shared/` does the
rest. Its configuration is `{instances: [{account, secret, password}]}`,
as code-server's with the account's login for a Windows machine, and the
agent takes each instance's port itself from 3101 up
([../../protocol.md](../../protocol.md), "The account layer in the state").

**Two artifacts, each its own archive.** `data/manifests/codeg.json` names,
per platform, the server bundle at the module's version: `codeg-server`,
`codeg-mcp`, `codeg-computer-helper` and `web/`, the web UI. Beside it is
Node.js 22, the same build CloudCLI's manifest pins, held again under this
module and pinned for every version. The server's versions and digests come
from Codeg's GitHub releases, its one source. The agent opens `package
{module: codeg, artifact, digest}` for each and unpacks it under
`codeg/<directory>/` in the state root, `server/` and `node/`, read-only to
every account and on no `PATH`. Codeg's binaries need glibc 2.34, the
agent's own floor, so the Linux entries name no `min_version`.

**The data directory is the account's.** `CODEG_DATA_DIR` is
`~/.local/share/neutrino/agent/codeg/` on Linux, `~/Library/Application
Support/Neutrino/agent/codeg/` on macOS and
`%LOCALAPPDATA%\Neutrino\agent\codeg\` on Windows, made as the account: the
database `codeg.db`, `uploads/`, `logs/`, and the prefix and cache of the
npm packages Codeg installs. Codeg's own `~/.codeg`, where it keeps its
installed skills, is the account's, and the module reads and writes nothing
there.

**The service's environment is written from scratch** by the account service
layer ([module_template.md](../module_template.md), "The run"):

| Variable | Value |
| --- | --- |
| `CODEG_HOST` | `127.0.0.1` |
| `CODEG_PORT` | an internal loopback port the agent picks and records in the instance's record; the instance's port is the forwarder's |
| `CODEG_TOKEN` | derived from the instance's secret, `base64url(HMAC-SHA256(secret, label))`, `label` a fixed string in the module's `constants.py` |
| `CODEG_DATA_DIR` | the data directory |
| `CODEG_STATIC_DIR` | `web/` inside the server artifact's directory |
| `CODEG_BRIDGE_PORTS` | `off` |
| `NPM_CONFIG_PREFIX`, `npm_config_cache` | two directories under the data directory |
| `PATH` | the module's Node first, then the account's `~/.local/bin` and `~/bin`, then the system's directories as CloudCLI lists them ([cloudcli.md](cloudcli.md)) |

The service runs under `umask 077`, so every file Codeg and the agents it
starts write is the account's alone; Codex copies the whole environment,
`CODEG_TOKEN` included, into its shell snapshots. Its stdout and stderr are
discarded on every system, because codeg-server prints the token to stderr
at startup. The `journal` verb reads Codeg's own daily log,
`logs/codeg-server.<date>.log` under the data directory, which holds no
token.

**The forwarder trades a token for the browser's login.** It listens on
`127.0.0.1` at the instance's port, where the agent's end of a `connect`
stream reaches it, and passes what it admits to `127.0.0.1:<CODEG_PORT>`:

| A request | The forwarder |
| --- | --- |
| carries `?tkn=<token>` that verifies | answers a page of its own that stores the instance token in `localStorage['codeg_token']`, sets the forwarder's own login cookie, `neutrino_codeg_<port>`, as code-server's forwarder does, and sends the browser to `/workspace` |
| carries `?tkn=<token>` that does not verify, has expired or was spent | 401 |
| carries `Authorization: Bearer <token>` equal to the instance token, or is a WebSocket upgrade whose `Sec-WebSocket-Protocol` carries `codeg-token.<base64url(token) without padding>` | passed on unchanged |
| carries the login cookie with a good signature and expiry | passed on unchanged, pages and files included |
| carries neither | 401 |

Every endpoint behind the check is passed on, Codeg's `/api/health` among
them. The token is the one every program run as an account takes
([module_template.md](../module_template.md), "The run"): the hub generates it from the
instance's secret on every `service` ask, it expires 60 seconds later, and
it works once. Codeg's web UI keeps the instance token in
`localStorage['codeg_token']` itself, as the publisher's own pages do, sends
it as the Bearer header on every call and as the second subprotocol of its
one WebSocket, `/ws/events`, and a 401 sends the browser back to `/login`.
The login cookie is `base64url(expiry || HMAC-SHA256(key, expiry))`, the key
derived from the instance's secret, and lasts seven days, the same shape as
code-server's ([code_server.md](code_server.md)); the instance token stays
what Codeg's own calls carry.

**The entry, the details and the refusals are code-server's.** Each instance
a running module serves is published as one app,
`codeg_<device id>_<account>`, titled `Codeg (<account>)`, whose one entry,
`web`, has
`is_token_required: true` and `description_code` `codeg_module`. `details`
is `{version, instances: [{account, port, is_running, code}]}`, and an apply
refuses `account_invalid`, `account_duplicate` and `secret_missing`, each
naming the `account`, and `account_unknown {account}` for an account the
machine does not have ([protocol.md](../../protocol.md), "The modules section, one entry per
module").

**The version moves in the hub.** Codeg's **Software Update** screen cannot
write a root-owned unpack, says so, and offers the release page. Another
version is installed from the module's tab, and a new tested version in
`codeg.json` reaches every machine that chose none at the next apply
([module_install.md](../module_install.md), "Module versions").

**Its agents are ACP adapters.** Codeg installs each coding agent itself,
with `npm install --global` and `--registry https://registry.npmjs.org` on
its own command line, which npm reads before any setting. That registry is
the one download whose source the hub does not choose
([module_install.md](../module_install.md), "Sources"). Its Claude Code and Codex
entries are the adapters `claude-agent-acp` and `codex-acp`, which read the
account's `~/.claude/settings.json` and `~/.codex/config.toml`, the files
cc-switch writes, so the machine's AI tools setting points them at the
gateway ([ai_tools.md](../ai_tools.md)). Codeg's own **Model Providers**
settings write the same files, so the setting wins at the next state.

An open session costs about 300 MB on the machine while its page is open,
and its agent process exits a few minutes after the page closes.
