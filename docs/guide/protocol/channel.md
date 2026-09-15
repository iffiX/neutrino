---
title: The channel
---

# The channel

The channel is the one WebSocket a hub serves every program it manages: a device agent on a Linux machine, or a person's client. A client written outside this repository speaks the same words as `neutrino_client`, and this page is that whole vocabulary: the enrolment link, the certificate pin, the two HTTP endpoints, the socket's eight frames, the stream layer, the two documents a client exchanges, the five service types it consumes, and the codes a hub sends it away with.

## The port and the pin

A hub listens on two ports. The panel port, 8080 by default, is plain HTTP behind a session cookie and serves the browser. The channel is on the agent port, 8443 by default, which serves `/api/channel` over TLS and nothing else.

The certificate on that port is self-signed and lasts ten years, so its fingerprint is the entire identity of the hub.

| Rule                                   | Value                                                                             |
| -------------------------------------- | --------------------------------------------------------------------------------- |
| What is pinned                         | the SHA-256 digest of the certificate's DER encoding, 64 lowercase hex characters |
| When it is checked                     | after every TLS handshake, before any request bytes leave the machine             |
| Chain and hostname verification        | off                                                                               |
| TLS floor                              | 1.2                                                                               |
| A mismatch                             | the socket closes and the enrolment stops, with no move to the next address       |
| An `https` address with no fingerprint | no connection at all                                                              |

A wrong certificate at a link's address is an impersonation, which is why a mismatch ends the enrolment instead of moving on quietly.

## The enrolment link

A person makes the link on the hub's **Clients** page and pastes it into the program. [The Clients page](../hub/clients.md) has the steps. It is `neutrino://enroll/<payload>`, where the payload is base64url over one JSON object:

```json
{
  "urls": ["https://192.168.100.1:8443", "https://10.8.0.1:8443"],
  "token": "sB1nYt9Qk2_pL0wV7xR4cZ8f",
  "fp": "<sha256-hex>",
  "role": "client"
}
```

| Field   | Holds                                                                                                                                    |
| ------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `urls`  | every address the hub is exposed at on the agent port; one of them is on the joining machine's network, so a program tries them in order |
| `token` | the enrolment ticket, valid for five minutes and spent once                                                                              |
| `fp`    | the fingerprint to pin                                                                                                                   |
| `role`  | `client` for a link from the Clients page, `agent` for one from the Devices page                                                         |

A program of the client role rejects a link whose `role` is `agent` with `link_not_for_client`. The base64url alphabet has no character a shell splits or a URL escapes, so the link pastes anywhere unquoted, and its `=` padding is optional: a decoder re-pads before decoding.

Making a link replaces whatever ticket was out, so one invitation is open at a time, and a hub restart forgets every ticket.

## Joining and leaving

A binding starts at `POST /api/channel/join` and ends at `POST /api/channel/leave`, both plain JSON on the pinned connection.

The join body has seven fields:

| Field        | Holds                                                                                                     |
| ------------ | --------------------------------------------------------------------------------------------------------- |
| `ticket`     | the `token` from the link                                                                                 |
| `role`       | `client`                                                                                                  |
| `protocol`   | the protocol number this build speaks, `1` in every 0.3.0 package                                         |
| `machine_id` | a uuid4 hex string this installation generates once and keeps                                             |
| `name`       | the computer's hostname, which the Clients page shows                                                     |
| `software`   | the program and its version, such as `neutrino_client/0.3.0`                                              |
| `platform`   | `{os, family, arch}`: `linux`, `windows` or `darwin`, the Linux distribution family, and the architecture |

The reply is `{id, token}`. The `id` is the binding id the hub generated when the link was made, and the `token` is a 192-bit secret that goes into every later `hello`. A program keeps both in a file only its own person can read.

Admission on `protocol` runs before anything else, so a rejected number spends no ticket. The ticket then leaves the hub's store in the same step that fetches it, so two programs racing one link cannot both join.

| Status | `detail`                                      | When                                                              |
| ------ | --------------------------------------------- | ----------------------------------------------------------------- |
| 409    | `protocol_too_old`, params `{peer, hub, min}` | the number is below the hub's `PROTOCOL_MIN`                      |
| 409    | `protocol_too_new`, params `{peer, hub, min}` | the number is above the hub's `PROTOCOL`                          |
| 409    | `role_mismatch`, params `{role}`              | the ticket was made for the other role                            |
| 401    | `ticket_spent`                                | the ticket is unknown, expired, already spent, or its row is gone |

An HTTP error's body is `{"detail": {"code": "...", "params": {}}}`, the same pair every refusal on the channel uses.

`POST /api/channel/leave` takes `{id, token}` and returns `{}`. The hub then removes the binding and revokes that client's gateway key, and the program deletes its own copy. A pair naming no binding is rejected with 401 `binding_unknown`.

## The socket

The socket is `wss://<hub-address>:8443/api/channel/socket`, where the address is the one the join succeeded at. It opens a fresh pinned connection, with the fingerprint checked again. A text frame is one JSON object whose `type` is one of the eight words; a binary frame is a big-endian `u32` stream id, then the bytes of that stream.

The hub pings every 20 seconds and drops a socket whose pong is more than 20 seconds late. `neutrino_client` treats 45 seconds of silence as a dead socket and reconnects with a backoff of 5 to 60 seconds.

### The handshake

The first frame each way is an identity card, and both cards have one shape. `hello` goes up within ten seconds of the socket opening, and `welcome` or `refused` comes down.

| Field      | `hello` (up)                        | `welcome` (down)     |
| ---------- | ----------------------------------- | -------------------- |
| `protocol` | the number this build speaks        | the hub's number     |
| `role`     | `client`                            | `hub`                |
| `id`       | the binding id                      | the hub's own id     |
| `name`     | the binding's name, or the hostname | the hub's name       |
| `software` | `neutrino_client/0.3.0`             | `neutrino_hub/0.3.0` |
| `token`    | the binding token                   | absent               |

The hub's `id` is a uuid generated at its setup and the `name` is what a person typed on its Settings page. A program joined to several hubs groups them by `id` and labels them by `name`, because the name changes and the id does not.

A rejected `hello` gets `refused {code, params}` and then close 4000. The handshake has no state hash; the first report has it.

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

## The stream layer

Everything beyond the two documents is a stream: its `open` is the request, its `close` is the reply, and `kind` is the whole method vocabulary.

| Concern       | Rule                                                                                                                                                          |
| ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Ids           | the hub opens streams with even ids and the peer with odd ids from 1 upward, each side counting on its own, so the two never collide                          |
| Bytes         | a binary frame is the stream id and then the bytes; a stream's text output is one line per frame                                                              |
| Credit        | `credit {stream, bytes}` grants the sender that many more bytes, and a receiver grants as it consumes; the hub's window is 1 MiB and its largest frame 64 KiB |
| Result        | `close {stream, code, params}` ends a stream from either side; an empty `code` makes `params` the result, and a code makes the close a refusal                |
| One close     | a stream one side closed gets no close back                                                                                                                   |
| Unknown kinds | a stream whose `kind` a program has no handler for is closed with `kind_unknown`                                                                              |

A client opens one kind, `service`, and the hub opens none to a client. The other kinds (`shell`, `file`, `command`, `package`, `log`, `desktop`) run between the hub and a device agent.

## The two documents

A client's half of the channel is two documents under one hash: `state` down, and `report` up.

### The state

```json
{
  "type": "state",
  "hash": "<state-hash>",
  "is_disabled": false,
  "services": [
    {
      "id": "samba_4b1c8f0d_media",
      "type": "file",
      "title": "media",
      "payload": {
        "protocol": "smb",
        "host": "192.168.100.24",
        "share": "media"
      },
      "is_healthy": true,
      "source": "module",
      "description": "published by the samba module on 192.168.100.24",
      "description_code": "samba_module",
      "description_params": { "host": "192.168.100.24" }
    }
  ]
}
```

| Field         | Holds                                                                                                               |
| ------------- | ------------------------------------------------------------------------------------------------------------------- |
| `hash`        | an opaque string the program keeps and names back in every report                                                   |
| `is_disabled` | `true` after **Disable** on the Clients page: the list is empty and every action is rejected with `client_disabled` |
| `services`    | the published list, resolved for the address this socket came from                                                  |

Each entry is `{id, type, title, payload, is_healthy, source, description, description_code, description_params}`:

| Field                | Holds                                                                                                                                       |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| `id`                 | what a `service` stream names                                                                                                               |
| `type`               | `web`, `port`, `ai`, `file` or `rdp`                                                                                                        |
| `title`              | the name a person reads                                                                                                                     |
| `payload`            | the type's own fields, in the next section                                                                                                  |
| `is_healthy`         | what the last probe measured, `null` where nothing probed it                                                                                |
| `source`             | `module` for a module on a device, `declared` for a person's own entry, `device` for a machine's desktop                                    |
| `description`        | the English provenance line                                                                                                                 |
| `description_code`   | the same provenance as a code a program words itself: `ai_gateway`, `container`, `declared`, `device_share`, `gitea_module`, `samba_module` |
| `description_params` | the values that sentence names                                                                                                              |

The hub sends one state on a connection's first report whose `state_hash` differs from its own, and after that whenever its own list changes. A program that reconnects from another network gets other hosts in the payloads, because the hub resolves every entry for the address the socket arrived from.

### The report

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

A report goes up as soon as the welcome is in, every 30 seconds after that, and once more whenever a state has been applied. `state_hash` is the hash of the state held, empty before the first one.

## The five service types

The `type` of an entry decides its payload and the button a person gets.

| `type` | `payload`                           | What a client does with it                                                                                |
| ------ | ----------------------------------- | --------------------------------------------------------------------------------------------------------- |
| `web`  | `{url}`                             | opens the address in the browser                                                                          |
| `port` | `{host, port}`                      | relays that address to a port on this computer's loopback                                                 |
| `ai`   | `{endpoint, protocol, models}`      | points a person's AI tools at the gateway; `protocol` is `openai` and `models` is what the gateway serves |
| `file` | `{protocol, host, share}`           | mounts the share; `protocol` is `smb`                                                                     |
| `rdp`  | `{protocol, host, port, attention}` | opens a RustDesk viewer at that address; `protocol` is `rustdesk` and `port` is 21118                     |

`attention` on an `rdp` entry is what somebody has to do at the sharing machine before a viewer sees anything: `rdp_nobody_seated` while no account is at the screen, `rdp_screen_not_allowed` while a Wayland session has not granted screen capture, and empty where a viewer gets the desktop.

## The service stream

An `rdp` and an `ai` entry take material the published list holds none of. The program opens a stream of kind `service` naming the entry, and the close is that material:

```json
{ "type": "open", "stream": 1, "kind": "service", "id": "rdp_4f21c0" }
```

| Entry's `type`        | The close's `params`                                                                                        |
| --------------------- | ----------------------------------------------------------------------------------------------------------- |
| `rdp`                 | `{host, port, password}`: the address as it resolves now, and the seat password unsealed for this one close |
| `ai`                  | `{base_url, api_key, model}`: the gateway, this client's own key, and the default model                     |
| `web`, `port`, `file` | empty; the entry's payload is the whole material                                                            |

A close with a code is a refusal, and the stream ends there:

| Code              | `params`       | Means                                                      |
| ----------------- | -------------- | ---------------------------------------------------------- |
| `service_unknown` | `{service_id}` | no entry with that id in the list resolved for this client |
| `rdp_not_shared`  | `{service_id}` | the machine stopped sharing its desktop                    |
| `client_disabled` |                | the client is switched off on the Clients page             |
| `vault_locked`    |                | the hub's vault is locked, so no secret can be unsealed    |
| `binding_unknown` |                | the hub holds no such client                               |

## Refusals and the binding

A refusal is `{code, params}` wherever it appears: as `detail` on an HTTP error, as a `refused` frame at the handshake, and as the code on a stream's close.

| Code               | Where                      | What it does to the binding                                     |
| ------------------ | -------------------------- | --------------------------------------------------------------- |
| `protocol_too_old` | `join`, `hello`            | keeps it; record the code and send `hello` again a minute later |
| `protocol_too_new` | `join`, `hello`            | keeps it, the same way                                          |
| `ticket_spent`     | `join`                     | nothing is bound yet; the person makes a fresh link             |
| `role_mismatch`    | `join`, `hello`            | keeps it                                                        |
| `binding_unknown`  | `hello`, `leave`, a stream | unbinds: delete the binding and join again with a new link      |
| `kind_unknown`     | a stream                   | keeps it                                                        |

`binding_unknown` is the one refusal that unbinds, because it says the row was deleted on the panel, and only the hub holding the pinned certificate can say it.

| Close code | Meaning                                                                                                                                           |
| ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| 4000       | `refused`; the `refused` frame before it says why                                                                                                 |
| 4010       | `replaced`: a second socket opened for the same binding and this one is closed. Reconnecting is a person's action, such as the window's reconnect |

## Protocol numbers

Compatibility between a hub and a program is one integer each build declares, `PROTOCOL`, and package versions take no part in it. A hub also has `PROTOCOL_MIN`, the oldest number it still accepts, and admits a peer whose number is within `PROTOCOL_MIN` to `PROTOCOL`.

Reading is tolerant and writing is strict: an unknown field is ignored, an unknown kind is closed with `kind_unknown`, and a program sends only what its own number defines.

| Rule                                                                                       | Effect on the number                                                              |
| ------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------- |
| Adding a kind, a field or a code                                                           | unchanged, and a patch release can add them                                       |
| Removing anything, or changing its meaning                                                 | one higher                                                                        |
| Changing the link, the ticket, the pin, or the words `hello`, `state`, `report` and `open` | one higher                                                                        |
| A number one higher                                                                        | a new minor version before 1.0, a new major after it                              |
| `PROTOCOL_MIN`                                                                             | rises only when a new minor opens, at most to the number the previous minor spoke |

| `PROTOCOL` | First minor |
| ---------- | ----------- |
| 1          | 0.3.0       |
