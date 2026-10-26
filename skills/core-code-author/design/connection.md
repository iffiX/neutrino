# The connection

A connection is the one session a client or an agent holds to the hub's
agent port, 8443 unless the **Network** page sets another: a TCP
connection carrying a Noise handshake and a go-yamux session, which the
hub's transport holds. Every service a client uses goes over it as a
stream, and the hub dials each service on the client's behalf. This page says what happens
on the port before a peer is admitted, what an admitted peer can reach, and
which limits hold.

The knock, the handshake, the frames, the stream layer and the timings are
in [protocol.md](protocol.md), "The channel". The relay's operation is in
[hub_components/network.md](hub_components/network.md), "The relay, the third way in", and
SakuraFrp's and OpenFrp's in its "SakuraFrp and OpenFrp".

On this page an entry is one service the hub publishes, a kind is the
permission an entry falls under, and a binding is the record of one enrolled
peer.

## One port, one connection

| Rule | Reason |
| --- | --- |
| A client dials the hub's agent port and no other address. Files, web pages, ports, the panel, remote desktops, terminals and the AI gateway are streams on that one session. | A person outside the home needs one reachable port. A service's address, port and secret stay inside the hub's LAN. |
| An agent dials the same port and listens on none of its own for the hub. The one port it opens for the machine's AI tools is on its own `127.0.0.1`, and for the machine's containers on the Podman bridges on Linux and on WSL's vEthernet adapter on Windows, each with a firewall rule scoped to that interface where the machine's firewall drops it ([agent.md](agent.md), "The listeners a container reaches"). Their connections go to the hub over that session. | A managed machine behind a firewall or a NAT is reached over the session it opened, and the AI gateway answers on the hub's loopback alone. |
| The hub relays every stream, on the LAN and from outside alike. Each of a client's streams ends at the hub. | A relayed stream works with the routes a home already has. One path has one set of permission checks. |
| A machine's own services stay reachable on its LAN at their own ports, under each service's own login. | A person at home keeps the tools they already use. The connection is the way from a client, and it closes no other way. |
| A stream is one TCP connection, or every datagram of one UDP `port` entry. A `port` entry states one protocol, TCP or UDP, and every other kind is TCP. | A container or a declared service on UDP is published the same way as one on TCP. One protocol for each entry gives each entry one permission check and one health check. |
| A UDP stream sends one datagram in one record, with the port the datagram left from on the client's machine in front of it. The far end keeps one socket for each such port, at most `UdpSourcesMax`, 64, the one idle the longest giving way, and closes a socket after `UdpIdleTimeout`, 60 seconds, with no datagram. A datagram its stream cannot take at once is dropped. | A reply returns to the local program that asked, and two programs on one forward stay two peers to the service. UDP has no close of its own and permits loss. A queue of datagrams adds delay and has no bound. |

## Where the port is reached

The port is the transport's one listener on two sockets, one for IPv4 and
one for IPv6 ([hub_components/network.md](hub_components/network.md),
"Direct"). Two more listeners of the transport on `127.0.0.1`, one per frp
vendor, serve the same channel to frpc on the hub alone ("The loopback
listeners" there). A way in adds an address to the
link's and the state's `urls` and changes nothing else about the port.

| Way in | The peer reaches the port at | Who else reaches it there |
| --- | --- | --- |
| The LAN | the hub's address in an exposed segment | every host whose address is inside that segment |
| NetBird, EasyTier | the hub's address on the overlay | every peer of that overlay |
| The SSH relay | the public port of the person's own server, which the hub forwards to its loopback | every host on the internet |
| Direct | every enabled interface, at its IPv4 addresses and its stable IPv6 addresses, and the public address the person states for the hub. One switch on the **Access** page opens the port there to every sender. | every host that reaches such an interface or that address |
| SakuraFrp, OpenFrp | the public port of the vendor's node, which frpc on the hub forwards to that vendor's loopback listener | every host on the internet |

| Rule | Reason |
| --- | --- |
| Direct opens the agent port alone, to every sender on an enabled interface. The panel and the hub's other ports keep the exposure the **Network** page gives them ([hub_components/network.md](hub_components/network.md), "What answers, and where"). | The agent port answers only a knock made with the hub's static key, and admits a peer by its own static key and its binding. The panel admits a browser by a password, and a password on a public address is open to guessing. |
| A change of the port's number reaches every online client and agent in `urls` first, and the port moves at once after. A peer offline at that moment joins again with a new link. | A peer reaches the hub only at an address it was given, so the new one is given before the old one closes. |
| The port treats a peer the same on every way in. No rule on it depends on the address a peer arrives from or the listener it arrives on; the listener names the way in and nothing else. | Through the relay and the frp nodes every peer arrives from loopback, so an address says nothing about the peer. |
| A client dials every candidate address of the hub at once, at every round: the hub's address on each virtual network that is up, the hub's name, and `urls`. The first connection whose handshake completes under the binding's `hub_key` carries the round's one `hello`, and the client closes the others before any `hello` on them ([client.md](client.md), "The Hubs page"). No address is preferred for having worked last, no prober runs between rounds, and each address keeps its own connect time; an address that refuses is dialled again every second until the round's connect time ends. A network change (a virtual network turning on, the device's connectivity changing, or new `urls` in the state) starts one round at once, and its winner takes a live channel only on a better path. | Under an order, a client on a network the first addresses do not reach waits out each of their connect times before the address that works. Dialling at once costs the hub one unadmitted connection per address for a few seconds. |
| An agent tries `urls` in a fixed order, at every reconnect as at its first connect: the hub's name on the current network, then `urls` in the hub's order, the frp nodes and the relay last. The address that last worked is not tried earlier for having worked, and a connected channel is not moved because a nearer address answers again. | The nearest address is tried first, and the path through another server is the last resort; an address taken while a nearer one refused for a moment, as during a hub restart, would otherwise stay in use after the nearer one is back. |
| The hub treats each connection of a client's round as any connection: it counts among the unadmitted ones until it closes or its `hello` is admitted. A second admitted session of one binding replaces the earlier one, which the hub ends with `refused {code: replaced}` ([protocol.md](protocol.md), "What a refusal does to the binding"). | A binding holds one session. The client sends one `hello` per round, so its own round never replaces itself. |

## Before a peer is admitted

A peer is admitted when its handshake completes under a static key a binding
holds and its `hello` names that binding. Until then the peer is anyone, and
the hub spends on it only what recognising it costs. The steps run in the
transport, a process of its own that is not root
([privilege.md](privilege.md)), and the one step that reaches the hub's
Python is a local question.

| Step | What the transport does | Why it comes before admission |
| --- | --- | --- |
| Accept | Counts the connection among the unadmitted ones and reads nothing from it yet. | The count is the bound on what unadmitted peers hold open. |
| Knock | Reads the knock and checks its version, its length and `mac1`, one keyed hash, then, while under load, `mac2` ("Under load"). A knock that fails is answered with nothing and the connection closes. | A knock costs the peer the hub's public key, which only a link carries, and costs the hub one hash before any Diffie-Hellman. A port that answers nothing to a scan is a port a scan does not find. |
| Message 1 | Opens message 1, which costs two Diffie-Hellman operations, and checks `time` against the replay window. | The peer's static key and its intent are inside it. |
| Question | Asks the hub's Python whose the static key is (`peer`), or, for a join, nothing until the `join` frame (`ticket`). | The Python holds every binding. |
| Answer | Writes message 2 under the psk the answer names, and starts the session. | A refusal is said under the hub's key, so the peer can trust it. |
| `hello` | Reads the first frame on the control stream and passes it to the Python, which sends `welcome` or `refused`. | The binding id is checked against the key that made the session. |

| Rule | Reason |
| --- | --- |
| The replay window is per static key: the transport keeps, for each key it accepted a knock from, the latest `time` it accepted, for at most `KnockReplayKeysMax`, 65536, keys, the one used longest ago giving way. A knock whose `time` is not later is answered with nothing. A transport that starts again keeps no window, and the first knock of each key is accepted. | A captured knock replayed costs the hub one Diffie-Hellman and no answer. The peer's clock is the only clock it has, so the window compares a key with itself and never with the hub's time. |
| A join's static key is new to the hub, so its knock is judged by the same window, and its ticket by the hub's Python in the `join` frame, inside the encrypted session. | The ticket never crosses the wire in a form a listener reads. |
| A knock that names a key no binding holds is completed under the zero psk and refused `binding_unknown`, and counts as a failed admission. | The peer learns from a source it can trust that its binding is gone, and a search for keys pauses the joins like a search for tickets. |

## What an unadmitted peer can cost the hub

Each limit is one count for the whole port, across every peer address and
both sockets, and the frame cap holds on admitted sessions too. The
first-byte time, the handshake time and the admission time start at the
accept. The constants are the transport's, apart from the failed admissions,
which the hub's Python counts in `modules/channel/constants.py`.

| Limit | Constant | At the limit | Reason |
| --- | --- | --- | --- |
| a connection that has sent no byte | `KnockFirstByteTimeout` 3 s | the connection is closed | A peer sends its knock within a round trip. A connection held open and silent is the cheapest way to fill the port. |
| the knock and the answer | `HandshakeTimeout` 10 s | the connection is closed | A handshake over the slowest way in completes in under a second. |
| the time from accept to an admitted `hello` | `AdmissionTimeout` 30 s | the connection is closed; a `join` or a `leave` in flight counts toward that time | It bounds how long one unadmitted connection holds a place. |
| connections that have not passed `hello` | `UnadmittedMax` 128 | one of them is closed to make room: the oldest that has not finished its handshake, and the oldest of all when every one has | A peer that has finished its handshake has done work a flood of bare connections has not, so it keeps its place longest. |
| knocks whose message 1 is being opened or whose question is open | `HandshakesInFlightMax` 64 | a further knock is closed with nothing written | The Diffie-Hellman and the question are the costly steps, and the limit bounds both at once. |
| under load: knocks in flight past `CookieLoadThreshold`, 16 | `CookieSecretLifetime` 120 s, the cookie secret's life and the cookie's | a knock without a valid `mac2` is answered with a cookie reply and closed ("Under load") | WireGuard's answer to a flood of knocks: the peer proves it reads what the hub writes to its address before the hub spends a Diffie-Hellman on it. |
| one control frame | `ControlFrameBytesMax` 2 MiB | the session is ended | Four times the largest frame a hub of 64 machines and 256 entries carries, a client's `state` of about 270 KB. |
| one record | `RecordBytesMax` 64 KiB | the stream is reset | A record is a chunk of a stream, never a whole file. |
| the answer to yamux's keepalive on an admitted session | `KeepAliveInterval` 20 s between pings, `KeepAliveTimeout` 60 s for the answer | the session ends and every stream on it ends; the transport writes one line for it, at most once a minute for each peer address | The ping waits behind what the session already queued: a desktop stream can hold a full window unconfirmed, and 60 seconds covers it at a slow uplink. |
| admitted sessions | `SessionsMax` 512 | the next `hello` is refused `channel_full {limit}` | One binding holds one session, and a home has far fewer than 512 bindings. |
| failed admissions across the hub | `CHANNEL_ADMISSION_FAILURES_MAX` 30 within `CHANNEL_ADMISSION_WINDOW_S` 60 | every `join` is refused `admission_paused {retry_after_s}` until the oldest failure leaves the window | It ends a search for a ticket long before the search can succeed. |

### Under load

| Rule | Reason |
| --- | --- |
| The transport is under load while more than `CookieLoadThreshold` knocks are in flight. Under load, a knock whose `mac2` does not verify is answered with a cookie reply and the connection closes; a knock whose `mac2` verifies is taken as any knock. | A peer that holds a cookie has read an answer the hub wrote to its address, which a sender that never reads cannot do. |
| The cookie is keyed by the peer's address alone, never its port, and the secret is made afresh every `CookieSecretLifetime`. | Each connection of a peer has a new source port, and the peer knocks again on a new connection. |
| No limit is keyed by the peer's address: the cookie proves the address reads, and nothing counts per address. | Through the relay and the frp nodes every peer arrives from loopback, so an address limit holds every peer behind one server to one peer's share. |

| Rule | Reason |
| --- | --- |
| A failed admission is a wrong credential: a `join` refused `ticket_spent` or `role_mismatch`, or a knock refused `binding_unknown`. A timeout, a wrong knock, a malformed frame and a connection closed to make room are not counted. | A port scan produces timeouts and malformed bytes. Counted, they pause every new enrolment for a peer that holds a valid link. |
| The `welcome` follows a valid `hello` within a second. Between the two the hub runs no overlay engine's command: the network a client arrived from is read from the overlay devices the last converge recorded, which the address sampler keeps current every `WEB_ADDRESS_SAMPLE_INTERVAL_S`, and an engine the converge did not record is not asked. | A client gives up after its 10-second connect time, and on Windows a status command against NetBird's daemon that is not running takes 10 seconds and EasyTier's 2; asked twice each, they kept a hub's `welcome` 24 seconds away and no client connected. |
| A pause holds back `join` alone. A bound peer's knock and `hello`, which every reconnecting peer sends, are judged as always. | Every bound peer with a valid key is admitted throughout a flood. |
| The peer's address is the connection's own, which the transport gives the hub's Python. The agent port and the panel ignore forwarded-address headers. | Through the relay, a frp node and the panel entry, a connection arrives from loopback, where a header a peer wrote is otherwise believed. |
| An IPv4-mapped IPv6 address, `::ffff:a.b.c.d`, is read as `a.b.c.d` wherever a peer's address is judged or recorded: the cookie, a join's recorded address, the loopback check and `reached_through`. | A dual-stack socket reports an IPv4 peer that way, and a mapped `127.0.0.1` is loopback. |

## Admission

| Credential | What it is | How long it holds | How the hub keeps it |
| --- | --- | --- | --- |
| The hub's static key | a Curve25519 key pair, its public half inside the link | as long as the hub keeps it | the transport keeps the private half; every binding keeps the public half |
| The ticket | 18 random bytes inside an enrolment link | 30 minutes, one use, one open ticket for each role | its SHA-256, on disk, so an unused link holds across a hub restart |
| The peer's static key | a Curve25519 key pair the peer makes when it first reads a link | until the peer leaves or the binding is removed | the peer keeps the private half in its binding; the hub keeps the public half on the binding's row |
| The token | 24 random bytes returned in `joined` | as long as the binding | its SHA-256, which is the psk of every later handshake ([protocol.md](protocol.md), "The session") |

| Rule | Reason |
| --- | --- |
| A link is generated by a person signed in to the panel and reaches a peer by a scan or a paste. | The hub's public key and the ticket have no other channel, so a link's address that answers without the hub's private key is an impersonation and ends the enrolment. |
| A client link also holds what joins the hub's overlays: the NetBird setup key, or the EasyTier network's secret. | A client away from the LAN joins the overlay first and reaches the port through it. With the material fetched over the connection, a first scan outside the home reaches nothing. |
| That material holds until the person replaces the setup key or changes the network's secret on the **Access** page. The panel shows a link to a signed-in person only. | A copy of a spent link still joins the overlay and still knocks: it reaches the port there and holds no binding to be admitted with. |
| A bound peer's handshake proves both of its secrets at once: its static key in Noise's own messages, and its token by the psk. | The hub's records, the psk and the peer's public key, admit nobody without the peer's private key, which only the peer's binding file holds. |
| A client and an agent are told apart by the table their key is in, and each role opens only its own kinds of stream. | One listener serves both, and an agent's key opens nothing a client opens. |

## Streams on the connection

A client names an entry by its id. The hub takes the host and the port from
the entry, and reads the secret a service needs from its own store.

| Kind | The client opens on its own machine | On the connection | The hub checks | The service is reached by |
| --- | --- | --- | --- | --- |
| Files | Linux and macOS: a loopback port and a system mount. Windows: the file network card and a drive letter. Android and iOS: nothing, the app reads the share itself. | one `connect` for each SMB connection | the `file` kind and the machine | the agent, at the machine's loopback port 445; the hub itself for a declared host |
| Web pages | a loopback port, and the browser | a `service` frame for the token where the page has one, then one `connect` for each connection | the `web` kind and the machine | the agent, at the page's loopback port; the hub itself for a declared page |
| Ports | a loopback port, TCP or UDP as the entry states | one `connect` for each TCP connection, or one for a UDP entry | the `port` kind and the machine | the agent for a container's port; the hub itself for a declared one |
| The panel | a loopback port, and the browser | a `service` frame for a sign-in token, then one `connect` for each connection | the `panel` kind | the hub, at the panel's loopback HTTP port |
| Remote desktops | a loopback port, and the viewer | a `service` frame for the seat password, then one `connect` for each connection | the `rdp` kind, the machine, and that the machine reports the share, which it does only while its Remote desktop switch is on | the agent, at the viewer port on the machine's loopback |
| Terminals | a terminal in the client's window | one `shell`, a `resize` record for each resize, and a `persist` or `stop_session` frame for each persist, share and end | the `terminal` kind and the machine | the agent, which keeps the session and runs the shell as the machine's Terminal module names, root by default |
| Commands | `nclient terminal exec`, its stdin, stdout and stderr | one `exec`, and a `resize` record for each resize with `--tty` | the `terminal` kind and the machine, as for a terminal | the agent, which runs the command once as the machine's Terminal module names, root by default, and keeps nothing |
| The AI gateway | a loopback port the AI tools point at | a `service` frame for the client's key, then one `connect` for each connection | the `ai` kind | the hub, at the gateway's loopback port |

## What an admitted client reaches

| Rule | Reason |
| --- | --- |
| A stream names an entry id, the panel, or a machine for a shell or a command. The host and the port come from the hub's own records. | A stolen client binding reaches what the hub publishes to that client. |
| The hub's transport asks the hub's Python about every `open`, which judges it against the client's kinds and each kind's machines; the transport then dials. | A permission changed on the **Clients** page holds for the next stream without a reconnect. |
| An agent dials a port only while its machine publishes that port, and closes any other with `port_not_published {port}`. | The agent makes the check itself, so a fault in the hub's check opens no port the machine does not publish. |
| Switching a client off, deleting it, or taking a kind or a machine from it immediately closes what the change covers: the session, through `session_close`, or the shells, the commands and the `connect` streams of that kind, through `streams_close`, and the panel sessions of that kind ([protocol.md](protocol.md), "The local channel"). | A person switches a client off because the device is lost. A shell that stays open is the access they meant to end. |
| The panel is a kind like the others: the **Clients** page sets it in the default and for each client. A new hub's default has it off. A client with it receives a sign-in token of 32 random bytes that holds 60 seconds for one use. | The panel changes the hub itself, so a person turns it on for the devices that are their own. |
| A client joins a terminal session that is its own or is shared, on a machine its `terminal` kind includes. A `shell` or a `persist` on any other session is refused `session_not_owned {session_id}`. | A session is a shell as root, or as the account the machine's Terminal module names, with its output on screen. A session that stops being shared closes to every viewer but its owner. |
| A session holds at most `ConnectStreamsMax`, 256, `connect` streams, and each stream is sent under the receiver's yamux window. | One client cannot exhaust the hub's sockets or its memory. |

## What a client opens on its own machine

| Rule | Reason |
| --- | --- |
| A forwarder listens on `127.0.0.1` and accepts any connection made on that machine. | The machine's accounts are the person's own. Loopback is the one boundary Linux, macOS and Windows share. |
| A datagram waits in two places, each until the stream's `accept` and at most `UdpHeldDatagramsMax`, 16, of them, and the rest are dropped: the client's forward before the hub's `accept`, and the hub's transport before the agent's `accept` on the agent's stream. No datagram waits anywhere else. | A program's first datagram is often its only one. A bounded hold keeps it without a queue. |
| A page behind a forwarder keeps its own token or login where it has one. | A program on the client machine that finds the port still needs the page's secret. |
| The Windows file network card has an address of its own, and its gateway and DNS fields are empty. Its endpoint returns an error for UDP. | Windows mounts SMB only on port 445 of an address. The card gives each share an address that leads to the client's own endpoint. |

## Why the hub relays everything

A client on the same overlay as a machine has a direct path to it, and the
hub relays the client's streams all the same. The relayed path works with
what a home already has: its LAN and one reachable port.

## What one session costs

| Limit | What follows from it |
| --- | --- |
| Every stream shares one TCP connection. A lost packet holds every stream on the session until it is sent again, and yamux's windows do not change that. | A stall on one stream is a stall on all of them, for the length of one retransmission. |
| A datagram in a stream keeps its boundary and loses its timing. It arrives late where plain UDP loses it. | UDP over the connection suits request and reply traffic: DNS, time, discovery, a small game server. Voice, video and fast games need a direct path. |
| The hub's uplink and its transport bound the speed of every stream. Through the relay or a frp node that server's bandwidth bounds it too. | Terminals, editors, a desktop and ordinary file copies fit inside that bound. A transfer that needs the line's full speed uses a direct path. |
| A direct path is a subnet route the person sets up in the overlay's own console. The hub lists the served networks for it and manages no route there. | That path is outside the connection. It reaches a machine's own ports under each service's own login, with no kind and no entry in between. |
