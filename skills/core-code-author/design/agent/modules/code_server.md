# The code-server module

The `code_server` module runs code-server, the browser build of VS Code
that Coder publishes (MIT), once per account on Linux and macOS. Its
extensions come from Open VSX, code-server's own default gallery. It is
a program run as a person's account ([module_template.md](../module_template.md)):
`agent/neutrino_agent/modules/code_server/` holds `config.py`,
`constants.py` and `hooks.py`, and `modules/shared/` does the rest. Its
configuration is `{instances: [{account, port, secret}]}`. Its manifest has
no Windows branch, so the Modules page greys it out on Windows.

**The account service layer runs it as the account, never as root**
([module_template.md](../module_template.md), "The run"): a unit
`neutrino_code_server@<account>.service` with `User=<account>` on Linux, and
a LaunchDaemon `com.neutrino.code_server.<account>` with `UserName` on
macOS, whose `StandardOutPath` and `StandardErrorPath` name
`/Library/Logs/Neutrino/agent/code_server_<account>.log`, the file its
journal reads there. Its settings and extensions are in code-server's own
directories under the account's home.

**The release comes from its publisher.** `data/manifests/code_server.json`
pins the standalone release for Linux and macOS on amd64 and arm64, each with
its url and sha256, at the source the edition names. In `cn` the installer
tries the pinned version at the mirror and checks its sha256; when the mirror
no longer carries it, the installer takes the mirror's current release,
checked by HTTPS alone, and `details` name the version installed
([install_and_dev.md](../../install_and_dev.md), "Where each edition fetches
from"). The module's installer fetches the archive into the module cache and
sends it down `package {module: code_server}`. The agent unpacks it under its
state root, `/var/lib/neutrino/agent/code_server/` on Linux and
`/Library/Application Support/Neutrino/agent/state/code_server` on macOS:
owned by root, read-only to every account, one copy per machine, never on
`PATH`. The release includes its own Node.js, which is code-server's alone
and which no other module reads.

**code-server listens on a socket only its account opens.** The service
runs `code-server --auth none --socket <run-dir>/code_server.sock
--socket-mode 600 --disable-telemetry --disable-update-check`, where
`<run-dir>` is `code_server/run/<account>/` under the state root, owned by the
account, mode 700. Root and the account alone can open the socket, so
`--auth none` admits nobody else.

**The agent's forwarder is in front of it, as in front of CloudCLI
([cloudcli.md](cloudcli.md)).** It
listens on `127.0.0.1` at the configured port, where the agent's end of a
`connect` stream reaches it, and passes what it admits to the socket:

| A request | The forwarder |
| --- | --- |
| carries `?tkn=<token>` that verifies | sets its own login cookie, `neutrino_code_server_<port>`, and redirects to the same path without the token |
| carries `?tkn=<token>` that does not verify, has expired or was spent | 401 |
| carries the login cookie with a good signature and expiry | passes it on unchanged, WebSocket included |
| carries neither | 401 |

The token is CloudCLI's ([cloudcli.md](cloudcli.md)): the hub mints it from
the instance's secret on every `service` ask, it expires 60 seconds later,
and it works once. The login cookie is `base64url(expiry || HMAC-SHA256(key,
expiry))`, the key derived from the instance's secret, and lasts seven days.
The agent keeps a root-only record per instance, its port and its secret, so
the forwarder comes back after an agent restart.

Each instance a running module serves is published as one `web` entry,
`code_server_<device id>_<account>`, titled `code-server (<account>)`, with
`is_token_required: true` and `description_code` `code_server_module`
([protocol.md](../../protocol.md), "The services section, one entry per
published service").
