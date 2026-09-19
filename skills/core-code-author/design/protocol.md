# The protocol

The protocol is everything the hub speaks: the panel's HTTP API and `/ws`
sockets on the panel port, and the channel on the agent port. One vocabulary
and one set of rules cover both, and this page is their only record. An
endpoint, a frame, a kind or a code absent from this page does not exist.
Adding one is an edit here in the same change.

## Two ports, two audiences

The hub listens on two ports because its two audiences verify it differently.
A browser trusts a password on a local network; an agent or a client trusts a
pinned certificate on any network.

| Port | Transport | Serves | Authenticated by |
| --- | --- | --- | --- |
| `listen_port`, default 8080 | plain HTTP | the panel: its page, every `/api/hub` and `/api/agent` route, every `/ws` socket | the session cookie |
| `agent_listen_port`, default 8443 | TLS, pinned by fingerprint | `/api/channel` and nothing else | the ticket at `join`, then the token in `hello` |

Both are uvicorn servers in the one `nhub run --only-web` process, with one
shared runtime. That runtime is where a ticket generated on the panel port is
spent on the agent port. The panel app does not include the channel routes,
so the channel has no plaintext form.

### The panel port

The session cookie is named after the port, `neutrino_session_<port>`, so two
hubs on one host keep separate sessions. The login page reads
`/api/hub/setup`, `/api/hub/auth` and `/api/hub/display` before a session
exists, so those prefixes take no session dependency. Every other route on
this port requires the session, and every state-changing route checks the
`Origin` header against the panel's own.

### The agent port

The agent port listens on every exposed interface, whatever its role, WAN
included, and on every exposed overlay. A served LAN that is not exposed keeps
DHCP, DNS and forwarding only. The addresses in an enrolment link are this same
set, `RouterNetworkConfig.exposed_interfaces` in `modules/router/interfaces.py`.
It is a pure function equal to `exposed_device_names + exposed_overlay_device_names`;
a LAN contributes its configured address, every other interface its live IPv4.

One test asserts that the link's address set equals the firewall's open set.
Enrolling a device on a LAN begins with exposing that LAN.

### The identity agents and clients pin

`nhub setup` writes a self-signed pair under `config/web/agent_tls/`:
`certificate.pem` in the clear, and `key.sealed`, the private key sealed under
the vault's data key. Serving unseals it into
`/var/lib/neutrino/agent_tls_key.pem`, mode 0600. The key is EC P-256 and the
certificate is valid for ten years. Verification is the fingerprint alone, so
the validity window only has to outlast the box.

`nhub apply` and `nhub run --only-web` generate a missing pair, and
`nhub reset all` deletes the pair with the vault key. An existing pair is kept
as it is, because every binding pins its fingerprint.

The fingerprint is the SHA-256 of the certificate's DER encoding, 64 lowercase
hex characters. It reaches a peer only inside a link a signed-in person
generated. A peer checks the fingerprint after every TLS handshake and before
any request bytes leave the machine. A mismatch closes the socket and aborts
the whole enrolment, because a wrong certificate on a link's address is an
impersonation.

A peer connects to an `https` URL only with a fingerprint to check it against.
Chain and hostname verification are off, and TLS 1.2 is the floor.

### The hub's own identity

`config/web/identity.json` is `{id, name}`: `id` is a uuid generated at setup
and `name` defaults to the hostname. The Settings page changes the name through
`POST /api/hub/setting/set` with `hub_name`; `nhub setup`, `nhub apply` and
`nhub run` create the file when it is missing, and `nhub reset all` deletes it.
The `welcome` frame includes both, so a client groups its hubs by `id` and
labels them by `name`.

## Keys and names

A key is a uuid4 hex string the hub generates, and a name is a display string a
person edits. The key is the same for the life of the binding, whatever the
name becomes.

| Thing | Key | Generated | The name changes on |
| --- | --- | --- | --- |
| a device | its binding id | by the hub when it first records the machine: at `join` for a blank link, earlier when a link is created for a row that already exists | the Devices page |
| a client | its binding id | by the hub when the client link is created for a machine it holds no row for; a machine it already holds one for joins back onto that row and keeps its key | the Clients page |
| the hub | `id` in `identity.json` | at `nhub setup` | the Settings page |

A device id and a client id have one shape and are told apart by `role`. Every
store the hub keeps per device is keyed by this id: `devices.json`,
`config/devices/<id>/`, the session registry, the desktop shares and the
published services. A rename writes the name and moves nothing.

## Paths

A path on the panel port is `/api/<group>/<page>/...`, grouped the way the
sidebar is. Every segment is a singular `under_score` noun, except the last
segment of a write, which is a verb.

| Rule | Reason |
| --- | --- |
| Group, then page. `/api/hub/<page>` is a page of the hub itself and `/api/agent/<page>` a page of a managed device (`file`, `module`; the terminal is a socket only). One page is one router file on one prefix, `web/routers/hub/<page>.py` or `web/routers/agent/<page>.py`; what belongs to a page nests under it (`/api/hub/overlay/netbird/...`, `/api/hub/ai/gateway/...`, `/api/agent/module/samba/...`), and a large nested block is a second file on the same prefix (`hub/overlay_netbird.py`, `hub/ai_gateway.py`, `agent/module_samba.py`). `/ws` splits the same way into `/ws/hub/...` and `/ws/agent/...`. `/api/channel` is on the agent port's own app and is in no group. | The sidebar has two groups, a reader of a path finds the page it draws, and nothing is mounted at the top level. |
| Every segment is a singular `under_score` noun, with an adjective in front where one is needed: `wifi_network`, `ssh_key`, `seat_password`. The panel shows plurals; a path has none. | One spelling per thing across paths, models and config keys. |
| An identifier names the member in the body or the query, never in the path: `?device_id=...` on a GET, `{device_id}` in a POST body. A path has no `{id}` in it. | A path is a fixed string a reader can grep, and an id is data. |
| A read is a GET on a path of nouns and returns a view. A write is a POST whose last segment is one verb, with every argument in the body, and it returns what the matching read returns. The methods are GET and POST. | The page replaces its state with the response and merges nothing, so it cannot hold a version of the box that the box does not. |
| A verb comes from the verb table, an opposite is added with its pair, and paths of paired verbs have the same depth: `channel/join` and `channel/leave`, `module/install` and `module/uninstall`, `module/start` and `module/stop`. A new verb enters the table before it enters a path. | The table is closed, so the route test checks every path against it. |
| A word with a fixed meaning inside a domain (`scrub`, `import`, `backup`) can be a noun in the middle of a path: `pool/scrub/stop`. | The domain's own word is the one a reader searches for. |
| `/api/hub/setup`, `/api/hub/auth` and `/api/hub/display` take no session dependency. `GET /api/hub/display` returns `{language, theme}` in one response, and both change through `POST /api/hub/setting/set`. | The login page reads them before there is a session. |
| The router file is named after its page; the library package under `modules/` keeps its own name, so `modules/router` serves `/api/hub/network` and `modules/xray` serves `/api/hub/proxy`. | A page is what a person sees; a package is what the code does. |

### The verbs

| Verb | Opposite | Writes |
| --- | --- | --- |
| `set` | none; a GET reads it | the settings of the thing named |
| `add` | `remove` | a member into or out of a list |
| `create` | `destroy` | a thing that exists on a machine afterwards: a pool, a dataset, a directory, a link |
| `join` | `leave` | a membership |
| `start` | `stop` | a unit, a task, a login flow |
| `enable` | `disable` | whether a thing is in force |
| `share` | `unshare` | whether a thing is published |
| `install` | `uninstall` | a package |
| `login` | `logout` | a session |
| `backup` | `restore` | an archive of `config/` |
| `online` | `offline` | a pool member |
| `download` | `upload` | the bytes of a file |
| `import` | none | the hub's copy of what a machine already has |
| `update` | none | the thing named, replaced with its own newest release |
| `reset` | none | a value generated afresh |
| `apply` | none | render and apply now |
| `scan` | none | a fresh reading of what is out there |
| `test` | none | one probe of a node |
| `probe` | none | one probe of a declaration |
| `wake` | none | a Wake-on-LAN packet |
| `reboot`, `shutdown` | none | the machine's power |
| `reinstall` | none | the agent, installed again over SSH |
| `restart` | none | a container stopped and started |
| `kill` | none | a process |
| `rename` | none | a name |
| `expand`, `replace` | none | a pool's members |
| `scrub` | none | a pool scrub started; `scrub/stop` ends it |

The whole design is symmetric where a thing has an opposite and single where
it has none:

| Layer | Paired | Single, and why |
| --- | --- | --- |
| HTTP verbs | `set`; `add`/`remove`; `create`/`destroy`; `join`/`leave`; `start`/`stop`; `enable`/`disable`; `share`/`unshare`; `install`/`uninstall`; `login`/`logout`; `backup`/`restore`; `online`/`offline`; `download`/`upload` | `import`, `update`, `reset`, `apply`, `scan`, `test`, `probe`, `wake`, `reboot`, `shutdown`, `reinstall`, `restart`, `kill`, `rename`, `expand`, `replace`, `scrub`: none has a reverse operation |
| Path depth | the same for the same function: `channel/join`/`leave`; `module/install`/`uninstall`, `start`/`stop`; `device/agent/install`/`reinstall`; `zfs/dataset/share`/`unshare`; `zfs/pool/create`/`destroy` | |
| Channel frames | `hello`/`welcome`; `open`/`close`; `state`/`report` | `refused`, `credit` |
| Stream kinds | none; installing and uninstalling follow from `want` | `shell`, `file`, `command`, `package`, `log`, `service`, `desktop` |
| CLI | `nagent join`/`leave`, `nclient join`/`leave`, `nagent rdp start`/`stop`, `nclient service ... mount`/`unmount`, port forwarding `start`/`stop` | `status`, `sync`, `run`, `gui`, `quit` |

### The page, its members and its writes

```text
GET  /api/hub/network          the view the page draws, whole
POST /api/hub/network/set      the page's own settings
```

`GET` returns everything the page needs for a first paint, in one response.
`set` on the bare prefix takes the settings that belong to the page itself,
the global switches. A page with nothing global to write has no bare `set`.

A singular sub-resource is one whose write is not a setting.
`POST /api/hub/network/mode/set` replaces every interface, gives the machine's
network back or takes it over, and returns a configuration nobody sent. The
body is what the new shape needs.

The test is whether a caller could send it beside the page's other settings
and expect nothing else to move. Where they could, it belongs in the bare
`set`.

A member is written by its verb with its identifier in the body:
`POST /api/hub/network/interface/set {name, ...}` and
`POST /api/hub/proxy/node/remove {node_id}`.

A write answers with what a read answers.
`POST /api/hub/network/interface/set` returns `NetworkView`, the model
`GET /api/hub/network` returns, and applying is part of the request: the
response means the interface is already doing this.

A field is spelled once. `is_exposed` is the key in
`config/router/network.json`, the attribute on the Pydantic model in
`web/models.py`, and the property on the TypeScript interface in
`frontend/src/api_types.ts`. A path segment is spelled the way the model that
returns it is, and booleans are questions in all three, `is_` and `has_`
([coding_style/naming_style.md](../coding_style/naming_style.md)).

### The principles behind every route

Exposure is the only control plane for what the box serves.
`exposed_interfaces` decides where the panel port, the agent port and every
published service listen; no route switches a service on for one network.

An action that needs the agent online is rejected with 409 `agent_offline`
while the machine is away. The path does not say which actions those are.

## Refusals

A refusal is `{code, params}`: `code` is an `under_score` token from a closed
set, and `params` holds the values a sentence about it needs. It has one shape
wherever it appears.

| Where | Shape |
| --- | --- |
| an HTTP error | the status, with `detail: {code, params}` |
| the handshake | `refused {code, params}`, then close 4000 |
| a stream | `close {stream, code, params}`; a close without a code is the stream's result |

The HTTP status names the class of the refusal:

| Status | Class | Codes |
| --- | --- | --- |
| 400 | a body that does not validate | |
| 401 | a missing session, a dead ticket, or a token that names no binding | `ticket_spent`, `binding_unknown` |
| 404 | an unknown member | `device_unknown` |
| 409 | a state the action cannot run in | `agent_offline`, `protocol_too_old`, `protocol_too_new`, `role_mismatch` |

Every surface words a code itself: the hub's catalogs are
`hub/frontend/src/locales/<language>/codes.json` under `code.<code>`, the
client's are `client/frontend/locales/<language>.json`, and each command line
has its `cli/wording.py`. A code with no sentence fails the completeness test
of its surface. `hub/tests/web/test_code_wording.py` walks every raise site in
the hub, and the agent's and the client's wording tests walk theirs. A new
code and its wording are one change.

## What exists

The pages of the hub group come first, in sidebar order. The pages of the
agent group follow, then the panel's live sockets, then the channel on its own
TLS port.

| Prefix | Serves |
| --- | --- |
| `/api/hub/setup` | The first run's questions and the steps that answer them, served by the setup wizard before the panel starts |
| `/api/hub/auth` | Signing in and out, and what the session is |
| `/api/hub/display` | The language and the palette the panel is drawn in, read before there is a session |
| `/api/hub/dashboard` | The summary, the traffic history, the DNS log; `/ws/hub/dashboard/stat` and `/ws/hub/dashboard/dns_log` are its live readings |
| `/api/hub/network` | The mode, the interfaces and their roles, Wi-Fi, what listens where |
| `/api/hub/overlay` | Which overlay engine the box runs, and under it `netbird` (the network it joins) and `easytier` (the network it defines: peers, networks, secret) |
| `/api/hub/proxy` | Routing policy, and under it `node` (the exit nodes), `balancer`, and `geodata` (the databases the split runs on: which release is installed, and updating them to the latest) |
| `/api/hub/ai` | The providers the gateway forwards to and their order, and under it `gateway` (the gateway itself: keys, accounts, usage, journal) |
| `/api/hub/device` | Every machine on record on the LAN: the list, a scan, names, enrolment links, installing or reinstalling the agent over SSH, waking, rebooting, shutting down, its processes, its remote desktops, its seat password, its published services, which module tabs its Modules page shows |
| `/api/hub/client` | Enrolled client sessions and the links that enrol them |
| `/api/hub/service` | The published service list and manual declarations |
| `/api/hub/credential` | The secrets the box keeps for somebody: SSH keys, logins and tokens |
| `/api/hub/setting` | The panel's own: its port, password, hub name, backup, restore, version |
| `/api/agent/file` | Browsing and moving files on a device through its agent |
| `/api/agent/module` | The modules a device hosts through its agent: observed state, install, start, stop, uninstall; under it one block per module, `samba`, `gitea`, `podman`, `zfs`, each importing what the machine already has and setting what it is to have |
| `/ws` | The panel's live sockets, grouped the same way: `/ws/hub/event` (cache invalidation, site-wide), `/ws/hub/dashboard/stat`, `/ws/hub/dashboard/dns_log`, `/ws/hub/task`; `/ws/agent/terminal` |
| `/api/channel` | Agents and clients on the agent port: `join` and `leave`, and `/api/channel/socket` for everything else |

Terminals opens `/ws/agent/terminal?device_id=...`, Files reads
`/api/agent/file?device_id=...`, and Modules reads
`/api/agent/module?device_id=...`. Adding a page adds a row and a file, and a
route that fits no row is a route whose page has not been decided.

### The hub group

A `{...}` is the POST body or the GET query; a GET with no parameters returns
the page's whole view.

#### `/api/hub/setup`

| Route | Parameters | Does |
| --- | --- | --- |
| `GET /api/hub/setup/context` | | the box as the wizard finds it |
| `GET /api/hub/setup/state` | | each step and where it is |
| `POST /api/hub/setup/link/create` | | a blank enrolment link for the box's own agent |
| `POST /api/hub/setup/answer/set` | the wizard's answers | writes them and runs the steps |

#### `/api/hub/auth`

| Route | Parameters | Does |
| --- | --- | --- |
| `POST /api/hub/auth/login` | `{password}` | opens the session; returns `SessionView` |
| `POST /api/hub/auth/logout` | | ends it; returns `SessionView` |
| `GET /api/hub/auth/session` | | `SessionView` |

#### `/api/hub/display`

| Route | Parameters | Does |
| --- | --- | --- |
| `GET /api/hub/display` | | `{language, theme}` |

#### `/api/hub/dashboard`

| Route | Parameters | Does |
| --- | --- | --- |
| `GET /api/hub/dashboard/summary` | | the summary tiles |
| `GET /api/hub/dashboard/history` | | the traffic history |
| `GET /api/hub/dashboard/dns_log` | | the DNS log's last entries |

#### `/api/hub/network`

| Route | Parameters | Does |
| --- | --- | --- |
| `GET /api/hub/network` | | `NetworkView` |
| `POST /api/hub/network/set` | the page's own settings | `NetworkView` |
| `POST /api/hub/network/mode/set` | `{mode, ...}` | replaces the whole shape; `NetworkView` |
| `POST /api/hub/network/interface/set` | `{name, ...}` | one interface's role and settings; `NetworkView` |
| `POST /api/hub/network/interface/remove` | `{name}` | `NetworkView` |
| `GET /api/hub/network/wifi_network` | | the saved Wi-Fi networks |
| `POST /api/hub/network/wifi_network/leave` | `{ssid}` | forgets one |
| `GET /api/hub/network/interface/wifi/scan` | `?name=` | what one radio sees |
| `POST /api/hub/network/interface/wifi/join` | `{name, ssid, ...}` | associates one radio; `NetworkView` |

#### `/api/hub/overlay`

| Route | Parameters | Does |
| --- | --- | --- |
| `GET /api/hub/overlay` | | the engine and its state |
| `POST /api/hub/overlay/set` | `{engine, ...}` | which engine the box runs |
| `GET /api/hub/overlay/netbird` | | the NetBird network the box joins |
| `POST /api/hub/overlay/netbird/join` | the setup key and management URL | joins it |
| `GET /api/hub/overlay/easytier` | | the EasyTier network the box defines |
| `POST /api/hub/overlay/easytier/set` | its settings | |
| `POST /api/hub/overlay/easytier/peer/set` | the peer list | |
| `POST /api/hub/overlay/easytier/network/set` | the network list | |
| `POST /api/hub/overlay/easytier/suggestion/create` | | a suggested network for a member |
| `GET /api/hub/overlay/easytier/secret` | | the network secret |

#### `/api/hub/proxy`

| Route | Parameters | Does |
| --- | --- | --- |
| `GET /api/hub/proxy` | | the view, with `geodata: {geoip_version, geosite_version, source, latest?}` |
| `POST /api/hub/proxy/set` | routing policy | |
| `POST /api/hub/proxy/apply` | | renders and applies xray |
| `GET /api/hub/proxy/node` | | the exit nodes |
| `POST /api/hub/proxy/node/add` | a share link or a node | |
| `POST /api/hub/proxy/node/set` | `{node_id, ...}` | |
| `POST /api/hub/proxy/node/remove` | `{node_id}` | |
| `POST /api/hub/proxy/node/test` | `{node_id}`, or `{}` for every node | measures now, returns the node list |
| `POST /api/hub/proxy/balancer/set` | the balancer's settings | |
| `POST /api/hub/proxy/geodata/scan` | | reads the two latest releases from GitHub; returns the read's `geodata` block with `latest` filled |
| `POST /api/hub/proxy/geodata/update` | | fetches both files, checks their sha256, writes them atomically, restarts the xray unit; returns `TaskStarted`, output on `/ws/hub/task` |

#### `/api/hub/ai`

| Route | Parameters | Does |
| --- | --- | --- |
| `GET /api/hub/ai` | | the providers and their order |
| `POST /api/hub/ai/provider/add` | a provider | |
| `POST /api/hub/ai/provider/set` | `{provider_id, ...}` | |
| `POST /api/hub/ai/provider/remove` | `{provider_id}` | |
| `POST /api/hub/ai/provider/order/set` | the ordered ids | |
| `GET /api/hub/ai/gateway` | | the gateway's settings |
| `POST /api/hub/ai/gateway/set` | its settings | |
| `POST /api/hub/ai/gateway/apply` | | renders and applies the gateway |
| `GET /api/hub/ai/gateway/usage` | | what it metered |
| `GET /api/hub/ai/gateway/journal` | | its journal |
| `POST /api/hub/ai/gateway/key/add` | a key's name | |
| `POST /api/hub/ai/gateway/key/remove` | `{key_id}` | |
| `GET /api/hub/ai/gateway/account` | | the signed-in accounts |
| `POST /api/hub/ai/gateway/account/remove` | `{name}` | |
| `POST /api/hub/ai/gateway/account_login/start` | the provider | starts a login flow; returns its `state` |
| `GET /api/hub/ai/gateway/account_login` | `?state=` | where that flow is |
| `POST /api/hub/ai/gateway/account_login/code/set` | `{state, code}` | the code the provider showed |
| `POST /api/hub/ai/gateway/account_login/stop` | `{state}` | abandons the flow |

#### `/api/hub/device`

| Route | Parameters | Does |
| --- | --- | --- |
| `GET /api/hub/device` | | every device on record |
| `POST /api/hub/device/scan` | | scans the LAN; the list |
| `GET /api/hub/device/online` | | the devices with a socket open |
| `POST /api/hub/device/enrollment/create` | `{device_id?, name?}` | a link for that row, or for a new one |
| `POST /api/hub/device/set` | `{device_id, name, shown_module}` | the name, and which module tabs its Modules page shows |
| `POST /api/hub/device/remove` | `{device_id}` | forgets the device; its socket is closed with `binding_unknown` |
| `POST /api/hub/device/wake` | `{device_id}` | Wake-on-LAN to the last link MAC; `wol_no_mac` when none is stored |
| `POST /api/hub/device/agent/install` | `{device_id, ...}` | installs the agent over SSH; `TaskStarted` |
| `POST /api/hub/device/agent/reinstall` | `{device_id}` | the `reinstall` verb over the channel |
| `POST /api/hub/device/reboot` | `{device_id}` | the `reboot` verb |
| `POST /api/hub/device/shutdown` | `{device_id}` | the `shutdown` verb |
| `POST /api/hub/device/process/kill` | `{device_id, pid}` | the `kill` verb |
| `GET /api/hub/device/remote_desktop` | `?device_id=` | a person's own AnyDesk or TeamViewer on the machine |
| `POST /api/hub/device/remote_desktop/password/set` | `{device_id, product, password}` | its unattended password |
| `POST /api/hub/device/desktop/seat_password/reset` | `{device_id}` | a new seat password, every viewer disconnected |
| `GET /api/hub/device/service` | `?device_id=` | what the device publishes |
| `GET /api/hub/device/install_output` | `?device_id=` | the last install's output |

#### `/api/hub/client`

| Route | Parameters | Does |
| --- | --- | --- |
| `GET /api/hub/client` | | every client, grouped as the page draws them |
| `POST /api/hub/client/enrollment/create` | `{name}` | a client link |
| `POST /api/hub/client/set` | `{client_id, name}` | |
| `POST /api/hub/client/enable` | `{client_id}` | |
| `POST /api/hub/client/disable` | `{client_id}` | its `state` is pushed with `is_disabled` |
| `POST /api/hub/client/remove` | `{client_id}` | forgets the client; its socket is closed with `binding_unknown` |

#### `/api/hub/service`

| Route | Parameters | Does |
| --- | --- | --- |
| `GET /api/hub/service` | | the published list |
| `GET /api/hub/service/share` | | the shares devices declared |
| `POST /api/hub/service/declaration/add` | a declaration | |
| `POST /api/hub/service/declaration/remove` | `{service_id}` | |
| `POST /api/hub/service/declaration/probe` | `{service_id}` | one health probe |

#### `/api/hub/credential`

| Route | Parameters | Does |
| --- | --- | --- |
| `GET /api/hub/credential/ssh_key` | | the stored keys |
| `POST /api/hub/credential/ssh_key/add` | a key | |
| `POST /api/hub/credential/ssh_key/remove` | `{key_id}` | |
| `GET /api/hub/credential/login`, `POST .../login/add`, `POST .../login/remove` | `{login_id}` on remove | the same shape for logins |
| `GET /api/hub/credential/token`, `POST .../token/add`, `POST .../token/remove` | `{token_id}` on remove | the same shape for tokens |

#### `/api/hub/setting`

| Route | Parameters | Does |
| --- | --- | --- |
| `GET /api/hub/setting` | | `SettingsView` |
| `POST /api/hub/setting/set` | the settings, `hub_name`, `language` and `theme` among them | `SettingsView` |
| `POST /api/hub/setting/password/set` | the old and the new password | |
| `POST /api/hub/setting/backup` | | an archive of `config/` |
| `POST /api/hub/setting/restore` | the archive | |
| `GET /api/hub/setting/about` | | versions and the credited components |

### The agent group

#### `/api/agent/file`

| Route | Parameters | Does |
| --- | --- | --- |
| `GET /api/agent/file` | `?device_id=&path=` | lists a directory |
| `GET /api/agent/file/download` | `?device_id=&path=` | one file's bytes |
| `GET /api/agent/file/directory/download` | `?device_id=&path=` | a directory as an archive |
| `POST /api/agent/file/upload` | multipart with `device_id` and `path` | |
| `POST /api/agent/file/directory/create` | `{device_id, path}` | |
| `POST /api/agent/file/rename` | `{device_id, path, name}` | |
| `POST /api/agent/file/remove` | `{device_id, path}` | |

#### `/api/agent/module`

| Route | Parameters | Does |
| --- | --- | --- |
| `GET /api/agent/module` | `?device_id=` | each module's observed `state`, `is_active` and `details` |
| `POST /api/agent/module/install` | `{device_id, module}` | writes `want: installed` |
| `POST /api/agent/module/start` | `{device_id, module}` | writes `want: running` |
| `POST /api/agent/module/stop` | `{device_id, module}` | writes `want: stopped` |
| `POST /api/agent/module/uninstall` | `{device_id, module}` | writes `want: absent` |
| `GET /api/agent/module/samba` | `?device_id=` | the hub's Samba configuration for the device |
| `POST /api/agent/module/samba/import` | `{device_id}` | the machine's shares and users become the hub's configuration |
| `POST /api/agent/module/samba/share/set` | `{device_id, shares}` | |
| `POST /api/agent/module/samba/user/set` | `{device_id, users}` | |
| `POST /api/agent/module/samba/user/password/set` | `{device_id, name, password}` | |
| `GET /api/agent/module/gitea` | `?device_id=` | |
| `POST /api/agent/module/gitea/import` | `{device_id}` | |
| `POST /api/agent/module/gitea/set` | `{device_id, ...}` | |
| `POST /api/agent/module/gitea/admin/add` | `{device_id, ...}` | |
| `POST /api/agent/module/gitea/admin/password/set` | `{device_id, username, password}` | |
| `GET /api/agent/module/podman` | `?device_id=` | |
| `POST /api/agent/module/podman/import` | `{device_id}` | |
| `POST /api/agent/module/podman/container/set` | `{device_id, ...}` | |
| `POST /api/agent/module/podman/mirror/set` | `{device_id, ...}` | |
| `GET /api/agent/module/podman/tag` | `?device_id=` | the tags an image has |
| `GET /api/agent/module/podman/container/journal` | `?device_id=&name=` | |
| `POST /api/agent/module/podman/container/start`, `.../stop`, `.../restart` | `{device_id, name}` | |
| `GET /api/agent/module/zfs` | `?device_id=` | pools, datasets and disks as reported |
| `POST /api/agent/module/zfs/scan` | `{device_id}` | a fresh reading of the disks |
| `POST /api/agent/module/zfs/pool/create` | `{device_id, ...}` | |
| `POST /api/agent/module/zfs/pool/destroy` | `{device_id, name}` | |
| `POST /api/agent/module/zfs/pool/scrub` | `{device_id, name}` | starts a scrub |
| `POST /api/agent/module/zfs/pool/scrub/stop` | `{device_id, name}` | |
| `POST /api/agent/module/zfs/pool/expand`, `.../replace`, `.../offline`, `.../online` | `{device_id, name, ...}` | |
| `POST /api/agent/module/zfs/pool/import` | `{device_id, name}` | |
| `POST /api/agent/module/zfs/dataset/create`, `.../destroy` | `{device_id, ...}` | |
| `POST /api/agent/module/zfs/dataset/share`, `.../unshare` | `{device_id, ...}` | |

### The live sockets

| Socket | Parameters | Does |
| --- | --- | --- |
| `/ws/hub/event` | | cache invalidation, site-wide |
| `/ws/hub/dashboard/stat` | | the live readings the Dashboard draws |
| `/ws/hub/dashboard/dns_log` | | the DNS log as it grows |
| `/ws/hub/task` | `?task_id=` | one task's output |
| `/ws/agent/terminal` | `?device_id=` | a shell on the device |
| `/ws/agent/terminal` | `?device_id=&container=` | a shell inside one of its containers |
| `/ws/agent/desktop` | `?device_id=` | reserved with the `desktop` kind; unimplemented |

### The channel endpoints

| Route | Parameters | Does |
| --- | --- | --- |
| `POST /api/channel/join` | `{ticket, role, protocol, machine_id, name, software, platform}` | `{id, token}` |
| `POST /api/channel/leave` | `{id, token}` | removes the binding: a device's row keeps its place, a client's row is deleted |
| `WS /api/channel/socket` | | the channel |

### The router files

| Directory | Files |
| --- | --- |
| `web/routers/hub/` | `setup.py`, `auth.py`, `display.py`, `dashboard.py`, `network.py`, `overlay.py` with `overlay_netbird.py` and `overlay_easytier.py`, `proxy.py` with `proxy_node.py`, `ai.py` with `ai_gateway.py`, `device.py`, `client.py`, `service.py`, `credential.py`, `setting.py` |
| `web/routers/agent/` | `file.py`, `module.py` with `module_samba.py`, `module_gitea.py`, `module_podman.py` and `module_zfs.py` |
| `web/routers/` | `channel.py`, on the agent port's app |
| `web/` | `ws.py`, both socket groups |

Each router's test is `hub/tests/web/routers/{hub,agent}/test_<page>.py`
([tests.md](tests.md)).

## The channel

The channel is one socket between the hub and each machine it manages. Under
the hub there are two roles: `agent`, the resident service on a device, and
`client`, a person's session. One handshake, one envelope, one stream layer
and one admission rule serve both roles. The role decides the contents of the
two documents and which streams each side opens.

### The link and the two endpoints

A link is `neutrino://enroll/<base64url>` over one JSON object:

```json
{"urls": ["https://192.168.100.1:8443", "..."], "token": "...", "fp": "<sha256-hex>", "role": "agent"}
```

`urls` is every exposed address on the agent port, because one of them is on
the joining machine's network and neither end knows which. `role` is `agent`
or `client`, read on the pasting side before the first request. A client
rejects a device link with `link_not_for_client` and an agent rejects a client
link with `link_not_for_agent`, each code's `params` naming the link's `role`.
The base64url alphabet has no character a shell splits or a URL escapes, so
the link pastes anywhere unquoted.

| Endpoint | Body | Returns |
| --- | --- | --- |
| `POST /api/channel/join` | `{ticket, role, protocol, machine_id, name, software, platform}` | `{id, token}`; admission by `protocol` runs first and a rejected protocol spends no ticket, then the ticket is spent |
| `POST /api/channel/leave` | `{id, token}` | the binding removed: a device's row stays and drops its token, a client's row is deleted with its gateway key |
| `WS /api/channel/socket` | | everything after |

`machine_id` and `platform` are what the body says about the machine itself,
and each role reads them somewhere else:

| Field | An agent sends | A client sends |
| --- | --- | --- |
| `machine_id` | `/etc/machine-id`, else `/var/lib/dbus/machine-id`, else empty | a uuid4 hex generated on the first read of its state file and kept there |
| `platform` | `{os, family, arch}`: `linux`, the distribution family `debian`, `rhel` or empty, and the architecture normalized to `amd64`, `arm64` or `armhf` | the same three keys, `os` one of `linux`, `windows` and `darwin`, and `family` empty off Linux |

An agent's id is the operating system's, so a machine joining with a blank
link is matched to the row it already had. A client's is one installation's,
so the same person on two machines is two clients, and a client joining again
from an installation the hub has a row for lands back on that row: the link's
fresh row goes, and the old row takes the link's name and keeps its key, its
switch and everything it last reported. The hub reads `family` to pick a
package family and `arch` to pick the package itself, and an architecture
outside the normalized set is the machine's own word and matches no branch.

The join request names no network; the link a socket runs on comes from
`getsockname()` and is in the first report. Joining and leaving have the same
two words on every surface:

| Surface | Join | Leave |
| --- | --- | --- |
| HTTP | `POST /api/channel/join` | `POST /api/channel/leave` |
| the agent's command line | `nagent join <link>` | `nagent leave` |
| the client's command line | `nclient join <link>` | `nclient leave [--hub <name>]` |
| the client window | **Join a hub** | **Leave** |

The agent's binding file is `{gateway_url, id, token, fingerprint, machine_id}`,
root-owned, mode 0600, and a file missing any field is an unbound agent. The
client keeps one binding per hub it joined, with the hub's `id` and `name`
from `welcome`.

### The handshake

The first frame each way is an identity card, and both cards have one shape.

| Field | `hello` (up) | `welcome` (down) |
| --- | --- | --- |
| `protocol` | the number this build speaks | the hub's number |
| `role` | `agent` or `client` | `hub` |
| `id` | the binding id | the hub id from `identity.json` |
| `name` | the hostname, or the binding's name | the hub's name from `identity.json` |
| `software` | `neutrino_agent/0.3.0`, `neutrino_client/0.3.0` | `neutrino_hub/0.3.0` |
| `token` | the binding token | absent |

A rejected `hello` gets `refused {code, params}` and close 4000. The handshake
has no state hash; the first `report` has it.

### The frames

| Frame | Direction | Body |
| --- | --- | --- |
| `hello` | up | the identity card, with `token` |
| `welcome` | down | the hub's identity card |
| `refused` | down | `{code, params}`, then close 4000 |
| `state` | down | `{hash, ...sections}`: what is to be true |
| `report` | up | `{state_hash, ...sections}`: what is true |
| `open` | both | `{stream, kind, ...args}`: a stream begins |
| `close` | both | `{stream, code, params}`: it ends, with its result |
| `credit` | both | `{stream, bytes}`: the sender can send that many more |
| binary | both | `<u32 stream id><bytes>` |

Every action is a stream: its `open` is the request, its `close` is the reply,
and `kind` is the whole method vocabulary.

### The stream layer

| Concern | Rule |
| --- | --- |
| Ids | The hub opens its first stream at 0 and a peer its first at 1, each side stepping by 2, so the hub's ids are even, an agent's and a client's are odd, and the two never collide. |
| Bytes | A binary frame is a big-endian u32 stream id, then the bytes. A stream's text output (an install log, a command's output) is its binary frames, one line each. |
| Credit | `credit {stream, bytes}` grants the sender that many more bytes. A receiver grants as it consumes, so a long transfer starves nothing and a large package does not stall after the first window. |
| Result | `close {stream, code, params}` ends a stream from either side. `params` is the result and the only place a result goes; a `code` makes the close a refusal. A stream one side closed gets no close back. |

### The timings

Every interval and every window the channel runs on is a constant in one of
the three packages, named here so that changing one is a change to this table.

| What it bounds | Hub | Agent | Client |
| --- | --- | --- | --- |
| a fresh socket's hello | `CHANNEL_HELLO_TIMEOUT_S` 10 | | |
| connecting and the handshake on top of it | | `AGENT_REQUEST_TIMEOUT_S` 10 | `CLIENT_CONNECT_TIMEOUT_S` 10 |
| a report while nothing changes | | `AGENT_REPORT_INTERVAL_S` 5 | `CLIENT_REPORT_INTERVAL_S` 30 |
| keepalive | `CHANNEL_PING_INTERVAL_S` 20, `CHANNEL_PING_TIMEOUT_S` 20 | | |
| silence before the socket is dead | | `AGENT_WS_SILENCE_TIMEOUT_S` 45 | `CLIENT_WS_SILENCE_TIMEOUT_S` 45 |
| reconnect backoff | | `AGENT_BACKOFF_MIN_S` 5, doubled to `AGENT_BACKOFF_MAX_S` 60 | `CLIENT_BACKOFF_MIN_S` 5, doubled to `CLIENT_BACKOFF_MAX_S` 60 |
| a stream's credit window | `CHANNEL_STREAM_CREDIT_BYTES` 1 MiB | `AGENT_WS_STREAM_CREDIT_BYTES` 1 MiB | grants none |
| one binary frame | `CHANNEL_CHUNK_BYTES` 64 KiB | `AGENT_WS_CHUNK_BYTES` 64 KiB | sends none |
| a stream waiting on credit | | `AGENT_WS_CREDIT_TIMEOUT_S` 60 | |
| a stream waiting for its close | | | `CLIENT_STREAM_TIMEOUT_S` 15 |
| a hub thread's call onto the loop | `CHANNEL_CALL_TIMEOUT_S` 15 | | |

Every number is seconds except the two rows in bytes. The hub's ping interval
is inside both silence windows, so a socket with nothing to say is kept open
by the pings alone, and a peer that reaches its window closes and reconnects.
A refused `hello` is retried at the backoff's maximum, the minute named under
the binding.

An agent reports six times as often as a client because its `machine` section
carries the metrics the Dashboard draws live; a client's carries its hostname
and platform, which change between releases.

### The sections

| Section | `state` to agent | `report` from agent | `state` to client | `report` from client |
| --- | --- | --- | --- | --- |
| `machine` | | `{hostname, platform, accounts, metrics}` | | `{hostname, platform}` |
| `network` | | `{link: {interface, mac, address}, interfaces: [{name, mac, addresses[]}]}` | | |
| `modules` | `{name: {want, config, install, uninstall}}` | `{name: {state, is_active, code, params, details}}` | | |
| `desktop` | `{seat_password}` | `{is_shared, account, share_id, port, attention, connected_count}` | | |
| `services` | | | `[{id, type, title, payload, is_healthy, source, description, description_code, description_params}]` | |
| `is_disabled` | | | bool | |
| `error` | | `{code, params}` | | |

The `error` section is the agent's most recent failure worth showing: the last
error, the state error, or a failed `reinstall`. The AI gateway is a `services`
entry whose `type` is `ai`, and a client gets its key through the `service`
stream.

### The modules section, one entry per module

```json
"samba": {
  "want": "running",
  "config": {"shares": ["..."], "users": ["..."]},
  "install": {"kind": "system_package", "packages": ["samba"], "pre_install": ["..."], "verify": "smbd -V"},
  "uninstall": {"packages": ["samba"], "post_uninstall": ["rm -f /etc/samba/smb.conf.neutrino"], "is_data_kept": true}
}
```

`install` and `uninstall` come from `data/manifests/<module>.json`, one branch
per platform, each with an `uninstall` block. The hub resolves the branch for
the machine's platform and sends it with the state; the agent has no manifest
logic of its own.

The agent observes each module it has a runner for and reports a state derived
from the same facts, whoever installed the software:

| Fact | Read from |
| --- | --- |
| installed | `install.verify` succeeds |
| active | the unit is active |
| configured | the root-only mark `/var/lib/neutrino_agent/configured/<module>` exists; written on the first successful apply of the hub's configuration, deleted on uninstall |

| `state` | Meaning |
| --- | --- |
| `absent` | the software is missing |
| `installed` | the software is present and the hub has never configured it; `is_active` says whether it runs |
| `stopped` | the hub has configured it and the unit is stopped |
| `running` | the hub has configured it and the unit is active |
| `installing`, `uninstalling` | in transit |
| `failed`, `unsupported` | the last step failed with `{code, params}`; the agent has no runner for this module |

This table is closed on every surface; a surface that meets a token outside it
shows the word for a machine that has not reported. That is also what the
panel shows for `agent_never_reported`, the code a request gets when the
machine it went to let the stream run out of time.

`want` is stored in `config/devices/<id>/modules.json`, and a panel action
writes it directly:

| Panel action | `want` | The agent |
| --- | --- | --- |
| **Install** | `installed` | installs the package only; writes no configuration, starts nothing |
| **Configure** or **Start** | `running` | ensures the package, applies the configuration, starts the unit |
| **Stop** | `stopped` | ensures the package, applies the configuration, stops the unit |
| **Uninstall** | `absent` | uninstalls by `uninstall`, deletes the configuration the hub wrote and the configured mark; the confirmation says so and that pools, share directories, repositories and container volumes stay, because `is_data_kept` is never false |

Once the machine reports a module wanted `absent` as `absent`, that want is
settled (`is_settled` in `modules.json`): the row keeps `absent`, the state
stops naming the module, and the next press asks for it again. A module the
state does not mention is left as it is and still observed and reported, so a
hand-installed Samba shows as `installed`. The agent's rule for
reconciling is one sentence: make each mentioned module's actual state equal
its `want`. A failure is reported with its code and is not retried while the
state's hash is unchanged. The agent starts and stops only the units its
recipe names, and disables or masks none.

Package operations on one machine run one at a time, serialized on the agent,
because one package manager holds the machine-wide lock.

Taking over a machine is automatic import. The first time **Configure** is
pressed for a module whose hub-side configuration is empty, the panel calls
`POST /api/agent/module/<name>/import {device_id}` for a module that has an
import (`samba`, `gitea`, `podman`; `zfs` has none). The hub turns the
`details` of the machine's latest report into its own configuration, and the
panel then opens the configuration section.

The first configuration pushed down therefore equals what the machine already
has. From then on the hub's copy is the only truth, and every render writes
the whole file back.

| Module | What `details` reports, and what import reads |
| --- | --- |
| Samba | `testparm -s` parsed into the global section and each share, `pdbedit -L` into the user list |
| Podman | `podman ps -a --format json` and `podman inspect`: each container's image, ports, volumes, environment, and whether a unit exists; the registry mirrors |
| ZFS | pools, vdevs and datasets; there is no wanted pool list, so nothing is imported |
| Gitea | the hub's own instance; a hand-installed one reports as running on its port and is not imported |

Package bytes come to the agent down a `package {module}` stream it opens, the
same stream that serves its own upgrade. An install's or an uninstall's output
goes up a `log {module}` stream line by line, and the Modules page shows it
under the module's tab as it arrives.

### The services section, one entry per published service

The `services` section is the typed list a client is sent, and `type` decides
what the entry's `payload` names:

| `type` | `payload` | An entry is in the list while |
| --- | --- | --- |
| `web` | `{url}` | a device's Gitea module reports a URL, or an `http` record is declared |
| `port` | `{host, port}` | a device's Podman container publishes a host port, or a `generic_tcp` record is declared |
| `ai` | `{endpoint, protocol, models}`, `protocol` being `openai` | the AI gateway is installed and enabled |
| `file` | `{protocol, host, share}`, `protocol` being `smb` | a device's Samba module reports the share, or a `samba` record is declared |
| `rdp` | `{protocol, host, port, attention}`, `protocol` being `rustdesk` | a machine keeps reporting that it shares its desktop; `attention` is what somebody must do at that machine before a peer sees the desktop, as a code, empty when nothing is in the way |

The five types are closed, `SERVICES_TYPES` in
`modules/services/constants.py`; a sixth is a row here in the same change.
`source` is `module`, `declared` or `device`. `is_healthy` is the module's own
health, the declared record's last probe, or true for a share a machine is
reporting now, and empty on a record no probe has reached.

`description` is the English provenance line the composer writes, and
`description_code` names the same provenance for a surface that words it in
its own language:

| `description_code` | `description_params` |
| --- | --- |
| `ai_gateway` | none |
| `container` | `{image}` |
| `declared` | none |
| `device_share` | `{device}` |
| `gitea_module` | `{host}` |
| `samba_module` | `{host}` |

A declared record whose person wrote a line of their own gets that line and an
empty `description_code`, because those are already their words.

### The kinds

The kind table is the one extension point of the channel. A module or a verb
is added without a change to the protocol; a kind is added by a row here.

| Opened by | `kind` | Arguments and result |
| --- | --- | --- |
| hub, to an agent | `shell` | `{cols, rows}`, or `{module: podman, container}` for a container's shell; terminal bytes both ways |
| hub, to an agent | `file` | one file operation `{op, path, ...}`; `op` is `list`, `download`, `upload`, `rename`, `remove`, `directory_create` or `directory_download` |
| agent, to the hub | `log` | `{module}`: opened for an install or an uninstall, output up as binary frames line by line, closed with `params: {state}` |
| hub, to an agent | `command` | `{module, verb, ...args}`: `{agent, reboot}`, `{samba, reload}`, `{zfs, validate, config}`; an unknown kind is closed `kind_unknown` and an unknown verb `verb_unknown`, which the panel shows as `unsupported`; closed with `params: {exit_code, output, result}` |
| agent, to the hub | `package` | `{module}` for a module's package bytes from the hub's cache, `{}` for the agent's own package; the close's `params` has the `sha256` |
| client, to the hub | `service` | `{id}`: one published entry. The close is the whole answer, its `params` the material that entry takes from the hub and its `code` the reason it takes none; a new service type adds no kind |
| hub, to an agent | `desktop` | reserved and unimplemented: no arguments, the agent connects to the machine's RustDesk direct port 21118 and relays bytes both ways for `/ws/agent/desktop`; the name says the purpose, the mechanism is the port |

Installing and uninstalling are no kind and no verb: they follow from `want`.

### The verbs on a `command` stream

| `module` | Verbs |
| --- | --- |
| `agent` | `reboot`, `shutdown`, `reinstall`, `resize`, `kill {pid}`, `remote_desktop_read`, `remote_desktop_password_set`; the HTTP routes `process/kill`, `remote_desktop` and `remote_desktop/password/set` map onto the last three |
| `samba`, `gitea`, `podman`, `zfs` | the module's own, spelled without a module prefix because the `module` field is the prefix: `set_password` on `samba`, `admin/password` on `gitea`, `control/journal` on `podman`, `op`, `scan` and `validate` on `zfs` |

`validate` is a module verb: `command {module: <name>, verb: validate, config}`
checks a configuration before it is saved. A terminal's first size is in its
`open`; a later size is `open {kind: command, module: agent, verb: resize,
shell: <id>, cols, rows}`, closed as soon as it is applied.

### The service stream's close

A `service` stream names one published entry by `id`, and the hub judges it
for that client at that moment. The checks run in the order below and the
first that fails gives the close its code:

| `code` | Given when |
| --- | --- |
| `binding_unknown` | no client row has the id this socket is bound to |
| `client_disabled` | that row is switched off on the Clients page |
| `service_unknown` | the id names no entry in the list resolved for this client |
| `rdp_not_shared` | the entry is an `rdp` one and its machine has stopped reporting the share |
| `vault_locked` | the entry is the `ai` one and the vault is locked, so this client's gateway key cannot be opened or generated |

`service_unknown` and `rdp_not_shared` put the id in `params` as
`service_id`; the other three send empty params. A close with no code makes
`params` the material, and what the material is follows from the type:

| `type` | The material |
| --- | --- |
| `rdp` | `{host, port, password}`: where the desktop answers, and the seat password of the machine sharing it |
| `ai` | `{base_url, api_key, model}`: the gateway on the address this client reaches it at, this client's own key, and the first model the gateway serves |
| `web`, `port`, `file` | empty: the entry's `payload` is already everything the client needs |

### The rules the details settle

| Concern | Rule |
| --- | --- |
| When `state` is pushed | One push on a connection's first `report` whose `state_hash` differs; after that only when the hub's own hash changes. An agent whose apply failed keeps reporting the old hash; the hub shows that and pushes nothing, and the agent retries only when the state's hash changes. |
| `nagent sync` | Sends one `report` now, from which the hub compares hashes. |
| The `package` stream | The agent opens it and grants credit as it writes to disk. The sha256 in the close's `params` is checked after the close, and only a matching file goes to `systemd-run`. A socket that drops mid-transfer deletes the temporary file and locks no update target; only a failed install locks it. |
| The two hashes | The fingerprint of the published service list is computed on the unresolved list and drives the push; the `state.hash` a client receives is computed on the list resolved for its scope. |
| Config writes on the report path | `mac_addresses` is written only when the set grows, under `CONFIG_WRITE_LOCK` and through `asyncio.to_thread`. A peer address used as the fallback link address is recorded, so an overlay-only device keeps its row on the Services page. |
| `PROTOCOL` | The constant has that name in all three packages, with no package prefix, an exception to `naming_style.md` stated there: one number has one name. |

## Admission and the binding

Admission is the check on `protocol` at `join` and in `hello`, and the binding
is what a successful `join` leaves on both sides.

### The numbers

Each package's `constants.py` has `PROTOCOL`, the integer this build speaks,
which is 1 in every 0.3.0 package. The agent and the client send theirs in
`hello`, and the hub sends its own in `welcome`. The hub alone also has
`PROTOCOL_MIN`, the oldest number it still accepts. An agent or a client
speaks one number; the hub meets peers from different releases and needs a
range, `PROTOCOL_MIN <= protocol <= PROTOCOL`.

| Code | When | `params` |
| --- | --- | --- |
| `protocol_too_old` | `protocol < PROTOCOL_MIN` | `{peer, hub, min}` |
| `protocol_too_new` | `protocol > PROTOCOL` | `{peer, hub, min}` |

Package versions take no part in admission. An agent whose `welcome` names a
newer `software` than its own upgrades itself with the package the hub keeps.
It stays as it is when the version does not parse or ends in `+dev`. The
hub's `software` is always `neutrino_hub/{HUB_VERSION}`, and the client has no
self-upgrade.

### What a leave does to the binding

`POST /api/channel/leave` is the peer's own word that it is going, answered
401 `binding_unknown` when the token belongs to no binding with that id. What
the hub keeps afterwards follows from the role:

| Role | The row | What goes with the leave |
| --- | --- | --- |
| `agent` | kept in `devices.json`, with its name, its icon, its `machine_id`, its MACs, its stored credentials and its `config/devices/<id>/` | the token alone, so the machine is still on the Devices page and a new link binds it again |
| `client` | deleted from the client list | the token and the client's gateway key, revoked in the same step |

A device row is kept past the binding because the row is the hub's record of
the machine; a client row is not, because the client is the binding.

### What a refusal does to the binding

A refusal keeps the binding. The agent or the client records it as
`last_error` and sends `hello` again a minute later. `protocol_too_old`,
`protocol_too_new`, `ticket_spent`, `role_mismatch` and every transient
refusal behave this way.

`binding_unknown` is the one refusal that unbinds: the hub says it has no such
binding, because the row was removed on the panel. Only the hub holding the
pinned certificate can say it, so the peer deletes its binding and is bound
again only by a new link.

A `refused` frame arrives at any point on an open socket, not only in answer
to `hello`, and means there what it means at the handshake: the peer reads its
code the same way, and the close 4000 behind it ends a refusal already
recorded.

| Close code | Meaning |
| --- | --- |
| 4000 | `refused`; the `refused` frame before it says why |
| 4010 | `replaced`: a second socket for the same binding opened, and this one is closed; the peer reconnects only when a person acts, with `nagent join`, a service restart, or the client window's reconnect |

## Devices on the channel

A device is a row in `devices.json` keyed by its binding id. The row stores
what is true of the machine: `machine_id`, and `mac_addresses`, every MAC the
agent has reported on its link.

| Question | Answered by |
| --- | --- |
| a blank link joins: which row | the row whose `machine_id` matches, else a new one |
| a scan row merges into which device | any stored MAC |
| Wake-on-LAN goes to | the most recent link MAC |
| `is_hub` | `machine_id` equals the hub box's own |

The device's address is the report's `network.link.address`; the socket's peer
address is the fallback when that is empty, and it is recorded.

### The address a caller is given

The hub chooses a device's address by the scope a client's socket arrived
from. Each published service still has one `host`, and the client chooses
nothing:

1. At `hello`, the hub takes the socket's peer address, afresh on every
   connection.
1. `host_scope.scope_of(peer, reached, served)` classifies it against the
   scopes the box serves: one per served LAN, named by its network CIDR, and
   one `overlay` scope per overlay interface holding an IPv4 address, told
   apart by the CIDR that address and its prefix name. The first scope whose
   network holds the peer is the answer. Anything else (an exposed WAN, the
   interface in server mode, a client behind NAT) is `link`.
1. `device_host_for(scope, interfaces, link_address)` takes the first of the
   device's reported `interfaces[].addresses` inside that scope, the link
   address first when it is among them. With none inside, it takes
   `network.link.address`. Only IPv4 is considered.
1. A service of the hub itself (the AI gateway, a declared web or port entry)
   gets the hub's own address in that scope. This is the collector's rewrite
   rule with the scope as its input.
1. The push fingerprint is computed on the unresolved list and the client's
   `state.hash` on the resolved one. A client that reconnects from another
   network gets other hosts.
1. The `host` in a `service` stream's close is computed the same way at that
   moment, never from a stored address.
1. Every hub a client is bound to resolves for itself.

A client behind NAT gets the link address, which can be unreachable from
there. That is the documented outcome, with no mechanism behind it.

`nhub apply` deletes every directory under `config/devices/` whose name is not
a stored id.

## Versioning

A protocol number changes when a peer speaking the old number misreads the new
one; a package version changes on every release. One rule ties the two.

| Rule | Reason |
| --- | --- |
| Adding a kind, a field or a code keeps `PROTOCOL`, and a patch release can add them. | A peer that reads tolerantly is unaffected. |
| Removing anything, or changing its meaning, adds one to `PROTOCOL`; so does a change to the link, the ticket, the pin or the four words `hello`, `state`, `report`, `open`. | An old peer misreads it. |
| The relation to the package version is one-way: a `PROTOCOL` change requires a new minor before 1.0 and a new major after it; a new minor or major can keep the number; a patch never changes `PROTOCOL`. | A person reads compatibility off the version and finds it true. |
| `PROTOCOL_MIN` rises only when a new minor opens (a new major after 1.0), and at most to the number the previous minor spoke. | A hub one release ahead still accepts the fleet it had. |

Reading is tolerant and writing is strict. An unknown kind is closed
`kind_unknown`, an unknown field is ignored, and a peer sends only what its own
number defines.

The frames and the four section documents are pinned as JSON schemas in
`hub/tests/web/channel_schema.json`. `hub/tests/web/test_channel_schema.py`
asserts that `PROTOCOL` equals the golden's and that every `Channel*` model's
`model_json_schema()` equals its golden. The model set is closed: one model
more or one fewer fails. Changing a channel model fails that test until
`PROTOCOL` moves or the change is shown to be additive.

| `PROTOCOL` | First minor |
| --- | --- |
| 1 | 0.3.0 |
