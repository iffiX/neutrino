# The connection

A connection is the one TLS socket a client or an agent holds to the hub's
agent port, 8443. Every service a client uses goes over it as a stream, and
the hub dials each service on the client's behalf. This page says what happens
on the port before a peer is admitted, what an admitted peer can reach, and
which limits hold.

The frames, the stream layer and the timings are in
[protocol.md](protocol.md), "The channel". The relay's operation is in
[modules/network.md](modules/network.md), "The relay, the third way in".

On this page an entry is one service the hub publishes, a kind is the
permission an entry falls under, and a binding is the record of one enrolled
peer.

## One port, one connection

| Rule | Reason |
| --- | --- |
| A client dials the hub's agent port and no other address. Files, web pages, ports, the panel, remote desktops, terminals and the AI gateway are streams on that one socket. | A person outside the home needs one reachable port. A service's address, port and secret stay inside the hub's LAN. |
| An agent dials the same port and listens on none of its own for the hub. | A managed machine behind a firewall or a NAT is reached over the socket it opened. |
| The hub relays every stream, on the LAN and from outside alike. Each of a client's streams ends at the hub. | A relayed stream works with the routes a home already has. One path has one set of permission checks. |
| A machine's own services stay reachable on its LAN at their own ports, under each service's own login. | A person at home keeps the tools they already use. The connection is the way from a client, and it closes no other way. |
| A stream is one TCP connection, or every datagram of one UDP `port` entry. A `port` entry states one protocol, TCP or UDP, and every other kind is TCP. | A container or a declared service on UDP is published the same way as one on TCP. One protocol for each entry gives each entry one permission check and one health check. |
| A UDP stream sends one datagram in one frame, with the port the datagram left from on the client's machine in front of it. The far end keeps one socket for each such port, at most `CHANNEL_UDP_SOURCES_MAX`, 64, the one idle the longest giving way, and closes a socket after `CHANNEL_UDP_IDLE_TIMEOUT_S`, 60 seconds, with no datagram. A datagram that arrives without credit is dropped. | A reply returns to the local program that asked, and two programs on one forward stay two peers to the service. UDP has no close of its own and permits loss. A queue of datagrams adds delay and has no bound. |

## Where the port is reached

The port is one listener on two sockets, one for IPv4 and one for IPv6
([modules/network.md](modules/network.md), "Direct"). A way in adds an
address to the link's and the state's `urls` and changes nothing else about
the port.

| Way in | The peer reaches the port at | Who else reaches it there |
| --- | --- | --- |
| The LAN | an exposed interface's address | every host on that network |
| NetBird, EasyTier | the hub's address on the overlay | every peer of that overlay |
| The relay | the public port of the person's own server, which the hub forwards to its loopback | every host on the internet |
| Direct | every enabled interface, at its IPv4 addresses and its stable IPv6 addresses, and the public address the person states for the hub. One switch on the **Access** page opens the port there, under the **Network** page's firewall rules. | every host that reaches such an interface or that address |

| Rule | Reason |
| --- | --- |
| Direct opens the agent port alone on an interface. The panel, the AI gateway and every other listener keep the exposure the **Network** page gives them ([modules/network.md](modules/network.md), "What answers, and where"). | The agent port admits a peer by a token and a pinned certificate. The panel admits a browser by a password, and a password on a public address is open to guessing. |
| The port treats a peer the same on every way in. No rule on it depends on the address a peer arrives from. | Through the relay every peer arrives from loopback, so an address says nothing about the peer. |
| A client dials every candidate address of the hub at once, at every round: the hub's address on each virtual network that is up, the hub's name, and `urls`. The first socket to complete TLS with the pinned fingerprint carries the round's one `hello`, and the client closes the others before any `hello` on them ([client.md](client.md), "The Hubs page"). No address is preferred for having worked last, no prober runs between rounds, and each address keeps its own connect time. A network change (a virtual network turning on, the device's connectivity changing, or new `urls` in the state) starts one round at once, and its winner takes a live channel only on a better path. | Under an order, a client on a network the first addresses do not reach waits out each of their connect times before the address that works. Dialling at once costs the hub one unadmitted socket per address for a few seconds. |
| An agent tries `urls` in a fixed order, at every reconnect as at its first connect: the hub's name on the current network, then `urls` in the hub's order, the relay last. The address that last worked is not tried earlier for having worked, and a connected channel is not moved because a nearer address answers again. | The nearest address is tried first, and the path through another server is the last resort; an address taken while a nearer one refused for a moment, as during a hub restart, would otherwise stay in use after the nearer one is back. |
| The hub treats each socket of a client's round as any socket: it counts among the unadmitted ones until it closes or its `hello` is admitted. A second admitted socket of one binding replaces the earlier one, which the hub closes with 4010 `replaced` ([protocol.md](protocol.md), "What a refusal does to the binding"). | A binding holds one socket. The client sends one `hello` per round, so its own round never replaces itself. |

## Before a peer is admitted

A peer is admitted when its `hello` holds a token the hub has on record. Until
then the peer is anyone, and the hub spends on it only what recognising it
costs. The steps run inside the panel's process, which is root
([privilege.md](privilege.md)), so the list stays this short.

| Step | What the hub does | Why it comes before admission |
| --- | --- | --- |
| Accept | Counts the socket among the unadmitted ones and reads nothing from it yet. | The count is the bound on what unadmitted peers hold open. |
| TLS | Completes the handshake with the agent certificate. The peer presents no certificate. | A peer pins the hub's certificate, and the hub identifies a peer by its token. |
| HTTP | Returns an answer on `POST /api/channel/join`, `POST /api/channel/leave` and the upgrade at `/api/channel/socket`. Every other path returns 404, the API description among them. | A join spends a ticket and a leave names a token, so both arrive before any session exists. Every other route belongs to the panel's ports. |
| Upgrade | Reads one text frame, the `hello`, and validates its shape. | The token is inside it. |
| Token | Looks the token's hash up among the clients or the agents, by the role the `hello` states. | This is admission. |

A `join` is checked in this order: the protocol number, whether joins are
paused, then the ticket. A paused join returns before any ticket is looked up,
so a flood of joins tests no ticket.

## What an unadmitted peer can cost the hub

Each limit is one count for the whole port, across every peer address and
both sockets, and the message cap holds on admitted sockets too. The first-byte time and the
admission time start at the accept; the handshake time starts at the first
byte. The constants are in the hub's `modules/channel/constants.py`.

| Limit | Constant | At the limit | Reason |
| --- | --- | --- | --- |
| a socket that has sent no byte | `CHANNEL_FIRST_BYTE_TIMEOUT_S` 3; on Windows the TLS handshake's 10 seconds, counted from the accept | the socket is closed | A peer starts its handshake within a round trip. A socket held open and silent is the cheapest way to fill the port. The event loop a Windows hub runs on cannot learn that a byte has arrived without reading it, and a byte read there is lost to the TLS layer. |
| a TLS handshake's time | `CHANNEL_TLS_HANDSHAKE_TIMEOUT_S` 10 | the socket is closed | A handshake over the slowest way in completes in under a second. |
| the time from accept to an admitted `hello` | `CHANNEL_ADMISSION_TIMEOUT_S` 30 | the socket is closed; a `join` or `leave` in flight counts toward that time | It bounds how long one unadmitted socket holds a place. |
| sockets that have not passed `hello` | `CHANNEL_UNADMITTED_MAX` 128 | one of them is closed to make room: the oldest that has not finished TLS, and the oldest of all when every one has | A peer that has finished TLS has done work a flood of bare sockets has not, so it keeps its place longest. |
| one message on a socket | `CHANNEL_MESSAGE_BYTES_MAX` 2 MiB | the socket is closed with 1009 before the message is read | Four times the largest message a hub of 64 machines and 256 entries carries, a client's `state` of about 270 KB. A data frame is at most `CHANNEL_CHUNK_BYTES`, 64 KiB, and its stream id. Without a cap of its own the server library buffers 16 MiB for each socket. |
| the body of a `join` or a `leave` | `CHANNEL_REQUEST_BYTES_MAX` 64 KiB | 413 `request_too_large {limit}`, before the body is parsed: at once when `Content-Length` is past the limit, else when the bytes read pass it | Both bodies are a few short fields. |
| the answer to the hub's keepalive ping on an admitted socket | `CHANNEL_PING_INTERVAL_S` 20 between pings, `CHANNEL_PING_TIMEOUT_S` 60 for the answer | the socket is closed with 1011 and every stream on it ends; the hub's journal says so in one line, at most once a minute for each peer address | The ping waits behind what the socket already queued: a desktop stream may hold 1 MiB unconfirmed, and 60 seconds covers a queue of about 2 MB at 256 kbit/s, where 20 seconds dropped a working desktop every few minutes. |
| channel sockets past `hello` | `CHANNEL_SOCKETS_MAX` 512 | the next `hello` is refused `channel_full {limit}` | One binding holds one socket, and a home has far fewer than 512 bindings. |
| failed admissions across the hub | `CHANNEL_ADMISSION_FAILURES_MAX` 30 within `CHANNEL_ADMISSION_WINDOW_S` 60 | every `join` returns 409 `admission_paused {retry_after_s}` until the oldest failure leaves the window | It ends a search for a ticket long before the search can succeed. |

| Rule | Reason |
| --- | --- |
| A failed admission is a wrong credential: a `join` refused `ticket_spent` or `role_mismatch`, or a `hello` refused `binding_unknown`. A timeout, a malformed frame and a socket closed to make room are not counted. | A port scan produces timeouts and malformed bytes. Counted, they pause every new enrolment for a peer that holds a valid link. |
| The `welcome` follows a valid `hello` within a second. Between the two the hub runs no overlay engine's command: the network a client arrived from is read from the overlay devices the last converge recorded, which the address sampler keeps current every `WEB_ADDRESS_SAMPLE_INTERVAL_S`, and an engine the converge did not record is not asked. | A client gives up after its 10-second connect time, and on Windows a status command against NetBird's daemon that is not running takes 10 seconds and EasyTier's 2; asked twice each, they kept a hub's `welcome` 24 seconds away and no client connected. |
| A pause holds back `join` alone. A `hello`, which every reconnecting peer sends, is judged as always. | Every bound peer with a valid token is admitted throughout a flood. |
| The peer's address is the socket's own. The agent port and the panel ignore forwarded-address headers. | Through the relay, and through the panel entry, a request arrives from loopback, where a header a peer wrote is otherwise believed. |
| An IPv4-mapped IPv6 address, `::ffff:a.b.c.d`, is read as `a.b.c.d` wherever a peer's address is judged or recorded: the port's counts, a join's recorded address, the loopback check and `reached_through`. | A dual-stack socket reports an IPv4 peer that way, and a mapped `127.0.0.1` is loopback. |
| On Windows the event loop cannot watch a socket for its first byte, so the handshake starts at the accept and the handshake time, 10 seconds, stands in for the first-byte time, on both sockets. | The bound on a silent socket holds, at the longer of the two times. |

## Admission

| Credential | What it is | How long it holds | How the hub keeps it |
| --- | --- | --- | --- |
| The ticket | 18 random bytes inside an enrolment link | 30 minutes, one use, one open ticket for each role | its SHA-256, on disk, so an unused link holds across a hub restart |
| The token | 24 random bytes returned by `join` | until the peer leaves or the binding is removed | its SHA-256, compared in constant time |
| The certificate's fingerprint | the SHA-256 of the agent certificate, inside the link | as long as the certificate, ten years | the peer keeps it and checks it after every handshake, before it sends a byte |

| Rule | Reason |
| --- | --- |
| A link is generated by a person signed in to the panel and reaches a peer by a scan or a paste. | The fingerprint and the ticket have no other channel, so a link's address with a wrong certificate is an impersonation and ends the enrolment. |
| A client link also holds what joins the hub's overlays: the NetBird setup key, or the EasyTier network's secret. | A client away from the LAN joins the overlay first and reaches the port through it. With the material fetched over the connection, a first scan outside the home reaches nothing. |
| That material holds until the person replaces the setup key or changes the network's secret on the **Access** page. The panel shows a link to a signed-in person only. | A copy of a spent link still joins the overlay. It reaches the port there and holds no token to be admitted with. |
| A client and an agent are told apart by the table their token is in, and each role opens only its own kinds of stream. | One listener serves both, and an agent's token opens nothing a client opens. |

## Streams on the connection

A client names an entry by its id. The hub takes the host and the port from
the entry, and reads the secret a service needs from its own store.

| Kind | The client opens on its own machine | On the connection | The hub checks | The service is reached by |
| --- | --- | --- | --- | --- |
| Files | Linux and macOS: a loopback port and a system mount. Windows: the file network card and a drive letter. Android: nothing, the app reads the share itself. | one `connect` for each SMB connection | the `file` kind and the machine | the agent, at the machine's loopback port 445; the hub itself for a declared host |
| Web pages | a loopback port, and the browser | a `service` for the token where the page has one, then one `connect` for each connection | the `web` kind and the machine | the agent, at the page's loopback port; the hub itself for a declared page |
| Ports | a loopback port, TCP or UDP as the entry states | one `connect` for each TCP connection, or one for a UDP entry | the `port` kind and the machine | the agent for a container's port; the hub itself for a declared one |
| The panel | a loopback port, and the browser | a `service` for a sign-in token, then one `connect` for each connection | the `panel` kind | the hub, at the panel's loopback HTTP port |
| Remote desktops | a loopback port, and the viewer | a `service` for the seat password, then one `connect` for each connection | the `rdp` kind, the machine, and that the machine reports the share, which it does only while its Remote desktop switch is on | the agent, at the viewer port on the machine's loopback |
| Terminals | a terminal in the client's window | one `shell`, and a `command` for each resize, persist, share and end | the `terminal` kind and the machine | the agent, which keeps the session and runs the shell as the machine's Terminal module names, root by default |
| Remote commands | `nclient terminal exec`, its stdin, stdout and stderr | one `exec`, and a `command` for each resize with `--tty` | the `exec` kind and the machine | the agent, which runs the command once as the machine's Terminal module names, root by default, and keeps nothing |
| The AI gateway | a loopback port the AI tools point at | a `service` for the client's key, then one `connect` for each connection | the `ai` kind | the hub, at the gateway's loopback port |

## What an admitted client reaches

| Rule | Reason |
| --- | --- |
| A stream names an entry id, the panel, or a machine for a shell or a command. The host and the port come from the hub's own records. | A stolen client token reaches what the hub publishes to that client. |
| The hub judges every `open` against the client's kinds and each kind's machines, then dials. | A permission changed on the **Clients** page holds for the next stream without a reconnect. |
| An agent dials a port only while its machine publishes that port, and closes any other with `port_not_published {port}`. | The agent makes the check itself, so a fault in the hub's check opens no port the machine does not publish. |
| Switching a client off, deleting it, or taking a kind or a machine from it immediately closes what the change covers: the socket, or the shells, the commands, the `connect` streams and the panel sessions of that kind. | A person switches a client off because the device is lost. A shell that stays open is the access they meant to end. |
| The panel is a kind like the others: the **Clients** page sets it in the default and for each client. A new hub's default has it off. A client with it receives a sign-in token of 32 random bytes that holds 60 seconds for one use. | The panel changes the hub itself, so a person turns it on for the devices that are their own. |
| A client joins a terminal session that is its own or is shared, on a machine its `terminal` kind includes. A `shell` or a `persist` on any other session is refused `session_not_owned {session_id}`. | A session is a shell as root, or as the account the machine's Terminal module names, with its output on screen. A session that stops being shared closes to every viewer but its owner. |
| A socket holds at most `CHANNEL_CONNECT_STREAMS_MAX`, 256, `connect` streams, and each stream is sent under the receiver's credit. | One client cannot exhaust the hub's sockets or its memory. |

## What a client opens on its own machine

| Rule | Reason |
| --- | --- |
| A forwarder listens on `127.0.0.1` and accepts any connection made on that machine. | The machine's accounts are the person's own. Loopback is the one boundary Linux, macOS and Windows share. |
| A datagram waits in two places, each until the stream's first credit and at most 16 of them, and the rest are dropped: the client's forward before the hub's first credit (`CLIENT_UDP_HELD_DATAGRAMS_MAX`), and the hub before the agent's first credit on the agent's stream (`CHANNEL_UDP_HELD_DATAGRAMS_MAX`). No datagram waits anywhere else. | A program's first datagram is often its only one. A bounded hold keeps it without a queue. |
| A page behind a forwarder keeps its own token or login where it has one. | A program on the client machine that finds the port still needs the page's secret. |
| The Windows file network card has an address of its own, and its gateway and DNS fields are empty. Its endpoint returns an error for UDP. | Windows mounts SMB only on port 445 of an address. The card gives each share an address that leads to the client's own endpoint. |

## Why the hub relays everything

A client on the same overlay as a machine has a direct path to it, and the
hub relays the client's streams all the same. The relayed path works with
what a home already has: its LAN and one reachable port.

## What one socket costs

| Limit | What follows from it |
| --- | --- |
| Every stream shares one TCP socket. A lost packet holds every stream on the socket until it is sent again. | A stall on one stream is a stall on all of them, for the length of one retransmission. |
| A datagram in a stream keeps its boundary and loses its timing. It arrives late where plain UDP loses it. | UDP over the connection suits request and reply traffic: DNS, time, discovery, a small game server. Voice, video and fast games need a direct path. |
| The hub's uplink and its one process bound the speed of every stream. Through the relay the server's bandwidth bounds it too. | Terminals, editors, a desktop and ordinary file copies fit inside that bound. A transfer that needs the line's full speed uses a direct path. |
| A direct path is a subnet route the person sets up in the overlay's own console. The hub lists the served networks for it and manages no route there. | That path is outside the connection. It reaches a machine's own ports under each service's own login, with no kind and no entry in between. |
