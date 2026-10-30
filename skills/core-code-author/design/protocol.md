# The protocol

The protocol is everything the hub speaks: the panel's HTTP API and `/ws`
sockets on the panel port, and what the channel's streams carry on the agent
port, its frames, its kinds of stream and the sections of its state. One
vocabulary and one set of rules cover both, and this page is their only
record. An endpoint, a frame, a kind or a code absent from this page does not
exist. Adding one is an edit here in the same change.

The wire under the channel is the transport's, in
[transport.md](transport.md): the knock and the handshake, the stream layer,
admission and the binding, and the local channel between the transport and
the Python beside it.

## Three ports, two audiences

The hub listens for two audiences, which verify it differently. A browser
trusts a password on a local network, and reaches the panel on two ports, one
per scheme; an agent or a client trusts the hub's static key on any network.
A browser opening a Web share reaches the agent port too, and trusts the
certificate fingerprint its link holds ([transport.md](transport.md), "The
guest path").

| Port | Transport | Serves | Authenticated by |
| --- | --- | --- | --- |
| `listen_port`, default 8080 | HTTP | the panel: its page, every `/api/hub` and `/api/agent` route, every `/ws` socket; while `is_https_enabled` is on, a 301 to the HTTPS port for every path but the authority's download | the session cookie |
| `https_listen_port`, default 443 | TLS with the hub's own certificate, whatever `is_https_enabled` says | the same panel | the session cookie |
| `agent_listen_port`, default 8443 | TCP: the transport's knock, Noise handshake and go-yamux session, or a Web share's WebRTC ([transport.md](transport.md)) | the channel, and a Web share's one app | the hub's static key and the peer's own, the ticket in `join`, then the binding's key; for a guest, the certificate fingerprint and the share's ticket |

The two panel ports are uvicorn servers in the one `nhub run --only-web`
process. The agent port is the transport's: `neutrino_transport`, the Go
program of `transport/`, which the hub runs as a process of its own and an
account of its own ([privilege.md](privilege.md)). It holds every peer's
session and relays every stream's bytes, and it asks the hub's Python over
the local channel whatever needs a decision ([transport.md](transport.md),
"The local channel"). A change
of any of the three ports through `POST /api/hub/setting/set` restarts the
process that holds it; a port that is one of the other two, or one of the
two frp loopback ports, is refused 400 `port_already_in_use {value}`. A new
port that another program on the box listens on, over IPv4 or IPv6, is
refused with the same code before any setting changes. The **Network** page
sets all three. The two frp loopback ports, and the file the transport
reads at its start, are in [transport.md](transport.md), "Where the port is
reached".

An agent port change moves every peer. Before the transport restarts, the
hub pushes every online client and agent its state, whose `urls` name the
new port, and then restarts it on that port at once. A peer offline at that
moment holds only the old addresses, cannot reach the hub, and joins again
with a new link. Before the save the page says how many clients and how many
agents are offline: those with a binding row and no live session at that
moment, which `SettingsView` holds as `offline_client_count` and
`offline_agent_count`. While Direct is on, the page also says that the
router's port forward and Direct's public port change with it, and while
SakuraFrp or OpenFrp has a tunnel picked, that the tunnel's local port at
the vendor changes with it.

### The panel ports

The session cookie is `neutrino_session_<hub>`, `<hub>` the first 12
characters of the hub's id ("The hub's own identity"). A password login and a
client's sign-in set it under that one name, on either port and from any
peer. Two hubs on one host keep two sessions, and so do two hubs' panels a
client opens on `127.0.0.1`, where a browser keeps cookies by host alone. One
session holds on both ports. A panel that cannot read its identity file names
the cookie `neutrino_session_`. The login page reads `/api/hub/setup`,
`/api/hub/auth` and `/api/hub/display` before a session exists, so those
prefixes take no session dependency, and neither do
`GET /api/hub/setting/https/authority`, which a browser downloads before it
trusts the panel, and
`GET /api/hub/setting/https/probe`, which a page on HTTP fetches from the
HTTPS port to learn whether this browser trusts the certificate. Every other
route requires the session, and every state-changing route checks the
`Origin` header against the panel's own.

`is_https_enabled` in `config/web/settings.json` is false until somebody
turns it on, and decides two things: whether the HTTP port answers 301 to
`https://<same host>[:<https_listen_port> when not 443]<path>`, and which
port the panel is on: the other port answers 301 to it for every path but
the authority's download and the trust probe, and closes a websocket. The
session cookie is `Secure` when it was set over HTTPS; the 301 from the port
the panel left deletes it, and
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
material of the `service` frame `{is_panel: true}` ("The service frame"): 32
random bytes in base64url, minted for that one answer, bound to
the client's id, held in the panel's memory alone, spent by its first use,
and dead after `WEB_PANEL_TOKEN_TTL_S` (60) seconds; a client holds at most
`WEB_PANEL_TOKENS_MAX` (8) unspent, and a ninth pushes out the oldest. A
token that spends opens an ordinary session marked with the client's id,
sets the session cookie, and answers 302 to the same address without
`tkn`, so the token leaves the address bar and the history at once. One
that is unknown, spent, expired, or whose client has since been
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
| a device | its binding id | by the hub when it first records the machine: at `join` for a blank link, earlier when a link is created for a row that already exists | the Agents page |
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
| Group, then page. `/api/hub/<page>` is a page of the hub itself and `/api/agent/<page>` the page of a managed device, the machine page, whose prefix is `module`, with `file` beside it for its path window. One page is one router file on one prefix, `web/routers/hub/<page>.py` or `web/routers/agent/<page>.py`; what belongs to a page nests under it (`/api/hub/overlay/netbird/...`, `/api/hub/ai/gateway/...`, `/api/agent/module/samba/...`), and a large nested block is a second file on the same prefix (`hub/overlay_netbird.py`, `hub/ai_gateway.py`, `agent/module_samba.py`). `/ws` splits the same way into `/ws/hub/...` and `/ws/agent/...`. The agent port serves no HTTP route. | The sidebar has two groups, a reader of a path finds the page it draws, and nothing is mounted at the top level. |
| Every segment is a singular `under_score` noun, with an adjective in front where one is needed: `wifi_network`, `ssh_key`, `seat_password`. The panel shows plurals; a path has none. | One spelling per thing across paths, models and config keys. |
| An identifier names the member in the body or the query, never in the path: `?device_id=...` on a GET, `{device_id}` in a POST body. A path has no `{id}` in it. | A path is a fixed string a reader can grep, and an id is data. |
| A read is a GET on a path of nouns and returns a view. A write is a POST whose last segment is one verb, with every argument in the body, and it returns what the matching read returns. The methods are GET and POST. | The page replaces its state with the response and merges nothing, so it cannot hold a version of the box that the box does not. |
| A verb comes from the verb table, an opposite is added with its pair, and paths of paired verbs have the same depth: `channel/join` and `channel/leave`, `module/install` and `module/uninstall`, `module/start` and `module/stop`. A new verb enters the table before it enters a path. | The table is closed, so the route test checks every path against it. |
| A word with a fixed meaning inside a domain (`login`, `import`, `backup`) can be a noun in the middle of a path: `openfrp/login/start`. | The domain's own word is the one a reader searches for. |
| `/api/hub/setup`, `/api/hub/auth`, `/api/hub/display`, `GET /api/hub/setting/https/authority` and `GET /api/hub/setting/https/probe` take no session dependency. `GET /api/hub/display` returns `{language, theme, update}` in one response; the language and the theme change through `POST /api/hub/setting/set`, and `update` is the hub's own update while it runs and for 30 minutes after it ends. | The login page reads them before there is a session, a page follows the hub's update across the restart that ends its session, a browser installs the authority before it trusts the panel, and a page on HTTP probes the HTTPS port before it offers HTTPS. |
| The router file is named after its page; the library package under `modules/` keeps its own name, so `modules/router` serves `/api/hub/network` and `modules/xray` serves `/api/hub/proxy`. | A page is what a person sees; a package is what the code does. |

### The verbs

| Verb | Opposite | Writes |
| --- | --- | --- |
| `set` | none; a GET reads it | the settings of the thing named |
| `add` | `remove` | a member into or out of a list |
| `create` | `destroy` | a thing that exists on a machine afterwards: a directory, a link |
| `join` | `leave` | a membership |
| `start` | `stop` | a unit, a task, a login flow |
| `enable` | `disable` | whether a thing is in force |
| `share` | `unshare` | whether a thing is published |
| `install` | `uninstall` | a package |
| `login` | `logout` | a session |
| `backup` | `restore` | an archive of `config/` |
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
| `reveal` | none | nothing; the read of a secret the hub generated, logged |
| `rotate` | none | a secret the hub generated, made afresh |
| `rename` | none | a name |

The whole design is symmetric where a thing has an opposite and single where
it has none:

| Layer | Paired | Single, and why |
| --- | --- | --- |
| HTTP verbs | `set`; `add`/`remove`; `create`/`destroy`; `join`/`leave`; `start`/`stop`; `enable`/`disable`; `share`/`unshare`; `install`/`uninstall`; `login`/`logout`; `backup`/`restore`; `download`/`upload` | `import`, `update`, `reset`, `apply`, `scan`, `test`, `probe`, `wake`, `reboot`, `shutdown`, `reinstall`, `restart`, `kill`, `rename`, `reveal`, `rotate`: none has a reverse operation |
| Path depth | the same for the same function: `module/install`/`uninstall`, `start`/`stop`; `device/agent/install`/`reinstall`; `podman/container/start`/`stop` | |
| Channel frames and records | `hello`/`welcome`; `join`/`joined`; `leave`/`left`; `state`/`report`; `ping`/`pong`; a question frame and its `reply`; the `open` and `close` records, `accept` between them | `refused`; the records `data`, `stderr`, `eof`, `resize`, `datagram` |
| Stream kinds | none; installing and uninstalling follow from `want` | `control`, `shell`, `exec`, `file`, `command`, `package`, `log`, `connect` |
| CLI | `nhub start`/`stop`, `nagent start`/`stop`, `nagent join`/`leave`, `nclient hub join`/`leave`, `nclient file mount`/`unmount`, `nclient app open`/`stop`, `nclient ssh config install`/`uninstall` | `status`, `sync`, `run`, `gui`, `quit`, and `list`, `show`, `set`, `attach`, `exec`, `connect`, `proxy` on `nclient` |

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

A field is spelled once. `is_ipv4_exposed` is the key in
`config/router/network.json`, the attribute on the Pydantic model in
`web/models.py`, and the property on the TypeScript interface in
`frontend/src/api_types.ts`. A path segment is spelled the way the model that
returns it is, and booleans are questions in all three, `is_` and `has_`
([coding_style/naming.md](../coding_style/naming.md)).

### The principles behind every route

Exposure is the only control plane for the hub's own ports. The exposed
segments decide which senders reach the panel ports, the agent port, DNS and
the SOCKS ports, on Linux, macOS and Windows alike; no route switches a port
on for one network ([network.md](hub_components/network.md), "What answers,
and where").

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
| a session | `refused {code, params}` on the control stream, then the hub ends the session |
| a stream | a `close` record, `{code, params}`; a close without a code is the stream's result |
| a frame that asks | `reply {request, code, params}`; a reply without a code is the answer |
| a local question | the Python's `{id, code, params}`; the transport's own `control_unavailable` when none comes |

The codes of the channel take no HTTP status.

The HTTP status names the class of the refusal:

| Status | Class | Codes |
| --- | --- | --- |
| 400 | a body, a query or a path that does not validate, or a value the route refuses | `body_invalid` for what the models refuse, then the route's own: `password_wrong`, `path_invalid`, `unknown_credential`, `login_refused`, `vault_locked`, `language_unknown`, `theme_unknown`, `hub_name_required`, `invalid_range`, `unsupported_kind`, `permission_kind_unknown {kind}`, `permission_device_unknown {device_id}`, `easytier_mode_unknown {mode}`, `easytier_config_server_invalid`, `overlay_subnet_overlap {title, subnet, conflict}`, `account_unknown {account}`, `account_duplicate {account}`, `credential_missing {account}`, `declared_service_invalid {field}`, `proxy_scope_unsupported {switch}`, `relay_host_invalid {host}`, `relay_account_invalid {account}`, `relay_ssh_missing`, `direct_host_invalid {host}`, `frpc_missing {title}`, `frp_credential_refused {title}`, `frp_tunnel_unknown {title, tunnel_id}`, `resolver_required {field}`, `resolver_address_invalid {address}`, `network_invalid {field, name}`, `shell_program_unusable {path}`, `web_share_entry_invalid {entry_id}`, `web_share_site_invalid {site}`, `share_name_taken {name}`, `share_name_invalid {name}`, `share_account_not_enabled {account}` |
| 401 | a missing session | `not_authenticated` |
| 404 | an unknown member | `device_unknown`, `https_authority_missing`, `declared_service_unknown`, `web_share_unknown`, `generated_credential_unknown`, `folder_share_unknown {name}` |
| 409 | a state the action cannot run in | `agent_offline`, `protocol_too_old`, `protocol_too_new`, `update_in_progress`, `release_not_latest`, `no_platform_build {module}`, `terms_not_accepted {module}`, `gateway_not_serving`, `frp_not_signed_in {title}`, `version_locked {module}`, `transport_key_missing` |
| 500 | the hub could not write its own `config/` | `config_unwritable {detail}`, from the per-device module routes |
| 502 | a service the hub asked did not answer as one | `gateway_unreachable`, `download_failed {file, sources}`, `relay_apply_failed {detail}`, `direct_apply_failed {detail}`, `frp_vendor_unreachable {title, detail}`, `frp_config_unusable {title}` |

Every surface words a code itself: the hub's catalogs are
`hub/frontend/src/locales/<language>/codes.json` under `code.<code>`, the
client's are `client/desktop/frontend/locales/<language>.json`, and each
command line has its `cli/wording.py`. A code with no sentence fails the
completeness test of its surface. `hub/tests/web/test_code_wording.py` walks
every raise site in the hub, and the agent's and the client's wording tests
walk theirs. A new code and its wording are one change.

### The codes 0.6.0 adds and removes

| Code | `params` | Where | Change |
| --- | --- | --- | --- |
| `control_unavailable` | `{retry_after_s}` from the hub's transport, 5; none from the hub's Python | a session's `refused`, a stream's `close` or a `reply`, when the hub's Python did not answer its transport in time ([transport.md](transport.md), "The local channel"); a bound peer refused it knocks again, and a client tries a join refused it again, after `retry_after_s` ([transport.md](transport.md), "What a refusal does to the binding") | added |
| `transport_key_missing` | none | 409 of `enrollment/create`, a link asked for while the transport has written no public key ([transport.md](transport.md), "The hub's static key") | added |
| `transport_apply_failed` | `{detail}` | the converge step's failure, the transport's `transport.json` or its start refused; its change codes are `transport_started` and `transport_restarted` | added |
| `replaced` | none | a session's `refused`, the session of a binding that opened a second one | added, in place of the close code 4010 |
| `hello_invalid` | none | a session's `refused`, a first frame that is no `hello`, `join` or `leave`, or a `hello` naming another binding | kept |
| `ticket_spent`, `role_mismatch`, `admission_paused` | `{}`, `{}`, `{retry_after_s}` | the `refused` answering a `join` frame | kept, now frames |
| `terminal_account_missing` | none | a `shell` or an `exec` on a machine whose Terminal module enables no account | added |
| `account_not_enabled` | `{account}` | a `shell` or an `exec` naming an account the Terminal module does not enable | added |
| `account_home_unknown` | `{account}` | the `code` of a `samba` row of `GET /api/agent/module/samba`, an enabled account with no `share_path` whose machine reports no home for it ("The account layer in the state") | added |
| `samba_hosts_allow_no_loopback`, `samba_interfaces_no_loopback`, `samba_domain_member` | none | the `code` of the `samba` module row on Linux, a `hosts allow` of the person's `[global]` that leaves out the loopback, a `bind interfaces only` whose `interfaces` leaves out `lo`, and a domain member's `security` or `server role`, each a setting of the person's the module never changes ([agent/modules/file_share.md](agent/modules/file_share.md), "Linux") | added |
| `share_users_unknown` | `{shares}` | the `code` of a `running` or `stopped` `samba` row, the folder shares with no account, which the module leaves off the server ([agent/modules/file_share.md](agent/modules/file_share.md)) | added |
| `share_name_taken` | `{name}` | an apply of the `samba` module, a share of the person's that has the name of a Home share or a folder share; and the folder share routes and `samba/set`, a name another share of the machine has, compared without case ("`/api/agent/module`") | widened to folder shares |
| `share_name_invalid`, `share_account_not_enabled`, `folder_share_unknown` | `{name}`, `{account}`, `{name}` | the folder share routes: a name outside the form a folder share's name takes, an account the file share does not enable, and a name no folder share of the machine has | added |
| `key_missing` | `{account}` | the SSH server's apply, an instance with no authorized key | added |
| `containers_not_applied` | none | the `code` of a `failed` container module row, its start while the last apply of Containers did not write the module's containers as the state names them ([agent/modules/containers.md](agent/modules/containers.md), "A refused declared container") | added |
| `state_not_settled` | `{module}` | a module verb that acts, refused while that module's task runs on past 30 seconds ([agent.md](agent.md), "A retry is the same press again") | params added |
| `waiting_for_lock` | `{lock, module}` | the `code` of a `queued` row and a task's `wait`: a step that waits for the step lock `lock`, which the task of `module` holds, `agent` for the self-update ([agent.md](agent.md), "Step locks") | added |
| `waiting_for_package_manager` | `{holder}` | a task's `wait`, and the `code` of an `installing` row: the package helper waiting for the system's own lock, `holder` the process the system names, empty when it names none | added |
| `waiting_for_module` | `{module}` | a task's `wait`, and the `code` of an `installing` row: a container module's `wait_containers` or `render` waiting for Containers' task | added |
| `waiting_for_check` | `{seconds}` | a task's `wait`, and the `code` of an `installing` row: a step that checks something outside the agent every `seconds`, 30 | added |
| `module_needed` | `{module, state}` | the `code` of an `install_failed` container module row: its `wait_containers` ended while Containers read `state` and not `running`, or while Containers' `want` was not `running` ([agent.md](agent.md), "A step that brings up another module") | added |
| `package_manager_busy` | `{holder}` | the `code` of an `install_failed` or `failed` row: a step whose package helper waited 300 seconds for the system's own lock ([agent.md](agent.md), "The system's own lock") | added |
| `ayakaleaf_setup_failed` | `{step, detail}` | an Ayakaleaf install whose first-start step failed, `step` being `replica_set`, `admin` or `tex` ([agent/modules/ayakaleaf.md](agent/modules/ayakaleaf.md), "The first start") | added |
| `share_unknown` | none | the `guest` question's answer, a guest session's `refused`, and a visitor's `service` or `connect`, for a share that does not exist or a ticket not its own ("Web shares") | added |
| `web_share_entry_invalid`, `web_share_site_invalid`, `web_share_unknown` | `{entry_id}`, `{site}`, none | `web_share/create` naming an entry no share can offer now or a site that is not a listed one or an `https://` address, and `web_share/destroy` naming no share | added |
| `ayakaleaf_guest_failed` | `{step, detail}` | a guest of the Ayakaleaf module in its `details.guests`, `step` being `admin_login`, `register`, `password` or `name` ([agent/modules/ayakaleaf.md](agent/modules/ayakaleaf.md), "The guest account") | added |
| `op_unknown` | `{op}` | a `file` stream naming any `op` but `list` | added |
| `hub_untrusted` | none | a client's or an agent's own word for a message 2 that opens under no psk | kept, now of the handshake |
| `client_not_running` | none | `nclient`'s own, any command but `gui` while no client runs | added |
| `hub_key_missing` | none | an agent's or a client's `last_error` for a binding of the 0.5 shape, which holds no hub key | added |
| `port_taken` | `{port}` | a client's forward of an app entry whose number another program or entry holds | kept, now for the hub's numbers too |
| `declared_service_invalid` | `{field}` | `declaration/add`, `field` being `name`, `host`, `entries` or `entries.<n>.<field>` | kept, for apps |
| `shell_unknown` | `{shell}` | a client's `command {resize}`, gone with resizes as records | removed |
| `port_duplicate`, `port_invalid` | `{port}` | the instance lists of the account-layer modules and Hermes WebUI, gone with ports the agent takes | removed |
| `session_unknown` | `{session_id}` | the Terminals page's `session/stop`, gone with the page; the agent's `reply` to `persist` and `stop_session` keeps it | removed from the panel |

## What exists

The pages of the hub group come first, in sidebar order. The machine page of
the agent group follows, then the panel's live sockets.

| Prefix | Serves |
| --- | --- |
| `/api/hub/setup` | The first run's questions and the steps that answer them, served by the hub's service before the box is set up, behind the setup token |
| `/api/hub/auth` | Signing in and out, and what the session is |
| `/api/hub/display` | The language and the palette the panel is drawn in, and the hub's own update, read before there is a session |
| `/api/hub/dashboard` | The summary, the traffic history, the DNS log; `/ws/hub/dashboard/stat` and `/ws/hub/dashboard/dns_log` are its live readings |
| `/api/hub/network` | The mode, the interfaces and their roles, Wi-Fi, what listens where |
| `/api/hub/overlay` | The **Access** page: which ways in the box runs, and under it `direct` (the agent port on every enabled interface, and the public address the person states), `relay` (the SSH relay, the reverse forward to a server the person owns), `sakurafrp` and `openfrp` (the account at each frp vendor and the tunnel picked there), `netbird` (the network it joins) and `easytier` (the network it defines: peers, networks, secret) |
| `/api/hub/proxy` | Routing policy, and under it `node` (the exit nodes), `balancer`, and `geodata` (the databases the split runs on: which release is installed, and updating them to the latest) |
| `/api/hub/ai` | The providers the gateway forwards to and their order, and under it `gateway` (the gateway itself: keys, accounts, usage, journal) |
| `/api/hub/device` | The **Agents** page: every managed machine, names and icons, the SSH credential the hub reaches a machine with, enrolment links, installing or reinstalling the agent over SSH, waking, rebooting, shutting down, its processes, its remote desktops, its seat password, its published services, which module tabs its machine page shows |
| `/api/hub/client` | Enrolled client sessions, the links that enrol them, and the Web shares |
| `/api/hub/service` | The apps and the other published services, and the apps declared by hand |
| `/api/hub/credential` | The secrets the box keeps for somebody, SSH keys, logins and tokens, and the ones it generated for the machines |
| `/api/hub/setting` | The panel's own: its two ports, its scheme and certificate authority, password, hub name, backup, restore, version, and updating the hub itself from its newest release |
| `/api/agent/file` | A machine's directory listing, for the panel's path window |
| `/api/agent/module` | The machine page `/agents/<id>`: the modules a device hosts through its agent, observed state, install, start, stop, uninstall, versions and the catalog; `account`, the machine's available accounts; and under it one block per module, `samba`, `terminal`, `ssh_server`, `remote_desktop`, `gitea`, `podman`, `vscode`, `code_server`, `cloudcli`, `codeg`, `siyuan`, `hermes_webui`, `ayakaleaf`, each setting what it is to have and `gitea` and `podman` importing what the machine already has |
| `/ws` | The panel's live sockets, grouped the same way: `/ws/hub/event` (cache invalidation, site-wide), `/ws/hub/dashboard/stat`, `/ws/hub/dashboard/dns_log`, `/ws/hub/task`; `/ws/agent/terminal` |

The machine page `/agents/<id>` reads `/api/agent/module?device_id=...`
and what "The agent group" lists, the path window reads
`/api/agent/file?device_id=...`, and the Containers tab's **Shell** opens
`/ws/agent/terminal?device_id=...&container=...`. Adding a page adds a row
and a file, and a route that fits no row is a route whose page has not been
decided.

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
| `GET /api/hub/display` | | `{language, theme, update}`: `update` is null, or `{stage, from_version, to_version, finished_at}` for an update under way or ended in the last 30 minutes, a run that died marked `failed` |

#### `/api/hub/dashboard`

| Route | Parameters | Does |
| --- | --- | --- |
| `GET /api/hub/dashboard/summary` | | the summary tiles |
| `GET /api/hub/dashboard/history` | | the traffic history the hub counts itself ([network.md](hub_components/network.md), "The traffic history") |
| `GET /api/hub/dashboard/dns_log` | | the DNS log's last entries |

#### `/api/hub/network`

| Route | Parameters | Does |
| --- | --- | --- |
| `GET /api/hub/network` | | `NetworkView`, with `hub_os` (`linux`, `darwin` or `windows`) and `modes`, which holds `server` alone outside Linux; each interface's `link.lease_dns` lists the resolvers its DHCP lease names, empty for a static uplink and for an interface holding no lease; `is_unsaved` is true for an interface the configuration does not name and the hub does not use, which is every such interface on Linux and none on macOS and Windows; each interface's `is_ipv4_exposed` and `is_ipv6_exposed`, with the networks each segment holds now, and each overlay's `is_exposed` |
| `POST /api/hub/network/set` | the page's own settings, `{uplink_policy, is_inter_lan_allowed, ipv4_exposed_interfaces, ipv6_exposed_interfaces, exposed_overlays, static_leases, interface_roles}`: the two interface lists name the interfaces whose IPv4 or IPv6 segment is exposed, and absent lists leave the exposure as it is; `interface_roles` maps a port with a segment turned on to the role it takes with it, `wan` or `lan` | `NetworkView`; in router mode 400 `network_invalid {field: role, name}` when a port with an exposed segment would keep the role `disabled` |
| `POST /api/hub/network/mode/set` | `{mode, ...}` | replaces the whole shape; `NetworkView` |
| `POST /api/hub/network/interface/set` | `{name, ...}`; a static uplink's `wan.dns` is its resolvers, `[{address, port}]`, `port` 53 when absent, in the order they are asked | one interface's role and settings; `NetworkView`; 400 `resolver_address_invalid {address}` for a row that is not an IP address, `port_out_of_range {minimum, maximum, value}`, in router mode `network_invalid {field: role, name}` for the role `disabled` on a port with an exposed segment, and `network_invalid {field: country_code, name}` for an access point on 5 GHz with no `ap_country_code` |
| `POST /api/hub/network/interface/remove` | `{name}` | `NetworkView` |
| `GET /api/hub/network/wifi_network` | | the saved Wi-Fi networks |
| `POST /api/hub/network/wifi_network/leave` | `{ssid}` | forgets one |
| `GET /api/hub/network/interface/wifi/scan` | `?name=` | what one radio sees |
| `POST /api/hub/network/interface/wifi/join` | `{name, ssid, ...}` | associates one radio; `NetworkView` |

#### `/api/hub/overlay`

| Route | Parameters | Does |
| --- | --- | --- |
| `GET /api/hub/overlay` | | `OverlayChoiceView`: `kinds`, one row per engine in the engine table's order, then the relay's, Direct's, SakuraFrp's and OpenFrp's, the order of the cards, `{key, title, is_enabled, is_integrated, is_supported, is_installed, is_active, client_count}`, `client_count` being the online clients whose socket comes from a network one of that engine's devices holds an address in; Direct's row is `key` `direct`, always installed, active while it is on, and `client_count` the online clients whose `reached_through` is `direct`; the relay's row is `key` `relay`, `is_installed` whether the system's OpenSSH client is present, `is_active` whether its state is `connected`, and `client_count` the online clients whose `reached_through` is `ssh_relay`; SakuraFrp's and OpenFrp's rows are `key` `sakurafrp` and `openfrp`, `is_installed` whether the carried frpc is present, `is_active` whether the state is `connected`, and `client_count` the online clients whose `reached_through` is that key; and `route_conflicts`, one `{code, params, is_withdrawn}` per route a running overlay installed that the hub refused, `code` being `overlay_default_route_refused` or `overlay_route_overlap` and `params` `{title, route, conflict}` |
| `POST /api/hub/overlay/set` | `{netbird: {is_enabled}, easytier: {is_enabled}, relay: {is_enabled}, direct: {is_enabled}, sakurafrp: {is_enabled}, openfrp: {is_enabled}}`, a way in left out keeping what it has | turns engines, the relay, Direct and the frp vendors on or off, any number at once, writing each of the last four into its own file under `config/overlay/`, and runs the converge step; 400 `overlay_not_integrated {title}`, `overlay_not_supported {title}` or `overlay_subnet_overlap {title, subnet, conflict}` when an engine is being turned on, 400 `relay_ssh_missing` when the relay is being turned on and the system has no OpenSSH client, 400 `frpc_missing {title}` when a frp vendor is being turned on and the carried frpc is absent, 502 `overlay_switch_failed {detail}` |
| `GET /api/hub/overlay/netbird` | | the NetBird network the box joins, and its `peers`, each with `latency_ms`: the engine's own, or for a relayed peer the engine gives none for, the round trip the hub measured to the peer's NetBird address, null when that measure had no answer |
| `POST /api/hub/overlay/netbird/join` | the setup key and management URL | joins it, keeps the key sealed in `config/netbird/netbird.json` once the join succeeds, and runs the converge step; 502 `overlay_join_failed {detail}` |
| `POST /api/hub/overlay/netbird/leave` | | asks the plane to delete the peer and deletes the profile; the kept key stays; runs the converge step; 502 `overlay_leave_failed {detail}` |
| `POST /api/hub/overlay/netbird/setup_key/set` | `{setup_key}`, empty to forget | replaces or forgets the kept key without joining, and runs the converge step |
| `GET /api/hub/overlay/easytier` | | the EasyTier network the box defines, its `mode`, `has_config_server`, `is_secure_mode`, and in console mode the `instances` the engine reports, each with the fields it came back without in `withheld` |
| `POST /api/hub/overlay/easytier/set` | `{mode, config_server, is_secure_mode, network_name, network_secret, address, hostname, peers, exported_networks}`: `mode` is `manual` or `console`; `config_server` null keeps the stored console address and empty forgets it; an empty `network_secret` keeps the stored secret | stores every setting at once, the console address with its token and the secret sealed in `config/easytier/easytier.json`, and runs the converge step; the manual network's name is checked in manual mode, and in console mode only when one is given; manual mode with no peer is refused 400 `easytier_invalid {field: peers}`; while EasyTier runs, a manual address whose network overlaps is refused 400 `overlay_subnet_overlap {title, subnet, conflict}`; 502 `easytier_apply_failed {detail}` |
| `POST /api/hub/overlay/easytier/suggestion/create` | | a suggested network for a member |
| `GET /api/hub/overlay/easytier/secret` | | the network secret |
| `GET /api/hub/overlay/direct` | | `DirectView`: `is_enabled`, `public_host`, `public_port`; `urls`, what Direct adds to `urls` while it is on, in the order `urls` holds them: the hub's stable IPv6 addresses in the exposed IPv6 segments, every enabled interface's other IPv4 and stable IPv6 addresses, then the stated public address, each once; `interface_state`, `added` when Direct adds an interface's address, `exposed` when it adds none because every interface address the hub holds is already in `urls` from an exposed segment, `none` when no interface has an address |
| `POST /api/hub/overlay/direct/set` | `{public_host, public_port}`, an empty host stating none, the port 1 to 65535 | stores them in `config/overlay/direct.json` and runs the converge step; `DirectView`; 400 `direct_host_invalid {host}` for a value that is neither an IP address nor a host name, `port_out_of_range {minimum, maximum, value}`; 502 `direct_apply_failed {detail}` |
| `GET /api/hub/overlay/relay` | | `RelayView`: `is_enabled`, `host`, `ssh_port`, `account`, `key_id`, `login_id`, `public_port`, `key_id` or `login_id` empty as `relay.json` holds it; `url`, the address the relay adds to `urls`, empty while it is not configured; `state`, one of the relay's state codes ([network.md](hub_components/network.md), "The states"); `host_key_fingerprint`, the recorded host key as `SHA256:<base64>`, empty when none is recorded; `last_error`, the last line `ssh` wrote before it exited or the failed check's reason, empty while connected; `checked_at`, the last check's time in ISO 8601, empty before the first |
| `POST /api/hub/overlay/relay/set` | `{host, ssh_port, account, key_id, login_id, public_port}`, the ports 1 to 65535, and exactly one of `key_id` and `login_id`, the other null or absent, as the agent install's request names its credential | stores them in `config/overlay/relay.json`, deletes the recorded host key when `host` or `ssh_port` changed, and runs the converge step; `RelayView`; 400 `relay_host_invalid {host}`, `relay_account_invalid {account}`, `unknown_credential {field: key_id}` for a key the vault does not hold or for a request naming both or neither, `unknown_credential {field: login_id}` for a login the vault does not hold, `port_out_of_range {minimum, maximum, value}`; 502 `relay_apply_failed {detail}` |
| `POST /api/hub/overlay/relay/host_key/remove` | | deletes the recorded host key and starts the relay again, which records the key it meets next; `RelayView`. The key is recorded by the connection, so the path has no `add` |
| `GET /api/hub/overlay/sakurafrp` | | `FrpView`, read from `config/overlay/sakurafrp.json` and the running frpc with no call to the vendor: `is_enabled`, `is_signed_in`, `tunnel_id`, `node_name`, `local_port`; `url`, the address the tunnel adds to `urls`, empty while none is picked; `state`, one of the frp state codes ([network.md](hub_components/network.md), "The frp states"); `last_error`, frpc's last line before it exited or the failed check's reason, empty while connected; `checked_at`, the last check's time in ISO 8601, empty before the first; `console_url`, the vendor's console |
| `POST /api/hub/overlay/sakurafrp/access_key/set` | `{access_key}`, empty to forget | checks a key with SakuraFrp and stores it sealed in `config/overlay/sakurafrp.json`; forgetting also clears the picked tunnel; runs the converge step; `FrpView`; 400 `frp_credential_refused {title}`; 502 `frp_vendor_unreachable {title, detail}` |
| `GET /api/hub/overlay/sakurafrp/tunnel` | | `FrpTunnelListView`: `tunnels`, the listed ones ([network.md](hub_components/network.md), "The tunnel list"), each `{tunnel_id, name, node_name, region, latency_ms, is_picked}`, `region` `mainland`, `hk_mo_tw`, `abroad` or `outside_mainland`, `latency_ms` null when no connect finished in time; 409 `frp_not_signed_in {title}`; 400 `frp_credential_refused {title}`; 502 `frp_vendor_unreachable {title, detail}` |
| `POST /api/hub/overlay/sakurafrp/tunnel/set` | `{tunnel_id}` | fetches the tunnel's config, writes frpc's file, stores the tunnel in `config/overlay/sakurafrp.json` and runs the converge step; `FrpView`; 400 `frp_tunnel_unknown {title, tunnel_id}` for an id the list does not hold; 409 `frp_not_signed_in {title}`; 502 `frp_vendor_unreachable {title, detail}`, `frp_config_unusable {title}` when the config holds no proxy of the tunnel's name |
| `GET /api/hub/overlay/openfrp` | | `OpenFrpView`: the fields of `FrpView`, with `is_login_expired`, whether OpenFrp answered 401 to the stored `Authorization`, and `login`, `{state, authorization_url}`: `state` `idle`, `waiting`, `timed_out` or `failed`, and `authorization_url` the address the person confirms at while `waiting`, empty otherwise |
| `POST /api/hub/overlay/openfrp/login/start` | | asks OpenFrp for an authorization URL, replacing any login in progress, and polls for the person's confirmation in the background; on success stores the `Authorization` sealed in `config/overlay/openfrp.json` and runs the converge step; `OpenFrpView` with `login.state` `waiting`; 502 `frp_vendor_unreachable {title, detail}` |
| `POST /api/hub/overlay/openfrp/logout` | | forgets the `Authorization` and the picked tunnel, and runs the converge step; `OpenFrpView`. OpenFrp is not called |
| `GET /api/hub/overlay/openfrp/tunnel`, `POST /api/hub/overlay/openfrp/tunnel/set` | as SakuraFrp's | as SakuraFrp's, against OpenFrp and `config/overlay/openfrp.json` |

Every write on this page, the relay's included, the Network page's writes and
the Proxy page's `apply` run one converge step, `PanelRuntime.converge_network`, and so does
the address sampler when the channel's address set or an overlay's device
moved. Its steps and their order are [network.md](hub_components/network.md),
"The converge step".

#### `/api/hub/proxy`

| Route | Parameters | Does |
| --- | --- | --- |
| `GET /api/hub/proxy` | | the view, with `geodata: {geoip_version, geosite_version, source, latest?}` |
| `POST /api/hub/proxy/set` | routing policy; `remote_dns` and `direct_dns` are lists of `{address, port}`, `port` 53 when absent, asked in their order; an empty `direct_dns` follows the network's resolvers ([proxy.md](hub_components/proxy.md), "Where names resolve") | 400 `proxy_scope_unsupported {switch}` for `is_proxy_enabled`, `is_overlay_proxy_enabled` or `is_local_proxy_enabled` switched on outside Linux, `resolver_required {field: remote_dns}` for an empty `remote_dns`, `resolver_address_invalid {address}`, `port_out_of_range {minimum, maximum, value}` |
| `POST /api/hub/proxy/apply` | | renders and applies xray |
| `GET /api/hub/proxy/node` | | the exit nodes |
| `POST /api/hub/proxy/node/add` | a share link or a node | |
| `POST /api/hub/proxy/node/set` | `{node_id, ...}` | |
| `POST /api/hub/proxy/node/remove` | `{node_id}` | |
| `POST /api/hub/proxy/node/test` | `{node_id}`, or `{}` for every node | measures now, returns the node list |
| `POST /api/hub/proxy/balancer/set` | the balancer's settings | |
| `POST /api/hub/proxy/geodata/scan` | | reads the two latest releases from their publisher's API with the method every download uses ([agent/module_install.md](agent/module_install.md), "Choosing a source"); returns the read's `geodata` block with `latest` filled |
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
| `GET /api/hub/device` | | every managed machine, one row each, as the **Agents** page draws it: `{id, name, icon, ipv4_address, link_mac, is_agent_online, client}`, `client` holding `version`, `platform_os`, `platform_arch`, `hostname`, `last_report_at`, `last_seen`, when its last session ended, `is_version_mismatched`, `last_error`, `{code, params}`, which is `hub_key_missing` for a stored row whose `client` holds a token's hash and no `public_key` and otherwise the error the agent last reported, and `metrics`, the readings the status cell's rings draw, CPU, memory, disk, each GPU and the temperature; and `count`, `{total, online}` for the title's badge. The stored row behind it, in `config/devices/devices.json`, keeps under `client` the token's hash and the agent's static `public_key` |
| `GET /api/hub/device/online` | | the devices with a session open |
| `POST /api/hub/device/enrollment/create` | `{device_id?, name?, is_hub?}` | a link for that row, or for a new one; `is_hub` makes the link for the agent on the hub's own machine, which names loopback first and is not refused `no_reachable_address`; 409 `transport_key_missing` while the transport has written no public key, which a client link is refused the same way |
| `POST /api/hub/device/set` | `{device_id, name, icon, ssh, shown_module}`, `device_id` and any of the others | the name, written by **Rename**, not empty; the icon, one of the panel's device icons, written by the icon picker at once; the stored SSH credential the hub reaches it with; and `shown_module`, the whole list of the modules whose tabs the machine page shows, written by the catalog's cards, the carried modules and every module that is not `absent` shown whatever it holds; the device list |
| `POST /api/hub/device/add` | `{host, ...}`, the host the person typed and the fields of `agent/install` except `device_id` | the **Add over SSH** dialog's press: creates the device's row, named by `host` until the machine reports, and starts the agent's install over SSH in the same request; `TaskStarted` |
| `POST /api/hub/device/remove` | `{device_id}` | **Forget**: forgets the device; its session is ended with `binding_unknown` |
| `POST /api/hub/device/wake` | `{device_id}` | Wake-on-LAN to the last link MAC, broadcast on every network of the exposed IPv4 segments, in every mode, never on an overlay; `wol_no_mac` when none is stored, `no_reachable_address` when there is no such network |
| `POST /api/hub/device/agent/install` | `{device_id, ...}` | installs the agent over SSH; `TaskStarted` |
| `POST /api/hub/device/agent/reinstall` | `{device_id}` | the `reinstall` verb over the channel: the agent installs the package the hub holds for its platform, the machine page's **Update agent** |
| `POST /api/hub/device/reboot` | `{device_id}` | the `reboot` verb |
| `POST /api/hub/device/shutdown` | `{device_id}` | the `shutdown` verb |
| `POST /api/hub/device/process/kill` | `{device_id, pid}` | the `kill` verb |
| `GET /api/hub/device/remote_desktop` | `?device_id=` | a person's own AnyDesk or TeamViewer on the machine |
| `POST /api/hub/device/remote_desktop/password/set` | `{device_id, product, password}` | its unattended password |
| `POST /api/hub/device/desktop/seat_password/reset` | `{device_id}` | a new seat password, every viewer disconnected |
| `GET /api/hub/device/service` | `?device_id=` | what the device publishes |
| `GET /api/hub/device/install_output` | `?device_id=` | the device's install tasks since the panel started, the agent's own and each module's install or uninstall, newest first, each with its output and its `exit_code`, which is not 0 for one that failed |

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
A client ticket's row waits to join for as long as its ticket lives
(`/api/hub/client`).

#### `/api/hub/client`

| Route | Parameters | Does |
| --- | --- | --- |
| `GET /api/hub/client` | | every client, grouped as the page draws them, each with its `permission` (null while it follows the default), `permission_devices`, `permission_entries` and `link_expires_in_s`, the seconds its link still works while the row waits to join and null once it joined, and the list's `default_permission`, `default_permission_devices`, `default_permission_entries`, `permission_kinds`, and `permission_rows`, the rows the fine mode lists under each kind, each `{id, title, device_id, device_name}`, in the order the Services page lists its apps; and `web_shares`, each `{id, name, app_id, entry_id, app_title, device_name, expires_at, expires_in_s, state, code, params, online_count, guest_email}`, `expires_at` null for a share that lasts until it is revoked; `web_share_entries`, the entries a share can offer now, each `{entry_id, app_id, title, device_name, guest_login, visitor_account}`, `visitor_account` the account a visitor uses the app as, for an entry whose `guest_login` is `run_account`, and empty for the others ("Web shares"); and `web_share_sites`, each `{url, title}` |
| `POST /api/hub/client/enrollment/create` | `{name, permission}`, `permission` null to follow the default, else `{kinds, devices, entries}` as `permission/set` takes them | makes the client's row at once, waiting to join with that name and permission, and its link, which works for `ENROLLMENT_TTL_S`, 30 minutes; `ClientEnrollmentView`, `{link, client_id, expires_at, expires_in_s}`; a client link still open from before stops working, and its waiting row goes; 400 as `permission/set`, 409 `transport_key_missing` |
| `POST /api/hub/client/set` | `{client_id, name}` | |
| `POST /api/hub/client/enable` | `{client_id}` | |
| `POST /api/hub/client/disable` | `{client_id}` | its `state` is pushed with `is_disabled` |
| `POST /api/hub/client/remove` | `{client_id}` | forgets the client; its session is ended with `binding_unknown`, and a waiting row's link stops working |
| `POST /api/hub/client/default_permission/set` | `{kinds, devices, entries}`, `devices` and `entries` optional | what a client with no permission of its own is allowed; every client's `state` is pushed |
| `POST /api/hub/client/permission/set` | `{client_id, kinds, devices, entries}`, `kinds` null to follow the default, `devices` and `entries` optional | that client's own permission; its `state` is pushed |
| `POST /api/hub/client/web_share/create` | `{name, entry_id, days, site}`: `days` 1, 7 or 30, or null for a share that lasts until it is revoked; `site` one of `web_share_sites`, or the `https://` address of a copy of the page | makes the share and returns `WebShareCreatedView`, `{link, share}`, the link given this once ("Web shares"); 400 `web_share_entry_invalid {entry_id}` for an entry that is no `web` entry published now, `web_share_site_invalid {site}`, `body_invalid` for an empty name or another `days`, `no_reachable_address` while the hub has no address a link can name; 409 `vault_locked`, `transport_key_missing` while the transport has made no DTLS certificate |
| `POST /api/hub/client/web_share/destroy` | `{share_id}` | **Revoke**: ends the share at once: its link stops working, every page open on it closes, and a guest account it made is removed ("Web shares"); the list; 404 `web_share_unknown` |

One client link adds one device. Its row is made when the link is, and
waits to join: it holds the name and the permission the link was made with,
no token and no static key, and the Clients page shows how long the link
still works ([ui_behavior.md](ui_behavior.md), "The Clients page"). The
`join` that spends its ticket binds that row, which keeps the permission. A
row whose ticket expires unused is removed by the hub within
`ENROLLMENT_SWEEP_INTERVAL_S`, 60 seconds, of its expiry, and so is the row
of a ticket that a newer client link replaced.

| Rule | Reason |
| --- | --- |
| The permission is chosen with the link, before the device joins. | The device has what it is allowed from its first `state`, and nothing is open between the join and the person's next visit to the page. |
| A waiting row is removed with its ticket. | A link that can no longer join leaves no row behind it to tidy by hand. |

A permission kind is a published service type (`web`, `port`, `ssh`, `ai`,
`file`, `rdp`), `overlay`, `terminal` or `panel`, `CLIENT_PERMISSION_KINDS`
in `modules/clients/constants.py`. `ssh` reaches the machines' SSH servers,
on a desktop client alone: `nclient ssh`, its SSH configuration and the
`ssh` entries' local ports ([client.md](client.md), "SSH for other
programs"). The first start of a 0.6.0 hub on a `clients.json` without
`is_ssh_granted` adds `ssh` once to each stored permission that names
`terminal`, the default and each client's own, with `terminal`'s device
list when it has one, and writes
`is_ssh_granted: true`; `clients.example.json` carries it true, and a
person who takes `ssh` away later keeps it away. `terminal` opens a `shell` on a managed
machine and runs one command there through an `exec` stream ("The exec
stream"). `panel` is the hub's own panel, opened from
a client through `connect {is_panel: true}` and signed in with the token of
the `service` frame `{is_panel: true}` ("The panel ports"); it is off unless a
permission names it, since it manages the hub without the panel password.

Every kind has two positions, off and on. On, the hub hands the client what
the kind reaches and signs it in: the `service` frame gives the credential
an entry takes, and the panel opens signed in. Off, the client's state names
none of it, and a stream or a `service` ask for it is refused
`permission_denied {kind}`. No position has the person type a password.

A permission is `{kinds, devices, entries}`, edited in one of two modes
([ui_behavior.md](ui_behavior.md), "The Clients page"):

| Mode | The person sets | Stored as |
| --- | --- | --- |
| coarse, the default | each kind on or off, and for each kind but `overlay` and `panel` the machines it is narrowed to | `kinds`, the kinds that are on; `devices`, a list of device ids per kind, where a kind with no list, or an empty one, allows every machine |
| fine | the kinds and their machines as in the coarse mode, and under each kind that has rows, each row on or off | `entries` beside the two, a map from a row's id to `true` or `false`; a row absent from it follows its kind |

A row is one thing a client reaches under one kind:

| Kind | A row | The row's id |
| --- | --- | --- |
| `web`, `port` | an app with an entry of that kind ("Apps") | the app's id |
| `ssh` | a machine's SSH server | its app's id, `ssh_server_<device id>` |
| `file` | a machine's Home share, one per enabled account of its file share; a machine's folder share, one row for the entries of all its accounts; a declared app with a `file` entry | the Home share's entry id, `samba_<device id>_<share>`; the folder share's id, `samba_folder_<device id>_<share>`; the app's id |
| `rdp` | a machine's desktop | its entry's id, `rdp_<device id>` |
| `terminal` | a managed machine | `terminal_<device id>` |
| `ai`, `overlay`, `panel` | none | |

One function, `is_permitted` in `modules/clients/permissions.py`, judges
every use against the client's permission, or against the default while
the client has none of its own. It takes the kind, the device that provides
the thing, and the thing's row id: the app's id for an entry of an app, the
folder share's id for an entry of a folder share, the entry's own id for
any other entry of no app, `terminal_<device id>` for a shell or
a command, and none for `ai`, `overlay` and `panel`.

1. A row id that `entries` names is allowed or refused by its value.
1. Otherwise the kind is allowed when it is in `kinds` and, where the kind
   has a `devices` list, the device is in it.

The function answers the `service` frame, `connect`, `shell` and `exec`, and
composes the client's `services`, `apps`, `terminals`, `overlays` and
`is_panel_allowed`. The device providing an entry is the device that hosts
it; the hub's own modules belong to the hub's own device when it has one; a
declared app belongs to the device at its address, and one at no device's
address passes only a kind with no list, or its own row.

| Rule | Reason |
| --- | --- |
| A row in `entries` wins over its kind both ways: a row set on is allowed while its kind is off, and a row set off is refused while its kind is on. | A person gives one app to a client that has nothing else, or keeps one app from a client that has the rest. |
| A row is one app whatever its entries' kinds. An app with entries of two kinds, Gitea's `web` and its SSH `port`, is a row under each, and both read and write its one id. | An app is one thing to the person ("Apps"). |
| A row absent from `entries` follows its kind, so an app published later is allowed or refused by its kind and its machines alone. | The coarse setting stays the rule, and the fine one names its exceptions. |
| `entries` keeps a row whose app or entry is not published now, and the function reads it again when the app comes back. Forgetting a device takes the rows its id names out of every permission, and removing a declared app or a folder share takes its row out. | A module stopped for a while comes back with the setting the person made, and a row of something gone for good is not kept. |
| A new permission, a fresh hub's default among them, has `entries` empty. | The coarse mode is the one a person meets first. |

`config/clients/clients.json` holds `default_permission: {kinds, devices,
entries}` beside `clients`, and each client a `permission` that is null or
`{kinds, devices, entries}`, `devices` and `entries` written only when they
name something; a file with no default allows every kind but `panel` on
every device, and the default a fresh hub copies from
`clients.example.json` names every kind but `panel`. A
`shell` or an `exec` the function refuses is refused `permission_denied
{kind: terminal}`. A `connect` is judged as the `service` frame is, and a
panel `connect` or `service` without `panel` is refused `permission_denied
{kind: panel}`. Switching a client off, removing it, its leave, and taking
`panel` from it, through its own permission or the default it follows, end
the panel sessions it opened. Taking `ai` away revokes its gateway key.
Deleting a device takes its id out of every list, the default's and each
client's, turns off each kind whose list named only that device, takes its
rows out of every `entries`, and pushes every client its state. A kind
outside the set, or `overlay` or `panel` given a list, is refused 400
`permission_kind_unknown {kind}`, and a device id no stored device has is
refused 400 `permission_device_unknown {device_id}`; an `entries` value that
is not `true` or `false` is refused `body_invalid`.

#### `/api/hub/service`

| Route | Parameters | Does |
| --- | --- | --- |
| `GET /api/hub/service` | | `ServiceListView`: `apps`, each `{id, title, source, device_id, device_name, local_name, description, entries}` with each entry `{id, name, type, payload, is_healthy, local_port, detail_code, guest_login}`, `detail_code` the probe's word on an unhealthy declared entry such as `share_missing`, else null, `guest_login` how a Web share's visitor signs in to a `web` entry, `app`, `guest_account` or `run_account`, and empty on an entry of another type ("Web shares"), a module's apps first, then the declared, then the manual, each group by title; and `services`, the entries of no app, the `ai` and `rdp` entries and a machine's `file` entries, as a client's list holds them |
| `GET /api/hub/service/share` | | the shares devices declared |
| `POST /api/hub/service/declaration/add` | `{name, host, description, entries}`, each entry `{type, port, scheme, path, protocol, share}`: `type` `web`, `port` or `file`; `scheme` `http` or `https` and `path` for `web`; `protocol` `tcp` or `udp` for `port`, `tcp` when absent; `share` for `file`, an SMB share's name, with `port` 445 when absent; one entry at least, no two of one type, port and protocol, and no two `file` entries whose shares give one slug ("The local name and the local port") | declares one app; `ServiceListView`; 400 `declared_service_invalid {field}` |
| `POST /api/hub/service/declaration/remove` | `{app_id}` | `ServiceListView`; 404 `declared_service_unknown` |
| `POST /api/hub/service/declaration/probe` | `{app_id}` | one health probe of each entry the app has; `ServiceListView` |

`config/services/declared.json` holds `apps`, each `{id, name, host,
description, created_at, entries}` as `declaration/add` takes it, beside
`services`, the records of 0.5. A 0.5 record of the kind `http`,
`generic_tcp` or `generic_udp` reads as an app of one entry with the
record's id, a `samba` record as an app with one `file` entry for each share
it names, and each is written into `apps` at the next write of the file. The
**Declare a service** dialog ([ui_behavior.md](ui_behavior.md), "The
page") declares an app alone, a NAS's share as a `file` entry of one.

A declared app's entry is probed as a 0.5 record of its kind was: a `web`
entry by an HTTP request to its path, a TCP `port` entry and a `file` entry
by a connection to the port, and a UDP one never.

#### `/api/hub/credential`

| Route | Parameters | Does |
| --- | --- | --- |
| `GET /api/hub/credential/ssh_key` | | the stored keys, each with `device_count` and `is_relay_key`, whether `config/overlay/relay.json` names it |
| `POST /api/hub/credential/ssh_key/add` | a key | |
| `POST /api/hub/credential/ssh_key/remove` | `{key_id}` | clears the key from every device and from the relay, whose state becomes `not_configured` and which the converge step stops |
| `GET /api/hub/credential/login`, `POST .../login/add`, `POST .../login/remove` | `{login_id}` on remove | the same shape for logins: each login carries `is_relay_login`, whether `config/overlay/relay.json` names it, and a remove clears it from the relay as a key's does |
| `GET /api/hub/credential/token`, `POST .../token/add`, `POST .../token/remove` | `{token_id}` on remove | the same shape for tokens |
| `GET /api/hub/credential/generated` | | `GeneratedCredentialListView`: `machines`, each `{device_id, name, items}`, one item per secret the hub generated for that machine, `{kind, account, fingerprint}`: `kind` `smb_password` for each account the file share enables, `seat_password` while the Remote desktop module has one, and `ssh_key` for each account the SSH server enables; `account` empty for the seat password; `fingerprint` the SSH key's `SHA256:<base64>`, empty for the two passwords. No value is in it |
| `POST /api/hub/credential/generated/reveal` | `{device_id, kind, account}` | `{value}`, the password opened for this answer alone; the hub writes one line to its journal, `credential_revealed`, naming the device, the kind, the account and the panel session's address; 400 `unsupported_kind` for `ssh_key`, whose private half is never shown; 400 `vault_locked`; 404 `generated_credential_unknown` |
| `POST /api/hub/credential/generated/rotate` | `{device_id, kind, account}` | generates the secret again, seals it where the module keeps it, and pushes the machine its state, writing one `credential_rotated` line the same way: a new SMB password, which the agent sets on the share's user; a new seat password, as `device/desktop/seat_password/reset` does, every viewer disconnected; a new SSH key pair, whose public half replaces the instance's one authorized key; the list; 400 `vault_locked`; 404 `generated_credential_unknown` |

#### `/api/hub/setting`

| Route | Parameters | Does |
| --- | --- | --- |
| `GET /api/hub/setting` | | `SettingsView`, with `offline_client_count` and `offline_agent_count`: the clients and the agents with a binding row and no live session at this moment |
| `POST /api/hub/setting/set` | the settings, `listen_port`, `https_listen_port`, `agent_listen_port`, `hub_name`, `language` and `theme` among them; an absent port keeps it | `SettingsView`; a port change restarts the panel after answering, an agent port change after every online peer was pushed its new `urls` ("Three ports, two audiences"); 400 `port_out_of_range {minimum, maximum, value}`, `port_already_in_use {value}` |
| `GET /api/hub/setting/https` | | `PanelHttpsView`: `is_https_enabled`, `listen_port`, `https_listen_port`, `has_authority`, the authority's `authority_fingerprint` and `authority_created_at`, `authority_file_name`, the served certificate's `leaf_names`, `leaf_issued_at` and `leaf_expires_at`, and `renewed_at`, the last time it was issued again since the panel started |
| `GET /api/hub/setting/https/authority` | | no session, and served by the HTTP port while HTTPS is on: the authority's DER as `neutrino-<hub>-ca.crt`, `application/x-x509-ca-cert`; 404 `https_authority_missing` before there is one |
| `GET /api/hub/setting/https/probe` | | no session: 204 and an empty body; a page on HTTP fetches it from the HTTPS port, and a fetch that completes means the browser trusts the certificate |
| `POST /api/hub/setting/https/enable` | | makes a missing authority, issues the served certificate and writes `is_https_enabled: true`; the HTTP port redirects from the next request, nothing restarts; `PanelHttpsView` |
| `POST /api/hub/setting/https/disable` | | writes `is_https_enabled: false`; the HTTP port serves the panel from the next request, nothing restarts, the certificates stay; `PanelHttpsView` |
| `POST /api/hub/setting/https/authority/reset` | | a new authority and a certificate signed by it, served from the next connection; every browser installs the new authority; `PanelHttpsResetView`, `PanelHttpsView` with `authority_der`, the new authority's DER in base64; 409 `https_reset_over_https` when the request came over HTTPS |
| `POST /api/hub/setting/password/set` | the old and the new password | |
| `POST /api/hub/setting/backup` | | an archive of `config/` without `clients/web_shares.json` ("Web shares") |
| `POST /api/hub/setting/restore` | the archive | |
| `GET /api/hub/setting/about` | | `AboutView`: versions, the credited components, and `os` and `os_version`, the system the hub runs on and its version |
| `GET /api/hub/setting/release` | | `HubReleaseView`: the version running, whether this hub came from a package, `package_family` (`deb`, `rpm`, `arch`, `msi`, `pkg`, or empty in a checkout) and `log_root`, the record of its last update with its `steps` and `output`, the tail of the package manager's log, and the staging task while one runs |
| `POST /api/hub/setting/release/scan` | | reads `latest.json` and the release's `SHA256SUMS` from the release sites ([architecture.md](architecture.md), "The hub updates itself outside its own process"); returns `HubReleaseScanView`: the release or none published, whether it carries a package of this hub's family (`has_package`; a release without one is not an error), whether it is newer or a new major, whether a rollback package can be had, and the room the update needs and has; 409 `hub_not_packaged` from a checkout |
| `POST /api/hub/setting/release/install` | `{version}`, the release confirmed | reads the newest release, or takes the one a scan read in the last 10 minutes, stages the package and hands the install to the `neutrino_hub_update` unit; returns `TaskStarted`, output on `/ws/hub/task`; 409 `release_not_latest` when the newest release is no longer the one named, `release_not_newer`, `release_major`, `disk_space_short`, `update_in_progress` |

### The agent group

The agent group serves the machine page, `/agents/<id>` in the panel
([ui_behavior.md](ui_behavior.md), "The machine page"), and the path window
it opens. The page reads:

| Part of the page | Reads |
| --- | --- |
| the header and **The agent** | the machine's row of `GET /api/hub/device`: its name, `is_agent_online`, and `client`'s `version`, `platform_os`, `platform_arch`, `hostname`, `last_report_at` and `is_version_mismatched` |
| **Monitor** | the same row's `client.metrics`, which holds the agent's `machine.metrics`: CPU in total and per core, memory, the system disk, the temperature, the load average, the uptime, the GPUs and the process table; then each `metrics` event on `/ws/hub/event`, whose readings the charts draw while the page is open; a process row's kill is `POST /api/hub/device/process/kill` |
| **Available accounts** | `GET /api/agent/module/account?device_id=` |
| the module tabs | `GET /api/agent/module?device_id=` for the list, and for the tab shown its own `GET /api/agent/module/<name>` where the module has one, `GET /api/agent/module/version` and `GET /api/agent/module/journal`, and `GET /api/hub/device/install_output` while the hub holds an install task of the module |
| **+ Add module** | `GET /api/agent/module/catalog?device_id=`; a card checked or unchecked writes `POST /api/hub/device/set {device_id, shown_module}` |
| the Remote desktop tab | also `GET /api/hub/device/remote_desktop` and its two writes, `remote_desktop/password/set` and `desktop/seat_password/reset` |
| **Update agent**, **Reinstall** | `POST /api/hub/device/agent/reinstall`, the `reinstall` verb over the channel, live while the machine is online and `is_version_mismatched`; and the install dialog, `POST /api/hub/device/agent/install` |

#### `/api/agent/file`

| Route | Parameters | Does |
| --- | --- | --- |
| `GET /api/agent/file` | `?device_id=&path=` | lists a directory for the path window as `{path, separator, entries}`, each entry `{name, path, is_dir, is_link, size_bytes, modified_at}` with `path` in the machine's own form; `separator` is the agent's, else `\` when the platform's `os` is `windows`; on Windows no path or `/` lists the drives |

The panel moves no file: a person reaches a machine's files through a
client's mount or SSH, and the panel's path window lists folders and files
to pick one.

#### `/api/agent/module`

| Route | Parameters | Does |
| --- | --- | --- |
| `GET /api/agent/module` | `?device_id=` | one row per module, `{name, title, description, runner, method, publisher, license, corresponding_source, uninstall_data, is_configured, task_id, want, state, is_active, version, code, params, details, is_supported, is_carried, is_shown}`: the manifest's words first, `uninstall_data` being the manifest's `{is_deleted, text}` with `{data_dir}` written in for the machine's system and absent for a module the agent carries ([agent/module_install.md](agent/module_install.md), "The manifest"), `is_configured` whether the hub holds a file for it, `task_id` the running install or removal task's, `want` the stored one, empty when the hub holds none, `version` the version installed as the machine reports it, `code` and `params` the reported failure or hold-up; the page's tabs are the rows `is_shown` names, in the page's order; beside the rows `memory_need`, `{need_gib, memory_gib}` on Windows and macOS while the container modules need more memory than the Podman machine has and null otherwise ([agent/modules/containers.md](agent/modules/containers.md), "Memory for the container modules") |
| `GET /api/agent/module/catalog` | `?device_id=` | `ModuleCatalogView`: `categories`, the activity filters in their order, and `modules`, each `{name, category, is_available, is_supported, is_carried, is_shown, state}`, in the order `data/module_catalog.json` lists them: `is_available` false for a module the hub has no manifest of yet, `is_supported` whether the machine's platform has an entry, `is_carried` for Terminal, Remote desktop and the SSH server, `is_shown` whether its tab is on the page, and `state` as last reported |
| `POST /api/agent/module/install` | `{device_id, module}` | writes `want: installed`; on a module whose last report is `failed` or `install_failed`, and on one reading `absent`, `stopped` or `running`, also a fresh `retry_mark`; for a `container` module, first `want: running` on `podman` when its `want` is another ([agent/module_install.md](agent/module_install.md), "From container images") |
| `POST /api/agent/module/start` | `{device_id, module}` | writes `want: running`; the same `retry_mark` on a failed module and on one reading `absent`, `installed` or `stopped`; for a `container` module, first `want: running` on `podman` as **Install** does |
| `POST /api/agent/module/stop` | `{device_id, module}` | writes `want: stopped`; the same `retry_mark` on a failed module and on one reading `absent`, `installed` or `running` |
| `POST /api/agent/module/uninstall` | `{device_id, module}` | writes `want: absent`; the same `retry_mark` on a failed module and on one reading `installed`, `stopped` or `running`; 409 `module_in_use {modules}` on `podman` while a `container` module has a `want` other than `absent` |
| `GET /api/agent/module/version` | `?device_id=&module=` | `ModuleVersionView`: `installed`, the version the machine reports; `chosen`, the machine's choice in `modules.json`, empty while it follows the tested one; `tested`; `newest`; `is_locked`, true for a module of the `agent`, `builtin` or `system` method and for a `container` module whose manifest names no `releases`; `versions`, newest first, each `{version, is_tested, is_untested}`, `is_untested` for a version newer than the tested one, and the one locked version for a locked module; `is_data_forward_only` from the manifest; and `read_at`, when the feeds were last read ([agent/module_install.md](agent/module_install.md), "Module versions") |
| `POST /api/agent/module/version/set` | `{device_id, module, version}`, `version` empty to follow the tested one | writes `version` into the module's entry in `modules.json` and pushes the state; `ModuleVersionView`; 400 `version_unknown {version}` for a version the feeds did not list for the machine's platform, 409 `version_locked {module}` for a module whose version is locked, 409 `agent_offline` |
| `GET /api/agent/module/journal` | `?device_id=&module=&lines=` | the tail of the module's log on the device: its units' journal on Linux, its own sources and the agent's lines naming it on Windows and macOS ([agent.md](agent.md), "Which modules each system runs") |
| `POST /api/agent/module/<name>/apply` | `{device_id}` | pushes the device's state again, for every module alike, with a fresh `retry_mark` on a module whose last report is `failed` or `install_failed`, or `absent`, `installed`, `stopped` or `running` other than its `want`; 409 `agent_offline` |
| `GET /api/agent/module/account` | `?device_id=` | `AccountListView`: `accounts`, the available accounts in the order they were added, each `{account, has_login, share_path, shell_path, is_ai_tools_enabled, tool_configs, modules, ai_tools}`, `modules` the module names that enable it and `ai_tools` its last AI tools result as reported, `{state, code, params}`, `state` empty before the machine reported it; `system_accounts`, the machine's `account_details` for the form's picker and its defaults; `platform_os`; `models`, the names the gateway serves, for the model pickers; and `is_gateway_serving` |
| `POST /api/agent/module/account/add` | `{device_id, account, password, share_path, shell_path, is_ai_tools_enabled, tool_configs}`, `password` on a Windows machine alone, `share_path` and `shell_path` empty for the defaults, each `tool_configs` slot empty for the gateway's default | adds the account: on Windows stores `password` as a vault login and names it `login_id`, turns the AI tools on for it when asked, and pushes the state; `AccountListView`; 400 `account_unknown {account}` for an account the machine does not report, `account_duplicate {account}`, `credential_missing {account}` for a Windows account with no password, `path_invalid {path}` for a path that is not absolute, the agent's own `shell_program_unusable {path}`, `vault_locked`; 409 `gateway_not_serving` for the AI tools turned on while the gateway serves no model, `agent_offline` |
| `POST /api/agent/module/account/set` | the fields of `add`, `password` empty to keep the login | replaces the account's row; a new password is a new login and the old one is deleted; an AI tools switch turned on mints the device's gateway key when it has none, and the last one turned off revokes it; `AccountListView`; the refusals of `add` |
| `POST /api/agent/module/account/remove` | `{device_id, account}` | removes the account from every module that enables it and from every folder share, switches its AI tools back, deletes its login and the secrets its modules generated, and pushes the state; `AccountListView` |
| `GET /api/agent/module/<name>` for `terminal`, `samba`, `ssh_server`, `vscode`, `code_server`, `cloudcli`, `codeg` and `siyuan` | `?device_id=` | `EnabledAccountsView`: the fields of every module view; and `accounts`, every available account in the machine page's order, each `{account, is_enabled, port, is_running, code, params}` with the last four as last reported, and on each row the module's own field: `shell_path` on `terminal`, `share_path` and `user`, the SMB user, on `samba`, where the row of an enabled account left out of the state for a missing home carries `account_home_unknown {account}` as its `code` and `params` ("The account layer in the state"); `ssh_server` adds `host_key_fingerprint` to the view, and `vscode` `is_terms_accepted` and `terms_url` |
| `POST /api/agent/module/<name>/set` for the same eight | `{device_id, accounts}`, the names of the enabled accounts, in the order they were checked | replaces the module's enabled accounts, generating each newly enabled account's secrets, and writes `want: running` with it as an apply of a configuration does, a `want` of `stopped` staying `stopped` ("The modules section, one entry per module"); `EnabledAccountsView`; 400 `account_unknown {account}` for an account that is not available, `account_duplicate {account}`; 409 `terms_not_accepted {module}` for `vscode` before its terms, `agent_offline`; the agent's own refusals as 400. On `samba` an account left unchecked leaves every folder share in the same write, and an account checked whose name a folder share has is refused 400 `share_name_taken {name}` |
| `POST /api/agent/module/vscode/terms/set` | `{device_id, is_accepted}` | records, with `is_accepted` true, that the person accepted the terms for this machine, as `terms_accepted_at` in `config/devices/<id>/vscode.json`; false deletes the record; `EnabledAccountsView`. The panel sends true alone, from the press that opens the terms. Until the record exists, `module/install`, `module/start` and `vscode/set` naming `vscode` on that machine are refused 409 `terms_not_accepted {module}` |
| `GET /api/agent/module/samba/status` | `?device_id=` | `SambaStatusView`: whether the unit is active, the sessions open and how full each share's disk is, as last reported |
| `GET /api/agent/module/samba/folder_share` | `?device_id=` | `FolderShareListView`: `shares`, the machine's folder shares in the order they were added, each `{name, path, accounts}`, `accounts` the accounts checked for it in the file share's order; and `accounts`, the file share's enabled accounts in their order, the ones a folder share can name |
| `POST /api/agent/module/samba/folder_share/add` | `{device_id, name, path, accounts}`, `accounts` one enabled account at least | adds the folder share to `samba.json`, writes `want: running` with it as an apply of a configuration does, a `want` of `stopped` staying `stopped`, and pushes the state; `FolderShareListView`; 400 `share_name_invalid {name}`, `share_name_taken {name}`, `path_invalid {path}` for a path that is not absolute, `share_account_not_enabled {account}`, `body_invalid` for an empty `accounts`, then the agent's own refusals; 409 `agent_offline` |
| `POST /api/agent/module/samba/folder_share/set` | `{device_id, name, path, accounts}` | replaces the path and the accounts of the folder share `name`, whose name stays; the same answer and refusals, and 404 `folder_share_unknown {name}` |
| `POST /api/agent/module/samba/folder_share/remove` | `{device_id, name}` | removes the folder share from `samba.json`, takes its row out of every permission, and pushes the state; the agent removes the share and leaves the folder and its files ([agent/modules/file_share.md](agent/modules/file_share.md)); `FolderShareListView`; 404 `folder_share_unknown {name}`, 409 `agent_offline` |
| `GET /api/agent/module/gitea` | `?device_id=` | |
| `POST /api/agent/module/gitea/import` | `{device_id}` | |
| `POST /api/agent/module/gitea/set` | `{device_id, ...}` | |
| `POST /api/agent/module/gitea/admin/add` | `{device_id, ...}` | |
| `POST /api/agent/module/gitea/admin/password/set` | `{device_id, username, password}` | |
| `GET /api/agent/module/remote_desktop` | `?device_id=` | `RemoteDesktopDeviceView`: the fields of every module view, `state` being the module's as last reported; `is_enabled`, the switch; `platform_os`, the machine's `linux`, `windows` or `darwin`; and `rdp`, the share as the machine last declared it, `{is_shared, account, port, attention, connected_count, is_available}`, the last true unless the machine's agent package reports the host absent |
| `POST /api/agent/module/remote_desktop/set` | `{device_id, is_enabled}` | stores `config/devices/<id>/remote_desktop.json` and pushes; turning it on generates the seat password when the device has none; 409 `agent_offline`; `RemoteDesktopDeviceView` |
| `GET /api/agent/module/hermes_webui` | `?device_id=` | `HermesWebuiDeviceView`: `port`, the forwarder's port as the machine reports it, and `state`, `version` and `details` as last reported |
| `GET /api/agent/module/ayakaleaf` | `?device_id=` | `AyakaleafDeviceView`: `port`, the forwarder's port as the machine reports it; `model`, the stored one, empty for the gateway's first; `models`, the names the gateway serves, for the picker; `is_gateway_serving`; and `state`, `version` and `details` as last reported |
| `POST /api/agent/module/ayakaleaf/set` | `{device_id, model}`, `model` empty for the gateway's first | stores `model` in `config/devices/<id>/ayakaleaf.json` and pushes the state, whose new environment restarts the app; `AyakaleafDeviceView`; 409 `agent_offline` |
| `GET /api/agent/module/podman` | `?device_id=` | `PodmanDeviceView`: the declared `containers`, each with its `services`; `hub_containers`, the hub containers the modules compose, read only; the `mirrors`; `running`, each container as last reported with its `module`, its `source`, its `host_bindings` and their `detected`, `source` being `hub`, `declared` or `manual` by the owner rule of [agent/modules/containers.md](agent/modules/containers.md), "Hub containers"; and on Windows and macOS `machine`, the stored Run settings, the machine as last reported (`details.machine`), the machine's available accounts, and `memory_need` as the module list carries it |
| `POST /api/agent/module/podman/import` | `{device_id}` | |
| `POST /api/agent/module/podman/container/set` | `{device_id, containers}` | replaces the declared containers, each with its `services`; 400 `container_name_reserved {name}` for a new name that starts with `neutrino_`; the agent's own refusals as 400, `service_invalid {name, port}`, `service_protocol_none {port}`, on Windows and macOS `volume_not_shared {name, volume}` and on Windows `udp_not_forwarded {name, port}` among them |
| `POST /api/agent/module/podman/machine/set` | `{device_id, account, cpus, memory_gib, disk_gib}`, `account` an available account, whose login a Windows machine signs in with | stores the Run settings as `machine` in `config/devices/<id>/podman.json` and pushes the state; `PodmanDeviceView`; 400 `unsupported_platform` for a Linux machine, `account_unknown {account}` for an account that is not available, `credential_missing {account}` for a Windows account with no login, `machine_disk_invalid {disk_gib}` for a Windows machine with a disk limit of 0, then the agent's own refusals (`machine_account_missing`, `machine_cpus_invalid {cpus, max}`, `machine_memory_invalid {memory_gib, max}`, `machine_disk_shrink {disk_gib, current_gib}`); 409 `agent_offline` |
| `POST /api/agent/module/podman/mirror/set` | `{device_id, ...}` | |
| `GET /api/agent/module/podman/tag` | `?device_id=` | the tags an image has |
| `GET /api/agent/module/podman/container/journal` | `?device_id=&name=` | |
| `POST /api/agent/module/podman/container/start`, `.../stop`, `.../restart` | `{device_id, name}` | 409 `container_hub_owned {name}` for a hub container |

The eight account-layer modules share one router,
`routers/agent/module_instances.py`, which reads each module's row of the
description table in `modules/devices/`
([agent/module_template.md](agent/module_template.md), "The hub side"), and
the available accounts are `routers/agent/module_account.py`. What each
module keeps in `config/devices/<id>/<module>.json` and what the state
carries are "The account layer in the state". VS Code's terms acceptance,
`terms_accepted_at` in `vscode.json`, is served by its own file,
`module_vscode_terms.py`. The device's gateway key lives in the gateway's
`device_keys` ([hub_components/ai.md](hub_components/ai.md), "A key per
device as well as per client"): the first account whose AI tools switch goes
on mints it, and the last one turned off and removing the device revoke it.

The folder shares are `routers/agent/module_samba.py`'s, beside the
module's status. A folder share's name is 1 to 64 characters, each a
letter, a digit, `-`, `_` or `.`, and is none of `global`, `homes` and
`printers`; any other is refused `share_name_invalid {name}`. A name is
refused `share_name_taken {name}` when, compared without case, an
available account of the machine has it, another folder share has it, or
one of its entries' ids would be another folder share entry's ("The
services section, one entry per published service"); a share of the
person's own of that name is refused by the agent's apply, as for a Home
share ([agent/modules/file_share.md](agent/modules/file_share.md)).

The module catalog is `data/module_catalog.json`: every module by the
activity it serves, in the order of the catalog's dialog, `{categories:
[id], modules: [{name, category}]}`, the categories `code`, `paper`, `lab`,
`design`, `notes`, `files`, `remote` and `other`, and the modules the hub
has no manifest of yet listed with them. Checking a card adds its module to
`shown_module` and unchecking takes it out; a module that is not `absent` on
the machine, and a carried one, stays checked. A module of the `container`
method draws its tab's state, its log and its buttons from `GET
/api/agent/module`; Ayakaleaf's model field reads and writes its own pair
of routes.

The panel's routes of 0.5 that served the pages this version removed are
gone: the Files page's `file/download`, `file/directory/download`,
`file/upload`, `file/directory/create`, `file/rename` and `file/remove`; the
Terminals page's `GET /api/agent/terminal/session`,
`POST /api/agent/terminal/session/stop` and the machine shell on
`/ws/agent/terminal`; the Modules page's **Global configuration**,
`ai_tool`, `ai_tool/enable`, `ai_tool/disable` and `ai_tool/set`, now each
account's switch; the file share's `samba/import`, `samba/share/set`,
`samba/user/set` and `samba/user/password/set`, now its enabled accounts,
and `GET /api/agent/module/samba` answering the enabled accounts in place of
the shares and the users; `terminal/set {account, shell_path}`; the instance lists
of `vscode/set`, `code_server/set`, `cloudcli/set` and `codeg/set`; and
`hermes_webui/set`, its port now the agent's. A person ends a client's kept
session from a client.

### The live sockets

| Socket | Parameters | Does |
| --- | --- | --- |
| `/ws/hub/event` | | cache invalidation, site-wide |
| `/ws/hub/dashboard/stat` | | the live readings the Dashboard draws |
| `/ws/hub/dashboard/dns_log` | | the DNS log as it grows |
| `/ws/hub/task` | `?task_id=` | one task's output |
| `/ws/agent/terminal` | `?device_id=&container=` | a shell inside one of a machine's containers, from the Containers tab's **Shell**; closed `container_hub_owned {name}` for a hub container. The browser sends `{type: input, data}` and `{type: resize, cols, rows}`, each resize a `resize` record on the agent's `shell` stream, and receives `{type: output, data}` and `{type: exit, code}`. A refusal sends `{type: closing, code, params}` and then closes the socket 1011 with the code as its reason; a close reason holds 123 bytes and a param can be longer, so the page fills the code's words from the frame's params |

The agent port's limits, the knock's among them, are in
[transport.md](transport.md), "What an unadmitted peer can cost the hub".
None of them is keyed by the peer's address.

### The router files

| Directory | Files |
| --- | --- |
| `web/routers/hub/` | `setup.py`, `auth.py`, `display.py`, `dashboard.py`, `network.py`, `overlay.py` with `overlay_direct.py`, `overlay_netbird.py`, `overlay_easytier.py`, `overlay_relay.py`, `overlay_sakurafrp.py` and `overlay_openfrp.py`, `proxy.py` with `proxy_node.py`, `ai.py` with `ai_gateway.py`, `device.py`, `client.py`, `service.py`, `credential.py`, `setting.py` |
| `web/routers/agent/` | `file.py`, `module.py` with `module_account.py`, `module_instances.py` (Terminal, the file share, the SSH server, VS Code, code-server, CloudCLI, Codeg and SiYuan) with `module_vscode_terms.py`, `module_samba.py` (its status), `module_remote_desktop.py`, `module_gitea.py`, `module_podman.py`, `module_hermes_webui.py` and `module_ayakaleaf.py` |
| `web/` | `ws.py`, both socket groups |

Each router's test is `hub/tests/web/routers/{hub,agent}/test_<page>.py`
([tests.md](tests.md)).

## The channel

The channel is one session between the hub's transport and each machine it
manages. Under the hub there are two roles: `agent`, the resident service on
a device, and `client`, a person's session. One handshake, one control
stream, one stream layer and one admission rule serve both roles. The role
decides the contents of the two documents and which streams each side opens.
Every machine carries the same transport: the hub, the agent and the desktop
client run `neutrino_transport`, and the Android and iOS apps embed it as a
library. The session under the channel, its knock, handshake and stream
layer, the link a peer enrols from and the binding it keeps are in
[transport.md](transport.md); this part of the page holds what the streams
carry.

### Joining and leaving

A peer joins and leaves on the control stream of a session of its own
("The control stream"):

| Frame | The first frame of | Body | The hub answers |
| --- | --- | --- | --- |
| `join` | a session whose knock says `is_join` | `{ticket, role, protocol, machine_id, name, software, platform}` | `joined {id, token}`, or `refused {code, params}`; admission by `protocol` runs first and a rejected protocol spends no ticket, then the ticket is spent; the hub ends the session after its answer |
| `leave` | a bound peer's session, in place of `hello` | `{}` | `left {}`: a device's row stays with its `config/devices/<id>/` and drops its token, a client's row is deleted with its gateway key; the hub ends the session after its answer |

`machine_id` and `platform` are what the body says about the machine itself,
and each role reads them somewhere else:

| Field | An agent sends | A client sends |
| --- | --- | --- |
| `machine_id` | `/etc/machine-id`, else `/var/lib/dbus/machine-id`, else empty | a uuid4 hex generated on the first read of its state file and kept there |
| `platform` | `{os, family, arch, version}`: `linux`, `windows` or `darwin`, the distribution family `debian`, `rhel` or empty, the architecture normalized to `amd64`, `arm64` or `armhf`, and the system's version: the glibc version on Linux (`2.36`), the build number on Windows (`26100`), the product version on macOS (`15.3.1`), empty where it cannot be read | the same first three keys, `os` one of `linux`, `windows`, `darwin`, `android` and `ios`, and `family` empty off Linux |

A client's report also carries, in its `machine` section, `os_machine_id`:
the operating system's id for the machine, read where an agent reads its
`machine_id` (`/etc/machine-id`, else `/var/lib/dbus/machine-id` on Linux,
`IOPlatformUUID` on macOS, `MachineGuid` on Windows), empty where it cannot
be read. The hub keeps it on the client's row and answers one question with
it, which entries the client's own machine provides (`is_own_machine` on the
entry); the installation's id stays the client's key.

An agent's id is the operating system's, so a machine joining with a blank
link is matched to the row it already had. A client's is one installation's,
so the same person on two machines is two clients, and a client joining again
from an installation the hub has a row for lands back on that row: the link's
waiting row goes, and the old row takes the link's name and permission and
keeps its key, its switch and everything it last reported. The hub reads `family` to pick a
package family and `arch` to pick the package itself, and an architecture
outside the normalized set is the machine's own word and matches no platform
entry. The hub compares a manifest entry's floor with an agent's `version`.

The join names no network; the agent's first report names the link its
session runs on, the local address of its connection. Joining and leaving
have the same two words on every surface:

| Surface | Join | Leave |
| --- | --- | --- |
| the control stream | `join` | `leave` |
| the agent's command line | `nagent join <link>` | `nagent leave` |
| the client's command line | `nclient hub join <link>` | `nclient hub leave <hub>` |
| the client window | **Join a hub** | **Leave** |

### The control stream

The peer opens the session's first stream as `open {kind: control}`, and the
transport accepts it. Its `data` records ([transport.md](transport.md), "The
stream layer") carry one byte stream of JSON
lines: one frame per line, its `type` the frame's name, UTF-8, each at most
`ControlFrameBytesMax`, split into records at any byte, so a large frame
spans several records. The peer's
Python writes the first frame, `hello`, `join` or `leave`, through its
transport; any other first frame, or none within `HelloTimeout`, is refused
`hello_invalid`. The transport passes the frames of an admitted session to
the hub's Python and back ([transport.md](transport.md), "The local
channel"), and handles three itself:
it answers `ping` with `pong`, turns `join` into the `ticket` question and
writes the `joined` or `refused` that answers it, and turns a client's
`service` into the `token` question and writes its `reply`.

The `hello` and the `welcome` are identity cards of one shape.

| Field | `hello` (up) | `welcome` (down) |
| --- | --- | --- |
| `protocol` | the number this build speaks | the hub's number |
| `role` | `agent` or `client` | `hub` |
| `id` | the binding id | the hub id from `identity.json` |
| `name` | the hostname, or the binding's name | the hub's name from `identity.json` |
| `software` | `neutrino_agent/0.6.0`, `neutrino_client/0.6.0` | `neutrino_hub/0.6.0` |
| `time` | absent | the hub's clock as it sends the card, in seconds since the epoch, with a fraction |

An agent takes the offset between `time` and its own clock and checks every
token the hub minted against the hub's time ([agent.md](agent.md), "Every
later connection"). A `hello` whose `id` is not the binding the session's
static key belongs to, or whose `protocol` or `role` is not the knock's, is
refused `hello_invalid`, as is one that cannot be read. A `hello` past
`SessionsMax` admitted sessions is refused
`channel_full {limit}`, and otherwise the admission codes of
[transport.md](transport.md), "The numbers", hold. The
handshake has no state hash; the first `report` has it.

| Frame | Direction | Body |
| --- | --- | --- |
| `hello` | up | the identity card |
| `welcome` | down | the hub's identity card |
| `join`, `joined` | up, down | "Joining and leaving" |
| `leave`, `left` | up, down | "Joining and leaving" |
| `refused` | down | `{code, params}`; the hub ends the session after it |
| `state` | down | `{hash, ...sections}`: what is to be true |
| `report` | up | `{state_hash, ...sections}`: what is true |
| `ping` | up | `{nonce}`: a peer's round-trip probe; `nonce` is its own opaque string of at most 64 characters |
| `pong` | down | `{nonce}`: the transport's answer, at once and on the same stream, `nonce` echoed as received, an empty string when the `ping` had none, cut to 64 characters |
| `service` | up, from a client | `{request, id}` for one published entry, or `{request, is_panel: true}`: the material that entry takes from the hub ("The service frame") |
| `persist` | up from a client, down to an agent | `{request, session_id, is_persistent, is_shared}`: whether a kept shell stays when its last stream closes and whether every viewer with terminal rights on the machine can attach to it, a flag left out keeping its value |
| `stop_session` | up from a client, down to an agent | `{request, session_id}`: ends a kept shell |
| `reply` | down to a client, up from an agent | `{request, code, params}`: the answer to the `service`, `persist` or `stop_session` of the same `request`, `params` the result and a `code` a refusal |

`request` is the asker's own opaque string of at most 64 characters, one
for each question it has open. Every action that carries bytes is a stream,
whose `open` is the request and whose `close` is the reply, and `kind` is
the stream's whole method vocabulary; a question with one answer is a frame
and its `reply`.

A client sends a `ping` every `CLIENT_PING_INTERVAL_S` on the live session
and once right after the channel moves to a new session, never before
`welcome`. The `pong` whose `nonce` is the last `ping` sent on that session
sets `rtt_ms`; a `pong` with another `nonce` is dropped. The transport
answers any admitted peer, agent or client, and stores nothing. Keepalive is
yamux's own ping, which every side sends every `KeepAliveInterval`.

### The timings

Every interval the Python sides run on is a constant named here, in the
`constants.py` of each package. The transport's own constants are in
[transport.md](transport.md), "The timings".

| What it bounds | Hub | Agent | Client |
| --- | --- | --- | --- |
| a report while nothing changes | | `AGENT_REPORT_INTERVAL_S` 5 | `CLIENT_REPORT_INTERVAL_S` 30 |
| the client's round-trip probe | | | `CLIENT_PING_INTERVAL_S` 20, the client's `ping` frame, whose `pong` sets `rtt_ms` |
| a `reply` to a `service`, `persist` or `stop_session` | `CHANNEL_REPLY_TIMEOUT_S` 15 | | `CLIENT_STREAM_TIMEOUT_S` 15 |
| a hub thread's call onto the loop | `CHANNEL_CALL_TIMEOUT_S` 15 | | |
| the least time between two log lines for a binding's `control_unavailable` refusals | | `AGENT_REFUSAL_LOG_INTERVAL_S` 60 | `CLIENT_REFUSAL_LOG_INTERVAL_S` 60 |

An agent reports six times as often as a client because its `machine` section
carries the metrics the Dashboard draws live; a client's carries its hostname
and platform, which change between releases.

### The sections

| Section | `state` to agent | `report` from agent | `state` to client | `report` from client |
| --- | --- | --- | --- | --- |
| `machine` | | `{hostname, platform, accounts, account_details, metrics, sessions}`, `account_details` one `{account, home, shell}` per account | | `{hostname, platform, os_machine_id}` |
| `is_refresh` | | | | bool: a refresh the person asked for, answered with the whole state |
| `network` | | `{link: {interface, mac, address}, interfaces: [{name, mac, addresses[]}]}` | | |
| `modules` | `{name: {want, config, install, retry_mark}}` | `{name: {state, is_active, version, code, params, details, task}}` | | |
| `desktop` | `{seat_password}` | `{is_shared, origin, account, share_id, port, attention, connected_count}`, `origin` `switch` or `command` (a share an old `nagent rdp start` record keeps running), empty while nothing is shared | | |
| `ai_tools` | `{is_enabled, is_forwarded, gateway_port, base_url, api_key, accounts: [{account, password, tool_configs}], cc_switch_version, cc_switch_artifact, retry_mark}` | `{accounts: [{account, state, code, params, has_records}]}` | | |
| `source_sets` | `{name: {probe, sources, variables}}`: each source set a recipe of the state names, as `data/source_sets.json` defines it | | | |
| `services` | | | `[{id, type, title, payload, is_healthy, source, description, description_code, description_params, device_id, device_name, is_own_machine, app_id, name, local_port}]`, the last three on `web`, `port` and `ssh` entries alone | |
| `apps` | | | `[{id, title, source, device_id, device_name, local_name}]`: the apps the `web`, `port` and `ssh` entries belong to ("Apps") | |
| `is_disabled` | | | bool | |
| `urls` | `["tcp://<address>:<port>", ...]` | | the same list | |
| `ssh_relay_url`, `sakurafrp_url`, `openfrp_url` | | | the member of `urls` that is the SSH relay's address, SakuraFrp's and OpenFrp's, each empty while its way in adds none; a client ranks a candidate's path by them ([client.md](client.md), "A network change starts a round") | |
| `overlays` | | | `[{provider, ...}]`: what the client joins each of the hub's overlays with, the preferred first | |
| `terminals` | | | `[{device_id, name, is_online, accounts, sessions}]`: the managed machines its permission allows under `terminal`, where it opens a `shell` or an `exec`, each with the Terminal module's enabled accounts, the first being the default, and the sessions this client sees there | |
| `is_panel_allowed` | | | bool: the client is allowed to open the hub's panel through `connect {is_panel: true}` | |
| `reached_through` | | | `lan`, `netbird`, `easytier`, `ssh_relay`, `direct`, `sakurafrp` or `openfrp`: the way this client's session reached the hub | |
| `error` | | `{code, params}` | | |

The `error` section is the agent's most recent failure worth showing: the last
error, the state error, or a failed `reinstall`.

`source_sets` holds the sets the machine's recipes name, an artifact's
`source_set` and a `container` entry's `source_sets`, and no other; it is
empty while no recipe names one. The agent probes a set's sources itself,
since the fastest source depends on the machine's own network
([agent/module_install.md](agent/module_install.md), "Source sets"). The
section comes with 0.6.0, as the recipe's shape does, and keeps `PROTOCOL`
4.

`task` in a module row of the agent's report is the module's task
([agent.md](agent.md), "The steps"): `{steps, index, wait, is_running}`,
`steps` the plan as `[{name, params}]`, `index` the 1-based step that runs
or the last one run, `wait` the `{code, params}` of what that step waits for
now and empty while it works, and `is_running` whether the task runs. It is
null for a module that has had no task since the agent started, and a row
keeps its last task's `task` until the next one starts. It is an added
field and keeps `PROTOCOL` 4.

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
frame.

`urls` is every address the hub answers the channel on: the link's set, which
holds the hub's address on every running overlay it is exposed on, plus
NetBird's name for the hub where its daemon reports one; while Direct is on,
the stable IPv6 addresses and every enabled interface's addresses, in the
order the link gives them, and then the public address stated for it;
then SakuraFrp's and OpenFrp's public addresses while each has a tunnel
picked; and last the relay's `tcp://<host>:<public-port>` while the relay
is on and configured.
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
connection's peer address and listener ("The address a caller is given") and names the word
the client's Hubs row shows. Both are in the state's hash, so a client that
reconnects another way is pushed its state.

`terminals` lists every managed machine the client's `terminal` kind
allows, narrowed by that kind's device list, the hub's own among them,
online or not, with `is_online` read from its session; it is empty when the
permission does not allow `terminal`. A machine in it takes a `shell` and an
`exec` alike. The hub pushes every client its state when
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

`retry_mark`, in a module's entry and in the `ai_tools` section, is a
short random token the hub writes when a person presses a failed module's
own action again, or presses a module whose state is not its `want`
([agent.md](agent.md), "A retry is the same press again"). It changes its entry's hash, and with it the state's, and means
nothing else; no configuration reads it, and an entry without one is the
same entry. The hub
keeps one mark per module and one for the AI tools per device in
`device_retry_marks.json` under its state root, replaced by each press and
dropped with the device ([files.md](files.md)).

`ai_tools` in the state is the machine's AI tools setting, one switch per
available account ([agent/ai_tools.md](agent/ai_tools.md)). `is_enabled` is
true while at least one account's switch is on and the gateway serves a
model. `is_forwarded` says
whether the agent opens its AI gateway forward ([agent.md](agent.md), "The
AI gateway forward"): true on a managed machine while `is_enabled` is true
or a module that uses the gateway, a container module or SiYuan, is
installed, and false on the hub's own machine. `gateway_port` is the gateway's `listen_port` on the
hub's own machine while a container module that uses the gateway is
installed there, the port the
agent relays on the Podman bridges, and 0 otherwise. With `is_enabled` true,
`base_url` is `http://127.0.0.1:8317` on a managed machine, the forward, and
`http://127.0.0.1:<listen-port>` on the hub's own machine, the gateway
itself. The hub sets all three, and the agent infers none from anything
else in the state; `api_key` is the device's own gateway key. `accounts`
names every available account whose `is_ai_tools_enabled` is true, each with
its `tool_configs`, `{claude: {default, opus, sonnet, haiku}, codex: {model,
model_reasoning_effort}, gemini: {model}}`, every slot the person left at the
gateway's default filled with the gateway's first served model, as the
client's `resolved_configs` fills it, and `password`, the account's login,
sent only to a Windows machine. An account whose switch goes off leaves
`accounts`, and the agent switches it back. `cc_switch_version` is the version
`data/manifests/cc_switch.json` pins, the copy of cc-switch the agent runs,
and `cc_switch_artifact` that manifest's artifact for the machine's platform,
`{name, kind, digest}`, which the agent's `package` stream names; it is
absent where the manifest names no entry for the platform. With it false the
section is `{is_enabled: false, is_forwarded, gateway_port,
cc_switch_version, cc_switch_artifact}`, the version and the artifact there
so that a copy fetched for a switch back is the one the next switch runs. The section carries the device's `retry_mark` on and off alike,
so a press of off after a switch back that could not run tries it again. The report's
`ai_tools` lists each account the state names and each one switched back
under the current hash, `state` being `switched`, `switched_back` or
`failed`, with `{code, params}` on a failure, and `has_records` whether
the agent keeps the account's records, so whether a tool of it still points
at the hub; `download_failed {file, sources}` is every account's when the
agent could not get its copy of cc-switch. An agent
that restarted reports each account whose records stand as `switched` until
the next state arrives, and does not act on a state whose hash it already
tried. Both are added fields and keep `PROTOCOL`; an agent that predates them ignores the
section and reports none, which the panel draws as a machine that has not
reported.

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
client's `shell` naming a session another viewer owns and has not shared,
and a `persist` from any viewer other than the owner, are refused
`session_not_owned {session_id}` and reach no machine; a session the machine
does not list yet is the opener's own. The owner and the sharing are the
ones the hub stamped and relayed itself, else the machine's last report, so
an unshare holds before the next report and a session opened a moment ago
is not joined by guessing its id. When the owner's `persist` turns
`is_shared` off on a shared session, the hub closes every `shell` stream
other clients hold on it with `session_not_owned {session_id}`; the owner's
own streams stay. The panel is the hub's own viewer: it joins any session,
and an unshare closes no panel terminal. `stop_session` is not held to the
owner.

### The modules section, one entry per module

```json
"samba": {
  "want": "running",
  "config": {"shares": ["..."], "users": ["..."]},
  "install": {"runner": "samba", "method": "system", "params": {"version": "system", "packages": ["samba"], "pre_install": ["..."], "verify": "smbd -V", "uninstall": {"packages": ["samba"], "post_uninstall": ["rm -f /etc/samba/smb.conf.neutrino"]}}}
}
```

Terminal, Remote desktop and the SSH server are composed from their own
files, not from `modules.json`, and sent to every managed device:

```json
"terminal": {"want": "running", "config": {"accounts": [{"account": "lab", "shell_path": "", "password": ""}]}, "install": {"runner": "terminal", "method": "agent", "params": {}}},
"remote_desktop": {"want": "stopped", "config": {"is_enabled": false}, "install": {"runner": "remote_desktop", "method": "agent", "params": {}}},
"ssh_server": {"want": "running", "config": {"instances": [{"account": "lab", "authorized_key": "ssh-ed25519 ...", "shell_path": "", "password": ""}]}, "install": {"runner": "ssh_server", "method": "agent", "params": {}}}
```

`terminal`'s `want` is always `running`; its `config` holds the module's
enabled accounts ("The account layer in the state"), none when
`config/devices/<id>/terminal.json` is absent. `remote_desktop`'s `want` is `running` while `is_enabled` is true
and `stopped` otherwise; its `config` is `remote_desktop.json`,
`{is_enabled}`, false when the file is absent. Their manifests,
`terminal.json`, `remote_desktop.json` and `ssh_server.json`, name the
method `agent` with empty `params` in every platform entry: the agent's own
package holds the module. `GET /api/agent/module` answers the three
`is_supported: true` on every platform, and the four presses refuse them
400 `module_not_optional {name}`, as every module the agent carries.

The agent reports `terminal` `running` once it holds the accounts, and
`remote_desktop` `running` while its RustDesk service runs, with nobody at
the screen too, `stopped`
while the switch is off and none of its RustDesk processes runs, and
`failed` with `rdp_takeover_failed {step, detail}` or `rdp_restore_failed
{step, detail}`. The report's `rustdesk` row of earlier agents is gone. A
`shell` stream refused for the Terminal module's sake closes
`terminal_account_missing` while no account is enabled, `account_not_enabled
{account}` for an account the module does not enable, `account_unknown
{account}` for one the machine does not have, or `shell_program_unusable
{path}`.

`install` is the recipe the hub resolves from `data/manifests/<module>.json`
for the machine's platform and the version the machine chose: `{runner,
method, params}` ([agent/module_install.md](agent/module_install.md), "The
manifest"). The hub sends it with the state, and the agent has no manifest
logic of its own. `params` is the method's: a `system` entry's `packages`,
`pre_install`, `verify` and `uninstall`; a `hub` entry's `version`, its
`artifacts` without their `sources`, `packages`, `verify` and `uninstall`; a
`container` entry's `version`, its `artifacts` with their `sources`, and its
`source_sets`; an `npm` artifact's `source_set` in place of `sources`; and
nothing for `agent` and `builtin` ([agent/module_install.md](agent/module_install.md),
"Install methods"). The recipe holds no `releases` and no identity field.
A platform entry can name `min_version`, a dotted number the loader checks:
a machine whose platform `version` is below it resolves no entry, the same
as a platform the manifest does not name, and one that reports no `version`
is not ruled out. `GET /api/agent/module` answers such a module
`is_supported: false`, the machine page's catalog greys its card out and the
page never shows it as a tab, and a press on it is refused 409 `no_platform_build
{module}`.

The agent observes each module it has a runner for and reports a state derived
from the same facts, whoever installed the software:

| Fact | Read from |
| --- | --- |
| installed | the method's presence check: `verify` succeeds for `system` and `hub`, and every image's digest is in Containers' Podman for `container`; for a module the state does not name, which comes with no recipe, and for a `builtin` entry, the runner's own check ([agent/module_install.md](agent/module_install.md), "One presence check") |
| active | the unit is active, read whenever the row before reads installed |
| configured | the root-only mark `/var/lib/neutrino/agent/configured/<module>` exists; written on the first successful apply of the hub's configuration, deleted on uninstall |

| `state` | Meaning |
| --- | --- |
| `absent` | the software is missing; the row can hold a kept failure's `{code, params}` ([agent.md](agent.md), "A failure outlives a restart") |
| `installed` | the software is present and the hub has never configured it; `is_active` says whether it runs |
| `install_failed` | the last install failed with `{code, params}`, whatever it left on the machine |
| `stopped` | the hub has configured it and the unit is stopped |
| `running` | the hub has configured it and the unit is active; a `running` or `stopped` row can hold `{code, params}` a module names beside its state, `share_users_unknown {shares}` ([agent/modules/file_share.md](agent/modules/file_share.md)) |
| `installing`, `uninstalling` | in transit; an `installing` row can hold `{code, params}`, `reboot_required` while a Windows machine owes the restart an install step asked for ([agent.md](agent.md), "Status is typed") |
| `queued` | in transit: its task has not run its first step, which waits for a step lock, named by `waiting_for_lock {lock, module}` ([agent.md](agent.md), "Step locks") |
| `failed`, `unsupported` | the last step failed with `{code, params}`; the agent has no runner for this module |

`install_failed` and `failed` are kept by the agent across its restarts
until the module's next attempt, or a state that no longer names the module
([agent.md](agent.md), "A failure outlives a restart"). The hub keeps the
module's `want` and its configuration; **Install** and **Uninstall** on an
`install_failed` module write a fresh `retry_mark`, as every press on a
`failed` one does.

The agent has a runner for a `container` module only once a state names
it, so a `container` module that a machine's report leaves out reads
`absent` on every surface once that machine has reported.

This table is closed on every surface; a surface that meets a token outside it
shows the word for a machine that has not reported. That is also what the
panel shows for `agent_never_reported`, the code a request gets when the
machine it went to let the stream run out of time.

`want` is stored in `config/devices/<id>/modules.json`, and a panel action
writes it directly:

| Panel action | `want` | The agent |
| --- | --- | --- |
| **Install** | `installed` | installs the package only; writes no configuration, and starts nothing but Containers' `podman.socket`, which a Linux install enables |
| **Configure** or **Start** | `running` | ensures the package, applies the configuration, starts the unit |
| **Configure** on a module whose `want` is `stopped` | none written | nothing new: the panel opens, the first import of Gitea or Containers still runs, and the module stays stopped until its **Start** |
| **Stop** | `stopped` | ensures the package, applies the configuration, stops the unit |
| **Uninstall** | `absent` | uninstalls by `uninstall`, deletes the configuration the hub wrote and the configured mark, and calls the runner's `remove_data` when `is_data_kept` is false; the confirmation shows the row's `uninstall_data` line ([ui_behavior.md](ui_behavior.md), "The machine page"); every shipped `hub` and `system` entry keeps the data, so share directories, repositories and declared containers' volumes stay, and a `container` module is removed with its volumes ([agent/module_install.md](agent/module_install.md), "From container images") |

Once the machine reports a module wanted `absent` as `absent`, that want is
settled (`is_settled` in `modules.json`): the row keeps `absent`, the state
stops naming the module, and the next press asks for it again. A module the
state does not mention is left as it is and still observed and reported, so a
hand-installed Samba shows as `installed`. The agent's rule for
reconciling is one sentence: make each mentioned module's actual state equal
its `want`. A failure is reported with its code and is not retried while the
module's entry is unchanged. The agent starts and stops only the units its
recipe names, and disables or masks none but `podman.socket`, which
Containers' **Stop** disables and its install and every apply under `want`
`running` enable
([agent/modules/containers.md](agent/modules/containers.md), "Linux").

Package operations on one machine run one at a time, serialized on the agent,
because one package manager holds the machine-wide lock.

Taking over a machine happens at its first report on a session, for each
module that has an import (`gitea`, `podman`; the account layer's modules
have none) and no `want` in `modules.json`. A module reporting `stopped` or `running` gets that
state as its `want`, and its configuration is imported from the report's
`details` when the hub holds no file for it. A module reporting `installed`
is imported, and gets `running` or `stopped` as its `want` by `is_active`,
when the import finds something. An import that finds nothing leaves the
module as it reports, and Gitea is taken over only while the hub holds
`gitea_secrets.json` for the device. The state is pushed and the published
list recomposed in the same step; a later report on the same session takes
nothing over.

A module with no `want` that the machine reports `installed`, `stopped` or
`running`, one with no import such as the file share, VS Code,
code-server, CloudCLI, Codeg and SiYuan, or one whose import found nothing, is the person's from their first press: its
**Start** is live, and an apply of its configuration (`POST
/api/agent/module/<name>/set` and the like) writes `want: running` with it,
since applying a configuration asks the module to run it. An apply never
starts a module whose `want` is `stopped`: the `want` stays `stopped`, the
agent's `configure` under `stopped` takes the change, and the module runs
it from its next **Start**. The account layer's enabled accounts and the
file share's folder shares follow this as Containers' Run settings do.

**Configure** keeps its import for a module whose import was empty at the
first report: the panel calls `POST /api/agent/module/<name>/import
{device_id}` when the hub-side configuration is empty, and then opens the
configuration section.

The first configuration pushed down therefore equals what the machine already
has. From then on the hub's copy is the only truth, and every render writes
the whole file back.

| Module | What `details` reports, and what import reads |
| --- | --- |
| Samba | `testparm -s` parsed into the global section and each share, `pdbedit -L` into the user list; nothing is imported, since the shares follow the enabled accounts and the folder shares |
| Podman | `podman ps -a --format json` and `podman inspect`: each container's image, ports, volumes, environment (empty for a hub container), whether a unit exists, and `module`, the value of its label `neutrino.module` or empty; its `host_bindings`, read from `ps`'s `Ports`, which Podman 3.4 writes as `hostPort` and `hostIP` and later versions as `host_port` and `host_ip`, one `{address, port, protocol, detected}` per published host port, `protocol` being `tcp` or `udp`, `address` empty for every address, and `detected` `http`, `https` or `tcp` as the agent's probe found on a running TCP binding, empty on UDP and before the probe; the registry mirrors; the import leaves out a container whose image is empty or contains a space ([agent/modules/containers.md](agent/modules/containers.md), "A refused declared container"), gives every port the service `auto`, and on Windows and macOS its Run settings name the reported machine's account, with its disk's size now as the disk limit and 0 CPUs and memory |
| Gitea | the hub's own instance; a hand-installed one reports as running on its port and is not imported |
| VS Code | each server's account, port, url and whether it runs; nothing is imported |
| code-server | each instance's account, port and whether it runs; nothing is imported |
| Samba on Windows and macOS | only the shares the module made, in the Linux shape with `params` `comment`, `read only` and `valid users`; the accounts it made; the sessions; and `fence {is_present, is_enabled, blocked}` |

| Rule | Reason |
| --- | --- |
| The agent reports no environment of a hub container. | A hub container's environment holds its module's secrets, such as Hermes WebUI's password and the module's gateway key, and the hub composed it. |
| Every route and stream that hands a report's `details` to the panel gives each container's `environment` as the variables' names alone, never their values. The import of a container reads the values from the report the hub keeps, never through the browser. | A declared or hand-started container's environment can hold a person's secrets, and the panel lists the containers to every signed-in page. |

On Windows and macOS an agent with the `smb_server` capability runs the
`samba` module against the SMB server the system holds. Its entry is
`builtin`: the recipe the state holds is `{runner: samba_native, method:
builtin, params: {}}`, the agent's own check says whether the server is
there, an install installs
nothing, and the module reports `installed`, `stopped` or `running` like any
other. The configuration is the Linux one; `validate` wants a share path
absolute from a drive on Windows and from `/` on macOS, and an account name
of at most 20 characters on Windows. `stopped` takes the module's shares off
the server and keeps its accounts. An apply refuses a name the
machine already has for something the module did not make, on Linux too: a share with
`share_name_taken {name}`, an account with `user_name_taken {user}`. An
account the system will not make is refused with `user_create_failed {user,
detail}`, `detail` being the tool's own line, and a record of the name that is
not a usable account and that macOS will not let root delete with
`user_record_unusable {user, detail}`; either refusal comes once every other
account and every share is applied. An
account the module made signs in once the agent has set its password from
`passwords`.

The `vscode` module runs Microsoft's standalone CLI, `code serve-web`, once
per enabled account. Its configuration is `{address, instances: [{account,
token, password}]}` ("The account layer in the state"): `address` is empty, and every server listens on
`127.0.0.1` alone, where the agent's end of a `connect` stream reaches it
("The connect stream"); `token` is the instance's connection token,
which the hub keeps sealed and sends in the clear inside the state; and
`password` is the account's login, sent only to a Windows machine, where a
task that runs as an account signs in with it. Its recipe's runner is
`vscode` and its method `hub`, with one artifact of kind `tar_gz` for the
Linux tarball and `zip` for the Windows and macOS archives, and the agent
opens `package {module: vscode, artifact, digest}` for it and unpacks the
one `code` or `code.exe` inside it: to `/var/lib/neutrino/agent/vscode` on Linux, and to
`vscode` under the root the `hub_packages` capability names on Windows
(`%ProgramData%\Neutrino`) and macOS (`/Library/Application
Support/Neutrino`). `details` is `{instances: [{account, port, url,
is_running, code}]}`, `port` the one the agent took, the url without its
token, and `code` `credential_invalid` for a Windows task that cannot sign
its account in. An apply refuses `account_invalid`, `account_duplicate`,
`token_missing` and, on Windows, `credential_missing`, all naming the
`account`; `account_unknown {account}` for an
account a Linux machine or a Mac does not have; and `credential_invalid
{account}` when Windows refuses the login.

The `cloudcli` module runs CloudCLI once per enabled account
([agent/modules/cloudcli.md](agent/modules/cloudcli.md)), its configuration
`{instances: [{account, web_password, token_secret, password}]}`. Its recipe names
two artifacts: the Node.js archive `data/manifests/cloudcli.json` pins for
the platform, which the agent opens `package {module: cloudcli, artifact,
digest}` for, and the npm package, of kind `npm`, with the `npm` set as
its `source_set` and the host lists of its npm settings as `hosts`. An install that
fails reports the step: `download_failed {file, sources}`,
`cloudcli_npm_install_failed {account, detail}`,
`cloudcli_native_module_failed {account, module, detail}` or
`cloudcli_install_out_of_memory {account}`.

The `codeg` module runs Codeg once per enabled account, on Linux, macOS and
Windows ([agent/modules/codeg.md](agent/modules/codeg.md)). Its
configuration is `{instances: [{account, secret, password}]}`, `secret` the
instance's token
secret, generated the first time, kept sealed in
`config/devices/<id>/codeg.json` and sent opened inside the state as
code-server's is, with the login's password for a Windows machine as VS
Code's. Its recipe names two artifacts, the server bundle and Node.js,
which the agent opens `package {module: codeg, artifact, digest}` for. `details` is `{version,
instances: [{account, port, is_running, code}]}`. An apply refuses what
code-server's refuses, and on Windows `credential_missing {account}` and
`credential_invalid {account}` as VS Code's does.

The `siyuan` module runs SiYuan's kernel once per enabled account, on Linux,
macOS and Windows ([agent/modules/siyuan.md](agent/modules/siyuan.md)). Its
configuration is `{instances: [{account, secret, access_code, gateway_key,
password}], gateway_url, models}`: `secret` the instance's token secret,
`access_code` the kernel's own login, and `gateway_key` the instance's key
to the AI gateway, each generated by the hub, kept sealed in
`config/devices/<id>/siyuan.json` and sent opened inside the state;
`password` the login of a Windows account, as VS Code's; `gateway_url` the
gateway's address on the machine, `http://127.0.0.1:8317` on a managed
machine and the gateway's `listen_port` on the hub's own; and `models` the
names the gateway serves. Its recipe names one artifact, the desktop build,
of kind `tar_gz` on Linux, `dmg` on macOS and `nsis` on Windows, which the
agent opens `package {module: siyuan, artifact, digest}` for. `details` is
`{version, instances: [{account, port, is_running, code}]}`. An apply
refuses what Codeg's refuses.

The `code_server` module runs code-server once per enabled account, on
Linux and macOS ([agent/modules/code_server.md](agent/modules/code_server.md)).
Its configuration is `{instances: [{account, secret}]}`, `secret` the
instance's token
secret, which the hub generates the first time, keeps sealed in
`config/devices/<id>/code_server.json` and sends opened inside the state,
as it sends CloudCLI's. Its recipe names the release of the version the
machine runs, which the agent opens `package {module: code_server,
artifact, digest}` for. `details` is `{version,
instances: [{account, port, is_running, code}]}`, `version` being the
release installed. An apply refuses `account_invalid`,
`account_duplicate` and `secret_missing`, each naming the `account`, and
`account_unknown {account}` for an account the machine does not have.

The `ssh_server` module runs the agent's own SSH server once per enabled
account ([agent/modules/ssh_server.md](agent/modules/ssh_server.md)). Like
Terminal and Remote desktop it is composed for every managed device, its
`want` `running` while it enables an account and `stopped` while it enables
none, and its recipe is `{runner: ssh_server, method: agent, params: {}}`.
Its configuration is `{instances: [{account, authorized_key, shell_path,
password}]}` and its `details` `{host_key, host_key_fingerprint, instances:
[{account, port, is_running, code}]}`; the module's page has its refusals.

The `gitea` module runs Gitea on Linux, macOS and Windows ([agent/modules/gitea.md](agent/modules/gitea.md)). Its configuration is `{listen_port, root_url,
is_registration_enabled, address, secrets, ssh_port}` on every system:
`ssh_port` is the `local_port` of the Gitea app's `ssh` entry ("The local
name and the local port"), which Gitea writes into the clone addresses it
shows beside `127.0.0.1`. Its recipe names
the release binary of the version the machine runs, of kind `binary`, which
the cache recognises by the ELF, Mach-O or PE header and the agent opens
`package {module: gitea, artifact, digest}` for, and on Linux the package
`git` in `packages`. `details` is
`{is_running, port, ssh_listen_port, url, version, admins}`, `ssh_listen_port`
being the loopback port the agent took for Gitea's own SSH server. The server
listens on `127.0.0.1` alone, so its `web` and `ssh` entries are reached
through the agent's `connect` stream ("The connect stream"). On macOS and Windows an install
and an apply refuse `gitea_git_missing` while the machine has no usable
`git`, and an install on macOS refuses `user_create_failed {user, detail}`
when the system will not make the server's account.

The `podman` module runs the declared containers on Linux, Windows and
macOS ([agent/modules/containers.md](agent/modules/containers.md)). Its
configuration is `{containers, hub_containers, mirrors, machine}`.
`hub_containers` is the list the hub composes from the `container` modules,
each `{module, name, image, ports, volumes, environment, command,
is_autostart, services, source_sets, after, page_port, stop_timeout_s}` with
`image` as `{digest, sources}`, and empty while no such module is installed:
`source_sets` names the sets whose fastest source the agent writes into the
container's environment, `after` the module's containers it starts after,
`page_port` the container port the module's forwarder serves, and
`stop_timeout_s` the seconds its stop waits before SIGKILL, 10 when absent
([agent/modules/containers.md](agent/modules/containers.md), "Hub
containers"). Each container is
`{name, image, ports, volumes, environment, command, is_autostart,
services}`, and `services` is a list of `{port, kind, scheme, protocols}`
per host port: `kind` `auto`, `web` or `port`, `scheme` `http` or `https`
for `web`, and `protocols` a list of `tcp` and `udp` for `port`; a host
port the list does not name is `auto`. `machine` is the Run settings,
`{account, cpus, memory_gib, disk_gib}`, a 0 being the default except
a Windows `disk_gib`, which is 1 or more, `account` an available account,
with `password`, that account's login, added for a Windows machine. The hub sends `machine` to a Windows or macOS machine
alone, and a Linux state never names it. The Linux recipe's runner is
`podman` and its method `system`; the Windows and macOS recipe's runner is
`podman_machine` and its method `hub`:

```json
"podman": {
  "want": "running",
  "config": {"containers": ["..."], "hub_containers": [], "mirrors": [], "machine": {"account": "lab", "cpus": 0, "memory_gib": 0, "disk_gib": 0, "password": "..."}},
  "install": {"runner": "podman_machine", "method": "hub", "params": {"version": "6.1.4", "artifacts": [{"name": "wsl", "kind": "msi", "directory": "wsl", "digest": "sha256:..."}, {"name": "podman", "kind": "msi", "directory": "podman", "digest": "sha256:..."}, {"name": "image", "kind": "tar_zst", "directory": "image", "digest": "sha256:..."}], "packages": [], "verify": "\"C:\\Program Files\\Podman\\podman.exe\" --version", "uninstall": {"post_uninstall": [], "is_data_kept": true}}}
}
```

The macOS recipe names two artifacts, `podman` of kind `pkg` and `image` of
kind `raw_zst`, and the `verify` `/opt/podman/bin/podman --version`; its
entry's `min_version` is `13`, and the Windows entry's `19041`. The agent
opens `package {module: podman, artifact, digest}` for each. On Windows and macOS `details` adds
`machine`, `{account, is_running, cpus, memory_gib, disk_gib,
default_memory_gib}`, what the machine reports through the agent's read
(`podman info`), `disk_gib` the size of its disk now, and
`default_memory_gib` the memory a 0 in the Run settings gives on the
computer.

An apply refuses `service_invalid {name, port}` for a service whose port
the container does not publish, whose `kind`, `scheme` or protocol is
unknown, or whose port appears twice, and `service_protocol_none {port}`
for a `port` service with no protocol checked. On Windows and macOS it also refuses
`machine_account_missing`, `machine_cpus_invalid {cpus, max}`,
`machine_memory_invalid {memory_gib, max}`, `machine_disk_shrink {disk_gib,
current_gib}`, `volume_not_shared {name, volume}` and `account_unknown
{account}`, and on Windows `machine_disk_invalid {disk_gib}` for a disk
limit of 0, `credential_missing {account}`, `credential_invalid {account}`
as VS Code's does, and `udp_not_forwarded {name, port}` for a port
published on UDP. An install ends
`windows_feature_failed {feature, exit_code}` or `podman_install_failed
{artifact, exit_code}`; the machine's own steps fail with
`machine_image_missing`, `machine_init_failed {detail}`,
`machine_set_failed {detail}` and `machine_unreachable {detail}`. `machine`,
its `default_memory_gib`, `services`, `detected`, `hub_containers`, each
reported container's `module` and the code on an `installing` row are added
fields and keep `PROTOCOL`. The recipe's shape, `{runner, method, params}`, and each
module's `version` in the report come with 0.6.0, which no released agent
read before, and keep `PROTOCOL` 4 ("Versioning").

A `container` module's recipe is `{runner: container, method: container,
params: {version, artifacts, source_sets}}`, each artifact of kind `image`
with its `digest` and `sources`, `source_sets` the sets its containers
fetch from, and no `verify`
([agent/module_install.md](agent/module_install.md), "From container
images"). The agent installs it by choosing a source for each image and
pulling `<source>@<digest>` with Containers' Podman, and ends an install no
source serves `download_failed {file, sources}`; it reads the module
`running` while every hub container with its label runs. Its uninstall
removes those containers, their units, the network `neutrino_<module>`, the
images and the named volumes `neutrino_<module>_<volume>`.

The `hermes_webui` module runs Hermes WebUI as two hub containers, the
agent's gateway and the webui ([agent/modules/hermes_webui.md](agent/modules/hermes_webui.md)).
Its configuration is `{secret, password, cookie_name, local_name}`: the
token secret; the webui's password; the name of the webui's login cookie,
`hermes_session_` and the first 12 characters of the device id, which the hub
also sets in the webui's environment; and the app's local name, which its
forwarder checks the `Host` against. The agent takes the forwarder's port
itself, from 8787 up. The hub generates both secrets the first time the
module is installed, keeps them sealed in
`config/devices/<id>/hermes_webui.json` beside the module's gateway key, and
sends them opened inside the state, as it sends CloudCLI's. Its manifest
names two `image` artifacts, `webui` and `agent`, no `releases`, and
`source_sets: ["pypi"]`. It reads `running` while both containers run and
the webui's `/health` returns 200, and `installing` from the install, or a
version change, until the first such read. `details` is `{version, port}`,
`port` the forwarder's.

The `ayakaleaf` module runs Ayakaleaf as three hub containers, the app,
MongoDB and Redis ([agent/modules/ayakaleaf.md](agent/modules/ayakaleaf.md)).
Its configuration is `{secret, password, cookie_name, local_name, guests}`:
the token secret; the password of the administrator the module makes; the
name of the app's session cookie, `ayakaleaf_sid_` and the first 12
characters of the device id, which the hub also sets in the app's
`COOKIE_NAME`; the app's local name; and `guests`, `[{account, email,
password, secret}]`, the guest account of each live Web share of the app,
opened from the share's record ([agent/modules/ayakaleaf.md](agent/modules/ayakaleaf.md),
"The guest account"). The agent takes the forwarder's port itself, from 8900 up. The
hub generates the secret, the password and the app's session and invitation
secrets the first time the module is installed, keeps them sealed in
`config/devices/<id>/ayakaleaf.json` beside the module's gateway key and the
tab's `model`, and sends the first two opened inside the state and the other
two in the app's environment. Its manifest names three `image` artifacts,
`app`, `mongo` and `redis`, one `oci` feed in `releases`, `source_sets:
["ctan"]` and `is_data_forward_only`. It reads `running` while the three
containers run and the app's `/status` returns 200, and `installing` from the
install, or a version change, until its first start's steps are done and the
first such read; a step that fails ends the install `ayakaleaf_setup_failed
{step, detail}`. `details` is `{version, port, guests}`, `port` the
forwarder's and `guests` `[{account, code, params}]`, each guest the hooks
made or tried, `code` empty once made and `ayakaleaf_guest_failed {step,
detail}` while a step fails; a Web share of the app reads its state from it
("Web shares").

Package bytes come to the agent down a `package {module, artifact, digest}`
stream it opens, `artifact` naming the artifact and `digest` the bytes
wanted, the same stream that serves its own upgrade. A package asked
for before the device's first report of the connection waits for that
report, up to 15 seconds, since the report carries the platform that names
the file; only then is it refused. An agent older than the hub whose own
package was refused that way is sent `reinstall` once on that connection,
when the report naming its platform lands; the agent on the hub's own
machine is left to the hub's update, which installs it. cc-switch, which
the machine's AI tools run and no module installs, comes down the same
stream as `package
{module: cc_switch, artifact, digest}`: `data/manifests/cc_switch.json` pins
it, says `is_module: false`, and so stays out of the catalog's modules. When
no source serves a file, the hub closes the stream `download_failed {file,
sources}` ([agent/module_install.md](agent/module_install.md), "Choosing a
source"). Every task's output goes up a `log {module}` stream line by
line, and the machine page shows it under the module's tab as it arrives.

### The account layer in the state

A module of the account layer runs one instance per enabled account
([agent.md](agent.md), "The two layers and the accounts"). The hub composes
its `config` from the machine's available accounts,
`config/devices/<id>/accounts.json`, and the module's own file, which holds
the enabled accounts in the order the person enabled them and the secrets
the hub generated for each, sealed under the vault's data key:

| Module | `config/devices/<id>/<module>.json` | The module's `config` in the state |
| --- | --- | --- |
| `terminal` | `{accounts: [{account}]}` | `{accounts: [{account, shell_path, password}]}` |
| `samba` | `{accounts: [{account, password_sealed}], shares}`, `shares` the folder shares in the order they were added, each `{name, path, accounts}`, `accounts` the enabled accounts checked for it | `{shares, users, passwords}`: for each enabled account a Home share `{name: <account>, path, comment: "", is_read_only: false, valid_users: [<user>], force_user: <account>}`, its user's name in `users`, and `passwords`, `{<user>: <password>}`, the user being the account's SMB user `neutrino-<account>` ([agent.md](agent.md), "The file share's accounts"), and `force_user` the account the share's files are written as on Linux; then each folder share `{name, path, comment: "", is_read_only: false, valid_users}`, `valid_users` the SMB users of its accounts in their order and empty when it has none, with no `force_user`, its files being written as the connected user's account through the per-user include ([agent/modules/file_share.md](agent/modules/file_share.md)); the agent sets each user's password from `passwords` at every apply whose password differs, in place of the `set_password` verb of 0.5 |
| `vscode` | `{terms_accepted_at, accounts: [{account, token_sealed}]}` | `{address, instances: [{account, token, password}]}` |
| `code_server` | `{accounts: [{account, secret_sealed}]}` | `{instances: [{account, secret, local_name, cookie_name}]}` |
| `cloudcli` | `{accounts: [{account, web_password_sealed, token_secret_sealed}]}` | `{instances: [{account, web_password, token_secret, password, local_name, cookie_name}]}`, `token_secret` being the secret its tokens are minted from |
| `codeg` | `{accounts: [{account, secret_sealed}]}` | `{instances: [{account, secret, password, local_name, cookie_name}]}` |
| `siyuan` | `{accounts: [{account, secret_sealed, access_code_sealed, gateway_key_sealed}]}`, `gateway_key_sealed` present while the account is enabled | `{instances: [{account, secret, access_code, gateway_key, password, local_name, cookie_name}], gateway_url, models}` |
| `ssh_server` | `{accounts: [{account, private_key_sealed}]}` | `{instances: [{account, authorized_key, shell_path, password}]}`, `authorized_key` the public half of the sealed key |

| Rule | Reason |
| --- | --- |
| The share's `path` is the account row's `share_path`, and the hub writes the account's `home` from the machine's `account_details` for an empty one. An enabled account whose `share_path` is empty while the machine reports an empty `home` for it is left out of `shares`, `users` and `passwords` until a report brings its home, and its row on the module's page carries `account_home_unknown {account}`; the hub composes no path from a home it has not been told. `shell_path` goes as the row holds it, and the agent starts the account's login shell, PowerShell on Windows, for an empty one. `password` is the account's login, sent to a Windows machine alone. | One form per account holds them ("The two layers and the accounts" there), and each side fills in the default it knows. An account that never signed in on Windows has no profile folder; a folder the hub makes under the expected name first makes Windows put the profile beside it under another name. |
| The hub generates a module's secret for an account the first time that account is enabled, and keeps it when the account is disabled and enabled again; removing the available account deletes it. SiYuan's gateway key alone is voided when the account is disabled, and a new one is generated when it is enabled again. | A browser's login, a mounted share's password and a key a client wrote stay valid across a toggle. |
| Every instance with a forwarder in front of it, code-server's, CloudCLI's, Codeg's and SiYuan's, also carries `local_name`, its app's, and `cookie_name`, its entry's, `neutrino_` and the first 12 hex characters of the SHA-256 of the entry's id ([agent/module_template.md](agent/module_template.md), "The run"); the Hermes WebUI and Ayakaleaf modules carry `local_name` beside their own `cookie_name`. | The forwarder accepts a `Host` of `127.0.0.1`, `[::1]`, `localhost` or `local_name`, and names its login cookie `cookie_name`. |
| No instance names a port. The agent takes a free port on `127.0.0.1` for each instance at its first start, from the module's base port in its `constants.py` up, keeps it in the instance's root-only record under its state root, across a disable and an enable, and reports it in `details`, the port a `connect` reaches, the forwarder's where the module has one; the hub publishes the entry at the reported port. A kept port another program holds at a start is replaced by the next free one and reported. | A port the person never sees needs no field, and the machine is the one that knows which ports are free. |
| An account that is not available, or is not one the machine reports, is not composed into any module; the agent's own `validate` refuses an account the machine does not have with `account_unknown {account}`. | A module never starts a process for an account the machine page does not list. |

The `ai_tools` section is the same layer's: it names the available accounts
whose switch is on ("The sections").

### The services section, one entry per published service

The `services` section is the typed list a client is sent, and `type` decides
what the entry's `payload` names:

| `type` | `payload` | An entry is in the list while |
| --- | --- | --- |
| `web` | `{url, is_token_required}`, `is_token_required` present and true only on a VS Code, code-server, CloudCLI, Codeg or SiYuan instance and on Hermes WebUI and Ayakaleaf, whose page opens with a token the `service` frame hands | a device's Gitea module reports a URL, a device's VS Code, code-server, CloudCLI, Codeg or SiYuan module runs an instance, a device's Hermes WebUI or Ayakaleaf module reads `running`, a device's Podman container publishes a TCP port whose service is web, chosen or detected (`http` or `https` under `auto`), with `url` `<scheme>://<host>:<port>/`, or a declared app names a `web` entry |
| `port` | `{host, port, protocol}`, `protocol` being `tcp` or `udp`, `tcp` when absent. One entry has one protocol, so a number published on both is two entries | a device's Podman container publishes a host port whose service is port, chosen or under `auto` on a TCP binding detected `tcp` or not yet detected and on every UDP binding, one entry for each item of its `host_bindings` (a report with no `host_bindings`, from an agent before 0.5.0, gives each `host_ports` number as `tcp`), or a declared app names a `port` entry |
| `ssh` | `{host, port, account, host_key_fingerprint, account_key_fingerprint}`: `port` the loopback port the account's instance of the machine's SSH server listens on, `account` the account it runs as, `host_key_fingerprint` the machine's host key and `account_key_fingerprint` the account's key the hub made, each as `SHA256:<base64>` | a device's SSH server module enables that account ([agent/modules/ssh_server.md](agent/modules/ssh_server.md)); the hub lists a machine's `ssh` entries in the order the module enables the accounts |
| `ai` | `{endpoint, protocol, models}`, `protocol` being `openai` | the AI gateway is installed and enabled |
| `file` | `{protocol, host, share, users, account}`, `protocol` being `smb`; `users` is `[<user>]`, the SMB user the entry logs in as, and empty on a declared app's entry; `account` is the account a folder share's entry logs in as, and empty on a Home share's entry, whose share has the account's name, and on a declared app's | a device's Samba module reports the share, one entry for a Home share and one for each account of a folder share, or a declared app names a `file` entry |
| `rdp` | `{protocol, host, port, attention, platform_os}`, `protocol` being `rustdesk`, `platform_os` the sharing machine's `linux`, `windows` or `darwin` | a machine keeps reporting that it shares its desktop; `attention` is what somebody must do at that machine before a peer sees the desktop, as a code, empty when nothing is in the way and always empty from a Mac |

The six types are closed, `SERVICES_TYPES` in
`modules/services/constants.py`; a seventh is a row here in the same change.
The `ai` entry's id is `ai` on every hub, an `rdp` entry's `rdp_<device id>`
of the machine sharing its desktop, and a Home share's `file` entry's
`samba_<device id>_<share>`; each is its row's id in a permission
(`/api/hub/client`). A folder share's entries are
`samba_folder_<device id>_<share>_<account>`, one per account checked for
it, and their one row in a permission is the folder share's id,
`samba_folder_<device id>_<share>`. Two entries of one machine never have
one id: a folder share whose entry would take another's id is refused
("`/api/agent/module`").
Every `host`, `port`, `url` and `endpoint` in a payload is where the
service is on the hub's networks, resolved for the client's scope ("The
address a caller is given"). A client shows it to the person and dials none
of it: every byte to a service goes over a `connect` stream.
`source` is `module`, `declared` or `device`. `is_healthy` is the module's own
health, the declared app's last probe of that entry, or true for a share a
machine is reporting now, and empty on an entry no probe has reached. A UDP
entry of a declared app is never probed, so its health stays empty. Only
`false` is unhealthy: an entry with empty health carries no health word and
keeps its actions ([client.md](client.md), "The button rule"). A Gitea entry
is healthy while its machine reports the server running, and the hub dials
nothing on the machine to judge it. A container's entry, `web` or `port` on
either protocol, is healthy while the container runs, and a container's TCP
binding is a `web` entry or a `port` entry, never both
([agent/modules/containers.md](agent/modules/containers.md), "Services of
a container"). An `ssh` entry is healthy while its machine reports the
instance running, and is listed while the account is enabled, so a client
keeps its key and its configuration across a restart of the instance. A
client shows a payload's `port` and forwards at `local_port`; it dials
neither.

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
| `codeg_module` | `{host, account}`; the same |
| `siyuan_module` | `{host, account}`; the same |
| `hermes_webui_module` | `{host}`; the entry exists only while the device reports the module `running` |
| `ayakaleaf_module` | `{host}`; the same |
| `ssh_server_module` | `{host, account}`; the entry exists while the module enables the account |

A declared app whose person wrote a line of their own gets that line on each
of its entries and an empty `description_code`, because those are already
their words.

`device_name` is what the hub calls the machine that provides the entry: the
device's name for an entry a device hosts, the hub's own hostname for one of
the hub's modules, the device at that address for a declared app, and
empty when no machine the hub knows is there; the client then shows the
entry's address in its place.

`device_id` is the id of the managed machine that provides the entry, for an
entry whose `source` is `module` or `device` and that a machine hosts, and
empty for a declared app and for the hub's own gateway. A client keys what
it keeps per machine by it, since a name changes and an address depends on
the way the hub was reached.

`is_own_machine` is true when the machine that provides the entry is the
machine the client runs on: the `os_machine_id` of the client's last report
equals the provider's `machine_id`, which is the device's, as its agent
reported it, for an entry a device hosts or a declared app at a device's
address, and the hub box's own for one of the hub's modules. It is false
when either id is empty or no machine the hub knows provides the entry.

### Apps

An app is what a person uses as one thing: one program on one machine, with
one or more entries. Every `web`, `port` and `ssh` entry belongs to exactly
one app and carries three fields more: `app_id`, the app's id; `name`, the
entry's name inside its app; and `local_port`, the port a client forwards it
on ("The local name and the local port"). An entry's `id` is
`<app id>_<name>`. A declared app's `file` entry belongs to its app too and
carries no `local_port`. The `ai` and `rdp` entries and a machine's `file`
entries belong to no app. The
client's `apps` section lists the apps its entries name, each `{id, title,
source, device_id, device_name, local_name}`:

| The app | `id` | `title` | `source` | Its entries, by `name` |
| --- | --- | --- | --- | --- |
| an instance of VS Code, code-server, CloudCLI, Codeg or SiYuan | `<module>_<device id>_<account>` | `<module title> (<account>)` | `module` | `web` |
| Gitea | `gitea_<device id>` | `Gitea` | `module` | `web`, and `ssh`, a TCP `port` entry for Gitea's own SSH server ([agent/modules/gitea.md](agent/modules/gitea.md)) |
| the SSH server | `ssh_server_<device id>` | `SSH` | `module` | one `ssh` entry per account the module enables, named by its account |
| a container module, Hermes WebUI and Ayakaleaf among them | `<module>_<device id>` | the module's title | `module` | `web`, its forwarder's page, and for every other port its containers publish `<port>`, or `<port>_udp` for a UDP one |
| a container the Containers module declares | `podman_<device id>_<container>` | the container's name | `declared` | `<port>`, or `<port>_udp` for a UDP one |
| a container a person started by hand | `podman_<device id>_<container>` | the container's name | `manual` | the same |
| an app declared on the Services page | the declaration's `id` | its `name` | `declared` | `web_<port>` for a `web` entry, `port_<port>` for a TCP `port` entry, `port_<port>_udp` for a UDP one, `file_<slug of the share>` for a `file` entry |

| Rule | Reason |
| --- | --- |
| A module the hub manages is one app however many containers it runs, and its source is `module`. A container the hub does not manage is one app of its own, `declared` when the Containers module's configuration names it and `manual` when a person started it by hand, the owners the Containers tab's chips name ([agent/modules/containers.md](agent/modules/containers.md), "Hub containers"). | The person thinks of Hermes WebUI as one thing and of each container they run as one thing, and the chip says who answers for it. |
| An app's entries are in the list only while the client's permission allows them, by kind and machine or by the app's own row (`/api/hub/client`); an app none of whose entries is allowed is not in `apps`. | One judging function decides every entry, an app's as any other. |
| The SSH server is in `apps` and on no page: no client's Apps page and not the panel's Services page shows its row or an `ssh` entry. Its row gives the `ssh` entries their ids and their local ports, and gives a desktop client the machine part of the host its SSH configuration names ([client.md](client.md), "SSH for other programs"). | The SSH server is a function of every machine, as the terminal and the remote desktop are, used by the programs on a desktop that speak SSH; a phone reaches a shell on its Terminals page. |
| A declared app's `file` entry is mounted on the Files page as a machine's share is, at a port the client picks, and with the login the person types there ([client.md](client.md), "The Files page"). The hub generates no password for it. | A NAS's share has its own users, which the hub neither makes nor knows. |
| `app_id` and `name` are added fields and keep `PROTOCOL`; `apps` is an added section. | A reader that predates them reads each entry as before. |

### The local name and the local port

Each app has a local name and each entry a local port, the same on every
client of the hub, so an address a person saves or a program writes into its
own configuration holds on every client. The hub computes both and sends
them; a client takes them as given and computes neither.

```text
local_name(app) = slug(app title) + "." + slug(machine name) + ".localhost"
slug(text)      = text in lowercase, each run of characters other than a to z and 0 to 9
                  turned into one "-", "-" taken off both ends, cut to 63 characters,
                  and "app" or "machine" when nothing is left
local_port(id)  = 24000 + (the first four bytes of SHA-256 of the entry id in UTF-8,
                  read as a big-endian unsigned integer) mod 8000
```

The machine name is the entry's `device_name`, or the hub's own name for an
entry no machine the hub knows provides. Two machines of one hub whose names
give one slug each take `-` and the first six hex characters of its device
id after it, and so do two apps of one machine. `local_port` lies in 24000
to 31999.

| Rule | Reason |
| --- | --- |
| The port follows from the entry's id alone. Two entries of one protocol whose ports collide keep the same number from the hub. | Every client, and Gitea's own configuration, compute the same number without asking anybody. |
| The range, 24000 to 31999, lies below the ports every system hands outgoing connections, 32768 up on Linux and 49152 up on Windows and macOS, and above the picks of the forwards of no app, 20000 to 23999 ([client.md](client.md), "The local port table"). | A port the system has handed an outgoing connection is taken for that connection's life, so a fixed port inside that range fails now and then for no reason the person can see. |
| A client never moves a port by itself. The entry forwarded first holds a number its two entries share, and the other's forward fails `port_taken {port}`; a number another program holds fails the same way. The person then gives one of them a number of their own in **Configure** ([client.md](client.md), "The local port table"). | A port moved silently on one client breaks a saved address, a clone address or a tool's setting there alone. |
| A number the person sets holds on that client alone, kept in its local port table. | The derived number is the default every client shares, and a change is that client's own business. |
| A device's rename changes its apps' local names and none of their ports. | The name is what a person reads; the port is what a program keeps. |

### The kinds

The kind table is the one extension point of the channel. A module or a verb
is added without a change to the protocol; a kind is added by a row here.
"Relayed" names a stream whose bytes the hub's transport carries between two
streams of its own after the hub's Python answered the open
([transport.md](transport.md), "The local channel"), and "handed" one that
the transport gives whole to the Python on its side.

| Opened by | `kind` | Arguments and result |
| --- | --- | --- |
| a peer, to the hub | `control` | `{}`: the session's first stream and its only control stream ("The control stream") |
| hub, to an agent | `shell` | `{cols, rows, account}`, the shell running as `account`, an enabled account of the Terminal module, the first one when `account` is empty, with that account's shell; refused `terminal_account_missing` while the module enables none, `account_not_enabled {account}`, `account_unknown {account}` or `shell_program_unusable {path}` when the machine cannot; with `{module: podman, container}` added for a container's shell, which the module does not touch, and which on Windows and macOS the agent starts as `podman exec -it` through the Podman machine's read URL with the account's machine key, on the pseudo console or pseudo-terminal a shell takes ([agent/modules/containers.md](agent/modules/containers.md), "Reads and writes"), and whose every process in the container the agent ends once the shell exits or the stream closes ([agent/modules/containers.md](agent/modules/containers.md), "A container's shell"), or `{session_id, is_resumed, owner, is_shared}` for a shell the agent keeps: `session_id` names the session and is generated by whoever opened the shell; an id the machine holds attaches to that session beside every stream already attached to it, and its kept output is sent first; `is_resumed: true` asks only for a session the machine holds, refused `session_unknown {session_id}` otherwise; `owner` is the hub's stamp, which the agent keeps as given and reports; `is_shared`, false when absent, says whether a new session starts shared; a shell opened without an id ends with its stream. Terminal bytes both ways as `data`, a later size as `resize`; closed with `params: {exit_code}` once the shell ends, or empty when the stream closed on a shell that runs on. On the agent the transport hands it to the agent's Python, which holds the pseudo-terminal |
| hub, to an agent | `exec` | `{argv, is_tty, cols, rows, account}`: one run of `argv`, a list of strings run as given with no shell between, as `account`, chosen as a `shell`'s is; never kept, and no `session_id`. Without `is_tty` the process's stdin, stdout and stderr are pipes: its stdout goes down as `data`, its stderr as `stderr`, the `data` up is its stdin, and `eof` closes its stdin; with `is_tty` it runs on a pseudo-terminal of `cols` by `rows` as a shell does. Closed with `params: {exit_code}` once the process ended and its output is sent; refused as a `shell` is, and `shell_program_unusable {path}` when `argv` is empty or its program cannot be found or run. Handed to the agent's Python, as a `shell` is. "The exec stream" has the rest |
| hub, to an agent | `file` | `{op: list, path}`: one directory listing, every path absolute in the machine's own form, for the panel's path window ([ui_behavior.md](ui_behavior.md), "Modals, and where a record's detail lives"). It closes with `params: {path, separator, entries}`, `separator` being `\` on Windows and `/` elsewhere and each entry `{name, path, kind, size, modified_at, mode}`; on Windows a `list` of `/` or of no path closes with `path` `/` and one `dir` entry per drive, named `C:` with `path` `C:\`. Any other `op` is closed `op_unknown {op}`. Opened by the hub's Python and handed to the agent's |
| agent, to the hub | `log` | `{module}`: opened for every task of the module, one line `step <i>/<n>: <name> <params>` at each step's start and the step's output line by line, up as `data`, closed with `params: {state}`, and with the failure's code and params when the task failed; the hub's task for it then ends with the `exit_code` those params name, else 1. Handed to the hub's Python |
| hub, to an agent | `command` | `{module, verb, ...args}`: `{agent, reboot}`, `{samba, reload}`, `{podman, validate, config}`; an unknown module is closed `kind_unknown` and an unknown verb `verb_unknown`, which the panel shows as `unsupported`; closed with `params: {exit_code, output, result}`. Opened by the hub's Python and handed to the agent's |
| agent, to the hub | `package` | `{module, artifact, digest}` for one artifact of a module, or of cc-switch, from the hub's cache, `{}` for the agent's own package; the bytes come down as `data`, and the close's `params` has the `sha256` of the bytes sent and `name`, the file's own name as its release gave it, with no directory. Handed to the hub's Python |
| client, to the hub | `shell` | `{device_id, cols, rows, account, session_id, is_resumed, is_shared}`: a shell on a managed machine, which the hub opens as the agent's own `shell` with the same `account`, `session_id`, `is_resumed` and `is_shared`, stamped `owner: client:<id>`; relayed, records unchanged both ways; closed with `params: {exit_code}`, or refused `binding_unknown`, `client_disabled`, `permission_denied {kind: terminal}` (its permission does not allow `terminal` on the machine), `session_not_owned {session_id}` (a session another viewer owns and has not shared) or `agent_offline {device}` before any agent stream opens; closed with the agent's refusal, `terminal_account_missing`, `account_not_enabled {account}`, `account_unknown {account}` or `shell_program_unusable {path}` among them; closed `session_not_owned {session_id}` when the owner stops sharing the session |
| client, to the hub | `exec` | `{device_id, argv, is_tty, cols, rows, account}`: one command on a managed machine, which the hub opens as the agent's own `exec` with the same `argv`, `is_tty`, `cols`, `rows` and `account`; relayed, records unchanged both ways, the client's `eof` included; no `session_id`, and no `owner` stamped; closed with the agent's `params: {exit_code}`, or refused `binding_unknown`, `client_disabled`, `permission_denied {kind: terminal}` (its permission does not allow `terminal` on the machine) or `agent_offline {device}` before any agent stream opens; closed with the agent's refusal |
| client, to the hub | `connect` | `{id}`, one published entry by the id a `service` frame takes, or `{is_panel: true}`, the hub's own panel: one TCP connection to that service, or every datagram of one UDP `port` entry. Relayed to an agent's `connect`, or dialled by the hub's transport itself; closed with a refusal's code before its `accept`. "The connect stream" has the checks, the far ends and the codes |
| agent, to the hub | `connect` | `{id: ai}`, the `ai` entry's id, as a client's AI forward opens it: one TCP connection from the machine's AI tools, opened for each connection the agent's AI gateway forward accepts ([agent.md](agent.md), "The AI gateway forward"); the hub's transport dials the gateway on `127.0.0.1` at its `listen_port` and relays the bytes; refused `service_unknown {service_id}` for any other `id`, and `permission_denied {kind: ai}` while that machine's AI tools setting is off and no module that uses the gateway, a container module or SiYuan, is installed there; no `connect_limit` holds on an agent's session; `connect_failed {reason}` when the dial fails |
| hub, to an agent | `connect` | `{port, protocol}`, `protocol` being `tcp` or `udp` and `tcp` when absent: one TCP connection to `127.0.0.1:<port>` on the machine, or every datagram of one UDP entry to that port, a port the machine publishes now on that protocol; the agent's transport asks the agent's Python whether the port is published and dials it itself; refused `port_not_published {port}` for any other port or protocol, `connect_failed {reason}` when the dial fails |

Installing and uninstalling are no kind and no verb: they follow from `want`.

### The verbs on a `command` stream

| `module` | Verbs |
| --- | --- |
| `agent` | `reboot`, `shutdown`, `reinstall`, `kill {pid}`, `remote_desktop_read`, `remote_desktop_password_set`; the HTTP routes `process/kill`, `remote_desktop` and `remote_desktop/password/set` map onto `kill` and the two remote desktop verbs |
| `gitea`, `podman` | the module's own, spelled without a module prefix because the `module` field is the prefix: `admin` and `password` on `gitea`, `control` and `journal {name}` on `podman` |

Two verbs every module answers: `validate`, as `command {module: <name>,
verb: validate, config}`, checks a configuration before it is saved, `config`
being the module's section as the state will carry it, composed by the same
step (Samba's with the networks its shares answer, Gitea's with its address
and secrets, the tokens and logins of VS Code, code-server, CloudCLI, Codeg
and SiYuan opened, SiYuan's gateway keys among them); and
`journal`, as `command {module: <name>, verb: journal, lines}`, closes with
the tail of the module's log in `output`: the units' journal on Linux, merged
by time when the module runs as more than one unit, and the module's own
sources with the agent's lines on Windows and macOS; it answers while an
apply runs. On `podman`, a `journal` naming a
container is that container's; one naming none is the module's own.

### Kept shells

A terminal's first size is in its `open`, and a later size is a `resize`
record on the same stream, applied at once; on an `exec` stream opened
without `is_tty` a `resize` is dropped. `persist` and `stop_session` are
frames on the control stream ("The control stream"): the hub sends each to
the machine holding the session, the one this client's open `shell` names for
the id or else the online machine whose report lists it, and the agent
answers with `reply`. `persist` sets whether a session stays when its last
stream closes, `is_persistent`, and whether every viewer with terminal
rights on the machine can attach to it, `is_shared`; a flag the frame leaves
out keeps its value. `stop_session` ends a session. Both are answered
`session_unknown {session_id}` for a session the machine does not hold, and
a client's `persist` on a session the machine reports under another owner is
answered `session_not_owned {session_id}`, with the `shell` stream's
permission refusals for that machine.

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
ends it, and every attached stream closes with the exit code. Every system
answers both frames. The sessions are the agent process's own, so an agent
restart or upgrade ends every one.

### The service frame

A `service` frame names one published entry by `id`, or the panel by
`is_panel: true`, and the hub judges it for that client at that moment: the
hub's transport asks the hub's Python whether the material is given
([transport.md](transport.md), "The local channel") and sends the answer as
the `reply` of the same `request`. The checks run in the order below and the
first that fails gives the reply its code; the panel's are
`binding_unknown`, `client_disabled` and `permission_denied {kind: panel}`:

| `code` | Given when |
| --- | --- |
| `binding_unknown` | no client row has the id this session is bound to |
| `client_disabled` | that row is switched off on the Clients page |
| `service_unknown` | the id names no entry in the list resolved for this client |
| `permission_denied` | the client's permission does not allow the entry: `is_permitted` refuses its type, its device and its row (`/api/hub/client`) |
| `rdp_not_shared` | the entry is an `rdp` one and its machine has stopped reporting the share |
| `vault_locked` | the entry is the `ai` one and the vault is locked, so this client's gateway key cannot be opened or generated; or it is a VS Code instance whose token does not open, a code-server, CloudCLI, Codeg or SiYuan instance, Hermes WebUI or Ayakaleaf whose secret does not open, an `ssh` entry whose key does not open, or a `file` entry whose password does not open |
| `control_unavailable` | the hub's Python did not answer the transport within `ControlQuestionTimeout` |

`service_unknown` and `rdp_not_shared` put the id in `params` as
`service_id`, `permission_denied` puts the entry's type in `params` as
`kind`, the transport's `control_unavailable` puts 5 in `params` as
`retry_after_s`, and the other three send empty params. A reply with no
code makes `params` the material, and what the material is follows from the
type:

| `type` | The material |
| --- | --- |
| `rdp` | `{password}`: the seat password of the machine sharing the desktop |
| `ai` | `{api_key, model}`: this client's own gateway key, which the gateway checks on every request, and the first model the gateway serves |
| `web` with `description_code` `vscode_module` | `{token}`: the instance's connection token |
| `web` with `description_code` `code_server_module`, `cloudcli_module`, `codeg_module`, `siyuan_module`, `hermes_webui_module` or `ayakaleaf_module` | `{token}`: `base64url(expiry \|\| nonce \|\| HMAC-SHA256(secret, expiry \|\| nonce))`, minted by the hub for this answer alone with `expiry` 60 seconds ahead by the hub's clock and `secret` the instance's own, or the container module's ([agent/module_template.md](agent/module_template.md), "The run"); it works once, and the agent judges its expiry by the hub's time ("The control stream") |
| `ssh` | `{account, private_key, host_key}`: the private half of the key the hub made for that account on that machine, in OpenSSH form, and the machine's host public key in OpenSSH form, which the client writes into Neutrino's own known_hosts ([agent/modules/ssh_server.md](agent/modules/ssh_server.md), "Keys") |
| `file` of a device's Samba module | `{user, password}`: the SMB user of the entry's account, the Home share's own account or a folder share entry's `account`, and the password the hub generated for it ([agent.md](agent.md), "The file share's accounts"), which the client mounts with and asks the person nothing |
| `web` with no token, `port`, a declared `file` | empty: the entry's `payload` is already everything the client needs; a declared share's login is the person's, typed on the client |
| the panel, `{is_panel: true}` | `{token}`: a sign-in for one browser, minted for this answer alone, which the client opens at its panel forward's address with `?tkn=<token>` ("The panel ports") |

A Web share's visitor sends the `service` frame too, for the one entry its
share offers ("Web shares"), and its material follows from the entry's
`guest_login` ([agent/module_install.md](agent/module_install.md), "The
manifest"):

| `guest_login` | The material a visitor gets |
| --- | --- |
| `app`, a declared app's or a container's `web` entry | empty: the visitor signs in on the app's own page |
| `guest_account`, a module's `web` entry whose manifest names it | `{token}`: minted as for a client, `expiry` 60 seconds ahead and spent once, with `secret` the share's guest account's own, so the forwarder signs the visitor in as that account and never as the owner ([agent/module_template.md](agent/module_template.md), "The run") |
| `run_account`, a module's `web` entry whose manifest names it | the material a client gets for the entry above: VS Code's connection token, or a `{token}` minted with the instance's own secret or the container module's, so the visitor is signed in as the account the app runs as, as the owner's clients are |

A client opens every `web` entry with `is_token_required` at its forward's
own address with `?tkn=<token>` added ([client.md](client.md), "The Apps
page"), and never at the entry's address.

| Rule | Reason |
| --- | --- |
| A client writes a reply's material to no log, no report and no file but the one the material is for: a share's password into the mount's credentials for the one mount and nowhere after it, a key into the one file [client.md](client.md) names. The hub's Python and the transport log the entry's id and the code, never the params. | The material is the secret itself, and a log is read by more people than the entry admits. |
| A client asks for the material each time it uses it, a mount, a key it writes, a page it opens, and keeps none in its own state document. | A permission taken away on the **Clients** page ends the next use, not the one after a restart. |

### The connect stream

A `connect` stream carries the bytes of one TCP connection between a client
and one service the hub publishes, or the hub's own panel, or every datagram
of one UDP `port` entry. With it a client reaches every service through the
hub's agent port and dials nothing else. An agent opens one for each
connection its AI gateway forward accepts, and the hub joins it to the
gateway on `127.0.0.1` ([agent.md](agent.md), "The AI gateway forward"). A
client opens one stream per connection its local listener accepts, and one
stream for a UDP entry for as long as that entry is forwarded
([client.md](client.md), "The local port table").

The hub judges the `open` before it dials anything: the transport counts the
session's `connect` streams itself, and asks the hub's Python about the
entry ([transport.md](transport.md), "The local channel"). The checks are
the `service` frame's, in its order, with the stream limit among them;
`vault_locked` has no place, since a `connect` opens no secret. The first
check that fails closes the stream with its code:

| `code` | Given when |
| --- | --- |
| `connect_limit {limit}` | the session already holds `ConnectStreamsMax` open `connect` streams; the transport counts it before it asks |
| `binding_unknown` | no client row has the id this session is bound to |
| `client_disabled` | that row is switched off on the Clients page |
| `service_unknown {service_id}` | the id names no entry in the list resolved for this client |
| `permission_denied {kind}` | the client's permission does not allow the entry, or `panel` for the panel: `is_permitted` refuses its type, its device and its row (`/api/hub/client`) |
| `rdp_not_shared {service_id}` | the entry is an `rdp` one and its machine has stopped reporting the share |
| `control_unavailable` | the hub's Python did not answer the transport within `ControlQuestionTimeout` |

The far end follows from where the entry is, as the hub's Python names it,
and the hub's transport alone dials it:

| The entry | The hub connects the stream to |
| --- | --- |
| provided by a managed machine, `source` `module` or `device` | that machine's agent, with `connect {port, protocol}` on the agent's session; `agent_offline {device}` when the machine has no session, and the same code when its session ends under an open stream |
| a declared app's entry, `source` `declared` | the app's host at the entry's port, dialled by the hub's transport, since the hub is on the LAN of the machines it serves |
| the `ai` entry | the gateway on `127.0.0.1` at its `listen_port` |
| the panel | the panel's HTTP port on `127.0.0.1`, over plain HTTP; the panel's login guards it as on the LAN ("The panel ports") |

The port is the entry's own: a `web` entry's url port, 80 or 443 by its
scheme when the url names none; a `port` or `rdp` entry's `port`; 445 for a
`file` entry. A dial that fails closes the stream `connect_failed
{reason}`, `reason` being `refused`, `timeout` (after
`ConnectDialTimeout`) or `unreachable`. A stream to an agent closes with
whatever the agent closed it with, and its `accept` is passed to the client
as the client's.

The agent's end dials `127.0.0.1:<port>`, or the host address a container
port is published on when it names one, and only a port the machine
publishes at that moment on the stream's protocol ([agent.md](agent.md), "The
connect stream"); any other port, and a number published on the other
protocol alone, is refused `port_not_published {port}`. Gitea, VS Code and
every forwarder listen on `127.0.0.1` alone, so this dial is the one way a
client reaches them, and no module opens a port for them in the machine's
firewall.

| Concern | Rule |
| --- | --- |
| Bytes | After the `accept`, a TCP stream carries its connection's bytes raw, with no records, under yamux's window; the hub's transport copies each side to the other. |
| End | End of file on either end's socket ends the stream once everything read from that socket is sent. The side whose stream ends writes what it holds and closes its own socket. There is no half-close. |
| A dropped session | A client session that ends ends every `connect` stream on it, and the hub closes the far ends. |
| Transport | TCP for every entry, and UDP for a `port` entry whose `protocol` is `udp`. |

A UDP stream is the one stream of a UDP entry, and its rules differ from a
TCP stream's where a datagram differs from a byte stream:

| Concern | Rule |
| --- | --- |
| Record | One datagram is one `datagram` record: `<u16 source, big-endian><the datagram>`. `source` is the port the datagram left from on the client's machine, and towards the client it names the local program the reply is for. A record shorter than the two source bytes is dropped. The largest datagram, 65507 bytes, fits one record, so nothing is split or joined; a datagram of zero bytes is a record of two bytes and is carried. |
| No wait | A sender whose stream cannot take a record at once, its window being full, drops the datagram; it does not wait and keeps no queue. The hub's transport relays each record unchanged, source bytes included, and drops a record for a side that cannot take it. |
| Before the `accept` | A datagram waits in two places, and only until the stream's `accept`: the client holds what its program sends before the hub's `accept`, and the hub's transport holds what the client sends before the agent's `accept` on the agent's stream, at most `UdpHeldDatagramsMax`, 16, in each place, passing them on in order when it comes. More are dropped. When the agent refuses the open, what the hub held is dropped and the client's stream closes with the agent's code. |
| The far end | The agent's transport for a machine's port, the hub's transport for a declared record, keeps for the stream a table from `source` to one connected UDP socket to the target: `127.0.0.1`, the address a binding names, or the record's host. A datagram from a new `source` gets a socket; a reply goes into the stream with its socket's `source`. A source with no datagram either way for `UdpIdleTimeout` has its socket closed and is forgotten. A table holds at most `UdpSourcesMax` sources, and one more replaces the one idle the longest. |
| Errors | An error on a source's socket, a port the system reports unreachable or a send that fails, loses that datagram and nothing else, and the stream stays open. A first socket that cannot be opened at all closes the stream `connect_failed {reason}` with the TCP reasons. |
| End | The stream has no idle close. It ends when the client closes it, when the hub or the agent closes it with a code, `agent_offline`, `permission_denied` after a change on the Clients page or `port_not_published` once the port is no longer published, or with the client's session. It holds one of the session's `ConnectStreamsMax` streams while it is open. |

### The exec stream

An `exec` stream runs one command on a managed machine and carries its
input, its two outputs and its exit code. A client opens one for each
`nclient terminal exec` ([client.md](client.md), "The command line"),
and the hub opens the agent's own `exec` for it. It names no session:
it is never kept, never shared, never in a report's `sessions`, and ends
with its stream.

The hub judges the `open` before it opens anything on the agent, in this
order, and the first check that fails closes the stream with its code:

| `code` | Given when |
| --- | --- |
| `binding_unknown` | no client row has the id this session is bound to |
| `client_disabled` | that row is switched off on the Clients page |
| `permission_denied {kind: terminal}` | the client's permission does not allow `terminal` on the machine, its row being `terminal_<device id>` (`/api/hub/client`) |
| `agent_offline {device}` | the machine has no session, and the same code when its session ends under an open stream |
| `control_unavailable` | the hub's Python did not answer the transport within `ControlQuestionTimeout` |

The agent then judges what it runs, and the hub closes the client's stream
with the agent's code:

| `code` | Given when |
| --- | --- |
| `terminal_account_missing` | the Terminal module enables no account on the machine |
| `account_not_enabled {account}` | `account` names an account the Terminal module does not enable |
| `account_unknown {account}` | the account is not one the machine has |
| `shell_program_unusable {path}` | `argv` is empty or not a list of strings, `path` empty; or its first member cannot be found on the `PATH` the process gets, or cannot be run, `path` that member |

| Concern | Rule |
| --- | --- |
| Down | `data` records carry what the process wrote to stdout, and `stderr` records what it wrote to stderr. With `is_tty` every record is `data`, since a pseudo-terminal has one output. |
| Up | `data` records carry the process's stdin, written in the order received. |
| Order | Each output's bytes arrive in the order the process wrote them; records of the two interleave in the order the agent read them, and no order between them is kept. |
| End of input | One `eof` record after the last stdin record: the client sends it when its own stdin ends, the hub's transport relays it after every record before it, and the agent closes the process's stdin once it wrote them. A stdin record after `eof` is dropped. With `is_tty` the client sends none and the agent ignores one. |
| End | Once the process ended and both outputs reached end of file, the agent sends what it holds and closes `params: {exit_code}`: the process's code, or 128 plus the signal's number for a process a signal ended. The hub's transport relays the close to the client. |
| A closed stream | A client that closes its stream, or whose session ends, makes the hub close the agent's stream, and the agent kills the process and everything it started, as a shell's end does. |
| Size | `cols` and `rows` size the pseudo-terminal with `is_tty`, and a later size is a `resize` record ("Kept shells"); without `is_tty` they are ignored. |
| Account | `account`, an enabled account of the Terminal module, the first one when it is empty, as a new shell runs ([agent/modules/terminal.md](agent/modules/terminal.md)); never root or SYSTEM. The account's shell is not read, since `argv` names the program. |

### Web shares

A Web share offers one app's `web` entry to anyone who holds its link, in a
browser, for as long as the share lasts; a visitor installs nothing and is
no client. The Clients page makes and revokes shares
([ui_behavior.md](ui_behavior.md), "The Clients page"), the visitor's page
is [web_share.md](web_share.md), and its connection is the guest path
([transport.md](transport.md), "The guest path").

`config/clients/web_shares.json` holds `shares`, each `{id, name, app_id,
app_title, entry_id, device_id, module, created_at, expires_at,
ticket_sha256, ufrag, pwd_sealed, guest}`: `id` a uuid4 hex; `app_title`
the app's title when the share was made, which the list shows while the app
is not published; `device_id` the machine providing the entry and `module`
the module whose page it is, each empty where none is, which a share ends
with; `expires_at` Unix seconds, null for a share that
lasts until it is revoked; `ticket_sha256` the SHA-256 of the share's
ticket, which the hub keeps of it alone; `ufrag` in the clear and
`pwd_sealed`, the pwd sealed under the vault's data key, the share's pair
for the guest door; and `guest`,
`{account, email, password_sealed, secret_sealed}`, the share's account in
the app, for an entry whose `guest_login` is `guest_account` and absent for
any other ([agent/module_install.md](agent/module_install.md), "The
manifest").

Every `web` entry has a `guest_login`, so a share can offer the `web` entry
of any app: `guest_login` is `app` for a declared app's or a container's
`web` entry and the value the manifest's `web_share` names for a module's
([agent/module_install.md](agent/module_install.md), "The manifest"), and
an entry of another type has none. For `run_account` the entry's
`visitor_account` in `web_share_entries` is the account the app runs as: the
instance's account for code-server, VS Code, Codeg, CloudCLI and SiYuan, and
`hermeswebui`, the user its webui runs as, for Hermes WebUI, which runs as
no account of the machine ([agent/modules/hermes_webui.md](agent/modules/hermes_webui.md),
"The containers"). No share offers a
terminal, a file share, an SSH server, a remote desktop, a port, the AI
gateway or the panel; a file is shared as an app whose page serves it.

| State | The share is |
| --- | --- |
| `active` | admitting visitors: its entry is published and its machine has a session, and a guest account it needs is made |
| `preparing` | waiting for its machine to report its guest account made |
| `unavailable` | holding its link while its entry is not published or its machine has no session |
| `failed` | holding its link while its machine reports the guest account's failure, which `code` and `params` name |

`online_count` is the share's guest sessions open now, which the hub counts
from the transport's `session_open` and `session_end` events of role
`guest` ([transport.md](transport.md), "The hub's local channel"). A visitor
is no client: the hub keeps no row, no record and no address of one, and a
visitor's session ends with its page.

A visitor's `service` frame and `connect` stream are judged in this order,
`connect_limit` first on a stream, and the first check that fails gives the
reply or the close its code:

| `code` | Given when |
| --- | --- |
| `share_unknown` | the share no longer exists: revoked, expired, or removed with its machine, its app or its module |
| `permission_denied {kind}` | the id is not the share's entry; for `{is_panel: true}`, `kind` is `panel` |
| `agent_offline {device}` | the machine providing the entry has no session |
| `service_unknown {service_id}` | the entry is not published now, or the share is `preparing` or `failed` |
| `vault_locked` | on a `service` alone, the secret the visitor's material comes from does not open: the share's guest secret, or the instance's own secret or token for `run_account` |
| `control_unavailable` | the hub's Python did not answer the transport within `ControlQuestionTimeout` |

| Rule | Reason |
| --- | --- |
| A share admits any number of visitors until it expires or is revoked, and limits none of them. | A share's protection is that it reaches one app, that it ends, and that one press ends it, with the app's own login, or its guest account, inside. A limit on visitors stops no leak and stops a classmate who changes devices. |
| A share ends at its `expires_at`, within `WEB_SHARE_SWEEP_INTERVAL_S`, 60 seconds, and at once on **Revoke**. An end deletes the record, sends the transport `shares_set` without it and `session_close {code: share_unknown}` for each of its sessions, and takes its guest out of the module's state, whose apply removes the account. The hub keeps nothing of an ended share: `web_shares` leaves it out from the next read, and a page opened later on its link meets the guest door's silence and shows the hub-offline screen ([web_share.md](web_share.md), "The connection"). | Every page open on an ended share closes, and its link stops working. An ended share never comes back, so the hub has nothing to keep of it and nothing to answer an old link from. |
| Forgetting a device and uninstalling a module end the shares of their entries, and removing a declared app ends its shares. A container's entry that stops being published leaves its share `unavailable`. | A share follows what it offers: an app gone for good takes its shares with it, and one stopped for a while keeps them. |
| A restore ends every share the hub held, as a revoke does, and brings none back. The backup leaves `config/clients/web_shares.json` out, and the restore removes it once the archive is unpacked, a copy in the archive included ([../misc/config.md](../misc/config.md), "Backup and migrate"). | A link revoked after a backup was made never works again. |
| The ticket, the ufrag and the pwd are made with the share, and the link is given once, in `web_share/create`'s answer. | The hub keeps a hash of the ticket alone, so the link cannot be read back from the hub. |
| The Web side offers apps and nothing else, now and in later releases. | A terminal, a file share or a desktop in a browser is a web client, which Neutrino does not make. |

### The rules the details settle

| Concern | Rule |
| --- | --- |
| When `state` is pushed | To an agent, one push on a connection's first `report` whose `state_hash` differs, and after that only when the hub's own hash changes; to a client, on any report whose `state_hash` differs or that says `is_refresh: true`, and when the hub's own hash changes. An agent whose apply failed keeps reporting the old hash; the hub shows that and pushes nothing, and the agent retries only when the state's hash changes. |
| `nagent sync` | Sends one `report` now, from which the hub compares hashes. |
| The `package` stream | The agent opens it and takes the bytes as it writes them to disk. The sha256 in the close's `params` is checked after the close, and only a matching file goes to `systemd-run`. A session that drops mid-transfer deletes the temporary file and locks no update target; only a failed install locks it. |
| The two hashes | The fingerprint of the published service list is computed on the unresolved list and drives the push; the `state.hash` a client receives is computed on the list resolved for its scope. |
| Config writes on the report path | `mac_addresses` is written only when the set grows, under `CONFIG_WRITE_LOCK` and through `asyncio.to_thread`. A peer address used as the fallback link address is recorded, so an overlay-only device keeps its row on the Services page. |
| `PROTOCOL` | The constant has that name in all three packages and in the transport, with no package prefix, an exception to `naming.md` stated there: one number has one name. |

## Devices on the channel

A device is a row in `devices.json` keyed by its binding id. The row stores
what is true of the machine: `machine_id`, and `mac_addresses`, every MAC the
agent has reported on its link.

| Question | Answered by |
| --- | --- |
| a blank link joins: which row | the row whose `machine_id` matches, else a new one |
| Wake-on-LAN goes to | the most recent link MAC, on the networks of the exposed IPv4 segments |
| `is_hub` | `machine_id` equals the hub box's own |

The device's address is the report's `network.link.address`; the session's
peer address, which the transport gives the hub's Python with the session,
is the fallback when that is empty, and it is recorded. The hub's own
machine's address is `127.0.0.1`, whichever of the hub's addresses its
session runs on.

### The address a caller is given

The hub chooses the address an entry names by the scope a client's session
arrived from. Each published service still has one `host`, which the client
shows and never dials, since its bytes go over `connect`:

1. At `hello`, the hub takes the session's peer address, afresh on every
   connection.
1. `host_scope.scope_of(peer, reached, served)` classifies it against the
   scopes the box serves: one per served LAN, named by its network CIDR, and
   one `overlay` scope per overlay interface holding an IPv4 address, told
   apart by the CIDR that address and its prefix name. The first scope whose
   network holds the peer is the answer. Anything else (an uplink, the
   interface in server mode, a client behind NAT, a client that came
   through Direct) is `link`, with the address the client dialled as the
   hub's own. A peer on loopback came through the relay or a frp node and
   dialled that server's address, which is no address of this hub: it is `link` with the
   hub's own name as the hub's own, so the hub's own entries show that name
   and two hubs behind one server do not look like one host.
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

The same peer address, and the listener the connection arrived on, settle the
client's `reached_through`, an IPv4-mapped IPv6 address read as its IPv4
address:

| The peer | `reached_through` |
| --- | --- |
| on SakuraFrp's loopback listener, `FRP_SAKURAFRP_LOOPBACK_PORT` | `sakurafrp` |
| on OpenFrp's loopback listener, `FRP_OPENFRP_LOOPBACK_PORT` | `openfrp` |
| on the agent port from loopback, `127.0.0.0/8`, `::1` or a mapped `127.0.0.1` | `ssh_relay` |
| inside the network of a NetBird device the box holds an address on | `netbird` |
| inside the network of an EasyTier device the box holds an address on | `easytier` |
| inside the network of an address one of the box's other interfaces holds, IPv4 or IPv6: a served LAN, the interface in server mode, an exposed uplink's own network; or an IPv6 link-local address, `fe80::/10`, which reaches one link only | `lan` |
| anywhere else: from outside every network the box holds an address in, through an exposed uplink or the public address stated for Direct | `direct` |

An engine's devices are the ones the Overlay page's `client_count` counts
by, so the word and the count agree.

The hub's own address for a peer, a set and a name, and the order a peer
dials it in are in [transport.md](transport.md), "Where the port is
reached".

`nhub apply` deletes every directory under `config/devices/` whose name is not
a stored id.

## Versioning

A protocol number changes when a peer speaking the old number misreads the new
one; a package version changes on every release. One rule ties the two.
`PROTOCOL` and `PROTOCOL_MIN`, and which numbers the hub admits, are in
[transport.md](transport.md), "The numbers".

| Rule | Reason |
| --- | --- |
| Adding a kind, a field or a code keeps `PROTOCOL`, and a patch release can add them. | A peer that reads tolerantly is unaffected. |
| Removing anything, or changing its meaning, adds one to `PROTOCOL`; so does a change to the link, the ticket, the hub's key, the knock, the handshake, the record layout or the four words `hello`, `state`, `report`, `open`. | An old peer misreads it. |
| The relation to the package version is one-way: a `PROTOCOL` change requires a new minor before 1.0 and a new major after it; a new minor or major can keep the number; a patch never changes `PROTOCOL`. | A person reads compatibility off the version and finds it true. |
| `PROTOCOL_MIN` rises only when a new minor opens (a new major after 1.0). It rises at most to the number the previous minor spoke, except where the owner decides a change is too wide to carry the old peers, as 0.5.0 raises it to its own 3 and 0.6.0 to its own 4. | A hub one release ahead still accepts the fleet it had, unless its release notes say how that fleet is updated or reinstalled. |

Reading is tolerant and writing is strict. An unknown kind is closed
`kind_unknown`, an unknown field is ignored, and a peer sends only what its own
number defines.

The frames, the open records of every kind and the four section documents
are pinned as JSON schemas in `hub/tests/web/channel_schema.json`, which the
transport's tests read too. `hub/tests/web/test_channel_schema.py`
asserts that `PROTOCOL` equals the golden's and that every `Channel*` model's
`model_json_schema()` equals its golden. The model set is closed: one model
more or one fewer fails. Changing a channel model fails that test until
`PROTOCOL` moves or the change is shown to be additive.

| `PROTOCOL` | First minor |
| --- | --- |
| 1 | 0.3.0 |
| 2 | 0.4.0 |
| 3 | 0.5.0 |
| 4 | 0.6.0 |

3 renamed the link's and the client state's `overlay`, one object or null,
to `overlays`, a list. A 0.3 or 0.4 agent or client is refused
`protocol_too_old` and does not update itself from the hub; such an agent is
reinstalled from the Agents page or by hand.

4 changes what a peer of 3 reads. The channel is the transport's: the knock,
the Noise handshake under the hub's static key, go-yamux streams with their
records, and the control stream, in place of TLS pinned by a certificate's
fingerprint and one WebSocket of JSON and binary frames
([transport.md](transport.md), "The member path"). Every address is `tcp://`,
the link carries `key` in place of `fp`, `join` and `leave` are frames, and
`service`, `persist` and `stop_session` are frames answered by `reply`. A
`terminals` entry lists a machine with no flag beside it, and an `exec`
stream is judged by the `terminal` kind, as a `shell` is ("The exec
stream"). The `ai_tools` section's `base_url` names the agent's own AI
gateway forward on `127.0.0.1`, and the agent opens a `connect` stream to
the hub for each connection made to it ("The connect stream"). A module's
recipe is `{runner, method, params}`, and a `package` stream names `{module,
artifact, digest}` ("The modules section, one entry per module").
`PROTOCOL_MIN` is 4. An agent or a client of 0.5 speaks TLS, which the
port refuses, and is installed again with 0.6 and joins again
([transport.md](transport.md), "A peer of 0.5").
