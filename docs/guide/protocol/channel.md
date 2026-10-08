---
title: The channel
---

# The channel

The channel is the one WebSocket a hub keeps with each machine it manages, at protocol 3 from Neutrino 0.5.0. Two roles use it: `agent`, the service on a managed machine, and `client`, a person's desktop client or phone app. This page lists the vocabulary a program written outside this repository speaks. It covers the link, the pin, the two HTTP endpoints, the frames, the streams, the documents each role exchanges, and the codes.

## The port and the pin

The channel is on the agent port, 8443 by default, which serves `/api/channel` over TLS and nothing else. The panel port is separate, and turning the panel's HTTPS on or off leaves the channel as it is.

The certificate on the agent port is self-signed and valid for ten years, so its fingerprint is the hub's whole identity.

| Rule                                   | Value                                                                             |
| -------------------------------------- | --------------------------------------------------------------------------------- |
| What is pinned                         | the SHA-256 digest of the certificate's DER encoding, 64 lowercase hex characters |
| When it is checked                     | after every TLS handshake, before any request bytes leave the machine             |
| Chain and hostname verification        | off                                                                               |
| TLS floor                              | 1.2                                                                               |
| A mismatch on a link's address         | the socket closes and the enrolment stops, with no move to the next address       |
| An `https` address with no fingerprint | no connection                                                                     |

## The enrolment link

A person creates a client link on the hub's **Clients** page and an agent link on **Devices**. [Install a client](../install/client.md) has the steps for a client link, and [Install an agent](../install/agent.md) has them for an agent link.

The link is `neutrino://enroll/<payload>`. The payload is one JSON object written with no spaces, compressed with zlib (RFC 1950, level 9), and the compressed bytes in base64url without padding. A QR code holds the same link, and a reader inflates the payload before it parses it:

```json
{
  "urls": ["https://192.168.100.1:8443", "https://100.92.14.7:8443"],
  "token": "sB1nYt9Qk2_pL0wV7xR4cZ8f",
  "fp": "<sha256-hex>",
  "role": "client",
  "overlays": [
    {
      "provider": "netbird",
      "setup_key": "...",
      "management_url": "",
      "fqdn": "hub.netbird.cloud",
      "hub_address": "100.88.0.1"
    }
  ]
}
```

| Field      | Holds                                                                                                                                                                                                     |
| ---------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `urls`     | every address the hub exposes on the agent port; a program tries them all, since one of them is on the joining machine's network                                                                          |
| `token`    | the enrolment ticket, valid for thirty minutes and spent one time                                                                                                                                         |
| `fp`       | the fingerprint to pin                                                                                                                                                                                    |
| `role`     | `client` or `agent`                                                                                                                                                                                       |
| `overlays` | a client link only: the same list as the client state's `overlays`, taken for the default permission when the link is created; empty when that permission leaves out `overlay` or no overlay has material |

A client rejects an agent link with `link_not_for_client`, and an agent rejects a client link with `link_not_for_agent`; each code's `params` names the link's `role`. The base64url alphabet holds no character a shell splits or a URL escapes, so the link pastes unquoted.

## Joining and leaving

| Endpoint                  | Body                                                             | Returns                                                                                                          |
| ------------------------- | ---------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| `POST /api/channel/join`  | `{ticket, role, protocol, machine_id, name, software, platform}` | `{id, token}`: the binding id and a secret every later `hello` carries                                           |
| `POST /api/channel/leave` | `{id, token}`                                                    | `{}`; a device's row stays on **Devices** and loses its token, a client's row is deleted with its AI gateway key |

`machine_id` and `platform` describe the machine itself, and each role reads them from a different place:

| Field        | An agent sends                                                                                                                                                                                                                                           | A client sends                                                  |
| ------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------- |
| `machine_id` | `/etc/machine-id`, else `/var/lib/dbus/machine-id`, else empty                                                                                                                                                                                           | a uuid4 hex string generated one time per installation and kept |
| `platform`   | `{os, family, arch, version}`: `linux`, `windows` or `darwin`; `debian`, `rhel` or empty; `amd64`, `arm64` or `armhf`; and the glibc version on Linux (`2.36`), the build number on Windows (`26100`), the product version on macOS (`15.3.1`), or empty | `{os, family, arch}`, with `family` empty off Linux             |

The hub compares an agent's `version` with a module's floor. A module whose floor the machine is below reads as one the system cannot run. An agent that sends no `version` is not ruled out.

A client that joins again from an installation the hub has a row for returns to that row. The row keeps its key, its switch and its last report.

| Status | `detail`                                      | When                                                |
| ------ | --------------------------------------------- | --------------------------------------------------- |
| 409    | `protocol_too_old`, params `{peer, hub, min}` | the number is below the hub's `PROTOCOL_MIN`        |
| 409    | `protocol_too_new`, params `{peer, hub, min}` | the number is above the hub's `PROTOCOL`            |
| 409    | `role_mismatch`, params `{role}`              | the ticket was made for the other role              |
| 401    | `ticket_spent`                                | the ticket is unknown, expired or already spent     |
| 401    | `binding_unknown`                             | `leave` named an id and token that match no binding |

The protocol check runs before the ticket is read, so a rejected number spends no ticket. An HTTP error's body is `{"detail": {"code": "...", "params": {}}}`.

## The socket

The socket is `wss://<hub-address>:8443/api/channel/socket`, where `<hub-address>` is an address the program reached the hub at, on a fresh pinned connection. A text frame is one JSON object whose `type` is one of the frame names. A binary frame is a big-endian `u32` stream id followed by that stream's bytes.

### The handshake

The first frame each way is an identity card of one shape. `hello` goes up within ten seconds of the socket opening, and `welcome` or `refused` comes down.

| Field      | `hello` (up)                                      | `welcome` (down)                 |
| ---------- | ------------------------------------------------- | -------------------------------- |
| `protocol` | the number this build speaks, `3`                 | the hub's number, `3`            |
| `role`     | `agent` or `client`                               | `hub`                            |
| `id`       | the binding id                                    | the hub's own id, a uuid         |
| `name`     | the hostname, or the binding's name               | the hub's name from **Settings** |
| `software` | `neutrino_agent/0.5.0` or `neutrino_client/0.5.0` | `neutrino_hub/0.5.0`             |
| `token`    | the binding token                                 | absent                           |

A client joined to several hubs groups them by the hub's `id` and labels them by its `name`. A rejected `hello` gets `refused {code, params}` and close 4000. `hello_invalid` marks a first frame that is late, binary, of another type, or unreadable, and `channel_full {limit}` a port that already holds its most admitted sockets.

### The frames

| Frame     | Direction | Body                                                                                                        |
| --------- | --------- | ----------------------------------------------------------------------------------------------------------- |
| `hello`   | up        | the identity card, with `token`                                                                             |
| `welcome` | down      | the hub's identity card                                                                                     |
| `refused` | down      | `{code, params}`, then close 4000                                                                           |
| `state`   | down      | `{hash, ...sections}`: what is to be true                                                                   |
| `report`  | up        | `{state_hash, ...sections}`: what is true                                                                   |
| `open`    | both      | `{stream, kind, ...args}`: a stream begins                                                                  |
| `close`   | both      | `{stream, code, params}`: it ends, with its result                                                          |
| `credit`  | both      | `{stream, bytes}`: the sender can send that many more                                                       |
| `ping`    | up        | `{nonce}`: a round-trip probe; `nonce` is the sender's own string of at most 64 characters                  |
| `pong`    | down      | `{nonce}`: the hub's reply, sent at once on the same socket, with the `ping`'s `nonce` cut to 64 characters |
| binary    | both      | `<u32 stream id><bytes>`; on a UDP `connect` stream `<u32 stream id><u16 source><one datagram>`             |

The hub sends a WebSocket ping every 20 seconds and closes a socket whose pong has not come back within 60 seconds. These are `CHANNEL_PING_INTERVAL_S` and `CHANNEL_PING_TIMEOUT_S`, and every peer replies with a WebSocket pong as the WebSocket standard requires. The hub replies to a `ping` frame from any admitted peer and stores nothing.

A client sends a `ping` frame every 20 seconds, and one more right after its channel moves to a new socket, never before `welcome`. The `pong` with the `nonce` of the last `ping` sent on that socket gives `rtt_ms`, the time from sending that `ping` to receiving its `pong`. A `pong` with another `nonce` is dropped. A client sends no WebSocket ping of its own.

Agents and clients treat 45 seconds without a frame as a dead socket, and reconnect with a backoff from 5 to 60 seconds.

## The stream layer

Every action is a stream: its `open` is the request, its `close` is the reply, and `kind` names the method.

| Concern       | Rule                                                                                                                                    |
| ------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| Ids           | the hub opens streams with even ids from 0 and the peer with odd ids from 1, each side stepping by 2, so the two never collide          |
| Bytes         | a binary frame holds one stream's bytes; a stream's text output is one line per frame                                                   |
| Credit        | `credit {stream, bytes}` grants that many more bytes; the window is 1 MiB and the largest frame 64 KiB                                  |
| Result        | `close {stream, code, params}` ends a stream from either side; an empty `code` makes `params` the result, and a code makes it a refusal |
| One close     | a stream one side closed gets no close back                                                                                             |
| Unknown kinds | a kind a program has no handler for is closed with `kind_unknown`, and an unknown verb on a `command` stream with `verb_unknown`        |

## The client's state

The hub sends a client its `state` after a report whose `state_hash` differs from the hub's or that has `is_refresh: true`. It also sends it whenever the hub's own changes.

| Section            | Holds                                                                                                                                           |
| ------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| `hash`             | an opaque string the client names back in every report                                                                                          |
| `is_disabled`      | `true` after **Disable** on **Clients**: the lists are empty and every action is rejected with `client_disabled`                                |
| `services`         | the published entries this client is allowed, resolved for the address its socket came from                                                     |
| `urls`             | every address the hub serves the channel on, which the client keeps for its next connection round                                               |
| `relay_url`        | the member of `urls` that is the SSH Relay's address, an empty string while the relay is off; the client ranks a candidate address's path by it |
| `overlays`         | what the client joins each of the hub's overlays with, the preferred first                                                                      |
| `terminals`        | the managed machines the client is allowed to open a shell on, each `{device_id, name, is_online, sessions}`                                    |
| `is_panel_allowed` | `true` while the client is switched on and its permission includes `panel`: it can open the hub's panel through `connect`                       |
| `reached_through`  | the path this client's socket took to the hub: `lan`, `direct`, `netbird`, `easytier` or `relay` (the SSH Relay), the last being the SSH Relay  |

### Overlays

`overlays` holds one object per running overlay that has material, NetBird first. It is empty when the hub runs no overlay, the client is off, its permission leaves out `overlay`, or the hub's vault is locked.

```json
[
  {
    "provider": "netbird",
    "setup_key": "...",
    "management_url": "",
    "fqdn": "hub.netbird.cloud",
    "hub_address": "100.88.0.1"
  },
  {
    "provider": "easytier",
    "mode": "manual",
    "network_name": "...",
    "network_secret": "...",
    "peer": "tcp://203.0.113.7:11010",
    "hub_address": "10.0.0.1"
  }
]
```

| Provider and mode     | Fields                                                                                                                               |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| `netbird`             | `setup_key`, the reusable key; `management_url`, empty for NetBird's own plane; `fqdn`, the hub's name on the overlay; `hub_address` |
| `easytier`, `manual`  | `network_name`, `network_secret`; `peer`, `tcp://<join-host>:11010`; `hub_address` <!-- scan: allow -->                              |
| `easytier`, `console` | `config_server`, the console address with its account token; `is_secure_mode`; `hub_address`                                         |

`hub_address` is the hub's own address on that network, without its prefix length, and empty when none is known. A client dials it with the other candidate addresses while the network is on.

### Terminals and sessions

`terminals` lists every managed machine, the hub's own among them, when the client's permission includes `terminal`, narrowed to the machines that permission names. Each entry's `sessions` is the shell sessions this client sees on the machine. These are every session it opened, and every shared session where it has terminal rights. They are ordered by `started_at`, and the list is empty while the machine is offline:

| Field            | Holds                                                                                                                              |
| ---------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| `session_id`     | the id the opener generated, a uuid                                                                                                |
| `account`        | the account the shell runs as                                                                                                      |
| `started_at`     | when it was opened, in Unix seconds                                                                                                |
| `title`          | the title the shell last set, or the shell's name                                                                                  |
| `owner`          | who opened it, as the hub stamped the `shell` open                                                                                 |
| `is_attached`    | whether a stream is attached now                                                                                                   |
| `is_persistent`  | whether the session stays when its last stream closes                                                                              |
| `is_shared`      | whether every client with terminal rights on the machine can attach to it; a shared session also stays when its last stream closes |
| `attached_count` | how many streams are attached now                                                                                                  |
| `device_id`      | the machine holding the session                                                                                                    |
| `device_name`    | what the hub calls that machine                                                                                                    |
| `is_owned`       | whether this client opened it; only the owner sets `is_persistent` and `is_shared`                                                 |
| `owner_name`     | what the owner is called: the hub's name, or the owning client's name                                                              |

The hub stamps `owner` on every `shell` open it sends a machine: `client:<id>` for a client's stream, `hub` for the panel's terminal. The hub pushes every client its state when an agent's channel opens or ends, and when a machine's list of sessions changes.

## The client's report

```json
{
  "type": "report",
  "state_hash": "<state-hash>",
  "machine": {
    "hostname": "laptop",
    "platform": { "os": "darwin", "family": "", "arch": "arm64" },
    "os_machine_id": "<os-machine-id>"
  }
}
```

A report goes up after the welcome, every 30 seconds after that, and after each state is applied. `state_hash` is empty before the first state. A report with `is_refresh: true`, sent when the person presses refresh, gets the whole state back whatever its hash.

`os_machine_id` is the operating system's id for the machine: `/etc/machine-id` on Linux, `IOPlatformUUID` on macOS, `MachineGuid` on Windows, or empty. The hub compares it with each provider's `machine_id` to set `is_own_machine` on the service entries.

## The service entries

Each entry of `services` is `{id, type, title, payload, is_healthy, source, description, description_code, description_params, device_id, device_name, is_own_machine}`.

| `type` | `payload`                                                                                                                                         |
| ------ | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| `web`  | `{url, is_token_required}`; `is_token_required` is present and true on a VS Code, code-server or CloudCLI instance only                           |
| `port` | `{host, port, protocol}`; `protocol` is `tcp` or `udp`, and a payload without it is `tcp`. A number used on both protocols is two entries         |
| `ai`   | `{endpoint, protocol, models}`, `protocol` being `openai`                                                                                         |
| `file` | `{protocol, host, share, users}`, `protocol` being `smb`                                                                                          |
| `rdp`  | `{protocol, host, port, attention, platform_os}`, `protocol` being `rustdesk`, `platform_os` the sharing machine's `linux`, `windows` or `darwin` |

Every `host`, `port`, `url` and `endpoint` in a payload is where the service sits on the hub's networks. It is resolved for the address the client's socket came from. A client shows it to the person and dials none of it; every byte to a service goes over a `connect` stream.

`attention` on an `rdp` entry names what somebody must do at the sharing machine first: `rdp_nobody_seated`, `rdp_screen_not_allowed`, or empty. `users` on a `file` entry lists the accounts that can open the share. A phone fills in the user name from it and prompts for the password. The list is empty on a declared share.

| Field                | Holds                                                                                                                                                                                            |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `is_healthy`         | the last probe's result, `null` where nothing probed it                                                                                                                                          |
| `source`             | `module`, `declared` or `device`                                                                                                                                                                 |
| `description_code`   | the provenance as a code a program words itself: `ai_gateway`, `container`, `declared`, `device_share`, `gitea_module`, `samba_module`, `vscode_module`, `code_server_module`, `cloudcli_module` |
| `description_params` | the values that sentence names; `vscode_module`, `code_server_module` and `cloudcli_module` take `{host, account}`                                                                               |
| `device_id`          | the id of the managed machine providing the entry; empty for a declared record and for the hub's own gateway. A program keys what it keeps per machine by this id                                |
| `device_name`        | the name of the machine providing the entry, empty when no machine on the hub's records provides it                                                                                              |
| `is_own_machine`     | `true` when the machine providing the entry is the one the client runs on; `false` when either id is empty                                                                                       |

## The streams a client opens

### The service stream

`open {kind: service, id}` requests what one entry needs from the hub. The checks run in this order, and the first that fails gives the close its code:

| `code`              | Given when                                                                                                          |
| ------------------- | ------------------------------------------------------------------------------------------------------------------- |
| `binding_unknown`   | no client row has this socket's binding id                                                                          |
| `client_disabled`   | the client is switched off on **Clients**                                                                           |
| `service_unknown`   | the id names no entry in the list resolved for this client                                                          |
| `permission_denied` | the entry's type, or the machine providing it, is outside this client's permission                                  |
| `rdp_not_shared`    | the entry's machine stopped sharing its desktop                                                                     |
| `vault_locked`      | the hub's vault is locked, so the AI key, the VS Code token, or the code-server or CloudCLI secret cannot be opened |

A close with no code holds the material. A client opens a `web` entry with `is_token_required` at its own forward's address with `?tkn=<token>` added, never at the entry's address:

| Entry                                                                   | The close's `params`                                                                                                         |
| ----------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| `rdp`                                                                   | `{password}`: the seat password of the machine sharing the desktop                                                           |
| `ai`                                                                    | `{api_key, model}`: this client's own key, which the gateway checks on every request, and the first model the gateway serves |
| `web` with `description_code` `vscode_module`                           | `{token}`: the instance's connection token                                                                                   |
| `web` with `description_code` `code_server_module` or `cloudcli_module` | `{token}`: a token the hub makes for this reply alone, valid for 60 seconds and for one use                                  |
| other `web`, `port`, `file`                                             | empty; the payload is all the client needs                                                                                   |

### The connect stream

`open {kind: connect, id}` holds one TCP connection to one published entry, and `open {kind: connect, is_panel: true}` holds one to the hub's own panel. A client opens one stream for each connection its local listener accepts, and one stream for as long as a UDP `port` entry is connected. It dials no address an entry's payload names. The hub runs the service stream's checks with the stream limit among them, without `vault_locked`:

| `code`                         | Given when                                                                                           |
| ------------------------------ | ---------------------------------------------------------------------------------------------------- |
| `binding_unknown`              | no client row has this socket's binding id                                                           |
| `client_disabled`              | the client is switched off on **Clients**                                                            |
| `connect_limit {limit}`        | the socket already holds 256 open `connect` streams                                                  |
| `service_unknown {service_id}` | the id names no entry in the list resolved for this client                                           |
| `permission_denied {kind}`     | the entry's type, or `panel` for the panel, is outside this client's permission                      |
| `rdp_not_shared {service_id}`  | the entry's machine stopped sharing its desktop                                                      |
| `agent_offline {device}`       | the machine that provides the entry has no channel, or its channel ended under the stream            |
| `connect_failed {reason}`      | the dial to the far end failed; `reason` is `refused`, `timeout` (after 10 seconds) or `unreachable` |
| `port_not_published {port}`    | the machine that provides the entry no longer publishes the port                                     |

| The entry                     | Where the hub connects the stream                                   |
| ----------------------------- | ------------------------------------------------------------------- |
| provided by a managed machine | that machine's agent, which dials the port on its own loopback      |
| a declared record             | the record's own address, dialled by the hub                        |
| `ai`                          | the gateway on the hub's loopback                                   |
| the panel                     | the panel's HTTP port on the hub's loopback, with no HTTPS redirect |

Bytes go as binary frames both ways under credit, with the window and frame size of a `shell` stream. End of file on either end closes the stream with empty params after everything read is sent. The side that receives the close writes what it holds and closes its own socket. A stream has no half-close, and a client socket that ends ends every `connect` stream on it.

On a UDP stream each binary frame is one datagram, preceded by its `source`. The `source` is a big-endian `u16`, the port the datagram left from on the client's machine.

A reply holds the `source` it replies to. A side that holds too little credit for a frame drops the datagram. The far end forgets a `source` that is quiet for 60 seconds.

### The shell and command streams

| `open`                                                                                | What the hub does                                                                                                                                                                                                                                                                                                                                                                    |
| ------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `{kind: shell, device_id, cols, rows, session_id, is_resumed, is_shared}`             | opens a shell on that machine under `session_id`, stamped as this client's and shared when `is_shared` is true, and relays terminal bytes both ways; an id the machine holds attaches to that session beside every stream already attached, and its recent output comes first; `is_resumed: true` attaches only, and closes `session_unknown` when the machine holds no such session |
| `{kind: command, module: agent, verb: resize, shell, cols, rows}`                     | resizes the client's own `shell` stream; `shell_unknown` when no such stream is open                                                                                                                                                                                                                                                                                                 |
| `{kind: command, module: agent, verb: persist, session_id, is_persistent, is_shared}` | sets whether the session stays after its last stream closes, and whether it is shared; a flag the command leaves out keeps its value                                                                                                                                                                                                                                                 |
| `{kind: command, module: agent, verb: stop_session, session_id}`                      | ends the session on its machine                                                                                                                                                                                                                                                                                                                                                      |

Any number of streams attach to one session at once. Each receives all the output, input from any of them reaches the shell, and the shell's size is the smallest attached window's columns and rows. A `shell` stream is refused with `binding_unknown`, `client_disabled`, `permission_denied {kind: terminal}` or `agent_offline {device}` before the hub opens anything on the machine.

`persist` and `stop_session` close with `session_unknown` when no machine holds the session. `persist` closes with `session_not_owned` on a session another viewer opened, and `stop_session` ends any session the client sees. An agent restart or update ends every session on that machine.

## The agent's sections

An agent's documents hold these sections; the `modules` entries come from the hub's manifests, resolved for the agent's `platform`.

| Section    | `state` to an agent                                                                                             | `report` from an agent                                                     |
| ---------- | --------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| `machine`  |                                                                                                                 | `{hostname, platform, accounts, metrics, sessions}`                        |
| `network`  |                                                                                                                 | `{link: {interface, mac, address}, interfaces: [{name, mac, addresses}]}`  |
| `modules`  | `{<name>: {want, config, install, uninstall, retry_mark}}`                                                      | `{<name>: {state, is_active, code, params, details}}`                      |
| `desktop`  | `{seat_password}`                                                                                               | `{is_shared, origin, account, share_id, port, attention, connected_count}` |
| `ai_tools` | `{is_enabled, base_url, api_key, tool_configs, accounts: [{account, password}], cc_switch_version, retry_mark}` | `{accounts: [{account, state, code, params, has_records}]}`                |
| `urls`     | every address the hub serves the channel on                                                                     |                                                                            |
| `error`    |                                                                                                                 | `{code, params}`: the agent's most recent failure worth showing            |

| Field or value                  | Meaning                                                                                                                                                                                       |
| ------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `retry_mark`                    | a short random token the hub writes when a person presses a failed module's action, or the AI tools switch, again; it changes the hash and means nothing else                                 |
| `queued`, as a module's `state` | the module's `want` differs from its report, and the agent applies another module first                                                                                                       |
| `origin`                        | how the desktop share started: `switch` for the **Remote desktop** switch, `command` for a share an old `nagent rdp start` record keeps running; empty while nothing is shared                |
| `ai_tools.is_enabled`           | `true` while the machine's AI tools setting is on and the gateway serves a model; then `base_url`, `api_key` and `tool_configs` name the gateway, the machine's key and the models            |
| `ai_tools.accounts`             | in the state, every account with a VS Code, code-server or CloudCLI instance, with its login on Windows alone; in the report, each account's `state`: `switched`, `switched_back` or `failed` |
| `cc_switch_version`             | the version of cc-switch the agent fetches from the hub and runs; a failed fetch reports `cc_switch_download_failed` on every account                                                         |

An agent reports every 5 seconds. The hub opens `shell`, `file`, `command` and `connect` streams to it, and the agent opens `log` and `package` streams to the hub.

A `connect {port, protocol}` stream is one TCP connection the agent dials on `127.0.0.1`, or on the one address a container port is published on. On UDP it is every datagram of one entry to that port, and `protocol` absent is `tcp`. A port the machine does not publish on that protocol at that moment closes with `port_not_published {port}`, and a failed dial with `connect_failed {reason}`.

## Refusals and the binding

A refusal is `{code, params}` wherever it appears: `detail` on an HTTP error, a `refused` frame, or the code on a stream's close. A refusal keeps the binding; the program records it and sends `hello` again a minute later.

| Code                           | Where                      | Effect on the binding                                         |
| ------------------------------ | -------------------------- | ------------------------------------------------------------- |
| `protocol_too_old`             | `join`, `hello`            | kept                                                          |
| `protocol_too_new`             | `join`, `hello`            | kept                                                          |
| `role_mismatch`                | `join`, `hello`            | kept                                                          |
| `hello_invalid`                | `hello`                    | kept                                                          |
| `channel_full`                 | `hello`                    | kept; transient                                               |
| `admission_paused`             | `join`                     | kept; transient, the ticket stays valid                       |
| `ticket_spent`                 | `join`                     | nothing is bound yet; a person creates a fresh link           |
| `binding_unknown`              | `hello`, `leave`, a stream | removed: the program deletes its binding and needs a new link |
| `kind_unknown`, `verb_unknown` | a stream                   | kept                                                          |

`binding_unknown` is the one refusal that unbinds, because it means the row was removed on the panel. Only the hub holding the pinned certificate can send it.

| Close code | Meaning                                                                                                   |
| ---------- | --------------------------------------------------------------------------------------------------------- |
| 4000       | `refused`; the `refused` frame before it holds the code                                                   |
| 4010       | `replaced`: a second socket opened for the same binding; the program reconnects only on a person's action |

## Protocol numbers

Each build declares one integer, `PROTOCOL`, and package versions take no part in admission. The hub also holds `PROTOCOL_MIN` and admits a peer whose number is within `PROTOCOL_MIN` to `PROTOCOL`.

| `PROTOCOL` | First minor |
| ---------- | ----------- |
| 1          | 0.3.0       |
| 2          | 0.4.0       |
| 3          | 0.5.0       |

`PROTOCOL_MIN` is 3 from 0.5.0. Protocol 3 renamed the link's and the client state's `overlay`, one object or null, to `overlays`, a list. A 0.3 or 0.4 agent or client is rejected with `protocol_too_old` and does not update itself from a 0.5.0 hub. Each such machine installs the 0.5.0 package and joins with a new link.

Reading is tolerant and writing is strict. An unknown field is ignored, an unknown kind closes with `kind_unknown`, and a program sends only what its own number defines. Adding a kind, a field or a code keeps the number. Removing anything, changing its meaning, or changing the link, the ticket, the pin or the words `hello`, `state`, `report` and `open` raises it by one.
