---
title: The channel
---

# The channel

The channel is the one WebSocket a hub keeps with each machine it manages, at protocol 3 from Neutrino 0.5.0. Two roles use it: `agent`, the service on a managed machine, and `client`, a person's desktop client or phone app. This page is the vocabulary a program written outside this repository speaks: the link, the pin, the two HTTP endpoints, the frames, the streams, the documents each role exchanges, and the codes.

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

A person creates the link on the hub's **Clients** page for a client and on **Devices** for an agent. [Clients](../hub/clients.md) has the steps for a client link. [Devices](../hub/devices.md) has them for an agent link. The link is `neutrino://enroll/<payload>`, where the payload is base64url over one JSON object:

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
      "fqdn": "hub.netbird.cloud"
    }
  ]
}
```

| Field      | Holds                                                                                                                                                                                                     |
| ---------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `urls`     | every address the hub is exposed at on the agent port; a program tries them in order, since one of them is on the joining machine's network                                                               |
| `token`    | the enrolment ticket, valid for five minutes and spent once                                                                                                                                               |
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

| Field        | An agent sends                                                                                                                                                                                                                                           | A client sends                                              |
| ------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------- |
| `machine_id` | `/etc/machine-id`, else `/var/lib/dbus/machine-id`, else empty                                                                                                                                                                                           | a uuid4 hex string generated once per installation and kept |
| `platform`   | `{os, family, arch, version}`: `linux`, `windows` or `darwin`; `debian`, `rhel` or empty; `amd64`, `arm64` or `armhf`; and the glibc version on Linux (`2.36`), the build number on Windows (`26100`), the product version on macOS (`15.3.1`), or empty | `{os, family, arch}`, with `family` empty off Linux         |

The hub compares an agent's `version` with a module's floor, and a module whose floor the machine is below reads as one the system cannot run. An agent that sends no `version` is not ruled out.

A client joining again from an installation the hub already has a row for lands on that row, keeping its key, its switch and its last report.

| Status | `detail`                                      | When                                                |
| ------ | --------------------------------------------- | --------------------------------------------------- |
| 409    | `protocol_too_old`, params `{peer, hub, min}` | the number is below the hub's `PROTOCOL_MIN`        |
| 409    | `protocol_too_new`, params `{peer, hub, min}` | the number is above the hub's `PROTOCOL`            |
| 409    | `role_mismatch`, params `{role}`              | the ticket was made for the other role              |
| 401    | `ticket_spent`                                | the ticket is unknown, expired or already spent     |
| 401    | `binding_unknown`                             | `leave` named an id and token that match no binding |

The protocol check runs before the ticket is read, so a rejected number spends no ticket. An HTTP error's body is `{"detail": {"code": "...", "params": {}}}`.

## The socket

The socket is `wss://<hub-address>:8443/api/channel/socket`, where `<hub-address>` is the address the join succeeded at, on a fresh pinned connection. A text frame is one JSON object whose `type` is one of the frame names; a binary frame is a big-endian `u32` stream id followed by that stream's bytes.

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

A client joined to several hubs groups them by the hub's `id` and labels them by its `name`. A rejected `hello` gets `refused {code, params}` and close 4000; `hello_invalid` marks a first frame that is late, binary, of another type, or unreadable.

### The frames

| Frame     | Direction | Body                                                  |
| --------- | --------- | ----------------------------------------------------- |
| `hello`   | up        | the identity card, with `token`                       |
| `welcome` | down      | the hub's identity card                               |
| `refused` | down      | `{code, params}`, then close 4000                     |
| `state`   | down      | `{hash, ...sections}`: what is to be true             |
| `report`  | up        | `{state_hash, ...sections}`: what is true             |
| `open`    | both      | `{stream, kind, ...args}`: a stream begins            |
| `close`   | both      | `{stream, code, params}`: it ends, with its result    |
| `credit`  | both      | `{stream, bytes}`: the sender can send that many more |
| binary    | both      | `<u32 stream id><bytes>`                              |

The hub pings every 20 seconds and drops a socket whose pong is more than 20 seconds late. Agents and clients treat 45 seconds of silence as a dead socket and reconnect with a backoff from 5 to 60 seconds.

## The stream layer

Every action is a stream: its `open` is the request, its `close` is the reply, and `kind` names the method.

| Concern       | Rule                                                                                                                                    |
| ------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| Ids           | the hub opens streams with even ids from 0 and the peer with odd ids from 1, so the two never collide                                   |
| Bytes         | a binary frame carries one stream's bytes; a stream's text output is one line per frame                                                 |
| Credit        | `credit {stream, bytes}` grants that many more bytes; the window is 1 MiB and the largest frame 64 KiB                                  |
| Result        | `close {stream, code, params}` ends a stream from either side; an empty `code` makes `params` the result, and a code makes it a refusal |
| One close     | a stream one side closed gets no close back                                                                                             |
| Unknown kinds | a kind a program has no handler for is closed with `kind_unknown`, and an unknown verb on a `command` stream with `verb_unknown`        |

## The client's state

The hub sends a client its `state` on any report whose `state_hash` differs from the hub's or that says `is_refresh: true`, and whenever the hub's own changes.

| Section       | Holds                                                                                                            |
| ------------- | ---------------------------------------------------------------------------------------------------------------- |
| `hash`        | an opaque string the client names back in every report                                                           |
| `is_disabled` | `true` after **Disable** on **Clients**: the lists are empty and every action is rejected with `client_disabled` |
| `services`    | the published entries this client is allowed, resolved for the address its socket came from                      |
| `urls`        | every address the hub serves the channel on, which the client keeps for its next reconnect                       |
| `overlays`    | what the client joins each of the hub's overlays with, the preferred first                                       |
| `terminals`   | the managed machines the client is allowed to open a shell on, each `{device_id, name, is_online, sessions}`     |

### Overlays

`overlays` holds one object per running overlay that has material, NetBird first. It is empty when the box runs no overlay, the client is switched off, the client's permission leaves out `overlay`, or the hub's vault is locked.

```json
[
  {
    "provider": "netbird",
    "setup_key": "...",
    "management_url": "",
    "fqdn": "hub.netbird.cloud"
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

| Provider and mode     | Fields                                                                                                                                                              |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `netbird`             | `setup_key`, the reusable key; `management_url`, empty for NetBird's own plane; `fqdn`, the hub's name on the overlay                                               |
| `easytier`, `manual`  | `network_name`, `network_secret`; `peer`, `tcp://<join-host>:11010`; `hub_address`, the hub's address on the network without its prefix length <!-- scan: allow --> |
| `easytier`, `console` | `config_server`, the console address with its account token; `is_secure_mode`; `hub_address`                                                                        |

### Terminals and sessions

`terminals` lists every managed machine, the hub's own among them, when the client's permission includes `terminal`, narrowed to the machines that permission names. Each entry's `sessions` is the shell sessions this client sees on the machine: every session it opened, and every shared session on a machine it has terminal rights on. They are ordered by `started_at`, and the list is empty while the machine is offline:

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
    "platform": { "os": "darwin", "family": "", "arch": "arm64" }
  }
}
```

A report goes up after the welcome, every 30 seconds after that, and after each state is applied. `state_hash` is empty before the first state. A report with `is_refresh: true`, sent when the person presses refresh, is answered with the whole state whatever its hash.

## The service entries

Each entry of `services` is `{id, type, title, payload, is_healthy, source, description, description_code, description_params, device_name}`.

| `type` | `payload`                                                                           |
| ------ | ----------------------------------------------------------------------------------- |
| `web`  | `{url, is_local_only}`; `is_local_only` is present and true on a VS Code entry only |
| `port` | `{host, port}`                                                                      |
| `ai`   | `{endpoint, protocol, models}`, `protocol` being `openai`                           |
| `file` | `{protocol, host, share, users}`, `protocol` being `smb`                            |
| `rdp`  | `{protocol, host, port, attention}`, `protocol` being `rustdesk`                    |

An entry with `is_local_only` opens only through a port forwarded to the client's own `127.0.0.1`, so a phone shows it as desktop only. `attention` on an `rdp` entry is what somebody must do at the sharing machine first: `rdp_nobody_seated`, `rdp_screen_not_allowed`, or empty. `users` on a `file` entry lists the accounts that can open the share, so a phone offers the user name and asks only for the password. It is empty on a declared share, and a hub before 0.5.0 sends none.

| Field                | Holds                                                                                                                                                   |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `is_healthy`         | the last probe's result, `null` where nothing probed it                                                                                                 |
| `source`             | `module`, `declared` or `device`                                                                                                                        |
| `description_code`   | the provenance as a code a program words itself: `ai_gateway`, `container`, `declared`, `device_share`, `gitea_module`, `samba_module`, `vscode_module` |
| `description_params` | the values that sentence names; `vscode_module` takes `{host, account}`                                                                                 |
| `device_name`        | the name of the machine providing the entry, empty when no machine on the record of the hub provides it                                                 |

## The streams a client opens

### The service stream

`open {kind: service, id}` asks for what one entry takes from the hub. The checks run in this order, and the first that fails gives the close its code:

| `code`              | Given when                                                                         |
| ------------------- | ---------------------------------------------------------------------------------- |
| `binding_unknown`   | no client row has this socket's binding id                                         |
| `client_disabled`   | the client is switched off on **Clients**                                          |
| `service_unknown`   | the id names no entry in the list resolved for this client                         |
| `permission_denied` | the entry's type, or the machine providing it, is outside this client's permission |
| `rdp_not_shared`    | the entry's machine stopped sharing its desktop                                    |
| `vault_locked`      | the hub's vault is locked, so the AI key or the VS Code token cannot be opened     |

A close with no code carries the material:

| Entry                                         | The close's `params`                                                                                                    |
| --------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `rdp`                                         | `{host, port, password}`: the address as it resolves now and the seat password                                          |
| `ai`                                          | `{base_url, api_key, model}`: the gateway, this client's own key, and the first model the gateway serves                |
| `web` with `description_code` `vscode_module` | `{token}`; the client forwards the entry's port to its own `127.0.0.1` and opens `http://127.0.0.1:<port>/?tkn=<token>` |
| other `web`, `port`, `file`                   | empty; the payload is all the client needs                                                                              |

### The shell and command streams

| `open`                                                                                | What the hub does                                                                                                                                                                                                                                                                                                                                                                    |
| ------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `{kind: shell, device_id, cols, rows, session_id, is_resumed, is_shared}`             | opens a shell on that machine under `session_id`, stamped as this client's and shared when `is_shared` is true, and relays terminal bytes both ways; an id the machine holds attaches to that session beside every stream already attached, and its recent output comes first; `is_resumed: true` attaches only, and closes `session_unknown` when the machine holds no such session |
| `{kind: command, module: agent, verb: resize, shell, cols, rows}`                     | resizes the client's own `shell` stream; `shell_unknown` when no such stream is open                                                                                                                                                                                                                                                                                                 |
| `{kind: command, module: agent, verb: persist, session_id, is_persistent, is_shared}` | sets whether the session stays after its last stream closes, and whether it is shared; a flag the command leaves out keeps its value                                                                                                                                                                                                                                                 |
| `{kind: command, module: agent, verb: stop_session, session_id}`                      | ends the session on its machine                                                                                                                                                                                                                                                                                                                                                      |

Any number of streams attach to one session at once. Each receives all the output, input from any of them reaches the shell, and the shell's size is the smallest attached window's columns and rows. A `shell` stream is refused with `binding_unknown`, `client_disabled`, `permission_denied {kind: terminal}` or `agent_offline {device}` before the hub opens anything on the machine. `persist` and `stop_session` close with `session_unknown` when no machine holds the session, and `persist` closes with `session_not_owned` on a session another viewer opened; `stop_session` ends any session the client sees. An agent restart or update ends every session on that machine.

## The agent's sections

An agent's documents carry these sections; the `modules` entries come from the hub's manifests, resolved for the agent's `platform`.

| Section   | `state` to an agent                            | `report` from an agent                                                    |
| --------- | ---------------------------------------------- | ------------------------------------------------------------------------- |
| `machine` |                                                | `{hostname, platform, accounts, metrics, sessions}`                       |
| `network` |                                                | `{link: {interface, mac, address}, interfaces: [{name, mac, addresses}]}` |
| `modules` | `{<name>: {want, config, install, uninstall}}` | `{<name>: {state, is_active, code, params, details}}`                     |
| `desktop` | `{seat_password}`                              | `{is_shared, account, share_id, port, attention, connected_count}`        |
| `urls`    | every address the hub serves the channel on    |                                                                           |
| `error`   |                                                | `{code, params}`: the agent's most recent failure worth showing           |

An agent reports every 5 seconds. The hub opens `shell`, `file` and `command` streams to it, and the agent opens `log` and `package` streams to the hub.

## Refusals and the binding

A refusal is `{code, params}` wherever it appears: `detail` on an HTTP error, a `refused` frame, or the code on a stream's close. A refusal keeps the binding; the program records it and sends `hello` again a minute later.

| Code                           | Where                      | Effect on the binding                                         |
| ------------------------------ | -------------------------- | ------------------------------------------------------------- |
| `protocol_too_old`             | `join`, `hello`            | kept                                                          |
| `protocol_too_new`             | `join`, `hello`            | kept                                                          |
| `role_mismatch`                | `join`, `hello`            | kept                                                          |
| `hello_invalid`                | `hello`                    | kept                                                          |
| `ticket_spent`                 | `join`                     | nothing is bound yet; a person creates a fresh link           |
| `binding_unknown`              | `hello`, `leave`, a stream | removed: the program deletes its binding and needs a new link |
| `kind_unknown`, `verb_unknown` | a stream                   | kept                                                          |

`binding_unknown` is the one refusal that unbinds, because it means the row was removed on the panel, and only the hub holding the pinned certificate can send it.

| Close code | Meaning                                                                                                   |
| ---------- | --------------------------------------------------------------------------------------------------------- |
| 4000       | `refused`; the `refused` frame before it carries the code                                                 |
| 4010       | `replaced`: a second socket opened for the same binding; the program reconnects only on a person's action |

## Protocol numbers

Each build declares one integer, `PROTOCOL`, and package versions take no part in admission. The hub also holds `PROTOCOL_MIN` and admits a peer whose number is within `PROTOCOL_MIN` to `PROTOCOL`.

| `PROTOCOL` | First minor |
| ---------- | ----------- |
| 1          | 0.3.0       |
| 2          | 0.4.0       |
| 3          | 0.5.0       |

`PROTOCOL_MIN` is 3 from 0.5.0. Protocol 3 renamed the link's and the client state's `overlay`, one object or null, to `overlays`, a list. A 0.3 or 0.4 agent or client is rejected with `protocol_too_old` and does not update itself from a 0.5.0 hub. The hub's own update reinstalls the box's own agent; every other machine takes the 0.5.0 package from **Devices** or by hand.

Reading is tolerant and writing is strict. An unknown field is ignored, an unknown kind closes with `kind_unknown`, and a program sends only what its own number defines. Adding a kind, a field or a code keeps the number; removing anything, changing its meaning, or changing the link, the ticket, the pin or the words `hello`, `state`, `report` and `open` raises it by one.
