# The protocol

The protocol is everything the hub speaks: the panel's HTTP API and `/ws`
sockets on the panel port, and the channel on the agent port. One vocabulary
and one set of rules cover both, and this page is their only record. An
endpoint, a frame, a kind or a code absent from this page does not exist.
Adding one is an edit here in the same change.

## Three ports, two audiences

The hub listens for two audiences, which verify it differently. A browser
trusts a password on a local network, and reaches the panel on two ports, one
per scheme; an agent or a client trusts a pinned certificate on any network.

| Port | Transport | Serves | Authenticated by |
| --- | --- | --- | --- |
| `listen_port`, default 8080 | HTTP | the panel: its page, every `/api/hub` and `/api/agent` route, every `/ws` socket; while `is_https_enabled` is on, a 301 to the HTTPS port for every path but the authority's download | the session cookie |
| `https_listen_port`, default 443 | TLS with the hub's own certificate, whatever `is_https_enabled` says | the same panel | the session cookie |
| `agent_listen_port`, default 8443 | TLS, pinned by fingerprint | `/api/channel` and nothing else | the ticket at `join`, then the token in `hello` |

All three are uvicorn servers in the one `nhub run --only-web` process, with
one shared runtime. That runtime is where a ticket generated on a panel port
is spent on the agent port. The panel app does not include the channel
routes, so the channel has no plaintext form. A panel port change through
`POST /api/hub/setting/set` restarts the process; a port that is the other
panel port or the agent port is refused 400 `port_already_in_use {value}`.

### The panel ports

The session cookie is named after the HTTP port, `neutrino_session_<port>`,
so two hubs on one host keep separate sessions, and one session holds on both
ports. The login page reads `/api/hub/setup`, `/api/hub/auth` and
`/api/hub/display` before a session exists, so those prefixes take no session
dependency, and neither do `GET /api/hub/setting/https/authority`, which a
browser downloads before it trusts the panel, and
`GET /api/hub/setting/https/probe`, which a page on HTTP fetches from the
HTTPS port to learn whether this browser trusts the certificate. Every other
route requires the session, and every state-changing route checks the
`Origin` header against the panel's own.

`is_https_enabled` in `config/web/settings.json` is false until somebody
turns it on, and decides two things: whether the HTTP port answers 301 to
`https://<same host>[:<https_listen_port> when not 443]<path>`, and which
port the panel is on: the other port answers 301 to it for every path but
the authority's download and the trust probe, and closes a websocket. There
is one session cookie, `neutrino_session_<http port>`, `Secure` when it was
set over HTTPS; the 301 from the port the panel left deletes it, and
`enable` and `disable` end the caller's session, so a browser holds a
session on one port at a time and no `Secure` cookie stays to block a plain
login, which a browser refuses to overwrite. A login whose cookie the
browser still refused reads as no session, and the login page offers the
HTTPS address, whose 301 removes the old cookie. The running app reads the
setting at every request, so turning it on or off restarts nothing. A
request whose peer is on loopback is served on the HTTP port with no 301,
whatever the setting says: it is the hub's own forward of a client's
**Panel** ("The connect stream"), which the channel already encrypts.

A request on the HTTP port whose peer is on loopback and whose query
carries `tkn` is a sign-in from a client holding `panel`. The token is the
material of a `service {is_panel: true}` stream ("The service stream's
close"): 32 random bytes in base64url, minted for that one answer, bound to
the client's id, held in the panel's memory alone, spent by its first use,
and dead after `WEB_PANEL_TOKEN_TTL_S` (60) seconds; a client holds at most
`WEB_PANEL_TOKENS_MAX` (8) unspent, and a ninth pushes out the oldest. A
token that spends opens an ordinary session marked with the client's id,
sets the session cookie, and answers 302 to the same address without
`tkn`. One that is unknown, spent, expired, or whose client has since been
switched off or lost `panel` opens nothing and answers the same 302, so the
browser lands on the login page; the hub logs why and shows nothing. A
`tkn` from any other peer is never looked up and is dropped by the same
302. Loopback is the socket's peer address as the HTTP server sees it,
read by the one test the 301 above uses. A session a client opened ends
when that client is switched off, removed, leaves, or loses `panel` from its
own permission or from the default it follows; the hub logs `panel: signed
in by client <name>` and `panel: session of client <name> ended (<why>)`.
Inside such a session the vault's passphrase still unlocks the vault and
`password/set` still asks for the current password.

The certificate is signed by the hub's
own certificate authority: EC P-256, valid for ten years, `CA:TRUE` with a
path length of 0, and name constraints that permit `10.0.0.0/8`,
`172.16.0.0/12`, `192.168.0.0/16`, `100.64.0.0/10`, `127.0.0.0/8` and the
DNS names `localhost`, the host name, `neutrino.internal` and
`netbird.cloud`. Chrome enforces those constraints on a root a person
installed, so the authority cannot vouch for a public name. It lives in
`config/web/panel_tls/`, `authority.pem` in the clear and
`authority_key.sealed` under the vault's data key, so a backup carries it.
`nhub setup`, `nhub apply` and `nhub run --only-web` make a missing one, and
`nhub reset all` deletes it.

The certificate the panel serves is EC P-256, valid for 397 days, with
`serverAuth` and one subject alternative name for each of
`hub.neutrino.internal`, `localhost`, the host name, `127.0.0.1`, every
private or CGNAT address in the channel's address set, and the NetBird name
when it ends in `netbird.cloud`. A public address is never in it. It and its
key are state, `/var/lib/neutrino/hub/panel_tls_certificate.pem` and
`panel_tls_key.pem`, mode 0600. The address sampler issues it again when that
name set changes or it expires within 30 days, and loads it into the live TLS
context, so the next connection gets it without a restart.

### The agent port

The agent port listens on every exposed interface, whatever its role, WAN
included, and on every exposed overlay. A served LAN that is not exposed keeps
DHCP, DNS and forwarding only. The addresses in an enrolment link are this same
set, `RouterNetworkConfig.exposed_interfaces` in `modules/router/interfaces.py`.
It is a pure function equal to `exposed_device_names + exposed_overlay_device_names`;
a LAN contributes its configured address, every other interface its live IPv4.

One test asserts that the link's address set equals the firewall's open set,
with one extra member: the relay's address while the relay is on and
configured, which no local interface holds. Enrolling a device on a LAN begins with exposing that LAN.

### The identity agents and clients pin

`nhub setup` writes a self-signed pair under `config/web/agent_tls/`:
`certificate.pem` in the clear, and `key.sealed`, the private key sealed under
the vault's data key. Serving unseals it into
`/var/lib/neutrino/hub/agent_tls_key.pem`, mode 0600. The key is EC P-256 and the
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
| Group, then page. `/api/hub/<page>` is a page of the hub itself and `/api/agent/<page>` a page of a managed device (`file`, `module`, `terminal`, whose shells are a socket and whose sessions are routes). One page is one router file on one prefix, `web/routers/hub/<page>.py` or `web/routers/agent/<page>.py`; what belongs to a page nests under it (`/api/hub/overlay/netbird/...`, `/api/hub/ai/gateway/...`, `/api/agent/module/samba/...`), and a large nested block is a second file on the same prefix (`hub/overlay_netbird.py`, `hub/ai_gateway.py`, `agent/module_samba.py`). `/ws` splits the same way into `/ws/hub/...` and `/ws/agent/...`. `/api/channel` is on the agent port's own app and is in no group. | The sidebar has two groups, a reader of a path finds the page it draws, and nothing is mounted at the top level. |
| Every segment is a singular `under_score` noun, with an adjective in front where one is needed: `wifi_network`, `ssh_key`, `seat_password`. The panel shows plurals; a path has none. | One spelling per thing across paths, models and config keys. |
| An identifier names the member in the body or the query, never in the path: `?device_id=...` on a GET, `{device_id}` in a POST body. A path has no `{id}` in it. | A path is a fixed string a reader can grep, and an id is data. |
| A read is a GET on a path of nouns and returns a view. A write is a POST whose last segment is one verb, with every argument in the body, and it returns what the matching read returns. The methods are GET and POST. | The page replaces its state with the response and merges nothing, so it cannot hold a version of the box that the box does not. |
| A verb comes from the verb table, an opposite is added with its pair, and paths of paired verbs have the same depth: `channel/join` and `channel/leave`, `module/install` and `module/uninstall`, `module/start` and `module/stop`. A new verb enters the table before it enters a path. | The table is closed, so the route test checks every path against it. |
| A word with a fixed meaning inside a domain (`scrub`, `import`, `backup`) can be a noun in the middle of a path: `pool/scrub/stop`. | The domain's own word is the one a reader searches for. |
| `/api/hub/setup`, `/api/hub/auth`, `/api/hub/display`, `GET /api/hub/setting/https/authority` and `GET /api/hub/setting/https/probe` take no session dependency. `GET /api/hub/display` returns `{language, theme}` in one response, and both change through `POST /api/hub/setting/set`. | The login page reads them before there is a session, a browser installs the authority before it trusts the panel, and a page on HTTP probes the HTTPS port before it offers HTTPS. |
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
| Stream kinds | none; installing and uninstalling follow from `want` | `shell`, `file`, `command`, `package`, `log`, `service`, `connect` |
| CLI | `nhub start`/`stop`, `nagent start`/`stop`, `nagent join`/`leave`, `nclient join`/`leave`, `nagent rdp start`/`stop`, `nclient service ... mount`/`unmount`, `nclient service port forward`/`unforward` | `status`, `sync`, `run`, `gui`, `quit` |

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
published service listen; no route switches a service on for one network. A
hub on macOS or Windows has no exposure and answers on every interface
([network.md](modules/network.md), "Outside Linux, the system firewall").

An action that needs the agent online is rejected with 409 `agent_offline`
while the machine is away. The path does not say which actions those are.

## Refusals

What an apply did is said the same way a refusal is: codes with params,
never a sentence. `POST …/apply` answers `{changes: [{code, params}]}`,
`xray_restarted` and `devices_pushed {count}` among them, and the frontend
words each one ([ui_text.md](ui_text.md), "Localization").

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
| 400 | a body, a query or a path that does not validate, or a value the route refuses | `body_invalid` for what the models refuse, then the route's own: `password_wrong`, `path_invalid`, `unknown_credential`, `login_refused`, `vault_locked`, `language_unknown`, `theme_unknown`, `hub_name_required`, `invalid_range`, `unsupported_kind`, `permission_kind_unknown {kind}`, `permission_device_unknown {device_id}`, `easytier_mode_unknown {mode}`, `easytier_config_server_invalid`, `overlay_subnet_overlap {title, subnet, conflict}`, `account_duplicate {account}`, `port_duplicate {port}`, `credential_missing {account}`, `proxy_scope_unsupported {switch}`, `relay_host_invalid {host}`, `relay_account_invalid {account}`, `relay_ssh_missing`, `resolver_required {field}`, `resolver_address_invalid {address}` |
| 401 | a missing session, a dead ticket, or a token that names no binding | `ticket_spent`, `binding_unknown` |
| 404 | an unknown member | `device_unknown`, `https_authority_missing`, `session_unknown {session_id}` |
| 409 | a state the action cannot run in | `agent_offline`, `protocol_too_old`, `protocol_too_new`, `role_mismatch`, `update_in_progress`, `release_not_latest`, `no_platform_build {module}`, `admission_paused {retry_after_s}`, `terms_not_accepted {module}` |
| 500 | the hub could not write its own `config/` | `config_unwritable {detail}`, from the per-device module routes |
| 502 | a service the hub asked did not answer as one | `gateway_unreachable`, `geodata_unreachable`, `release_dns_failed`, `release_timed_out`, `release_refused`, `release_http_error {status}`, `release_unreachable`, `relay_apply_failed {detail}` |

Every surface words a code itself: the hub's catalogs are
`hub/frontend/src/locales/<language>/codes.json` under `code.<code>`, the
client's are `client/desktop/frontend/locales/<language>.json`, and each
command line has its `cli/wording.py`. A code with no sentence fails the
completeness test of its surface. `hub/tests/web/test_code_wording.py` walks
every raise site in the hub, and the agent's and the client's wording tests
walk theirs. A new code and its wording are one change.

## What exists

The pages of the hub group come first, in sidebar order. The pages of the
agent group follow, then the panel's live sockets, then the channel on its own
TLS port.

| Prefix | Serves |
| --- | --- |
| `/api/hub/setup` | The first run's questions and the steps that answer them, served by the hub's service before the box is set up, behind the setup token |
| `/api/hub/auth` | Signing in and out, and what the session is |
| `/api/hub/display` | The language and the palette the panel is drawn in, read before there is a session |
| `/api/hub/dashboard` | The summary, the traffic history, the DNS log; `/ws/hub/dashboard/stat` and `/ws/hub/dashboard/dns_log` are its live readings |
| `/api/hub/network` | The mode, the interfaces and their roles, Wi-Fi, what listens where |
| `/api/hub/overlay` | The **Access** page: which ways in the box runs, and under it `netbird` (the network it joins), `easytier` (the network it defines: peers, networks, secret) and `relay` (the reverse forward to a server the person owns) |
| `/api/hub/proxy` | Routing policy, and under it `node` (the exit nodes), `balancer`, and `geodata` (the databases the split runs on: which release is installed, and updating them to the latest) |
| `/api/hub/ai` | The providers the gateway forwards to and their order, and under it `gateway` (the gateway itself: keys, accounts, usage, journal) |
| `/api/hub/device` | Every machine on record on the LAN: the list, a scan, names and icons, the SSH credential the hub reaches a machine with, enrolment links, installing or reinstalling the agent over SSH, waking, rebooting, shutting down, its processes, its remote desktops, its seat password, its published services, which module tabs its Modules page shows |
| `/api/hub/client` | Enrolled client sessions and the links that enrol them |
| `/api/hub/service` | The published service list and manual declarations |
| `/api/hub/credential` | The secrets the box keeps for somebody: SSH keys, logins and tokens |
| `/api/hub/setting` | The panel's own: its two ports, its scheme and certificate authority, password, hub name, backup, restore, version, and updating the hub itself from its newest release |
| `/api/agent/file` | Browsing and moving files on a device through its agent |
| `/api/agent/module` | The modules a device hosts through its agent: observed state, install, start, stop, uninstall; under it one block per module, `samba`, `gitea`, `podman`, `zfs`, `vscode`, `code_server`, `cloudcli`, each setting what it is to have and all but `zfs`, `vscode`, `code_server` and `cloudcli` importing what the machine already has |
| `/api/agent/terminal` | The shell sessions every online machine holds, and ending one; the shells themselves are `/ws/agent/terminal` |
| `/ws` | The panel's live sockets, grouped the same way: `/ws/hub/event` (cache invalidation, site-wide), `/ws/hub/dashboard/stat`, `/ws/hub/dashboard/dns_log`, `/ws/hub/task`; `/ws/agent/terminal` |
| `/api/channel` | Agents and clients on the agent port: `join` and `leave`, and `/api/channel/socket` for everything else |

Terminals opens `/ws/agent/terminal?device_id=...&session_id=...` and reads
`/api/agent/terminal/session`, Files reads
`/api/agent/file?device_id=...`, and Modules reads
`/api/agent/module?device_id=...`. Adding a page adds a row and a file, and a
route that fits no row is a route whose page has not been decided.

### The hub group

A `{...}` is the POST body or the GET query; a GET with no parameters returns
the page's whole view.

#### `/api/hub/setup`

| Route | Parameters | Does |
| --- | --- | --- |
| `GET /api/hub/setup/context` | | `SetupContext`, the box as the wizard finds it, with `hub_os` (`linux`, `darwin` or `windows`) and `modes`, which holds `server` alone outside Linux |
| `GET /api/hub/setup/state` | | each step and where it is; once done, `panel_url`, the `https://` address when the answers turned HTTPS on, with no port when it is 443, and `authority` then: `{url, file_name, fingerprint, der}`, `url` on the HTTP port and the DER in base64 so the last page downloads it while the panel starts |
| `POST /api/hub/setup/link/create` | | a blank enrolment link for the box's own agent |
| `POST /api/hub/setup/answer/set` | the wizard's answers, the document `nhub setup --stdin` reads, `listen_port`, `https_listen_port` and `is_https_enabled` among them | writes them and runs the steps |

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
| `GET /api/hub/network` | | `NetworkView`, with `hub_os` (`linux`, `darwin` or `windows`) and `modes`, which holds `server` alone outside Linux; each interface's `link.lease_dns` lists the resolvers its DHCP lease names, empty for a static uplink and for an interface holding no lease |
| `POST /api/hub/network/set` | the page's own settings, `{uplink_policy, is_inter_lan_allowed, exposed_interfaces, exposed_overlays, static_leases}`; absent lists leave the exposure as it is | `NetworkView` |
| `POST /api/hub/network/mode/set` | `{mode, ...}` | replaces the whole shape; `NetworkView` |
| `POST /api/hub/network/interface/set` | `{name, ...}`; a static uplink's `wan.dns` is its resolvers, `[{address, port}]`, `port` 53 when absent, in the order they are asked | one interface's role and settings; `NetworkView`; 400 `resolver_address_invalid {address}` for a row that is not an IP address, `port_out_of_range {minimum, maximum, value}` |
| `POST /api/hub/network/interface/remove` | `{name}` | `NetworkView` |
| `GET /api/hub/network/wifi_network` | | the saved Wi-Fi networks |
| `POST /api/hub/network/wifi_network/leave` | `{ssid}` | forgets one |
| `GET /api/hub/network/interface/wifi/scan` | `?name=` | what one radio sees |
| `POST /api/hub/network/interface/wifi/join` | `{name, ssid, ...}` | associates one radio; `NetworkView` |

#### `/api/hub/overlay`

| Route | Parameters | Does |
| --- | --- | --- |
| `GET /api/hub/overlay` | | `OverlayChoiceView`: `kinds`, one row per engine in the engine table's order and then the relay, `{key, title, is_enabled, is_integrated, is_supported, is_installed, is_active, client_count}`, `client_count` being the online clients whose socket comes from a network one of that engine's devices holds an address in; the relay's row is `key` `relay`, `is_installed` whether the system's OpenSSH client is present, `is_active` whether its state is `connected`, and `client_count` the online clients whose socket comes from a loopback address; and `route_conflicts`, one `{code, params, is_withdrawn}` per route a running overlay installed that the hub refused, `code` being `overlay_default_route_refused` or `overlay_route_overlap` and `params` `{title, route, conflict}` |
| `POST /api/hub/overlay/set` | `{netbird: {is_enabled}, easytier: {is_enabled}, relay: {is_enabled}}`, a way in left out keeping what it has | turns engines and the relay on or off, any number at once, writing the relay's into `config/overlay/relay.json`, and runs the converge step; 400 `overlay_not_integrated {title}`, `overlay_not_supported {title}` or `overlay_subnet_overlap {title, subnet, conflict}` when an engine is being turned on, 400 `relay_ssh_missing` when the relay is being turned on and the system has no OpenSSH client, 502 `overlay_switch_failed {detail}` |
| `GET /api/hub/overlay/netbird` | | the NetBird network the box joins |
| `POST /api/hub/overlay/netbird/join` | the setup key and management URL | joins it, keeps the key sealed in `config/netbird/netbird.json` once the join succeeds, and runs the converge step; 502 `overlay_join_failed {detail}` |
| `POST /api/hub/overlay/netbird/leave` | | asks the plane to delete the peer and deletes the profile; the kept key stays; runs the converge step; 502 `overlay_leave_failed {detail}` |
| `POST /api/hub/overlay/netbird/setup_key/set` | `{setup_key}`, empty to forget | replaces or forgets the kept key without joining, and runs the converge step |
| `GET /api/hub/overlay/easytier` | | the EasyTier network the box defines, its `mode`, `has_config_server`, `is_secure_mode`, and in console mode the `instances` the engine reports, each with the fields it came back without in `withheld` |
| `POST /api/hub/overlay/easytier/set` | `{mode, config_server, is_secure_mode, network_name, network_secret, address, hostname, peers, exported_networks}`: `mode` is `manual` or `console`; `config_server` null keeps the stored console address and empty forgets it; an empty `network_secret` keeps the stored secret | stores every setting at once, the console address with its token and the secret sealed in `config/easytier/easytier.json`, and runs the converge step; the manual network's name is checked in manual mode, and in console mode only when one is given; while EasyTier runs, a manual address whose network overlaps is refused 400 `overlay_subnet_overlap {title, subnet, conflict}`; 502 `easytier_apply_failed {detail}` |
| `POST /api/hub/overlay/easytier/suggestion/create` | | a suggested network for a member |
| `GET /api/hub/overlay/easytier/secret` | | the network secret |
| `GET /api/hub/overlay/relay` | | `RelayView`: `is_enabled`, `host`, `ssh_port`, `account`, `key_id`, `public_port`; `url`, the address the relay adds to `urls`, empty while it is not configured; `state`, one of the relay's state codes ([network.md](modules/network.md), "The states"); `host_key_fingerprint`, the recorded host key as `SHA256:<base64>`, empty when none is recorded; `last_error`, the last line `ssh` wrote before it exited or the failed check's reason, empty while connected; `checked_at`, the last check's time in ISO 8601, empty before the first |
| `POST /api/hub/overlay/relay/set` | `{host, ssh_port, account, key_id, public_port}`, the ports 1 to 65535 | stores them in `config/overlay/relay.json`, deletes the recorded host key when `host` or `ssh_port` changed, and runs the converge step; `RelayView`; 400 `relay_host_invalid {host}`, `relay_account_invalid {account}`, `unknown_credential {field: key_id}` for a key the vault does not hold, `port_out_of_range {minimum, maximum, value}`; 502 `relay_apply_failed {detail}` |
| `POST /api/hub/overlay/relay/host_key/remove` | | deletes the recorded host key and starts the relay again, which records the key it meets next; `RelayView`. The key is recorded by the connection, so the path has no `add` |

Every write on this page, the relay's included, the Network page's writes and
the Proxy page's `apply` run one converge step, `PanelRuntime.converge_network`, and so does
the address sampler when the channel's address set or an overlay's device
moved. Its steps and their order are [network.md](modules/network.md),
"The converge step".

#### `/api/hub/proxy`

| Route | Parameters | Does |
| --- | --- | --- |
| `GET /api/hub/proxy` | | the view, with `geodata: {geoip_version, geosite_version, source, latest?}` |
| `POST /api/hub/proxy/set` | routing policy; `remote_dns` and `direct_dns` are lists of `{address, port}`, `port` 53 when absent, asked in their order; an empty `direct_dns` follows the network's resolvers ([proxy.md](modules/proxy.md), "Where names resolve") | 400 `proxy_scope_unsupported {switch}` for `is_proxy_enabled`, `is_overlay_proxy_enabled` or `is_local_proxy_enabled` switched on outside Linux, `resolver_required {field: remote_dns}` for an empty `remote_dns`, `resolver_address_invalid {address}`, `port_out_of_range {minimum, maximum, value}` |
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
| `GET /api/hub/ai/gateway/usage` | | what it metered, per key id: the hub's, each client's and each device's |
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
| `POST /api/hub/device/enrollment/create` | `{device_id?, name?, is_hub?}` | a link for that row, or for a new one; `is_hub` makes the link for the agent on the hub's own machine, which names loopback first and is not refused `no_reachable_address` |
| `POST /api/hub/device/set` | `{device_id, name, icon, ssh, shown_module}`, each optional | the name, the icon, the stored SSH credential the hub reaches it with, and which module tabs its Modules page shows |
| `POST /api/hub/device/remove` | `{device_id}` | forgets the device; its socket is closed with `binding_unknown` |
| `POST /api/hub/device/wake` | `{device_id}` | Wake-on-LAN to the last link MAC, broadcast on every network the hub serves, or in `server` mode on the network of every exposed interface that holds an IPv4 address, never on an overlay; `wol_no_mac` when none is stored, `no_reachable_address` when there is no such network |
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

A ticket, the secret a link carries to `join`, is on disk from the moment
`enrollment/create` makes it, on this page and on the Clients page alike. The
hub writes it to `enrollment_tickets.json` under the state root, mode 0600
([files.md](files.md)): one entry per open ticket, `{token_sha256, kind,
name, device_id, client_id, expires_at}`, where `token_sha256` is the SHA-256
of the ticket in hex, `kind` is `agent` or `client`, `device_id` or
`client_id` names the row it binds, and `expires_at` is Unix seconds. The
ticket itself is never written. The hub reads the file back when it starts
and drops every entry past `expires_at`. A `join` hashes the ticket it
carries, and the entry with that hash leaves the file and the memory in one
step before it is judged; an expired entry leaves both whenever a ticket is
made or spent. Making a ticket replaces the open ticket of its kind, and
a ticket lives `ENROLLMENT_TTL_S` 30 minutes whether the hub restarted or not.

#### `/api/hub/client`

| Route | Parameters | Does |
| --- | --- | --- |
| `GET /api/hub/client` | | every client, grouped as the page draws them, each with its `permission` (null while it follows the default) and `permission_devices`, and the list's `default_permission`, `default_permission_devices` and `permission_kinds` |
| `POST /api/hub/client/enrollment/create` | `{name}` | a client link |
| `POST /api/hub/client/set` | `{client_id, name}` | |
| `POST /api/hub/client/enable` | `{client_id}` | |
| `POST /api/hub/client/disable` | `{client_id}` | its `state` is pushed with `is_disabled` |
| `POST /api/hub/client/remove` | `{client_id}` | forgets the client; its socket is closed with `binding_unknown` |
| `POST /api/hub/client/default_permission/set` | `{kinds, devices}`, `devices` optional | what a client with no permission of its own is allowed; every client's `state` is pushed |
| `POST /api/hub/client/permission/set` | `{client_id, kinds, devices}`, `kinds` null to follow the default, `devices` optional | that client's own permission; its `state` is pushed |

A permission kind is a published service type (`web`, `port`, `ai`, `file`,
`rdp`), `overlay`, `terminal` or `panel`, `CLIENT_PERMISSION_KINDS` in
`modules/clients/constants.py`. `panel` is the hub's own panel, opened from
a client through `connect {is_panel: true}` and signed in with the token of
`service {is_panel: true}` ("The panel ports"); it is off unless a
permission names it, since it manages the hub without the panel password. A permission may narrow each
kind but `overlay` and `panel` to the entries some devices provide: `devices` maps a kind to a list
of device ids, and a kind with no list, or an empty one, allows every device.
`config/clients/clients.json` holds `default_permission: {kinds, devices}`
beside `clients`, and each client a `permission` that is null or `{kinds,
devices}`, `devices` written only when it names a list; a file with no
default allows every kind but `panel` on every device, and the default a
fresh hub copies from `clients.example.json` names every kind but `panel`.
The device providing an entry is
the device that hosts it; the hub's own modules belong to the hub's own
device when it has one; a declared record belongs to the device at its
address, and one at no device's address passes only a kind with no list. A
client's `services` section holds only the entries whose type and device it
is allowed, its `terminals` only the machines its `terminal` list allows, and
a `shell` on a machine outside that list is refused `permission_denied {kind:
terminal}`. A `connect` is judged as the `service` stream is, and a panel
`connect` or `service` without `panel` is refused `permission_denied {kind:
panel}`. Switching a client off, removing it, its leave, and taking `panel`
from it, through its own permission or the default it follows, end the
panel sessions it opened.
Taking `ai` away revokes its gateway key. Deleting a device takes
its id out of every list, the default's and each client's, turns off each kind
whose list named only that device, and pushes every client its state. A kind
outside the set, or `overlay` or `panel` given a list, is
refused 400 `permission_kind_unknown {kind}`, and a device id no stored device
has is refused 400 `permission_device_unknown {device_id}`.

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
| `GET /api/hub/credential/ssh_key` | | the stored keys, each with `device_count` and `is_relay_key`, whether `config/overlay/relay.json` names it |
| `POST /api/hub/credential/ssh_key/add` | a key | |
| `POST /api/hub/credential/ssh_key/remove` | `{key_id}` | clears the key from every device and from the relay, whose state becomes `not_configured` and which the converge step stops |
| `GET /api/hub/credential/login`, `POST .../login/add`, `POST .../login/remove` | `{login_id}` on remove | the same shape for logins |
| `GET /api/hub/credential/token`, `POST .../token/add`, `POST .../token/remove` | `{token_id}` on remove | the same shape for tokens |

#### `/api/hub/setting`

| Route | Parameters | Does |
| --- | --- | --- |
| `GET /api/hub/setting` | | `SettingsView` |
| `POST /api/hub/setting/set` | the settings, `listen_port`, `https_listen_port`, `hub_name`, `language` and `theme` among them; an absent `https_listen_port` keeps it | `SettingsView`; a port change restarts the panel after answering; 400 `port_out_of_range {minimum, maximum, value}`, `port_already_in_use {value}` |
| `GET /api/hub/setting/https` | | `PanelHttpsView`: `is_https_enabled`, `listen_port`, `https_listen_port`, `has_authority`, the authority's `authority_fingerprint` and `authority_created_at`, `authority_file_name`, the served certificate's `leaf_names`, `leaf_issued_at` and `leaf_expires_at`, and `renewed_at`, the last time it was issued again since the panel started |
| `GET /api/hub/setting/https/authority` | | no session, and served by the HTTP port while HTTPS is on: the authority's DER as `neutrino-<hub>-ca.crt`, `application/x-x509-ca-cert`; 404 `https_authority_missing` before there is one |
| `GET /api/hub/setting/https/probe` | | no session: 204 and an empty body; a page on HTTP fetches it from the HTTPS port, and a fetch that completes means the browser trusts the certificate |
| `POST /api/hub/setting/https/enable` | | makes a missing authority, issues the served certificate and writes `is_https_enabled: true`; the HTTP port redirects from the next request, nothing restarts; `PanelHttpsView` |
| `POST /api/hub/setting/https/disable` | | writes `is_https_enabled: false`; the HTTP port serves the panel from the next request, nothing restarts, the certificates stay; `PanelHttpsView` |
| `POST /api/hub/setting/https/authority/reset` | | a new authority and a certificate signed by it, served from the next connection; every browser installs the new authority; `PanelHttpsResetView`, `PanelHttpsView` with `authority_der`, the new authority's DER in base64; 409 `https_reset_over_https` when the request came over HTTPS |
| `POST /api/hub/setting/password/set` | the old and the new password | |
| `POST /api/hub/setting/backup` | | an archive of `config/` |
| `POST /api/hub/setting/restore` | the archive | |
| `GET /api/hub/setting/about` | | `AboutView`: versions, the credited components, and `os` and `os_version`, the system the hub runs on and its version |
| `GET /api/hub/setting/release` | | `HubReleaseView`: the version running, whether this hub came from a package, `package_family` (`deb`, `rpm`, `arch`, `msi`, `pkg`, or empty in a checkout) and `log_root`, the record of its last update, and the staging task while one runs |
| `POST /api/hub/setting/release/scan` | | reads the newest release from GitHub; returns `HubReleaseScanView`: the release or none published, whether it carries a package of this hub's family (`has_package`; a release without one is not an error), whether it is newer or a new major, whether a rollback package can be had, and the room the update needs and has; 409 `hub_not_packaged` from a checkout |
| `POST /api/hub/setting/release/install` | `{version}`, the release confirmed | stages the package and hands the install to the `neutrino_hub_update` unit; returns `TaskStarted`, output on `/ws/hub/task`; 409 `release_not_latest` when the newest release is no longer the one named, `release_not_newer`, `release_major`, `disk_space_short`, `update_in_progress` |

### The agent group

#### `/api/agent/file`

| Route | Parameters | Does |
| --- | --- | --- |
| `GET /api/agent/file` | `?device_id=&path=` | lists a directory as `{path, separator, entries}`, each entry `{name, path, is_dir, is_link, size_bytes, modified_at}` with `path` in the machine's own form; `separator` is the agent's, else `\` when the platform's `os` is `windows`; on Windows no path or `/` lists the drives |
| `GET /api/agent/file/download` | `?device_id=&path=` | one file's bytes |
| `GET /api/agent/file/directory/download` | `?device_id=&path=` | a directory as an archive |
| `POST /api/agent/file/upload` | multipart with `device_id` and `path` | the file lands in the directory `path`; the stream's `path` is that directory joined with the file's name by the device's own separator, `\` when its platform's `os` is `windows` |
| `POST /api/agent/file/directory/create` | `{device_id, path}` | |
| `POST /api/agent/file/rename` | `{device_id, path, name}` | |
| `POST /api/agent/file/remove` | `{device_id, path}` | |

The VS Code block keeps `config/devices/<id>/vscode.json` as
`{terms_accepted_at, instances: [{account, port, login_id, token_sealed}]}`:
`terms_accepted_at` is the ISO 8601 time the person accepted Microsoft's terms
for this machine, absent before; each instance's connection
token is generated with `secrets.token_urlsafe(24)` the first time its
account is saved and sealed under the vault's data key, and `login_id` names
the vault login a Windows machine starts it with. The state carries the
module as `{address, instances: [{account, port, token, password}]}`, the
token opened, `password` the login's own and sent only to a Windows machine,
and no seal and no login id. Each instance a running module serves is
published as one `web` entry, `vscode_<device id>_<account>`, titled
`VS Code (<account>)`, at `http://<device>:<port>/` with
`is_token_required: true`.

The CloudCLI block, `routers/agent/module_cloudcli.py`, is shaped like
`module_vscode.py`: the instances are `{account, port}`, with a vault login
per instance on a Windows machine, and the payload it validates is the one
the agent receives. Each instance's CloudCLI password and token secret are
generated by the hub the first time and kept sealed under the vault's data
key in `config/devices/<id>/cloudcli.json`. Enabling the module on a device
mints that device's gateway key, and withdrawing it revokes the key
([modules/ai.md](modules/ai.md)). The state carries the instances with their
passwords and token secrets opened, as it carries a VS Code token, the
login's password for a Windows machine, the gateway's address and the
device's key. No token enters the state. Each instance a running module serves is
published as one `web` entry with `is_token_required: true`.

#### `/api/agent/terminal`

| Route | Parameters | Does |
| --- | --- | --- |
| `GET /api/agent/terminal/session` | | `TerminalSessionListView`: `sessions`, every session in the `machine` section of every online machine's latest report, whoever opened it, `{device_id, device_name, session_id, account, started_at, title, owner, owner_name, is_owned, is_attached, is_persistent, is_shared, attached_count}`, ordered by `started_at`; `is_owned` is true for the sessions the panel opened, `owner: hub`, and the page attaches only to those and to shared ones |
| `POST /api/agent/terminal/session/stop` | `{device_id, session_id}` | the `stop_session` verb on the machine, for any session whoever owns it, then the list once the machine reported; 404 `device_unknown`, 409 `agent_offline`, 404 `session_unknown {session_id}` when the machine holds no such session, 502 with any other code the agent closed with |

A session is started by opening `/ws/agent/terminal` with a new
`session_id`, so `session/stop` has no `session/start` beside it.

#### `/api/agent/module`

| Route | Parameters | Does |
| --- | --- | --- |
| `GET /api/agent/module` | `?device_id=` | each module's observed `state`, `is_active` and `details` |
| `POST /api/agent/module/install` | `{device_id, module}` | writes `want: installed` |
| `POST /api/agent/module/start` | `{device_id, module}` | writes `want: running` |
| `POST /api/agent/module/stop` | `{device_id, module}` | writes `want: stopped` |
| `POST /api/agent/module/uninstall` | `{device_id, module}` | writes `want: absent` |
| `GET /api/agent/module/journal` | `?device_id=&module=&lines=` | the tail of the module's log on the device: its units' journal on Linux, its own sources and the agent's lines naming it on Windows and macOS ([agent.md](agent.md), "Which modules each system runs") |
| `POST /api/agent/module/<name>/apply` | `{device_id}` | pushes the device's state again, for `samba`, `gitea`, `podman`, `zfs`, `vscode`, `code_server` and `cloudcli` alike; 409 `agent_offline` |
| `GET /api/agent/module/samba` | `?device_id=` | the hub's Samba configuration for the device |
| `GET /api/agent/module/samba/status` | `?device_id=` | `SambaStatusView`: whether the unit is active, the sessions open and how full each share's disk is, as last reported |
| `POST /api/agent/module/samba/import` | `{device_id}` | the machine's shares and users become the hub's configuration |
| `POST /api/agent/module/samba/share/set` | `{device_id, shares}` | |
| `POST /api/agent/module/samba/user/set` | `{device_id, users}` | |
| `POST /api/agent/module/samba/user/password/set` | `{device_id, name, password}` | |
| `GET /api/agent/module/gitea` | `?device_id=` | |
| `POST /api/agent/module/gitea/import` | `{device_id}` | |
| `POST /api/agent/module/gitea/set` | `{device_id, ...}` | |
| `POST /api/agent/module/gitea/admin/add` | `{device_id, ...}` | |
| `POST /api/agent/module/gitea/admin/password/set` | `{device_id, username, password}` | |
| `GET /api/agent/module/vscode` | `?device_id=` | `VscodeDeviceView`: the instances, each `{account, port, login_id, is_running, code}` with `is_running` and `code` as last reported, the `accounts` the machine reported, `is_terms_accepted` for this machine, and `terms_url`, the address of Microsoft's VS Code Server license terms |
| `POST /api/agent/module/vscode/terms/set` | `{device_id, is_accepted}` | records, with `is_accepted` true, that the person accepted the terms for this machine, as `terms_accepted_at` in `config/devices/<id>/vscode.json`; false deletes the record; `VscodeDeviceView`. The panel sends true alone, from the press that opens the terms. Until the record exists, `module/install`, `module/start` and `vscode/set` naming `vscode` on that machine are refused 409 `terms_not_accepted {module}` |
| `POST /api/agent/module/vscode/set` | `{device_id, instances: [{account, port, login_id}]}`, `port` 1024 to 65535 | replaces the instances, generating each account's connection token the first time; 400 `account_duplicate {account}`, `port_duplicate {port}`, `unknown_credential {field}` for a login the vault does not hold, `credential_missing {account}` for an instance of a Windows machine with no login; the agent's own refusals as 400 |
| `GET /api/agent/module/cloudcli` | `?device_id=` | the instances as `GET /api/agent/module/vscode` gives them, and the `accounts` the machine reported |
| `POST /api/agent/module/cloudcli/set` | `{device_id, instances: [{account, port, login_id}]}`, `port` 1024 to 65535, `login_id` for a Windows machine | replaces the instances, generating each instance's password the first time; the refusals of `vscode/set` |
| `GET /api/agent/module/code_server` | `?device_id=` | the instances, each `{account, port, is_running, code}` with `is_running` and `code` as last reported, and the `accounts` the machine reported |
| `POST /api/agent/module/code_server/set` | `{device_id, instances: [{account, port}]}`, `port` 1024 to 65535 | replaces the instances, generating each instance's token secret the first time; 400 `account_duplicate {account}`, `port_duplicate {port}`; the agent's own refusals as 400 |
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
| `/ws/agent/terminal` | `?device_id=&session_id=&is_resumed=&is_shared=` | a shell on the device, in the session the page generated `session_id` for, a uuid4 as 32 hex characters, which the hub opens stamped `owner: hub` and with `is_shared`, false when absent; with `is_resumed=true`, as the page opens a session the machine listed, it attaches to that session beside any other stream and its kept output comes first, and a session the machine no longer holds closes the socket with `session_unknown`. The browser sends `{type: input, data}`, `{type: resize, cols, rows}` and `{type: persist, is_persistent, is_shared}`, each resize and persist a `command` stream to the agent, a persist naming only the flags it carries; a persist on a session the machine reports under another owner opens nothing and is answered `{type: refused, code: session_not_owned, params: {session_id}}` with the socket left open. It receives `{type: output, data}` and `{type: exit, code}`, and a refusal closes the socket 1011 with the code as its reason. Closing the socket closes the agent's `shell` stream, which ends the session when no other stream is attached and it is neither persistent nor shared |
| `/ws/agent/terminal` | `?device_id=&container=` | a shell inside one of its containers |

### The channel endpoints

| Route | Parameters | Does |
| --- | --- | --- |
| `POST /api/channel/join` | `{ticket, role, protocol, machine_id, name, software, platform}` | `{id, token}`; 409 `admission_paused {retry_after_s}` while the hub's failed admissions are at their limit, before the ticket is looked up |
| `POST /api/channel/leave` | `{id, token}` | removes the binding: a device's row and its `config/devices/<id>/` stay, a client's row is deleted |
| `WS /api/channel/socket` | | the channel; a `hello` past the cap on channel sockets is refused `channel_full {limit}` |

The agent port's caps, timeouts and the count of failed admissions are in
[network.md](modules/network.md), "The agent port's limits". None of them is
keyed by the peer's address.

### The router files

| Directory | Files |
| --- | --- |
| `web/routers/hub/` | `setup.py`, `auth.py`, `display.py`, `dashboard.py`, `network.py`, `overlay.py` with `overlay_netbird.py`, `overlay_easytier.py` and `overlay_relay.py`, `proxy.py` with `proxy_node.py`, `ai.py` with `ai_gateway.py`, `device.py`, `client.py`, `service.py`, `credential.py`, `setting.py` |
| `web/routers/agent/` | `file.py`, `module.py` with `module_samba.py`, `module_gitea.py`, `module_podman.py`, `module_zfs.py`, `module_vscode.py`, `module_code_server.py` and `module_cloudcli.py`, `terminal.py` |
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

A link is `neutrino://enroll/<base64url>`: one JSON object, written with no
spaces, compressed with zlib (RFC 1950, level 9), and the compressed bytes in
base64url without padding. Every link is this form, the one a QR code carries
and the one a person pastes, and a reader inflates before it parses:

```json
{"urls": ["https://192.168.100.1:8443", "..."], "token": "...", "fp": "<sha256-hex>", "role": "client", "overlays": [{"provider": "netbird", "...": "..."}]}
```

A client link has `overlays`, the list of the same name in the client's
`state`, taken for the default permission when the link is created: empty
when that permission does not allow `overlay` or there is nothing to join. A
device link has no `overlays`. A peer that does not know the member ignores
it.

`urls` is every exposed address on the agent port, because one of them is on
the joining machine's network and neither end knows which. The link for the
hub's own agent, and every state the hub sends that agent, names
`https://127.0.0.1:<agent-port>` first, so it reaches the hub over loopback
whatever is exposed. While the relay
is on and configured, `https://<host>:<public-port>` is its last member
([network.md](modules/network.md), "The relay's address"). `role` is `agent`
or `client`, read on the pasting side before the first request. A client
rejects a device link with `link_not_for_client` and an agent rejects a client
link with `link_not_for_agent`, each code's `params` naming the link's `role`.
The base64url alphabet has no character a shell splits or a URL escapes, so
the link pastes anywhere unquoted. Compressed, a client link with two
overlays is about 550 characters and a QR code of 89 modules a side; the QR
code is that link and nothing less, so a phone that can reach the hub only
over an overlay it has not joined yet still has what it needs. The panel
draws the code at four pixels per module at least ([ui_behavior.md](ui_behavior.md)).

| Endpoint | Body | Returns |
| --- | --- | --- |
| `POST /api/channel/join` | `{ticket, role, protocol, machine_id, name, software, platform}` | `{id, token}`; admission by `protocol` runs first and a rejected protocol spends no ticket, then the ticket is spent |
| `POST /api/channel/leave` | `{id, token}` | the binding removed: a device's row stays with its `config/devices/<id>/` and drops its token, a client's row is deleted with its gateway key |
| `WS /api/channel/socket` | | everything after |

`machine_id` and `platform` are what the body says about the machine itself,
and each role reads them somewhere else:

| Field | An agent sends | A client sends |
| --- | --- | --- |
| `machine_id` | `/etc/machine-id`, else `/var/lib/dbus/machine-id`, else empty | a uuid4 hex generated on the first read of its state file and kept there |
| `platform` | `{os, family, arch, version}`: `linux`, `windows` or `darwin`, the distribution family `debian`, `rhel` or empty, the architecture normalized to `amd64`, `arm64` or `armhf`, and the system's version: the glibc version on Linux (`2.36`), the build number on Windows (`26100`), the product version on macOS (`15.3.1`), empty where it cannot be read | the same first three keys, `os` one of `linux`, `windows` and `darwin`, and `family` empty off Linux |

An agent's id is the operating system's, so a machine joining with a blank
link is matched to the row it already had. A client's is one installation's,
so the same person on two machines is two clients, and a client joining again
from an installation the hub has a row for lands back on that row: the link's
fresh row goes, and the old row takes the link's name and keeps its key, its
switch and everything it last reported. The hub reads `family` to pick a
package family and `arch` to pick the package itself, and an architecture
outside the normalized set is the machine's own word and matches no branch.
An agent's `version` is an added field and keeps `PROTOCOL` as it is; the hub
compares a manifest entry's floor with it, and an agent that predates it sends
none.

The join request names no network; the link a socket runs on comes from
`getsockname()` and is in the first report. Joining and leaving have the same
two words on every surface:

| Surface | Join | Leave |
| --- | --- | --- |
| HTTP | `POST /api/channel/join` | `POST /api/channel/leave` |
| the agent's command line | `nagent join <link>` | `nagent leave` |
| the client's command line | `nclient join <link>` | `nclient leave [--hub <name>]` |
| the client window | **Join a hub** | **Leave** |

The agent's binding file is `{gateway_url, id, token, fingerprint, machine_id}`
with `gateway_urls`, the set the last state named, beside them; it is
root-owned, mode 0600, a file missing any of the five is an unbound agent,
and one with no `gateway_urls` holds the set `[gateway_url]`. The client keeps
one binding per hub it joined, in the same shape, with the hub's `id` and
`name` from `welcome`.

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

A rejected `hello` gets `refused {code, params}` and close 4000: `hello_invalid`
when the first frame is late, not text, not a `hello`, or one the hub cannot
read, `channel_full {limit}` when the port already holds
`CHANNEL_SOCKETS_MAX` admitted sockets, and otherwise the admission codes
below. The handshake has no state
hash; the first `report` has it.

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
| a TLS handshake on the agent port | `CHANNEL_TLS_HANDSHAKE_TIMEOUT_S` 10 | | |
| a fresh socket's hello, from its upgrade | `CHANNEL_HELLO_TIMEOUT_S` 10 | | |
| a connection's admission, from accept to an admitted `hello` | `CHANNEL_ADMISSION_TIMEOUT_S` 30 | | |
| connecting and the handshake on top of it | | `AGENT_REQUEST_TIMEOUT_S` 10 | `CLIENT_CONNECT_TIMEOUT_S` 10 |
| a report while nothing changes | | `AGENT_REPORT_INTERVAL_S` 5 | `CLIENT_REPORT_INTERVAL_S` 30 |
| keepalive | `CHANNEL_PING_INTERVAL_S` 20, `CHANNEL_PING_TIMEOUT_S` 20 | | |
| silence before the socket is dead | | `AGENT_WS_SILENCE_TIMEOUT_S` 45 | `CLIENT_WS_SILENCE_TIMEOUT_S` 45 |
| reconnect backoff | | `AGENT_BACKOFF_MIN_S` 5, doubled to `AGENT_BACKOFF_MAX_S` 60 | `CLIENT_BACKOFF_MIN_S` 5, doubled to `CLIENT_BACKOFF_MAX_S` 60 |
| a stream's credit window | `CHANNEL_STREAM_CREDIT_BYTES` 1 MiB | `AGENT_WS_STREAM_CREDIT_BYTES` 1 MiB | `CLIENT_STREAM_CREDIT_BYTES` 1 MiB |
| one binary frame | `CHANNEL_CHUNK_BYTES` 64 KiB | `AGENT_WS_CHUNK_BYTES` 64 KiB | `CLIENT_WS_CHUNK_BYTES` 64 KiB |
| a stream waiting on credit | | `AGENT_WS_CREDIT_TIMEOUT_S` 60 | `CLIENT_WS_CREDIT_TIMEOUT_S` 60 |
| a stream waiting for its close | | | `CLIENT_STREAM_TIMEOUT_S` 15 |
| dialling the far end of a `connect` stream | `CHANNEL_CONNECT_DIAL_TIMEOUT_S` 10 | `AGENT_CONNECT_DIAL_TIMEOUT_S` 10 | |
| open `connect` streams on one client socket | `CHANNEL_CONNECT_STREAMS_MAX` 256 | | |
| a hub thread's call onto the loop | `CHANNEL_CALL_TIMEOUT_S` 15 | | |
| address rotation: the pause before the next address of the set | | `AGENT_ROTATE_DELAY_S` 1 | `CLIENT_ROTATE_DELAY_S` 1 |

Every number is seconds except the two rows in bytes and the count of
streams. The client's credit and frame size hold on every stream that
has binary frames, `shell` and `connect` alike. The hello timeout and the
admission timeout both run: a socket closes when either ends first, so the
handshake, the upgrade and the `hello` together fit in 30 seconds and the
`hello` alone in 10. The agent port's counts, `CHANNEL_UNADMITTED_MAX`,
`CHANNEL_SOCKETS_MAX` and the failed admissions per window, are in
[network.md](modules/network.md), "The agent port's limits". The hub's ping interval
is inside both silence windows, so a socket with nothing to say is kept open
by the pings alone, and a peer that reaches its window closes and reconnects.
A refused `hello` is retried at the backoff's maximum, the minute named under
the binding. A round through the whole address set with no answer backs off
as one address failing does.

An agent reports six times as often as a client because its `machine` section
carries the metrics the Dashboard draws live; a client's carries its hostname
and platform, which change between releases.

### The sections

| Section | `state` to agent | `report` from agent | `state` to client | `report` from client |
| --- | --- | --- | --- | --- |
| `machine` | | `{hostname, platform, accounts, metrics, sessions}` | | `{hostname, platform}` |
| `is_refresh` | | | | bool: a refresh the person asked for, answered with the whole state |
| `network` | | `{link: {interface, mac, address}, interfaces: [{name, mac, addresses[]}]}` | | |
| `modules` | `{name: {want, config, install, uninstall}}` | `{name: {state, is_active, code, params, details}}` | | |
| `desktop` | `{seat_password}` | `{is_shared, account, share_id, port, attention, connected_count}` | | |
| `services` | | | `[{id, type, title, payload, is_healthy, source, description, description_code, description_params, device_id, device_name}]` | |
| `is_disabled` | | | bool | |
| `urls` | `["https://<address>:<port>", ...]` | | the same list | |
| `overlays` | | | `[{provider, ...}]`: what the client joins each of the hub's overlays with, the preferred first | |
| `terminals` | | | `[{device_id, name, is_online, sessions}]`: the managed machines it may open a `shell` on, each with the sessions this client sees there | |
| `is_panel_allowed` | | | bool: the client is allowed to open the hub's panel through `connect {is_panel: true}` | |
| `reached_through` | | | `lan`, `netbird`, `easytier` or `relay`: the way this client's socket reached the hub | |
| `error` | | `{code, params}` | | |

The `error` section is the agent's most recent failure worth showing: the last
error, the state error, or a failed `reinstall`.

`sessions` lists the shells the agent keeps by id, oldest first, each
`{session_id, account, started_at, title, owner, is_attached, is_persistent,
is_shared, attached_count}`: `started_at` is Unix seconds, `title` the last
one the shell set with an OSC 0 or 2 sequence and the shell's name before
that, `owner` the stamp the hub put on the `shell` open that started it,
`is_attached` whether any `shell` stream is attached now and
`attached_count` how many are. It is an added field and keeps `PROTOCOL`
as it is; an agent that predates it sends none, and one before 0.5.0 sends
no `owner`, `is_shared` or `attached_count`. The AI gateway is a `services`
entry whose `type` is `ai`, and a client gets its key through the `service`
stream.

`urls` is every address the hub answers the channel on: the link's set, which
holds the hub's address on every running overlay it is exposed on, plus
NetBird's name for the hub where its daemon reports one, and last the
relay's `https://<host>:<public-port>` while the relay is on and configured.
Both states carry it
under their hash, and the hub pushes the state when the set changes: after a
converge step, and when the address sampler reads a different set, which it
does every `WEB_ADDRESS_SAMPLE_INTERVAL_S` seconds.

`overlays` is what a client joins the hub's overlays with as an ordinary
peer: one object per running overlay that has material, in the engine
table's order, NetBird first, which is the order the Overlay page draws and
the order of preference. Each object has one of three shapes:

```json
{"provider": "netbird", "setup_key": "...", "management_url": "", "fqdn": "hub.netbird.cloud", "hub_address": "100.88.0.1"}
{"provider": "easytier", "mode": "manual", "network_name": "...", "network_secret": "...", "peer": "tcp://203.0.113.7:11010", "hub_address": "10.0.0.1"}
{"provider": "easytier", "mode": "console", "config_server": "tcp://et-web.console.easytier.net:22020/<token>", "is_secure_mode": true, "hub_address": "10.126.126.1"}
```

The NetBird key is the reusable setup key kept sealed in
`config/netbird/netbird.json`, `management_url` is empty for NetBird's own
plane, and `fqdn` is the hub's name on the overlay. EasyTier's `mode` is the
one the hub runs. In manual mode `peer` is `tcp://<join host>:11010`, the join
host being the uplink's address first. In console mode `config_server` is the
console address with its account token, kept sealed in
`config/easytier/easytier.json`, and the console pushes the network itself.
`hub_address` is the hub's own address on that network, without its prefix
length, which a client probes before it counts the network as on: for
NetBird the address the daemon reports, for EasyTier the stored address in
manual mode and the one the engine reports in console mode, empty when none
is known. An overlay is left out of the
list when NetBird has no kept key, EasyTier in manual mode has no network or
no join host, EasyTier in console mode has no console address, or the vault
is locked; the list is empty when the box runs no overlay, the client is
switched off, or its permission does not allow `overlay`. The state is
pushed to every client by the converge step, which every write of a key, a
setting or an engine's switch runs, and a client reached through an engine
being turned off is pushed before that engine stops.

`is_panel_allowed` is true while the client is switched on and its
permission allows `panel`. `reached_through` is settled at `hello` from the
socket's peer address ("The address a caller is given") and names the word
the client's Hubs row shows. Both are in the state's hash, so a client that
reconnects another way is pushed its state.

`terminals` lists every managed machine, the hub's own among them, online or
not, with `is_online` read from its socket; it is empty unless the client's
permission allows `terminal`, and holds only the machines its `terminal`
device list names when it has one. The hub pushes every client its state when
an agent's channel opens or ends, when a report's `machine.sessions` differs
from the one before it, and when a device is deleted; the same report move
publishes `device_report` to the panel, whose session list reads it.

`sessions`, in an agent's `machine` section and in each `terminals` entry, is
every shell session the machine holds, `[{session_id, account, started_at,
title, owner, is_attached, is_persistent, is_shared, attached_count}]`: the id
its opener generated, the account its shell runs as, when it was opened in
Unix seconds, the title the shell set, who opened it as the hub stamped it,
whether a stream is attached now, whether it stays when its last stream
closes, whether every viewer with terminal rights on the machine can attach
to it, and how many streams are attached. A `terminals` entry lists them by
`started_at` and is empty for a machine that is offline. The list is an added
field and keeps `PROTOCOL`.

A `terminals` entry holds the sessions one viewer sees, which the hub's
`sessions_for` gives from the machines' latest reports: every session the
client owns, and every shared session on a machine it has terminal rights on.
Each carries `device_id`, `device_name`, `owner_name` and `is_owned` beside
the fields above, `is_owned` being true for the sessions this client opened
and `owner_name` being the hub's name or the owning client's name. The panel
is the viewer `owner: hub` and lists every session
(`GET /api/agent/terminal/session`).

The hub stamps `owner` on every `shell` open it sends an agent for a kept
shell: `hub` for the panel's `/ws/agent/terminal`, `client:<id>` for a
client's `shell` stream; whoever opens the shell does not send it. A
`persist` from any viewer other than the owner the machine reports is
refused `session_not_owned {session_id}` and reaches no machine; a session
the machine does not list yet is the opener's own. `stop_session` is not
held to the owner.

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
per platform, each with a `verify` command and, for a module the hub installs,
an `uninstall` block; the loader refuses a manifest that lacks either. A branch
whose `installer` is `builtin` names software the system itself carries, as
Samba's `windows` and `darwin` branches name the system's own SMB server: it
names nothing to download or install, needs neither `verify` nor `uninstall`,
and the agent's runner checks for the software itself; the loader refuses any
other branch `installer` and a builtin branch naming `url`, `packages` or any
other download field. The hub
resolves the branch for the machine's platform and sends it with the state;
the agent has no manifest logic of its own. A branch may name `min_version`,
a dotted number the loader checks: a machine whose platform `version` is
below it resolves no branch, the same as a platform the manifest does not
name, and one that reports no `version` is not ruled out. `GET
/api/agent/module` answers such a module `is_supported: false`, the Modules
page greys it out in its picker and never shows it as a tab, and a press on
it is refused 409 `no_platform_build {module}`.

The agent observes each module it has a runner for and reports a state derived
from the same facts, whoever installed the software:

| Fact | Read from |
| --- | --- |
| installed | `install.verify` succeeds; for a module the state does not name, which comes with no recipe, the runner's own check |
| active | the unit is active |
| configured | the root-only mark `/var/lib/neutrino/agent/configured/<module>` exists; written on the first successful apply of the hub's configuration, deleted on uninstall |

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
| **Uninstall** | `absent` | uninstalls by `uninstall`, deletes the configuration the hub wrote and the configured mark, and calls the runner's `remove_data` when `is_data_kept` is false; the confirmation says which from `is_data_kept`, and every shipped manifest keeps the data: pools, share directories, repositories and container volumes stay |

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

Taking over a machine happens at its first report on a socket, for each
module that has an import (`samba`, `gitea`, `podman`; `zfs` has none) and no
`want` in `modules.json`. A module reporting `stopped` or `running` gets that
state as its `want`, and its configuration is imported from the report's
`details` when the hub holds no file for it. A module reporting `installed`
is imported, and gets `running` or `stopped` as its `want` by `is_active`,
when the import finds something. An import that finds nothing leaves the
module as it reports, and Gitea is taken over only while the hub holds
`gitea_secrets.json` for the device. The state is pushed and the published
list recomposed in the same step; a later report on the same socket takes
nothing over.

**Configure** keeps its import for a module whose import was empty at the
first report: the panel calls `POST /api/agent/module/<name>/import
{device_id}` when the hub-side configuration is empty, and then opens the
configuration section.

The first configuration pushed down therefore equals what the machine already
has. From then on the hub's copy is the only truth, and every render writes
the whole file back.

| Module | What `details` reports, and what import reads |
| --- | --- |
| Samba | `testparm -s` parsed into the global section and each share, `pdbedit -L` into the user list |
| Podman | `podman ps -a --format json` and `podman inspect`: each container's image, ports, volumes, environment, and whether a unit exists; the registry mirrors |
| ZFS | pools, vdevs and datasets; there is no wanted pool list, so nothing is imported |
| Gitea | the hub's own instance; a hand-installed one reports as running on its port and is not imported |
| VS Code | each server's account, port, url and whether it runs; nothing is imported |
| code-server | each instance's account, port and whether it runs; nothing is imported |
| Samba on Windows and macOS | only the shares the module made, in the Linux shape with `params` `comment`, `read only` and `valid users`; the accounts it made; the sessions; and `fence {is_present, is_enabled, blocked}` |

On Windows and macOS an agent with the `smb_server` capability runs the
`samba` module against the SMB server the system carries. Its branch names
no packages: the recipe the state carries is `{kind: system_package}`, the
agent's own check says whether the server is there, an install installs
nothing, and the module reports `installed`, `stopped` or `running` like any
other. The configuration is the Linux one; `validate` wants a share path
absolute from a drive on Windows and from `/` on macOS, and an account name
of at most 20 characters on Windows. `stopped` takes the module's shares off
the server and keeps its accounts and its fence. An apply refuses a name the
machine already has for something the module did not make: a share with
`share_name_taken {name}`, an account with `user_name_taken {user}`. An
account the system will not make is refused with `user_create_failed {user,
detail}`, `detail` being the tool's own line, and a record of the name that is
not a usable account and that macOS will not let root delete with
`user_record_unusable {user, detail}`; either refusal comes once every other
account and every share is applied. An
account the module made signs in once `set_password` has set its password.

The `vscode` module runs Microsoft's standalone CLI, `code serve-web`, once
per account. Its configuration is `{address, instances: [{account, port,
token, password}]}`: `address` is empty, and every server listens on
`127.0.0.1` alone, where the agent's end of a `connect` stream reaches it
("The connect stream"); `token` is the instance's connection token,
which the hub keeps sealed and sends in the clear inside the state; and
`password` is the account's login, sent only to a Windows machine, where a
task that runs as an account signs in with it. Its recipe is `{kind:
vscode, package_kind, verify}`, `package_kind` being `tar` for the Linux
tarball and `zip` for the Windows and macOS archives, and the agent opens
`package {module: vscode}` for the archive and unpacks the one `code` or
`code.exe` inside it: to `/var/lib/neutrino/agent/vscode` on Linux, and to
`vscode` under the root the `hub_packages` capability names on Windows
(`%ProgramData%\Neutrino`) and macOS (`/Library/Application
Support/Neutrino`). `details` is `{instances: [{account, port, url,
is_running, code}]}`, the url without its token and `code`
`credential_invalid` for a Windows task that cannot sign its account in. An
apply refuses `account_invalid`, `account_duplicate`, `port_invalid`,
`port_duplicate`, `token_missing` and, on Windows, `credential_missing`, all
naming the `account` or the `port`; `account_unknown {account}` for an
account a Linux machine or a Mac does not have; and `credential_invalid
{account}` when Windows refuses the login.

The `cloudcli` module runs CloudCLI once per account
([agent.md](agent.md), "CloudCLI"). Its recipe names the Node.js archive
`data/manifests/cloudcli.json` pins for the platform, which the agent opens
`package {module: cloudcli}` for, and its configuration carries the
edition's `npm_registry` and `npm_environment`, the `npm_config_*` settings
the manifest names for that edition. An install that fails reports the
step: `cloudcli_node_download_failed`, `cloudcli_npm_install_failed
{account, detail}`, `cloudcli_native_module_failed {account, module,
detail}` or `cloudcli_install_out_of_memory {account}`; an instance whose
account has no `claude` reports `cloudcli_claude_missing {account}`.

The `code_server` module runs code-server once per account, on Linux and
macOS ([agent.md](agent.md), "code-server"). Its configuration is
`{instances: [{account, port, secret}]}`, `secret` the instance's token
secret, which the hub generates the first time, keeps sealed in
`config/devices/<id>/code_server.json` and sends opened inside the state,
as it sends CloudCLI's. Its recipe names the release
`data/manifests/code_server.json` pins for the platform, which the agent
opens `package {module: code_server}` for. `details` is `{version,
instances: [{account, port, is_running, code}]}`, `version` being the
release installed. An apply refuses `account_invalid`,
`account_duplicate`, `port_invalid`, `port_duplicate` and `secret_missing`,
each naming the `account` or the `port`, and `account_unknown {account}`
for an account the machine does not have.

Package bytes come to the agent down a `package {module}` stream it opens, the
same stream that serves its own upgrade. An install's or an uninstall's output
goes up a `log {module}` stream line by line, and the Modules page shows it
under the module's tab as it arrives.

### The services section, one entry per published service

The `services` section is the typed list a client is sent, and `type` decides
what the entry's `payload` names:

| `type` | `payload` | An entry is in the list while |
| --- | --- | --- |
| `web` | `{url, is_token_required}`, `is_token_required` present and true only on a VS Code, code-server or CloudCLI instance, whose page opens with a token the `service` stream hands | a device's Gitea module reports a URL, a device's VS Code, code-server or CloudCLI module runs an instance, or an `http` record is declared |
| `port` | `{host, port}` | a device's Podman container publishes a host port, or a `generic_tcp` record is declared |
| `ai` | `{endpoint, protocol, models}`, `protocol` being `openai` | the AI gateway is installed and enabled |
| `file` | `{protocol, host, share, users}`, `protocol` being `smb`; `users` is the share's `valid_users`, or every user of the device's Samba module when the share names none, and empty on a declared record; it is an added field, absent from a hub before 0.5.0, and keeps `PROTOCOL` | a device's Samba module reports the share, or a `samba` record is declared |
| `rdp` | `{protocol, host, port, attention, platform_os}`, `protocol` being `rustdesk`, `platform_os` the sharing machine's `linux`, `windows` or `darwin` | a machine keeps reporting that it shares its desktop; `attention` is what somebody must do at that machine before a peer sees the desktop, as a code, empty when nothing is in the way and always empty from a Mac |

The five types are closed, `SERVICES_TYPES` in
`modules/services/constants.py`; a sixth is a row here in the same change.
Every `host`, `port`, `url` and `endpoint` in a payload is where the
service is on the hub's networks, resolved for the client's scope ("The
address a caller is given"). A client shows it to the person and dials none
of it: every byte to a service goes over a `connect` stream.
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
| `vscode_module` | `{host, account}`; the entry exists only while the device reports the instance running |
| `cloudcli_module` | `{host, account}`; the same |
| `code_server_module` | `{host, account}`; the same |

A declared record whose person wrote a line of their own gets that line and an
empty `description_code`, because those are already their words.

`device_name` is what the hub calls the machine that provides the entry: the
device's name for an entry a device hosts, the hub's own hostname for one of
the hub's modules, the device at that address for a declared record, and
empty when no machine the hub knows is there. It is an added field and keeps
`PROTOCOL` at 2; a hub that predates it sends none, and the client shows the
entry's address in its place.

`device_id` is the id of the managed machine that provides the entry, for an
entry whose `source` is `module` or `device` and that a machine hosts, and
empty for a declared record and for the hub's own gateway. A client keys what
it keeps per machine by it, since a name changes and an address depends on
the way the hub was reached. It is an added field and keeps `PROTOCOL`.

### The kinds

The kind table is the one extension point of the channel. A module or a verb
is added without a change to the protocol; a kind is added by a row here.

| Opened by | `kind` | Arguments and result |
| --- | --- | --- |
| hub, to an agent | `shell` | `{cols, rows}`, with `{module: podman, container}` added for a container's shell, or `{session_id, is_resumed, owner, is_shared}` for a shell the agent keeps: `session_id` names the session and is generated by whoever opened the shell; an id the machine holds attaches to that session beside every stream already attached to it, and its kept output is sent first; `is_resumed: true` asks only for a session the machine holds, refused `session_unknown {session_id}` otherwise; `owner` is the hub's stamp, which the agent keeps as given and reports; `is_shared`, false when absent, says whether a new session starts shared; a shell opened without an id ends with its stream. Terminal bytes both ways; closed with `params: {exit_code}` once the shell ends, or empty when the stream closed on a shell that runs on |
| hub, to an agent | `file` | one file operation `{op, path, ...}`; `op` is `list`, `download`, `upload`, `rename`, `remove`, `directory_create` or `directory_download`, and every path is absolute in the machine's own form. `list` closes with `params: {path, separator, entries}`, `separator` being `\` on Windows and `/` elsewhere and each entry `{name, path, kind, size, modified_at, mode}`; on Windows a `list` of `/` or of no path closes with `path` `/` and one `dir` entry per drive, named `C:` with `path` `C:\`. `separator` and the drive list are added and keep `PROTOCOL`; an agent before 0.5.0 sends no `separator` |
| agent, to the hub | `log` | `{module}`: opened for an install or an uninstall, output up as binary frames line by line, closed with `params: {state}` |
| hub, to an agent | `command` | `{module, verb, ...args}`: `{agent, reboot}`, `{samba, reload}`, `{zfs, validate, config}`; an unknown kind is closed `kind_unknown` and an unknown verb `verb_unknown`, which the panel shows as `unsupported`; closed with `params: {exit_code, output, result}` |
| agent, to the hub | `package` | `{module}` for a module's package bytes from the hub's cache, `{}` for the agent's own package; the close's `params` has the `sha256` of the bytes sent and `name`, the file's own name as its release gave it, with no directory |
| client, to the hub | `service` | `{id}`: one published entry, or `{is_panel: true}`: a sign-in to the hub's own panel. The close is the whole answer, its `params` the material that entry takes from the hub and its `code` the reason it takes none; a new service type adds no kind |
| client, to the hub | `shell` | `{device_id, cols, rows, session_id, is_resumed, is_shared}`: a shell on a managed machine, which the hub opens as the agent's own `shell` with the same `session_id`, `is_resumed` and `is_shared`, stamped `owner: client:<id>`, and relays terminal bytes both ways, each side under the other's credit; closed with `params: {exit_code}`, or refused `binding_unknown`, `client_disabled`, `permission_denied {kind: terminal}` (no `terminal`, or a machine outside its device list) or `agent_offline {device}` before any agent stream opens |
| client, to the hub | `command` | `{module: agent, verb: resize, shell, cols, rows}`, `shell` being the client's own `shell` stream id, which the hub maps to the agent's; closed empty once sent on, `shell_unknown {shell}` when no such shell is open. `{module: agent, verb: persist, session_id, is_persistent, is_shared}` and `{module: agent, verb: stop_session, session_id}` go unchanged to the machine holding the session, the one this client's open `shell` names for the id or else the online machine whose report lists it, and close with the agent's close; `session_unknown {session_id}` when no machine holds it, `session_not_owned {session_id}` for a `persist` on a session the machine reports under another owner, and the `shell` stream's permission refusals for that machine. A `persist` names only the flags it carries. `verb_unknown` for any other module or verb. A hub before 0.4.0 closes both kinds `kind_unknown`, which a client reads as a refusal |
| client, to the hub | `connect` | `{id}`, one published entry by the id a `service` stream takes, or `{is_panel: true}`, the hub's own panel: one TCP connection to that service. Bytes both ways under credit; closed empty when either end's socket ends, or with a refusal's code. "The connect stream" has the checks, the far ends and the codes |
| hub, to an agent | `connect` | `{port}`: one TCP connection to `127.0.0.1:<port>` on the machine, a port the machine publishes now; bytes both ways under credit; closed empty when either socket ends, `port_not_published {port}` for any other port, `connect_failed {reason}` when the dial fails |

Installing and uninstalling are no kind and no verb: they follow from `want`.

### The verbs on a `command` stream

| `module` | Verbs |
| --- | --- |
| `agent` | `reboot`, `shutdown`, `reinstall`, `resize`, `kill {pid}`, `persist {session_id, is_persistent, is_shared}`, `stop_session {session_id}`, `remote_desktop_read`, `remote_desktop_password_set`; the HTTP routes `process/kill`, `remote_desktop` and `remote_desktop/password/set` map onto `kill` and the two remote desktop verbs; `persist` and `stop_session` refuse an id the agent does not hold with `session_unknown {session_id}` |
| `samba`, `gitea`, `podman`, `zfs` | the module's own, spelled without a module prefix because the `module` field is the prefix: `set_password` on `samba`, `admin` and `password` on `gitea`, `control` and `journal {name}` on `podman`, `op` and `scan` on `zfs` |

`persist` sets whether a session stays when its last stream closes,
`is_persistent`, and whether every viewer with terminal rights on the
machine can attach to it, `is_shared`; a flag the verb leaves out keeps its
value. `stop_session` ends a session, and
`POST /api/agent/terminal/session/stop` sends it. Both close
`session_unknown {session_id}` for a session the machine does not hold.

Two verbs every module answers: `validate`, as `command {module: <name>,
verb: validate, config}`, checks a configuration before it is saved; and
`journal`, as `command {module: <name>, verb: journal, lines}`, closes with
the tail of the module's log in `output`: the units' journal on Linux, merged
by time when the module runs as more than one unit, and the module's own
sources with the agent's lines on Windows and macOS; it answers while an
apply runs. On `podman`, a `journal` naming a
container is that container's; one naming none is the module's own. A terminal's first size is in its
`open`; a later size is `open {kind: command, module: agent, verb: resize,
shell: <id>, cols, rows}`, closed as soon as it is applied, and so is a
`persist`.

A shell the agent keeps is named by a `session_id` the opener generates, a
uuid, in the `shell` stream's `open`. An id the agent holds attaches the
stream to that shell; an id it does not hold starts a new shell under it,
unless the `open` says `is_resumed: true`, which is refused
`session_unknown`. Any number of streams attach to one session at once, as
in tmux: every stream receives all the output, input from any stream
reaches the shell, and the terminal's size is the smallest attached
window's columns and rows, set again on every attach, detach and resize.
A stream that attaches to a running shell is sent its last 256 KB of output
first, then the live output, and the terminal is resized to one row more
and back so a full-screen program draws itself again. When the last stream
closes, the shell ends unless it is persistent or shared; `stop_session`
ends it, and every attached stream closes with the exit code. Every system answers both verbs. The
sessions are the agent process's own, so an agent restart or upgrade ends
every one.

### The service stream's close

A `service` stream names one published entry by `id`, or the panel by
`is_panel: true`, and the hub judges it for that client at that moment.
The checks run in the order below and the first that fails gives the close
its code; the panel's are `binding_unknown`, `client_disabled` and
`permission_denied {kind: panel}`:

| `code` | Given when |
| --- | --- |
| `binding_unknown` | no client row has the id this socket is bound to |
| `client_disabled` | that row is switched off on the Clients page |
| `service_unknown` | the id names no entry in the list resolved for this client |
| `permission_denied` | the entry's type is not among the kinds this client is allowed, or the device providing it is not in that kind's device list |
| `rdp_not_shared` | the entry is an `rdp` one and its machine has stopped reporting the share |
| `vault_locked` | the entry is the `ai` one and the vault is locked, so this client's gateway key cannot be opened or generated; or it is a VS Code instance whose token does not open, or a code-server or CloudCLI instance whose secret does not open |

`service_unknown` and `rdp_not_shared` put the id in `params` as
`service_id`, `permission_denied` puts the entry's type in `params` as
`kind`, and the other three send empty params. A close with no code makes
`params` the material, and what the material is follows from the type:

| `type` | The material |
| --- | --- |
| `rdp` | `{password}`: the seat password of the machine sharing the desktop |
| `ai` | `{api_key, model}`: this client's own gateway key, which the gateway checks on every request, and the first model the gateway serves |
| `web` with `description_code` `vscode_module` | `{token}`: the instance's connection token |
| `web` with `description_code` `code_server_module` or `cloudcli_module` | `{token}`: `base64url(expiry \|\| nonce \|\| HMAC-SHA256(secret, expiry \|\| nonce))`, minted by the hub for this answer alone with `expiry` 60 seconds ahead and `secret` the instance's own ([agent.md](agent.md), "CloudCLI"); it works once |
| `web`, `port`, `file` | empty: the entry's `payload` is already everything the client needs |
| the panel, `{is_panel: true}` | `{token}`: a sign-in for one browser, minted for this answer alone, which the client opens at its panel forward's address with `?tkn=<token>` ("The panel ports") |

A client opens every `web` entry with `is_token_required` at its forward's
own address with `?tkn=<token>` added ([client.md](client.md), "The Web
page"), and never at the entry's address.

### The connect stream

A `connect` stream carries the bytes of one TCP connection between a client
and one service the hub publishes, or the hub's own panel. With it a client
reaches every service through the hub's agent port and dials nothing else.
A client opens one stream per connection its local listener accepts
([client.md](client.md), "The local port table").

The hub judges the `open` before it dials anything. The checks are the
`service` stream's, in its order, with the stream limit among them;
`vault_locked` has no place, since a `connect` opens no secret. The first
check that fails closes the stream with its code:

| `code` | Given when |
| --- | --- |
| `binding_unknown` | no client row has the id this socket is bound to |
| `client_disabled` | that row is switched off on the Clients page |
| `connect_limit {limit}` | the socket already holds `CHANNEL_CONNECT_STREAMS_MAX` open `connect` streams |
| `service_unknown {service_id}` | the id names no entry in the list resolved for this client |
| `permission_denied {kind}` | the entry's type, or `panel` for the panel, is not among this client's kinds, or the device providing the entry is not in that kind's device list |
| `rdp_not_shared {service_id}` | the entry is an `rdp` one and its machine has stopped reporting the share |

The far end follows from where the entry is, and the hub alone dials it:

| The entry | The hub connects the stream to |
| --- | --- |
| provided by a managed machine, `source` `module` or `device` | that machine's agent, with `connect {port}`; `agent_offline {device}` when the machine has no socket, and the same code when its socket ends under an open stream |
| a declared record, `source` `declared` | the record's own host and port, dialled by the hub itself, since the hub is on the LAN of the machines it serves |
| the `ai` entry | the gateway on `127.0.0.1` at its `listen_port` |
| the panel | the panel's HTTP port on `127.0.0.1`, over plain HTTP; the panel's login guards it as on the LAN ("The panel ports") |

The port is the entry's own: a `web` entry's url port, 80 or 443 by its
scheme when the url names none; a `port` or `rdp` entry's `port`; 445 for a
`file` entry. A dial that fails closes the stream `connect_failed
{reason}`, `reason` being `refused`, `timeout` (after
`CHANNEL_CONNECT_DIAL_TIMEOUT_S`) or `unreachable`. A stream to an agent
closes with whatever the agent closed it with.

The agent's end dials `127.0.0.1:<port>`, or the host address a container
port is published on when it names one, and only a port the machine
publishes at that moment ([agent.md](agent.md), "The connect stream"); any
other port is refused `port_not_published {port}`.

| Concern | Rule |
| --- | --- |
| Bytes | Binary frames both ways, each at most the sender's chunk size, under the receiver's credit, with the `shell` stream's window and chunk sizes. The hub relays each side under the other's credit, as it does a client's `shell`. |
| End | End of file on either end's socket closes the stream with empty params once everything read from that socket is sent. The side that receives the close writes what it holds and closes its own socket. There is no half-close. |
| A dropped socket | A client socket that ends ends every `connect` stream on it, and the hub closes the far ends. |
| Transport | TCP alone. |

### The rules the details settle

| Concern | Rule |
| --- | --- |
| When `state` is pushed | To an agent, one push on a connection's first `report` whose `state_hash` differs, and after that only when the hub's own hash changes; to a client, on any report whose `state_hash` differs or that says `is_refresh: true`, and when the hub's own hash changes. An agent whose apply failed keeps reporting the old hash; the hub shows that and pushes nothing, and the agent retries only when the state's hash changes. |
| `nagent sync` | Sends one `report` now, from which the hub compares hashes. |
| The `package` stream | The agent opens it and grants credit as it writes to disk. The sha256 in the close's `params` is checked after the close, and only a matching file goes to `systemd-run`. A socket that drops mid-transfer deletes the temporary file and locks no update target; only a failed install locks it. |
| The two hashes | The fingerprint of the published service list is computed on the unresolved list and drives the push; the `state.hash` a client receives is computed on the list resolved for its scope. |
| Config writes on the report path | `mac_addresses` is written only when the set grows, under `CONFIG_WRITE_LOCK` and through `asyncio.to_thread`. A peer address used as the fallback link address is recorded, so an overlay-only device keeps its row on the Services page. |
| `PROTOCOL` | The constant has that name in all three packages, with no package prefix, an exception to `naming_style.md` stated there: one number has one name. |

## Admission and the binding

Admission is the check on `protocol` at `join` and in `hello`, and the binding
is what a successful `join` leaves on both sides.

### The numbers

The agent's and the client's `constants.py`, and the hub's
`modules/channel/constants.py`, have `PROTOCOL`, the integer this build speaks,
which is 1 in every 0.3 package, 2 in every 0.4 package and 3 from 0.5.0. The agent and the client send theirs in
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
the machine; a client row is not, because the client is the binding. Only
`POST /api/hub/device/remove` deletes a device's row and its
`config/devices/<id>/`, so a machine that leaves and joins again is wanted as
it was.

### What a refusal does to the binding

A refusal keeps the binding. The agent or the client records it as
`last_error` and sends `hello` again a minute later. `protocol_too_old`,
`protocol_too_new`, `ticket_spent`, `role_mismatch` and every transient
refusal behave this way; `channel_full` and `admission_paused` are
transient.

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
| Wake-on-LAN goes to | the most recent link MAC, on the served networks, or a `server` hub's exposed ones |
| `is_hub` | `machine_id` equals the hub box's own |

The device's address is the report's `network.link.address`; the socket's peer
address is the fallback when that is empty, and it is recorded.

### The address a caller is given

The hub chooses the address an entry names by the scope a client's socket
arrived from. Each published service still has one `host`, which the client
shows and never dials, since its bytes go over `connect`:

1. At `hello`, the hub takes the socket's peer address, afresh on every
   connection.
1. `host_scope.scope_of(peer, reached, served)` classifies it against the
   scopes the box serves: one per served LAN, named by its network CIDR, and
   one `overlay` scope per overlay interface holding an IPv4 address, told
   apart by the CIDR that address and its prefix name. The first scope whose
   network holds the peer is the answer. Anything else (an exposed WAN, the
   interface in server mode, a client behind NAT) is `link`. A peer on
   loopback came through the relay: it is `link` with no hub address of its
   own, so every entry keeps the host it was composed with.
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
1. Every hub a client is bound to resolves for itself.

A client behind NAT gets the link address, which it only shows.

The same peer address settles the client's `reached_through`:

| The peer | `reached_through` |
| --- | --- |
| on loopback | `relay` |
| inside the network of a NetBird device the box holds an address on | `netbird` |
| inside the network of an EasyTier device the box holds an address on | `easytier` |
| anywhere else: a served LAN, the interface in server mode, an exposed WAN | `lan` |

An engine's devices are the ones the Overlay page's `client_count` counts
by, so the word and the count agree.

The hub's own address, for a peer, is a set and a name. `hub.neutrino.internal`
is the hub's name on every served network: dnsmasq answers it with the hub's
address on the network the query came in on, so the name resolves to the
hub of the network the peer stands on, whatever that address is today. A
binding holds the `urls` of the last state it took as `gateway_urls`, with
`gateway_url` the last address that answered. A round tries the name where
it resolves, then `gateway_url`, then the rest of `gateway_urls`, and the
first that answers with the pinned fingerprint is written back as
`gateway_url`. A fingerprint that does not match on the name is another
network's hub and is skipped; one that does not match on a stored address is
recorded as `last_error`, and the round goes on to the next address.

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
| `PROTOCOL_MIN` rises only when a new minor opens (a new major after 1.0). It rises at most to the number the previous minor spoke, except where the owner decides a change is too wide to carry the old peers, as 0.5.0 did by raising it to its own 3. | A hub one release ahead still accepts the fleet it had, unless its release notes say how that fleet is reinstalled. |

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
| 2 | 0.4.0 |
| 3 | 0.5.0 |

3 renamed the link's and the client state's `overlay`, one object or null,
to `overlays`, a list. `PROTOCOL_MIN` is 3 from 0.5.0: a 0.3 or 0.4 agent or
client is refused `protocol_too_old` and does not update itself from the hub.
The hub's update reinstalls the box's own agent from the hub's cache; any
other agent is reinstalled from the Devices page or by hand.
