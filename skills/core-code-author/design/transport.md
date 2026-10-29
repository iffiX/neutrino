# The transport

The transport is the Go program `neutrino_transport`, built from
`transport/`, and the wire it speaks on the hub's agent port, 8443 unless the
**Network** page sets another. The hub runs it as a process of its own,
which holds the port. An agent and a desktop client run it to dial the port,
and the Android and iOS apps embed it as a library
([../coding_style/go.md](../coding_style/go.md)). A member holds
one TCP connection to the port, which carries a knock, a Noise handshake and
then a go-yamux session. A guest reaches one shared app on the same port
through WebRTC. Every service a client uses is a stream, and the hub dials
each service on the client's behalf.

This page holds the bytes before and around the yamux session, every limit
on them, admission, and the local channel between each transport and the
Python beside it. What a stream carries, the control stream's frames, the
kinds of stream and the sections of the state, is in
[protocol.md](protocol.md), "The channel". The relay's operation is in
[hub_components/network.md](hub_components/network.md), "The relay, the third
way in", and SakuraFrp's and OpenFrp's in its "SakuraFrp and OpenFrp".

On this page a member, or peer, is an agent or a client, and a guest is a
browser opening a Web share. An entry is one service the hub publishes, a
kind is the permission an entry falls under, and a binding is the record of
one enrolled peer.

## One port, one connection

| Rule | Reason |
| --- | --- |
| A client dials the hub's agent port and no other address. Files, web pages, ports, the panel, remote desktops, terminals and the AI gateway are streams on that one session, and every stream, a file share's included, rides the peer's one TCP connection; no stream opens a second connection. | A person outside the home needs one reachable port. A service's address, port and secret stay inside the hub's LAN. One connection is one knock, one handshake and one admission for every stream. |
| An agent dials the same port and listens on none of its own for the hub. The one port it opens for the machine's AI tools is on its own `127.0.0.1`, and for the machine's containers on the Podman bridges on Linux and on WSL's vEthernet adapter on Windows, each with a firewall rule scoped to that interface where the machine's firewall drops it ([agent.md](agent.md), "The listeners a container reaches"). Their connections go to the hub over that session. | A managed machine behind a firewall or a NAT is reached over the session it opened, and the AI gateway answers on the hub's loopback alone. |
| The hub relays every stream, on the LAN and from outside alike. Each of a client's streams ends at the hub. | A relayed stream works with the routes a home already has. One path has one set of permission checks. |
| A machine's own services stay reachable on its LAN at their own ports, under each service's own login. | A person at home keeps the tools they already use. The connection is the way from a client, and it closes no other way. |
| A stream is one TCP connection, or every datagram of one UDP `port` entry. A `port` entry states one protocol, TCP or UDP, and every other kind is TCP. | A container or a declared service on UDP is published the same way as one on TCP. One protocol for each entry gives each entry one permission check and one health check. |
| A UDP stream sends one datagram in one record, with the port the datagram left from on the client's machine in front of it. The far end keeps one socket for each such port, at most `UdpSourcesMax`, 64, the one idle the longest giving way, and closes a socket after `UdpIdleTimeout`, 60 seconds, with no datagram. A datagram its stream cannot take at once is dropped. | A reply returns to the local program that asked, and two programs on one forward stay two peers to the service. UDP has no close of its own and permits loss. A queue of datagrams adds delay and has no bound. |

## The doors

The agent port is one TCP port, and the first bytes of a connection pick the
door it goes through. Every listener of the transport has the same doors,
the frp loopback listeners included.

| The first bytes | The door | Who comes through it |
| --- | --- | --- |
| the hub's magic, 4 bytes ("The header and the magic") | the member path | an agent or a client, which has the magic from its link |
| a STUN Binding Request in RFC 4571 framing, its 2-byte length starting with `0x00` ("The guest path") | the guest path, while a Web share is live | a browser opening a Web share |
| anything else | none: the connection is refused ("A refused connection") | |

| Rule | Reason |
| --- | --- |
| One TCP port carries every door. | A home has one reachable port, and through the SSH relay and the frp nodes one forwarded port is all a sender reaches. A member and a guest reach the hub at the same address. |
| The transport checks the first bytes as they arrive, and refuses a connection only after it has read a length drawn at random for that connection, `DoorReadBytesMin` 20 to `DoorReadBytesMax` 100 bytes, or after the peer stopped sending. The member path decides at the fourth byte and still reads to that length. The guest path decides at the end of the USERNAME, byte 55 to 59 of a browser's first frame, and cuts at the later of its decision and that length. | The door never stops reading at a byte of the magic, so the magic cannot be found byte by byte. How far the transport reads before it cuts has the same spread on both paths. A connection that passes its checks never waits for that length. |
| The magic's first byte is never `0x00` or `0x16`. | `0x00` opens a browser's frame, so the first byte alone tells the two doors apart. Avoiding `0x16`, the first byte of a TLS record, costs nothing. |

### A refused connection

A connection the transport refuses gets one reaction, whatever it sent. The
transport stops reading it and writes nothing to it. It holds the connection
open until a deadline drawn at random for that connection, `DoorHoldMin` 5
to `DoorHoldMax` 30 seconds after the accept, and then closes it with a
reset, `SO_LINGER` 0. A refusal after that deadline closes at once.

The transport refuses:

- a connection whose first bytes fit no door, a first byte of `0x00` among
  them while no share is live;
- a knock whose magic, version, message type, length or `mac1` is wrong,
  whose message 1 does not open, or whose `time` the replay window refuses;
- a guest's first frame at any check of the guest path's cut-off order;
- a connection that has not sent what its door checks by its hold deadline,
  or by its door's handshake time when that is earlier, an empty one among
  them.

| Rule | Reason |
| --- | --- |
| Every refusal is the same: silence, a hold to a deadline drawn at random, and a reset. | A prober reads one reaction whatever it sends. Nothing it reads tells a wrong magic from a wrong `mac1`, or a shut guest door from an open one. |
| Every read before the hub's first byte on a connection ends by the hold deadline, and by the door's own handshake time when that is earlier. | A connection with the right magic that then stays silent is held as long as one with a wrong magic. |
| The transport stops reading a refused connection and drains none of its bytes. | Once the kernel's receive buffer fills, TCP flow control stops the sender, so a held connection costs at most one buffer. A reset needs no draining. |
| The close is a reset. | Linux closes with a reset or with a FIN by whether unread bytes are left, and a prober reads the difference. |
| The door reads into a buffer the size of what it checks: a knock of at most `KnockBytesMax`, or a guest's first frame of at most 257 bytes. | A held connection costs the hub no more memory than its first bytes. |
| A held connection counts among the unadmitted ones until it closes, and at `UnadmittedMax` the held ones are closed first ("What an unadmitted peer can cost the hub"). | Refused connections that fill every place cannot shut out a peer with the link. |
| The hub writes its first byte to a connection only after a knock's `mac1` verifies, as an answer or a cookie reply, or after a guest's MESSAGE-INTEGRITY and FINGERPRINT verify. A sender without a link or a live share's pwd gets nothing back beyond TCP's own segments. | A flood from a sender without the link draws no traffic out of the hub: no amplification, and no byte of its own. |

## The member path

The member path is the door of a member, an agent or a client. Its session
is one TCP connection to the agent port, opened by the member, carrying one
Noise handshake and then one go-yamux session. The handshake is
`Noise_IKpsk2_25519_ChaChaPoly_BLAKE2s` with the 20 ASCII bytes `neutrino
transport 4` as its prologue: the peer is the initiator, and the hub's static
public key is the responder's key the peer knows in advance. Its first
message is the knock.

Every key on the wire is its 32 raw bytes, and every key, psk and digest
written anywhere else, in a link, a binding, a local line or a file, is 64
lowercase hex characters. A ticket and a token are the text
`secrets.token_urlsafe` gives, 24 and 32 characters, and a hash of either is
SHA-256 over that text's UTF-8 bytes.

### The header and the magic

Every message the two sides write before the session starts opens with the
same 8 bytes: the peer's knock, the hub's answer and the hub's cookie reply.

| Bytes | Field | Value |
| --- | --- | --- |
| 0 to 3 | magic | the hub's magic |
| 4 to 5 | version | u16, big-endian: 4 |
| 6 | message type | u8: 1 knock, 2 answer, 3 cookie reply |
| 7 | reserved | u8: sent as 0, ignored on receipt |

The magic is 4 bytes derived from the hub's static public key, so each hub
has its own, and its first byte is never `0x00` or `0x16`. For a counter
`c` of one byte, from 0 up, the derivation takes BLAKE2s-256 of the 8 ASCII
bytes `magic---`, the public key's 32 bytes and the byte `c`, in that order;
the magic is the first 4 bytes of the first digest whose first byte is
neither `0x00` nor `0x16`. A peer derives it from the link's `key`, and the
hub from its own public half, by `knock.Magic`.

| Rule | Reason |
| --- | --- |
| The magic is per hub, derived from the hub's static public key. | A member derives it from the key its link already holds, so the link gains no field. A scanner without the link is refused with no crypto spent. A firewall rule written against one hub's first bytes matches no other hub. |
| The version is the protocol number, 4, and the transport picks the handshake that follows by it. A connection whose version the transport does not speak is refused ("A refused connection"). | A later number can bring another handshake to the same port, and the transport tells the two apart before any crypto. |
| One header opens the knock, the answer and the cookie reply, and the message type tells them apart. | A peer reads every message of the handshake by one shape, and an answer and a cookie reply differ in one named byte. |
| The reserved byte is sent as 0 and ignored on receipt. | A later release can give it a meaning, and an older hub reads past it. |
| `mac1` covers the header. | A header altered on the way fails `mac1`, so the hub acts on the version and the type the peer wrote. |

### The knock and the answer

The transport checks a knock in the order its bytes arrive: the magic, the
version, the message type, the length and `mac1`. It refuses the connection
at the first mismatch ("A refused connection"), and opens message 1 only
after all of them pass.

| Step | On the wire | Rule |
| --- | --- | --- |
| Knock | the peer's first bytes: the header with type 1, then `<u16 length><Noise message 1><mac1, 16 bytes><mac2, 16 bytes>`, `length` counting message 1 alone, big-endian, and the whole knock at most `KnockBytesMax`, 1088 bytes: 1024 and the padding's 64 | `mac1` is BLAKE2s-128 keyed by BLAKE2s-256 of the ASCII `mac1----` followed by the hub's public key's 32 bytes, over every byte before `mac1`, the header's included. `mac2` is BLAKE2s-128 keyed by the cookie the peer holds, over every byte before `mac2`, or 16 zero bytes while it holds none. Message 1's payload is JSON `{protocol, role, is_join, time}` followed by its padding, `time` being the peer's clock in Unix nanoseconds, an integer. |
| Silence | nothing | A knock whose magic, version, type, length or `mac1` is wrong, whose message 1 does not open, or whose `time` is not later than the last one the transport accepted for the same static key is answered with no byte: the transport refuses the connection. |
| Cookie | under load, the answer to a knock with a valid `mac1` and no valid `mac2`: the header with type 3, then `<24-byte nonce><the cookie sealed, 32 bytes>`, after which the transport closes the connection | The cookie is BLAKE2s-128 keyed by the transport's cookie secret, made afresh every `CookieSecretLifetime`, over the peer's address as the connection gives it. It is sealed with XChaCha20-Poly1305 under BLAKE2s-256 of the ASCII `cookie--` followed by the hub's public key, with the knock's `mac1` as associated data. The peer keeps the cookie for `CookieSecretLifetime` and knocks again on a new connection with `mac2` set; a cookie made under the secret before the current one no longer verifies, and the peer is sent a new one. |
| Answer | the header with type 2, then `<u16 length><Noise message 2>`, its payload the padding | The transport mixes in the psk the table in "The handshake" names, after it asked the hub's Python whose the peer's static key is ("The local channel"). |
| Session | every byte after the answer: Noise transport messages, each `<u16 length><ciphertext>` of at most 65535 bytes, carrying one go-yamux session | The hub is yamux's server and the peer its client, so the hub's streams have even ids and the peer's odd ones. A session is not rekeyed: it keeps its handshake's keys until it ends. |

| Rule | Reason |
| --- | --- |
| Message 1's payload is the JSON object followed by 0 to `KnockPaddingBytesMax`, 64, random bytes, and message 2's payload is 0 to 64 random bytes, each count drawn for its message. The hub reads the one JSON value and ignores the bytes after it, and the peer ignores message 2's payload. | The padding is inside the encryption, so only its length shows. The knock, 209 to 211 bytes without it, and the answer, 58, then differ from one connection to the next, and no fixed size marks the port. |
| Data records and keepalives carry no padding. | The padding costs about 64 bytes for each connection and 320 for a round of five addresses. The traffic after the handshake carries every service, and its sizes say nothing about the port. |

### The handshake

The psk is the secret the hub handed the peer, by its SHA-256, which is
what the hub keeps of it:

| The knock | The psk |
| --- | --- |
| a join, `is_join: true` | 32 zero bytes; the ticket is in the `join` frame, inside the session |
| a bound peer's, admitted | the SHA-256 of the binding's token, the `token_sha256` the hub keeps for the binding |
| any knock the hub refuses, a static key no binding holds among them, and every refusal the transport makes itself, `control_unavailable` and `channel_full` | 32 zero bytes, and the control stream carries `refused {code, params}` as its first frame, written as soon as the transport accepts the stream and before the peer's first frame is read |

A peer opens message 2 under the psk it expects, and when that fails, under
32 zero bytes: a message 2 that opens under the zero psk is the hub's own,
since only the holder of the hub's private key can make one, and the frame
after it says why the hub refuses. A message 2 that opens under neither is
`hub_untrusted`; a peer whose token is not its binding's lands there too,
and the hub sees a connection end and counts nothing. Silence and a timeout
are not a failed handshake: the round goes on with the other addresses.

`neutrino_transport probe --key <public-key-hex> <address>` checks that an
address reaches the hub that holds a key: it dials, knocks as a join with a
static key made for the probe, and exits 0 when message 2 opens within
`HandshakeTimeout`, 1 otherwise, closing at once after message 2 and before
any frame. The hub's Python runs it for the relay's and the frp vendors'
checks ([network.md](hub_components/network.md), "The states"), naming its
own public key; the connection it opens on the hub ends with no frame and
counts as no failed admission.

## The guest path

The guest path is the door of a Web share: a person who holds a Web share
link opens one shared app in a browser. The page in the browser is plain
JavaScript, and it reaches the port through the browser's WebRTC, which dials
an address and a port the page names and trusts a certificate by the
fingerprint the page gives it. The guest door is the hub's transport's alone,
in the package `transport/gate/`, built on pion's `stun`, `dtls`, `sctp` and
`datachannel` packages and on no ICE agent
([../coding_style/go.md](../coding_style/go.md)).

| Step | What crosses the connection | Rule |
| --- | --- | --- |
| STUN | the browser's Binding Requests in RFC 4571 framing, each after its 2-byte length, and the hub's Binding Success responses | The hub is ICE-lite with one candidate, TCP and passive, at the agent port. It writes its first response only after every check of the cut-off order that follows passes, and then answers every later consent check on the connection under the same share's pwd, with MESSAGE-INTEGRITY and FINGERPRINT. Each response's XOR-MAPPED-ADDRESS is the connection's peer address and port, with a documentation address in place of a loopback, link-local or unspecified one. |
| DTLS | one DTLS handshake on the same connection, the hub its server | The browser authenticates the hub by the certificate fingerprint the link holds ("The DTLS certificate"). The hub's server requests no client certificate, requires the extended master secret, offers the SRTP profiles `SRTP_AEAD_AES_128_GCM` and `SRTP_AES128_CM_HMAC_SHA1_80` and uses neither, and writes records of at most `GateMTU`, 1200 bytes. |
| SCTP | one association over the DTLS connection | Its packets fit a DTLS record, `GateMTU` less 28 bytes, and its receive buffer is `GateReceiveBufferBytes`, 8 MiB. |
| Data channel | one reliable data channel, id 0, label `neutrino`, negotiated in advance on both sides | Both sides create it from the link's terms, which saves the round trip of an in-band open, and the hub closes every other stream the browser opens on the association. A message the hub writes is at most `GateMessageBytesMax`, 64 KiB, and one it reads at most `GateReadBytesMax`, 256 KiB, the size the page's session description states. |
| First message | one `open` record, type 1, in the layout of "The stream layer", its payload JSON `{protocol, ticket}`, at most `GateGuestOpenBytesMax`, 1024 bytes | `protocol` is the member header's version, 4, and `ticket` the share's ticket from the link. The transport asks the hub's Python `guest` ("The hub's local channel") and writes one `accept` record, type 2, whose payload is `{id}`, the share's id, or one `close` record, type 8, `{code, params}`, after which it closes the connection. |
| yamux | a yamux session inside the data channel, the hub its server and the page its client | The page opens the control stream first and sends `hello {protocol, role: guest, id, name, software}`, `id` the share's id from the `accept`. The hub's Python answers `welcome` and sends no `state`. |

The hub checks a guest's first bytes in this order, and refuses the
connection at the first check that fails ("A refused connection"):

1. The RFC 4571 frame's 2-byte length: its first byte `0x00`, and a length
   of at least 20, a STUN header's.
1. The STUN message type, `0x0001`, a Binding Request, and the STUN message
   length, the frame's length less the 20 bytes of the header.
1. The STUN magic cookie, `0x2112A442`.
1. The ufrag, the part of the USERNAME attribute before the colon, looked up
   among the live shares with no crypto.
1. MESSAGE-INTEGRITY, checked with the pwd of the share that ufrag names,
   and FINGERPRINT.

The hub writes its first byte only after the last two checks pass. While no
share is live the guest door is shut, and a first byte of `0x00` is refused
as one that fits no door. A browser's first Binding Request is 118 bytes
with a 24-character ufrag, and its USERNAME ends at byte 55 in Chrome,
Chromium and Safari and at byte 59 in Firefox. A sender without a live
share's ufrag is refused there, before any hash, and cut there or at the
drawn length, whichever is later.

An admitted guest session carries the frames and streams of one shared app
and nothing else:

| On the session | The hub |
| --- | --- |
| the control stream's frames | takes `hello`, `ping` and `service` up, and sends `welcome`, `pong`, `reply` and `refused` down; a first frame of `join` or `leave` is refused `hello_invalid` |
| `connect {id}` | relays it after the hub's Python allows it (`entry`): the share's entry alone, any other id refused `permission_denied {kind}`, and `{is_panel: true}` refused `permission_denied {kind: panel}` |
| `shell`, `exec`, `file`, `log`, `package` | closes it `kind_unknown` |

A share admits any number of guest sessions, and one never replaces
another. Each counts among the admitted sessions of `SessionsMax`, and holds
at most `ConnectStreamsMax`, 256, `connect` streams.

| Limit | On the guest path |
| --- | --- |
| the first check, until the hub's first byte | the connection's hold deadline, 5 to 30 seconds from the accept ("A refused connection") |
| the first check, DTLS, SCTP, the data channel and the open record | `GateHandshakeTimeout`, 20 seconds from the accept |
| the `hello` | `HelloTimeout`, 10 seconds from the `accept` record |
| admission, from the accept to an admitted `hello` | `AdmissionTimeout`, 30 seconds |
| connections not yet admitted | a guest's counts in `UnadmittedMax` from its accept, and in `HandshakesInFlightMax` from the moment its first check passes until its open record is answered |

| Rule | Reason |
| --- | --- |
| A guest reaches the port through WebRTC. | A page cannot open a raw TCP connection. A `wss://` connection fails on a self-signed certificate with no way past the failure, and a `ws://` one from an `https` page is blocked as mixed content. WebRTC's DTLS trusts the certificate whose fingerprint the page gives. |
| A guest sends no knock and runs no Noise handshake: DTLS authenticates the hub and encrypts the connection, and the share's ticket proves the guest's right to the app. | The page is plain JavaScript and loads at once, where the knock, Noise and yamux built for WebAssembly measured 1.7 MB compressed. For a share's page, loading fast comes first, security is required, and throughput comes second. |
| The hub's one candidate is TCP and passive, at the agent port, and the link names the hub by its IP address. | Networks that drop UDP still carry a share, as do the SSH relay and the frp tunnels, which carry TCP alone. Chromium dials a candidate only at an IP address. |
| The page writes the hub's side of the session description from the link, and the browser's own description stays in the page. | The hub reads nothing from it: ICE-lite verifies checks signed with its own pwd, and the hub's DTLS server takes the browser's certificate unchecked. The link is the whole of the signalling. |
| The DTLS server offers the two SRTP profiles and uses neither. | Every browser's ClientHello asks for `use_srtp`, a data channel's included, and a server that names no profile refuses the handshake. |
| Each share has its own ufrag, 24 hex characters, 96 random bits, and its own pwd, 32 hex characters, 128 random bits, made with its ticket and void when the share ends. | The ufrag is looked up with no crypto, so its size alone stops a guess before the first hash. The pwd keys MESSAGE-INTEGRITY, the first check that costs a hash. |
| The hub responds to every consent check on a live guest connection. | A browser checks consent every 2.5 to 5 seconds and drops the connection after 15 to 30 seconds without a response. |
| A Binding Success's XOR-MAPPED-ADDRESS is the connection's peer address and port. In place of a loopback, link-local or unspecified address, the hub writes `192.0.2.1` for IPv4 and `2001:db8::1` for IPv6, `GateMappedIPv4` and `GateMappedIPv6`. | Through frpc, the SSH relay and a local forwarder, a guest's connection comes from the hub's own loopback. By default Firefox discards a response whose mapped address is loopback, link-local or unspecified, and its ICE fails. Chromium and Safari accept any address. A browser records the mapped address as its own side of the pair and sends on the TCP connection it opened. A documentation address, from RFC 5737 or RFC 3849, belongs to no host and matches no candidate of the browser. Through a forwarder whose source was 127.0.0.1, Firefox 155 failed ICE at 12.8 seconds in 6 opens of 6 with the peer address. With the documentation address it opened the app 10 times of 10. |
| The hub's DTLS certificate is self-signed and long-lived. | The browser trusts it by the link's fingerprint, so no certificate authority or domain takes part, and a link holds for as long as its share. |
| The first message is one record in the layout every stream uses, and its `protocol` is the member header's number. Its `accept` carries the share's id, the one `accept` with a payload. | One record layout and one version number serve both paths, and the page's `hello` names the share it was admitted to. |
| A yamux session runs inside the data channel. | An app makes many requests at once, and each is a stream of its own. |
| A guest opens streams to the shared entry alone. | A share link reaches one app and nothing else behind the hub. |
| A guest's handshake, from its first check through its open record, has `GateHandshakeTimeout`, 20 seconds, where a member's knock and answer have `HandshakeTimeout`, 10. | On congested lines a browser's DTLS handshake often missed 10 seconds. `AdmissionTimeout` still bounds the whole admission at 30 seconds. |
| A refused guest counts as no failed admission, and the guest path has no cookie reply. | A guest's first check costs a lookup and one HMAC before any answer, and only the holder of a live link passes it; a pause of joins for a share's visitors stops a member's enrolment too. |
| A share that ends closes its sessions: the hub's Python sends `shares_set` without it, then `session_close {session, code: share_unknown}` for each of its sessions. | A revoked or expired share leaves no page open on it. |
| A session the hub refuses has its streams closed at once. The session ends when the peer closes it, or `RelayEndGrace`, 2 seconds, after the peer acknowledged every byte written to it. It ends at most `KeepAliveTimeout` after the refusal. A member's connection reports no acknowledgement, so a member's session ends at most 2 seconds after its refusal. | On a slow line the `refused` frame waits behind the bytes already queued for the page. Through a line of 64 KB/s, a page read it 30 seconds after the revoke. An end 2 seconds after the refusal left pages on an iPhone through SakuraFrp on the hub-offline screen. |

## The links

A member link is `neutrino://enroll/<base64url>`: one JSON object, written
with no spaces, compressed with zlib (RFC 1950, level 9), and the compressed
bytes in base64url without padding. Every member link is this form, the one a
QR code carries and the one a person pastes, and a reader inflates before it
parses:

```json
{"urls": ["tcp://192.168.100.1:8443", "..."], "token": "...", "key": "<public-key-hex>", "role": "client", "overlays": [{"provider": "netbird", "...": "..."}]}
```

`token` is the ticket, and `key` the hub's static public key ("The hub's
static key"). A client link has `overlays`, the list of the same name in the
client's `state`, taken for the permission the link is made with
([protocol.md](protocol.md), `/api/hub/client`): empty when that permission
does not allow `overlay` or there is nothing to join. A device link has no `overlays`. A peer that does not know a member
ignores it.

Every address in `urls`, in a link and in a state, is
`tcp://<host>:<port>`, an IPv6 host in brackets. A peer dials each address
whose scheme it knows and skips every other one, so a later way of carrying
the channel is one more scheme beside `tcp`.

`urls` is the hub's address in every exposed segment the agent port answers
in, because one of them is on the joining machine's network and neither end
knows which. The link for the hub's own agent, and every state the hub sends
that agent, names `tcp://127.0.0.1:<agent-port>` first, so it reaches the hub
over loopback whatever is exposed. While Direct is on, the hub's stable IPv6
addresses in the exposed IPv6 segments follow the exposed set, every enabled
interface's other IPv4 and then stable IPv6 addresses follow those, and the
public address stated for Direct follows them
([network.md](hub_components/network.md), "Direct"). While Direct is off,
every address in `urls` is IPv4. Each frp vendor's public address follows
while it has a tunnel picked, SakuraFrp's first
([network.md](hub_components/network.md), "The frp addresses"). While the
relay is on and configured, `tcp://<host>:<public-port>` is its last member
([network.md](hub_components/network.md), "The relay's address"). `role` is
`agent` or `client`, read on the pasting side before the first connection. A
client rejects a device link with `link_not_for_client` and an agent rejects
a client link with `link_not_for_agent`, each code's `params` naming the
link's `role`. The base64url alphabet has no character a shell splits or a
URL escapes, so the link pastes anywhere unquoted. Compressed, a client link
with two overlays is about 550 characters and a QR code of 89 modules a
side; the QR code is that link and nothing less, so a phone that can reach
the hub only over an overlay it has not joined yet still has what it needs.
The panel draws the code at four pixels per module at least
([ui_behavior.md](ui_behavior.md)).

A Web share link opens a static page in the browser, which reads the
share's facts from the link and connects to the port through the guest path.
The two links hold different facts and open different doors:

| Link | Holds | Opens |
| --- | --- | --- |
| a member link | the hub's addresses, its static public key, from which the magic follows, a one-use ticket, the role, and on a client link the overlays | the member path |
| a Web share link | the hub's IP address and port, the DTLS certificate's fingerprint, the share's ufrag and pwd, the share's ticket, and the app | the guest path, to that app alone |

| Rule | Reason |
| --- | --- |
| A Web share link holds no Noise public key. | The magic follows from that key alone, so a share link neither reveals the member door nor knocks on it. A leaked share link reaches one app. |

A Web share link is `<site>/__neutrino/#<base64url>`, `<site>` being the
address of the static page the share names. After `#` is one JSON object,
written with no spaces, in base64url without padding and not compressed; a
browser sends nothing after `#` to the site:

```json
{"v": 1, "hub": {"ip": "203.0.113.7", "port": 8443, "fp": "AB:CD:..."}, "ice": {"ufrag": "...", "pwd": "..."}, "ticket": "...", "app": {"entry": "<entry-id>", "title": "Ayakaleaf", "path": "/project"}}
```

`v` is the link's form, 1. `hub.fp` is the certificate's fingerprint as
`dtls_fingerprint` holds it ("The DTLS certificate"). `ticket` is the
share's ticket, 18 random bytes as `secrets.token_urlsafe` gives them.
`app.entry` is the shared entry's id, `app.title` its app's title, and
`app.path`, optional, the path the app opens at.

The link holds one address, chosen when the share is made: the first public
address in `urls` order, Direct's public address, then SakuraFrp's,
OpenFrp's and the relay's while each is a member of `urls`; else the hub's
address in its first exposed IPv4 segment, the first member of `urls`
([hub_components/network.md](hub_components/network.md), "Direct"). The hub
resolves a host name to its IP address at that moment and writes the
address's port beside it.

| Rule | Reason |
| --- | --- |
| A share link holds one address, a public one where the hub has one. | A visitor is most often outside the home, and the page offers the browser one candidate. Several candidates in one offer have not been measured. |
| The address is an IP address resolved when the share is made, and it stays the link's for the share's life. | Chromium dials a candidate at an IP address alone. A public address that changes later leaves the link pointing at the old one, and a new share gives a new link. |

## TCP first

Every door of the agent port is on TCP, and every address in a link or a
state is `tcp://`. Both paths meet at the yamux streams: past its first
message, a guest's stream is relayed as a member's is, under the same
questions to the hub's Python ("The local channel").

| Rule | Reason |
| --- | --- |
| Every door is on TCP. | Networks that drop UDP, a campus network among them, still pass TCP, and the SSH relay and the frp tunnels carry TCP alone, so TCP is the one carrier every way in passes. |
| A peer skips an address whose scheme it does not know ("The links"). Another carrier, UDP among them, enters as a path of its own beside the TCP doors, with one more scheme beside `tcp`, and the TCP doors stay as they are. | The guest path sits beside the member path, and each way in beside the others, so an added path leaves the paths before it unchanged. |

## The stream layer

| Concern | Rule |
| --- | --- |
| Ids | yamux's: the hub's streams are even and a peer's odd, so the two never collide. |
| Records | Every stream carries records, `<u8 type><u32 length, big-endian><payload>`, a payload being at most `RecordBytesMax`, 64 KiB; a TCP `connect` stream carries records only until its `accept` ([protocol.md](protocol.md), "The connect stream"). |
| Open | The opener's first record is `open`, `{kind, ...args}`. The other side answers with one `accept` record and goes on, or with one `close` record that refuses. |
| Windows | yamux's window per stream, from `StreamWindowInitialBytes` growing with the round trip to `StreamWindowMaxBytes`. A receiver takes bytes as it consumes them, so a long transfer starves nothing. |
| Result | `close {code, params}` ends a stream from either side. `params` is the result and the only place a result goes; a `code` makes the close a refusal. The side that receives a close writes nothing more and closes the stream, so a stream one side closed gets no close back. A TCP `connect` stream after its `accept` carries no record, so it ends with no code: its end is the end of its bytes, or a yamux reset in the place of the refusing `close` any other stream takes. |
| Order | The records of one stream arrive in the order they were written. |
| Small writes | Every socket that carries a stream's bytes over TCP sends them at once, with `TCP_NODELAY` on: the transport's sockets by Go's default, and every Python socket that relays a stream, an agent forwarder's both sockets ([agent/module_template.md](agent/module_template.md), "The run") and the Windows client's files adapter's among them, set by hand. |

| `type` | Record | Payload |
| --- | --- | --- |
| 1 | `open` | JSON `{kind, ...args}` |
| 2 | `accept` | empty, but JSON `{id}`, the share's id, answering a guest's first message ("The guest path") |
| 3 | `data` | bytes: a terminal's both ways, a process's stdin up and its stdout down, a file listing, a log's lines, a package's bytes, the control stream's frames |
| 4 | `stderr` | the bytes a process wrote to stderr, on an `exec` stream opened without `is_tty` |
| 5 | `eof` | empty: no more input follows from this side, on an `exec` stream alone |
| 6 | `resize` | JSON `{cols, rows}`, on a `shell` stream and on an `exec` stream opened with `is_tty` |
| 7 | `datagram` | `<u16 source, big-endian><one datagram>`, on a UDP `connect` stream |
| 8 | `close` | JSON `{code, params}` |

A record of a type the stream does not take is dropped. A stream's text
output, an install log or a command's output, is its `data` records, one
line each; the control stream's frames are the one stream whose lines can
span records.

## Where the port is reached

The port is the transport's one listener on two sockets, one for IPv4 and
one for IPv6 ([hub_components/network.md](hub_components/network.md),
"Direct"). The transport serves the same channel on two more listeners, one
per frp vendor, on `127.0.0.1` alone: `FRP_SAKURAFRP_LOOPBACK_PORT`, 18443,
and `FRP_OPENFRP_LOOPBACK_PORT`, 18444, open whether each way in is on or off
("The loopback listeners" there). frpc on the hub forwards a vendor's node to
its listener, and the listener a connection arrived on settles its
`reached_through`. The hub's Python renders what the transport opens into
`generated/transport.json` under the state root, `{listen_port,
frp_listeners: [{port, listener}], control_socket}`, and the transport reads
it at its start; a change of the file restarts the transport.

The agent port answers a sender inside every exposed segment, whatever the
interface's role, an uplink's included, and on every exposed overlay
([hub_components/network.md](hub_components/network.md), "What answers, and
where"). A served LAN whose segment is not exposed keeps DHCP and forwarding
only. The addresses in an enrolment link are the hub's own in that same set:
its IPv4 address in each exposed IPv4 segment (a LAN's configured address,
every other interface's live IPv4) and its address on each exposed overlay.

While Direct is on, every enabled interface's address follows the exposed
ones: the firewall opens the agent port alone there, to every sender. One
test asserts that the link's address set equals the hub's addresses in the
segments the firewall opens the agent port to, with the extra members no
local interface holds: the public address stated for Direct while Direct is
on, each frp vendor's public address while it has a tunnel picked, and the
relay's address while the relay is on and configured. Enrolling a device on a
LAN begins with exposing that LAN's segment. A way in adds an address to the
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
| Direct opens the agent port alone, to every sender on an enabled interface. The panel and the hub's other ports keep the exposure the **Network** page gives them ([hub_components/network.md](hub_components/network.md), "What answers, and where"). | The agent port writes nothing until a knock made with the hub's static key, or a Binding Request signed with a live share's pwd, arrives. It admits a peer by its own static key and its binding, and a guest to one app by its share's ticket. The panel admits a browser by a password, and a password on a public address is open to guessing. |
| A change of the port's number reaches every online client and agent in `urls` first, and the port moves at once after. A peer offline at that moment joins again with a new link. | A peer reaches the hub only at an address it was given, so the new one is given before the old one closes. |
| The port treats a peer the same on every way in. No rule on it depends on the address a peer arrives from or the listener it arrives on; the listener names the way in and nothing else. | Through the relay and the frp nodes every peer arrives from loopback, so an address says nothing about the peer. |
| A client dials every candidate address of the hub at once, at every round: the hub's address on each virtual network that is up, the hub's name, and `urls`. The first connection whose handshake completes under the binding's `hub_key` carries the round's one `hello`, and the client closes the others before any `hello` on them ([client.md](client.md), "The Hubs page"). No address is preferred for having worked last, no prober runs between rounds, and each address keeps its own connect time; an address that refuses is dialled again every second until the round's connect time ends. A network change (a virtual network turning on, the device's connectivity changing, or new `urls` in the state) starts one round at once, and its winner takes a live channel only on a better path. | Under an order, a client on a network the first addresses do not reach waits out each of their connect times before the address that works. Dialling at once costs the hub one unadmitted connection per address for a few seconds. |
| An agent dials every address of the hub at once, at every round, its first connect as every reconnect: the hub's name, `urls`, and the address that last answered. The first connection whose handshake completes under the binding's `hub_key` carries the round's one `hello`. The agent's transport closes the others before any `hello` on them. No address is preferred for having worked last, and each address keeps its own connect time. An address that refuses is dialled again every second until the round's connect time ends. A connected channel is not moved because another address answers. | Under an order, an agent waits out the connect time of each address before the one that works. In the lab, its first session took 13.5 seconds. An agent runs no round beside a live session, so its channel moves only when the session ends. |
| The hub treats each connection of a peer's round as any connection: it counts among the unadmitted ones until it closes or its `hello` is admitted. A second admitted session of one binding replaces the earlier one, which the hub ends with `refused {code: replaced}` ("What a refusal does to the binding"). | A binding holds one session. A peer sends one `hello` per round, so its own round never replaces itself. |

The hub's own address, for a peer, is a set and a name.
`hub.neutrino.internal` is the hub's name on every served network: dnsmasq
answers it with the hub's address on the network the query came in on, so
the name resolves to the hub of the network the peer stands on, whatever
that address is today. A binding holds the `urls` of the last state it took
as `gateway_urls`, with `gateway_url` the last address that answered. An
agent's round, a reconnect as much as the first, dials the name,
`gateway_urls`, and `gateway_url` when the list does not hold it, all at
once. A client's round dials the same addresses and the hub's address on
each virtual network that is up. The peer's transport resolves the name at
each round. On either, the first whose handshake completes under the
binding's `hub_key` is written back as `gateway_url`. Another network's hub
on the name answers the knock with silence, since the knock's magic and
`mac1` follow from a key it does not hold, and the address is skipped; an
answer that opens under no psk on a stored address is recorded as
`last_error`, and the round goes on with the other addresses.

### The redial

A peer's transport dials again by the code that ended the last session, so
the agent and the client hold one rule. A round of either dials every
address of the hub at once ("Where the port is reached").

| The session ended | The transport |
| --- | --- |
| with no refusal: the connection dropped, a keepalive went unanswered | starts a round at once, then backs off from `RedialBackoffMin` doubling to `RedialBackoffMax` while rounds fail |
| `refused` with `retry_after_s` in its `params`, the hub transport's own `control_unavailable` among them | waits `retry_after_s` and dials again |
| `refused` with any other code but the two below | waits `RedialBackoffMax` and dials again |
| `refused` `replaced` or `binding_unknown` | dials no more until the next `dial`: `replaced` waits for a person, and `binding_unknown` ends the binding ("What a refusal does to the binding") |

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
| Door | Reads the first bytes and takes the member path at the hub's magic ("The doors"); a browser's connection takes the guest path, whose steps are its own ("The guest path"). | Bytes compared cost nothing, and a sender without the link meets silence and then a reset ("A refused connection"). |
| Knock | Reads the knock and checks its version, its message type, its length and `mac1`, one keyed hash, then, while under load, `mac2` ("Under load"). A knock that fails is refused ("A refused connection"). | A knock costs the peer the hub's public key, which only a link carries, and costs the hub one hash before any Diffie-Hellman. A port that answers nothing to a scan is a port a scan does not find. |
| Message 1 | Opens message 1, which costs two Diffie-Hellman operations, and checks `time` against the replay window. A message 1 that fails either is refused. | The peer's static key and its intent are inside it. |
| Question | Asks the hub's Python whose the static key is (`peer`), or, for a join, nothing until the `join` frame (`ticket`). | The Python holds every binding. |
| Answer | Writes message 2 under the psk the answer names, and starts the session. | A refusal is said under the hub's key, so the peer can trust it. |
| `hello` | Reads the first frame on the control stream and passes it to the Python, which sends `welcome` or `refused`. | The binding id is checked against the key that made the session. |

| Rule | Reason |
| --- | --- |
| The replay window is per static key: the transport keeps, for each key it accepted a knock from, the latest `time` it accepted, for at most `KnockReplayKeysMax`, 65536, keys, the one used longest ago giving way. A knock whose `time` is not later is refused. A transport that starts again keeps no window, and the first knock of each key is accepted. | A captured knock replayed costs the hub one Diffie-Hellman and no answer. The peer's clock is the only clock it has, so the window compares a key with itself and never with the hub's time. |
| A join's static key is new to the hub, so its knock is judged by the same window, and its ticket by the hub's Python in the `join` frame, inside the encrypted session. | The ticket never crosses the wire in a form a listener reads. |
| A knock that names a key no binding holds is completed under the zero psk and refused `binding_unknown`, and counts as a failed admission. | The peer learns from a source it can trust that its binding is gone, and a search for keys pauses the joins like a search for tickets. |

## What an unadmitted peer can cost the hub

Each limit is one count for the whole port, across every peer address and
both sockets, and the frame cap holds on admitted sessions too. The hold
deadline, the handshake time and the admission time start at the accept.
The constants are the transport's, apart from the failed admissions, which
the hub's Python counts in `modules/channel/constants.py`.

| Limit | Constant | At the limit | Reason |
| --- | --- | --- | --- |
| a connection the doors refuse, or one that has not sent what its door checks | `DoorHoldMin` 5 s to `DoorHoldMax` 30 s after the accept, drawn for each connection | the connection is held unread until that deadline and then reset ("A refused connection") | A peer sends its knock, and a browser its Binding Request, within a round trip. A deadline drawn at random gives an empty connection the same reaction as every other refusal. |
| the knock and the answer | `HandshakeTimeout` 10 s | the connection is refused while the hub has written nothing ("A refused connection"), and closed after | A handshake over the slowest way in completes in under a second. |
| a guest's first check, DTLS, SCTP, the data channel and its open record | `GateHandshakeTimeout` 20 s | the connection is refused while the hub has written nothing, and closed after | On congested lines a browser's DTLS handshake often missed 10 seconds. |
| the time from accept to an admitted `hello` | `AdmissionTimeout` 30 s | the connection is closed; a `join` or a `leave` in flight counts toward that time | It bounds how long one unadmitted connection holds a place. |
| connections that have not passed `hello` | `UnadmittedMax` 128 | one of them is closed to make room: the oldest held after a refusal, then the oldest that has not finished its handshake, and the oldest of all when every one has | A held connection has failed a check, and a peer that has finished its handshake has done work a flood of bare connections has not. A flood that fills the places cannot shut out a peer with the link. |
| knocks whose message 1 is being opened or whose question is open, and guests from their first check passing until their open record is answered | `HandshakesInFlightMax` 64 | a further knock or guest is closed at once with nothing written | The Diffie-Hellman, the DTLS handshake and the questions are the costly steps, and the limit bounds them at once. Only a sender with a link or a live share's pwd reaches it. |
| under load: knocks in flight past `CookieLoadThreshold`, 16 | `CookieSecretLifetime` 120 s, the cookie secret's life and the cookie's | a knock without a valid `mac2` is answered with a cookie reply and closed ("Under load") | WireGuard's answer to a flood of knocks: the peer proves it reads what the hub writes to its address before the hub spends a Diffie-Hellman on it. |
| one control frame | `ControlFrameBytesMax` 2 MiB | the session is ended | Four times the largest frame a hub of 64 machines and 256 entries carries, a client's `state` of about 270 KB. |
| one record | `RecordBytesMax` 64 KiB | the stream is reset | A record is a chunk of a stream, never a whole file. |
| the answer to yamux's keepalive on an admitted session | `KeepAliveInterval` 20 s between pings, `KeepAliveTimeout` 60 s for the answer | the session ends and every stream on it ends; the transport writes one line for it, at most once a minute for each peer address | The ping waits behind what the session already queued: a desktop stream can hold a full window unconfirmed, and 60 seconds covers it at a slow uplink. |
| admitted sessions | `SessionsMax` 512 | the next `hello` is refused `channel_full {limit}` | One binding holds one session, and a home has far fewer than 512 bindings. |
| the bytes the hub's transport holds for one stream | `StreamWindowMaxBytes` 16 MiB, the stream's largest window | the window grows no further, and the sender waits | A stream whose reader is slow holds at most one window on the hub. |
| the bytes the hub's transport holds for every stream together | `TransportMemoryMaxBytes`, through go-yamux's memory manager | a window grows only while the total has room, and a stream the manager refuses at its open is reset; the transport writes one line for it, at most once a minute, with the count of streams reset since the line before | 512 sessions of 256 streams at a full window each is more memory than any hub box has. |
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

## The timings

Every interval and every window the transport runs on is a constant named
here, so that changing one is a change to this table. They hold for every
role, in the transport's own constants. The intervals of the Python sides
are in [protocol.md](protocol.md), "The timings".

| What it bounds | The transport's constant |
| --- | --- |
| a connection's first bytes until the hub's first byte, and a refused connection's hold, from the accept | `DoorHoldMin` 5 s to `DoorHoldMax` 30 s, drawn for each connection |
| the knock and the hub's answer, from the accept | `HandshakeTimeout` 10 s |
| a guest's first check, DTLS, SCTP, the data channel and its open record, from the accept | `GateHandshakeTimeout` 20 s |
| a session's first frame, from the answer | `HelloTimeout` 10 s |
| a connection's admission, from the accept to an admitted `hello` | `AdmissionTimeout` 30 s |
| a dial and the handshake on it | `DialTimeout` 10 s |
| keepalive | `KeepAliveInterval` 20 s between yamux pings, `KeepAliveTimeout` 60 s for the answer |
| a refused session's end, after the peer acknowledged every byte written to it | `RelayEndGrace` 2 s |
| redial backoff | `RedialBackoffMin` 5 s, doubled to `RedialBackoffMax` 60 s |
| the `retry_after_s` of every `control_unavailable` the hub's transport makes | `RelayControlRetryAfter` 5 s |
| a peer's redial of an address refused within a round, until `DialTimeout` from the round's start | `RedialInterval` 1 s |
| a stream's window | `StreamWindowInitialBytes` 256 KiB, growing to `StreamWindowMaxBytes` 16 MiB |
| one record's payload | `RecordBytesMax` 64 KiB |
| one control frame | `ControlFrameBytesMax` 2 MiB |
| dialling the far end of a `connect` stream | `ConnectDialTimeout` 10 s |
| open `connect` streams on one client session | `ConnectStreamsMax` 256 |
| a UDP stream's source with no datagram either way, before its far-end socket closes | `UdpIdleTimeout` 60 s |
| sources one UDP stream's far end keeps a socket for | `UdpSourcesMax` 64 |
| datagrams held while a UDP stream waits for its `accept`: the client's before the hub's, the hub's before the agent's | `UdpHeldDatagramsMax` 16 |
| a question to the Python beside it | `ControlQuestionTimeout` 5 s |
| a cookie's life, and the cookie secret's | `CookieSecretLifetime` 120 s |
| the bytes the hub's transport holds for every stream together | `TransportMemoryMaxBytes`, set by the transport's builder from a measurement and written here |

The transport's own TCP settings:

| Rule | Reason |
| --- | --- |
| Every TCP socket the transport holds keeps Go's default, `TCP_NODELAY` on. | A record goes out when it is written, and a keystroke or a small request never waits for an acknowledgement. |
| The transport never changes the system's TCP settings in 0.6.0: no `sysctl`, no registry value, and no buffer size of its own on a socket. The kernel's own buffers then bound one session's speed on a long path; measured on 2026-10-26 at a 100 ms round trip with Ubuntu 22.04's defaults, one session moved about 27 MB/s, and plain TCP about 30. | The hub could raise only its own side, while a client's or a phone's kernel stays at its default; and a setting the hub changed would be a change to the machine that no page shows. |
| The hub's transport caps the memory it holds for its streams' bytes: one stream at `StreamWindowMaxBytes`, go-yamux's own largest window, and every stream together at `TransportMemoryMaxBytes`, through go-yamux's memory manager ("What an unadmitted peer can cost the hub"). | A peer that reads slowly makes the hub hold up to a full window for each of its streams, in each direction it relays. |

The handshake time and the admission time both run: a connection closes
when either ends first, so the knock, the answer and the `hello` together
fit in 30 seconds, the knock and its answer alone in 10, and a guest's
handshake through its open record in 20. The limits on
connections and sessions are in "What an unadmitted peer can cost the hub".
A peer whose keepalive gets no answer
within `KeepAliveTimeout` ends the session and starts a round. A refused
knock or `hello` is retried after the refusal's `retry_after_s`, 5 seconds
after the hub transport's `control_unavailable`, and otherwise at the
backoff's maximum, the minute named under the binding. A round through the
whole address set with no answer backs off as one address failing does.

## Admission and the binding

Admission is the check on `protocol` in the knock, at `join` and in `hello`,
and the binding is what a successful `join` leaves on both sides.

| Credential | What it is | How long it holds | How the hub keeps it |
| --- | --- | --- | --- |
| The hub's static key | a Curve25519 key pair, its public half inside the link | as long as the hub keeps it | the transport keeps the private half; every binding keeps the public half |
| The hub's DTLS certificate | a self-signed certificate, its fingerprint inside a Web share link | ten years, until a reset makes a new one | the transport keeps it in `config/transport/` beside the static key ("The DTLS certificate") |
| The ticket | 18 random bytes inside an enrolment link | 30 minutes, one use, one open ticket for each role | its SHA-256, on disk, so an unused link holds across a hub restart |
| The peer's static key | a Curve25519 key pair the peer makes when it first reads a link | until the peer leaves or the binding is removed | the peer keeps the private half in its binding; the hub keeps the public half on the binding's row |
| The token | 24 random bytes returned in `joined` | as long as the binding | its SHA-256, which is the psk of every later handshake ("The handshake") |

| Rule | Reason |
| --- | --- |
| A link is generated by a person signed in to the panel and reaches a peer by a scan or a paste. | The hub's public key and the ticket have no other channel, so a link's address that answers without the hub's private key is an impersonation and ends the enrolment. |
| A client link also holds what joins the hub's overlays: the NetBird setup key, or the EasyTier network's secret. | A client away from the LAN joins the overlay first and reaches the port through it. With the material fetched over the connection, a first scan outside the home reaches nothing. |
| That material holds until the person replaces the setup key or changes the network's secret on the **Access** page. The panel shows a link to a signed-in person only. | A copy of a spent link still joins the overlay and still knocks: it reaches the port there and holds no binding to be admitted with. |
| A bound peer's handshake proves both of its secrets at once: its static key in Noise's own messages, and its token by the psk. | The hub's records, the psk and the peer's public key, admit nobody without the peer's private key, which only the peer's binding file holds. |
| A client and an agent are told apart by the table their key is in, and each role opens only its own kinds of stream. | One listener serves both, and an agent's key opens nothing a client opens. |

### The hub's static key

The hub's static key is the Curve25519 key pair a peer knows the hub by. The
transport generates it at its first start and keeps it under `config/`: the
private half is `config/transport/static_key`, mode 0600, in a directory of
mode 0700, both owned by the transport's own account, which is root or
SYSTEM on macOS and Windows ([files.md](files.md)), and the public half is
`public_key` beside it, 64 lowercase hex characters, which root reads. The
transport is the one program that uses the private half. The hub's Python
reads the public half to compose a link, and opens the private half only to
seal it into a backup and to put it back at a restore. The guest path's DTLS
certificate is kept beside them ("The DTLS certificate").

| Rule | Reason |
| --- | --- |
| The public half reaches a peer only inside a link a signed-in person generated, as the link's `key`, and every binding keeps it as `hub_key`. | The key has no other channel, so an address that answers without the private half is an impersonation. |
| A peer's handshake proves the hub holds the private half before any frame of the peer's is sent ("The handshake"). A handshake that fails on a link's address ends the whole enrolment; on a bound peer's address the round goes on with the other addresses. | A wrong key on a link's own address is an attack, and another network's hub on a stored address is only the wrong hub. |
| The transport keeps an existing pair. `nhub reset all` deletes it and sends `keys_reload` ("The local channel"), which makes a new pair. | Every binding pins the public half. |
| The pair is part of `config/`, so a backup of `config/` restored on another box keeps the hub's identity, and every agent and client goes on with its binding there. The Settings tab's backup carries the private half sealed under the vault's data key, as `config/transport/static_key.sealed` in the archive, and is refused `vault_locked` while the vault is locked; a restore unseals it into `config/transport/static_key`, owned by the transport's account, and sends `keys_reload`. | A hub moved to new hardware keeps every agent and client, and the archive still holds no secret in the clear ([../misc/config.md](../misc/config.md), "Backup and migrate"). |

### The DTLS certificate

The DTLS certificate is what a browser knows the hub by on the guest path.
The transport makes it at its first start when either of its files is
missing, and keeps it in `config/transport/` beside the static key:

| File | Mode | Holds |
| --- | --- | --- |
| `dtls_certificate.pem` | 0644 | the certificate: ECDSA P-256, self-signed, common name `neutrino-hub`, valid from one day before it was made to ten years after, with a random 128-bit serial |
| `dtls_key.pem` | 0600, the transport's account's | its private key |
| `dtls_fingerprint` | 0644 | the SHA-256 of the certificate's DER as uppercase hex pairs joined by colons, the form a session description carries, written again at every start |

The transport is the one program that uses the private key. The hub's
Python reads `dtls_fingerprint` to compose a share link, and opens
`dtls_key.pem` only to seal it into a backup and to put it back at a
restore.

| Rule | Reason |
| --- | --- |
| The transport keeps an existing pair at every start, and `keys_reload` reads it again, making a new one when a file is missing. `nhub reset all` deletes the three files with the static key and sends `keys_reload`. Nothing else makes a new certificate, and nothing renews it before its ten years. | Every share link holds the fingerprint, so a new certificate ends every link at once, and that is a step the person takes. |
| The certificate's validity starts a day before it was made. | A browser whose clock runs behind still accepts it. |
| The Settings tab's backup carries the private key sealed under the vault's data key, as `config/transport/dtls_key.pem.sealed`, beside the certificate and the fingerprint as they are, and is refused `vault_locked` while the vault is locked; a restore unseals it into `dtls_key.pem`, owned by the transport's account, and sends `keys_reload`. | A hub restored on new hardware keeps its fingerprint, as it keeps every binding ([../misc/config.md](../misc/config.md), "Backup and migrate"). |

### The binding

The agent's binding file is `{gateway_url, id, token, hub_key, private_key,
machine_id}` with `gateway_urls`, the set the last state named, beside them.
`hub_key` is the link's `key`, and `private_key` the peer's own static
private key, 64 lowercase hex characters, which the peer makes when it first
reads a link and keeps with the ticket until the join. The file is
root-owned, mode 0600; a file missing any of the six is an unbound agent,
and one with no `gateway_urls` holds the set `[gateway_url]`. The client
keeps one binding per hub it joined, in the same shape, with the hub's `id`
and `name` from `welcome`.

### The numbers

The agent's and the client's `constants.py`, the hub's
`modules/channel/constants.py` and the transport's constants have
`PROTOCOL`, the integer this build speaks, which is 1 in every 0.3 package,
2 in every 0.4 package, 3 in every 0.5 package and 4 from 0.6.0. The agent
and the client send theirs in the knock, in `join` and in `hello`, and the
hub sends its own in `welcome`. The hub alone also has `PROTOCOL_MIN`, the
oldest number it admits to the channel's whole use: 4 from 0.6.0, for agents
and clients alike. An agent or a client speaks one number; the hub meets
peers from different releases and needs a range, `PROTOCOL_MIN <= protocol
<= PROTOCOL`:

| Peer | `protocol` | At `join` | At `hello` |
| --- | --- | --- | --- |
| an agent or a client | `PROTOCOL_MIN` to `PROTOCOL` | admitted | admitted |
| an agent or a client | below `PROTOCOL_MIN` | refused `protocol_too_old` | refused `protocol_too_old` |
| an agent or a client | above `PROTOCOL` | refused `protocol_too_new` | refused `protocol_too_new` |

| Code | When | `params` |
| --- | --- | --- |
| `protocol_too_old` | `protocol < PROTOCOL_MIN` | `{peer, hub, min}` |
| `protocol_too_new` | `protocol > PROTOCOL` | `{peer, hub, min}` |

A peer of 0.5 or earlier speaks TLS and never reaches `join` or `hello` ("A
peer of 0.5"). A client refused `protocol_too_old` keeps its binding, and its
Hubs row reads that the client is too old and says to update it
([client.md](client.md), "The Hubs page"). The person installs the new
client, since a client does not update itself. A new client keeps the old
one's state, so the binding stays and the next round connects.

Package versions take no part in admission. An agent whose `welcome` names a
newer `software` than its own upgrades itself with the package the hub keeps.
The agent stays as it is when the hub's version does not parse or ends in
`+dev`, so a hub of `+dev` offers no update. The hub's `software` is always
`neutrino_hub/{HUB_VERSION}`, and the client has no self-upgrade.

### A peer of 0.5

An agent or a client of 0.5 speaks 3 over TLS, and the transport has no
door for TLS: the connection is refused as any first bytes that fit no door
("A refused connection"). The hub keeps no way for a peer of 0.5 to reach
it. Each machine's 0.5 agent is reinstalled by hand with the 0.6 agent and
joins again with a new link, and each client is installed again and scans a
new link.

A 0.6 agent or client that finds a binding of the 0.5 shape on its machine,
with a `fingerprint` and no `hub_key`, has no way to the hub's key. The
agent records `last_error` `hub_key_missing` and dials nothing until `nagent
join` binds it again. The client's row reads `join_refused` with
`hub_key_missing`, and **Leave** is its only action ([client.md](client.md),
"The Hubs page"). Every install of the hub's package replaces the agent on
the hub's own machine ([../misc/operations.md](../misc/operations.md), "The
hub's own agent follows its hub"), and that agent joins again the same way. The hub marks a stored
device row that holds a token and no static key with `hub_key_missing`, and
the **Agents** page and the machine page show that code's words for it
([ui_behavior.md](ui_behavior.md), "The Agents page").

| Rule | Reason |
| --- | --- |
| 0.6 carries no part of the 0.5 channel: no TLS door, no listener for it, and no move of a 0.5 binding to the hub's key. | The TLS door answered a scan with a certificate whose name scanning services index, and every second channel is a second way in to keep safe. |
| A machine that joins again lands on the row its ticket names, else on the row whose `machine_id` its join reports, else on a new row. Its row keeps the name, the icon, the MACs, the stored credentials and `config/devices/<id>/`, and takes a new token and a new static key. | A machine reinstalled with the 0.6 agent keeps every setting the hub stores for it. A machine whose system was reinstalled reports a new `machine_id` and lands on a new row, unless its link was made from its old row. |
| The hub's first 0.6.0 start moves each machine's 0.5 files into the account layer once ([protocol.md](protocol.md), "The account layer in the state"). The file share's 0.5 `shares` and `users` are dropped from `samba.json`, not carried: they are the person's own on the machine, served as they are and managed by nothing ([agent/modules/file_share.md](agent/modules/file_share.md), "Linux"). The ports 0.5 kept for VS Code, code-server and CloudCLI are not carried; the agent takes fresh ones. | What an earlier version made on a machine is the person's now, and the module runs beside it. |

### What a leave does to the binding

A `leave` frame is the peer's own word that it is going. A peer whose
static key names no binding meets `refused binding_unknown` before its
`leave` is read. What the hub keeps afterwards follows from the role:

| Role | The row | What goes with the leave |
| --- | --- | --- |
| `agent` | kept in `devices.json`, with its name, its icon, its `machine_id`, its MACs, its stored credentials and its `config/devices/<id>/` | the token and the static key alone, so the machine is still on the Agents page and a new link binds it again |
| `client` | deleted from the client list | the token, the static key and the client's gateway key, revoked in the same step |

A device row is kept past the binding because the row is the hub's record of
the machine; a client row is not, because the client is the binding. Only
`POST /api/hub/device/remove` deletes a device's row and its
`config/devices/<id>/`, so a machine that leaves and joins again is wanted as
it was.

### What a refusal does to the binding

A refusal of a bound peer's knock or `hello` keeps the binding. The agent or
the client records it as `last_error` and knocks again a minute later, or
after the refusal's `retry_after_s` when it names one.
`protocol_too_old`, `protocol_too_new`, `channel_full`,
`control_unavailable` and every other refusal of a bound peer except
`binding_unknown` behave this way.

| Rule | Reason |
| --- | --- |
| Every `control_unavailable` the hub's transport makes carries `retry_after_s`, `RelayControlRetryAfter`, 5 seconds, and a bound peer refused it knocks again after those 5 seconds. A `control_unavailable` the hub's Python answers itself carries no `retry_after_s`. | The hub's transport makes the refusal while its Python is away, as for a restart, and a peer that waits a minute comes back up to a minute after the Python. After a macOS hub's reboot its agents were back 71 seconds after the boot. |
| While bound peers are refused `control_unavailable`, the hub's transport, the agent, the desktop client and the phone apps each write one line at the first refusal, then at most one line a minute with the count of refusals since the line before, and one line when a session is admitted again. The hub's transport counts the refusals of every peer together, and a peer counts those of each binding apart. | The hub's Python may stay away for hours, and every peer knocks every 5 seconds. A line for each refusal fills each of those logs. |

A refused `join` leaves no binding to keep. `nagent join` exits with the
code, and a client's row reads the join's refusal ([client.md](client.md),
"Joining before the hub is reached"). `ticket_spent`, `role_mismatch` and
`protocol_too_old` end a join this way; after `admission_paused` the client
tries the join again once `retry_after_s` has passed. After
`control_unavailable` and `channel_full` the client keeps the ticket. It
tries the join again after the refusal's `retry_after_s`, 5 seconds for the
hub transport's `control_unavailable`, or a minute later when the refusal
names none.

`binding_unknown` is the one refusal that unbinds: the hub says it has no
binding for the peer's static key, because the row was removed on the panel.
Only the holder of the hub's private key can make the answer it arrives in
("The handshake"), so the peer deletes its binding and is bound again only by
a new link.

A `refused` frame arrives at any point on an open session, not only in
answer to `hello`, and means there what it means at the handshake: the peer
reads its code the same way, and the end of the session behind it ends a
refusal already recorded. `replaced` is the refusal of a session whose
binding opened a second session: the hub admits the second and ends the
first with it, and the peer reconnects only when a person acts, with `nagent
join`, a service restart, or the client window's reconnect.

## The local channel

The local channel is how a transport and the Python beside it talk on one
machine: the hub's transport and the hub's Python, the agent's transport and
the agent, the client's transport and the client's resident or phone app.
The transport keeps no record of who can do what, only its live sessions and
streams; the Python keeps every record and makes every decision. The
transport asks the Python when a session starts and when a stream opens, and
asks nothing while bytes flow.

| Rule | Reason |
| --- | --- |
| The transport carries the data and the Python makes the decisions: every permission, ticket, token and secret is the Python's, and the transport holds none of them. | One record of who can do what, kept where `config/` is. |
| A question the Python does not answer within `ControlQuestionTimeout`, 5 seconds, or one asked while no control connection is open, is a refusal, `control_unavailable`. The streams already open are not touched. | A Python that restarts or hangs stops new work and breaks none in flight. |
| A transport that starts again has nothing to rebuild: its sessions end, every peer dials again, and the Python keeps every record. | The transport's memory is only what is live. |

### The socket and its protection

The transport listens and the Python connects. The listener is a Unix socket
or a Windows named pipe in the run root of the package ([files.md](files.md)):

| Role | The listener | Who can open it |
| --- | --- | --- |
| hub | `/run/neutrino/hub/transport/transport.sock` on Linux, `/var/run/neutrino/hub/transport/transport.sock` on macOS, `\\.\pipe\neutrino_hub_transport` on Windows | mode 0600, owned by the transport's account, under a 0700 directory of that account, which root opens as root opens any file; the pipe's access list grants the transport's account, SYSTEM and the administrators |
| agent | `/run/neutrino/agent/transport.sock`, `/var/run/neutrino/agent/transport.sock`, `\\.\pipe\neutrino_agent_transport` | mode 0600 under the 0700 run directory, root's; the pipe grants SYSTEM and the administrators, as the agent's control pipe does |
| client | `$XDG_RUNTIME_DIR/neutrino/transport.sock`, `~/Library/Application Support/Neutrino/client/transport.sock`, `\\.\pipe\neutrino_client_transport_<user>`; on a phone, `transport.sock` in the directory the app gives `Start`, its own data directory, or, when that path is longer than the system's socket path limit, as in the iOS Simulator, in a directory of the library's own, mode 0700, under the system's temporary directory; `Start` returns the path it bound | mode 0600, the person's own; the pipe grants the person's account alone |

Every connection to the listener opens with one JSON line that holds
`secret`, 64 hex characters the transport received at its start; a
connection whose first line holds another secret, or none within one
second, is closed with nothing written.

| Role | How the transport receives the secret |
| --- | --- |
| hub on Linux | `control_secret` under the transport's state directory, 32 random bytes in hex, mode 0640, owned by root with the transport's group; the panel's process writes it when it is missing, and the transport reads it at its start, exiting when it is not there yet, so its unit starts it again |
| hub on macOS and Windows, the agent, the desktop client, and a checkout | the first line on the transport's standard input, written by the process that starts the transport as its child, which makes the secret afresh at each start |
| the Android and iOS apps | the argument of the library's `Start(directory, secret)`, which returns the socket's path; the library's whole surface beside `Stop()`. On Android the library is bound into one `.aar` with NetBird's, as the class `io.netbird.gomobile.mobile.Mobile` with `start` and `stop`; on iOS it is `Mobile.xcframework`, with `MobileStart` and `MobileStop` |

### Connections and lines

A local connection is one of three by its first line:

| First line | The connection |
| --- | --- |
| `{secret, op: control}` | the control connection: questions, commands and events, as JSON lines both ways; a second one replaces the first |
| `{secret, op: attach, stream}` | takes a stream the transport announced with the event `stream`, whose `open` the event carried; the Python writes the stream's answer first, `accept` or a refusing `close`, and the connection then carries the stream's records both ways, unchanged. A stream nobody attaches within `ControlQuestionTimeout` is closed `control_unavailable` |
| `{secret, op: open, session, open}` | opens a stream on that session (`binding` in place of `session` on the client, and nothing on the agent), `open` being the open record's JSON; the connection then carries the stream's records, the far side's `accept` or refusing `close` first, and after the `accept` of a TCP `connect` its raw bytes |

Every line is one JSON object in UTF-8, at most `ControlFrameBytesMax`:

| Line | Shape |
| --- | --- |
| a question, from the transport | `{id, question, ...fields}`, answered by the Python's `{id, ...answer}` |
| a command, from the Python | `{id, command, ...fields}`, answered by the transport's `{id}` or `{id, code, params}` |
| an event, from the transport | `{event, ...fields}`, with no answer |
| a frame, either way | `{frame, session}`, `binding` in place of `session` on the client and nothing on the agent: one frame of a control stream as the stream carries it, `{type, ...body}`, passed on with no answer; from the Python it can add `is_last: true`, and the transport ends the session once the frame is written |

`id` is the asker's own string, unique among its open questions or commands.
The questions open on a control connection that a second one replaces are
answered `control_unavailable`.

### The hub's local channel

| Question | Asked | Fields | The Python's answer |
| --- | --- | --- | --- |
| `peer` | after a bound peer's knock opened, before the transport answers it | `{public_key, role, protocol, address, listener}`, `listener` being `main`, `sakurafrp` or `openfrp` | `{binding_id, role, psk}` to admit, `role` being the table the key is in, which the session takes; or `{code, params}`, which the transport writes after a handshake under the zero psk: `binding_unknown` for a key no binding holds, `role_mismatch` for a knock whose role is not the key's, and the admission codes |
| `ticket` | at a `join` frame | `{ticket, role, protocol, public_key, machine_id, name, software, platform, address, listener}` | `{binding_id, token}`, the ticket spent and the binding made with `public_key`, which the transport writes as `joined {id, token}`; or `{code, params}`. `id` on an answer line is the question's own, so the binding's id is `binding_id` here as in `peer`'s answer |
| `entry` | when a client opens `connect`, `shell` or `exec`, a guest opens `connect`, or an agent opens `connect` | `{session, binding_id, open}`, a guest's `binding_id` being its share's id | `{kind, device_id, key, target}`: `target` is `{session, open}`, a stream to open on that agent session with the open record given, the hub's stamps written in, or `{address, port, protocol}`, a far end the transport dials itself; `kind` is the permission kind the stream falls under, `device_id` the machine it reaches and `key` its row id in a permission ([protocol.md](protocol.md), `/api/hub/client`), empty for `ai` and the panel, each kept with the stream for `streams_close`; or `{code, params}` |
| `token` | at a client's or a guest's `service` frame | `{session, binding_id, frame}` | `{params}`, the material, or `{code, params}`; the transport sends it as the `reply` |
| `guest` | at a guest's open record, after the gate opened the data channel under a live share's ufrag | `{ticket, share, protocol, address, listener}`, `share` being that ufrag | `{binding_id}`, the share's id, which the transport writes in the `accept` record and which the guest's session and its `hello` take; or `{code, params}`, which it writes in the `close` record: `share_unknown` when no share holds that ufrag or the ticket is not that share's, and `protocol_too_old` or `protocol_too_new {peer, hub, min}` by "The numbers". Nothing is spent, and a refusal counts as no failed admission |

| Command | Fields | The transport |
| --- | --- | --- |
| `session_close` | `{session, code, params}` | sends `refused {code, params}` on the session's control stream and ends the session |
| `streams_close` | `{binding_id, kind, device_id, key, session_id, code, params}`, `device_id`, `key` and `session_id` empty for every machine, every row and every kept shell | closes every stream of that binding it holds under `kind`, on that machine, under that row and on that kept shell where they are named, with `close {code, params}`, a raw TCP `connect` with a reset: `permission_denied {kind}` when a permission changes, a kind, a machine or a row taken away, `session_not_owned {session_id}` when an owner stops sharing a shell, closing the other clients' streams on it |
| `keys_reload` | `{}` | reads its static key and its DTLS certificate again, makes a new one of either when its file is missing, writes `public_key` and `dtls_fingerprint`, and ends every session |
| `shares_set` | `{shares: [{ufrag, pwd}]}`, every live share | replaces its table of live shares with the list; the guest door answers the ufrags it names alone, and stays shut while it is empty. The Python sends it at every change of a share and first on each new control connection |

These four are the commands. Besides them the Python sends frames: `welcome`,
`refused`, `state`, `left` with `is_last`, a `reply` to a `persist` or a
`stop_session`, and the `persist` and `stop_session` it sends an agent.

| Event | Fields | When |
| --- | --- | --- |
| `session_open` | `{session, binding_id, role, address, local_address, listener}`, `role` `guest` for a guest | a handshake completed for a key `peer` admitted, or a guest's open record was accepted, `local_address` being the hub's own address the peer's connection reached; the session's frames follow. On a new control connection it comes once for every live session, followed by that session's `hello`; the Python then sends no second `welcome`, and pushes the state at the session's next report as on a first report |
| `session_end` | `{session, reason}` | the session ended |
| a frame | `{frame, session}` | each frame of a session `session_open` named, but `ping` and a client's `service`: `hello`, `report`, `leave`, a client's `persist` and `stop_session`, an agent's `reply` |
| `stream` | `{stream, session, open}` | an agent opened `log` or `package`, which the Python takes with `attach` |

The hub's Python opens its own streams to an agent, a container's `shell`,
`file`, `command`, with an `open` connection. Every other stream on the hub
is relayed: the transport copies its records, or a TCP `connect`'s raw bytes,
between the two sessions it joins.

### The agent's local channel

The agent starts its transport as its child and drives one session to its
hub through it. The transport makes the knock and the handshake; the agent
writes every frame, `hello` first, as a frame line.

| Command | Fields | The transport |
| --- | --- | --- |
| `dial` | `{hub_key, private_key, psk, role, protocol, addresses}`, `addresses` the set "Where the port is reached" names | keeps one session to the hub, dialling every address at once at each round, and again after each end ("The redial") |
| `join` | `{hub_key, private_key, addresses, ticket, role, protocol, machine_id, name, software, platform}` | dials as a round does, knocks with `is_join` on the round's winner alone, sends the one `join` there, and answers `{binding_id, token}`, the `joined` frame's `id` and `token`, or `{code, params}`: `hub_unreachable {detail}` when no address answered, `hub_untrusted` when a link's address answered under neither psk, which ends the round, else the hub's own |
| `leave` | `{hub_key, private_key, psk, role, protocol, addresses}` | dials, sends `leave`, and answers `{}` or `{code, params}` |
| `forward_start` | `{listen, protocol, open}` | listens on `listen`, `127.0.0.1:8317` for the AI gateway forward, and opens a stream with `open`, `{kind: connect, id: ai}`, for each connection, relaying its bytes; answers `{id, listen}`, the address bound |
| `forward_stop` | `{listen, protocol}` | closes that listener |
| `undial` | `{}` | ends the session and dials no more |

| Question | Fields | The agent's answer |
| --- | --- | --- |
| `port` | `{port, protocol}`, at the hub's `connect` | `{address}`, the address to dial, `127.0.0.1` or the one a container's binding names; or `{code: port_not_published, params: {port}}` |

| Event | Fields | When |
| --- | --- | --- |
| `session_open` | `{address, local_address}` | a handshake completed and the control stream opened; the agent then writes `hello`. `local_address` is the connection's own, which the report names as the link |
| `session_end` | `{code, params}` | the session ended, with the refusal that ended it, if any |
| `round_end` | `{code, params, next_round_s}` | a round through the whole address set ended with no session: `hub_unreachable {detail}`, `hub_untrusted` or the hub's own `refused`, and the seconds until the next round, 0 when none follows |
| a frame | `{frame}` | each frame from the hub, `pong` included |
| `stream` | `{stream, open}` | the hub opened `shell`, `exec`, `file` or `command`, which the agent takes with `attach`; a `connect` the transport serves itself after `port` |

### The client's local channel

The client's resident on a desktop starts its transport as its child; a
phone app starts the library in its own process. One transport holds a
session to every hub the client is bound to, each named by `binding`, the
binding's id, and the client writes every frame of each, `hello` first.

| Command | Fields | The transport |
| --- | --- | --- |
| `dial` | `{binding, hub_key, private_key, psk, role, protocol, candidates}`, each candidate `{address, path}`, `path` being one of the paths [client.md](client.md) ranks | keeps one session to that hub by the round rules of [client.md](client.md), "The Hubs page" |
| `undial` | `{binding}` | ends that hub's session and dials it no more |
| `round` | `{binding}` | starts a round at once, as a network change does |
| `join`, `leave` | the agent's fields, with `binding`: on a `join` the client's own label for the binding it has no id for yet, which no event carries; the answer's `id` is the binding's | as on the agent |
| `forward_start` | `{binding, listen, protocol, open}` | listens on `listen` and opens a stream with `open` on that hub's session for each TCP connection, or one stream for a UDP listener, relaying its bytes; while the hub has no session the listener accepts nothing new; answers `{id, listen}`, the address bound, so a `listen` whose port is 0 gets the system's pick. A program that keeps a listener of its own opens each connection with an `open` connection instead, `{op: open, binding, open: {kind: connect, id}}` |
| `forward_stop` | `{listen, protocol}` | closes that listener and its streams; a TCP and a UDP forward may hold one number |

| Event | Fields | When |
| --- | --- | --- |
| `session_open` | `{binding, address, path, handshake_ms}` | a round's winner completed its handshake and opened its control stream; the client then writes `hello`. For a binding whose session is live it is a move to a better path ([client.md](client.md), "A network change starts a round"): the client writes `hello` on the new session, and the transport drops every frame of the session it moved off, its `refused replaced` among them, and sends no `session_end` for it, so a `replaced` the client reads is another client taking the binding |
| `round_end` | `{binding, code, params, next_round_s}` | a round ended with no session, with the code the client's Hubs row words: `hub_unreachable {detail}` when no address answered or completed a handshake, `detail` the last address's error, `hub_untrusted` when an address answered under neither psk, else the hub's own `refused`; and the seconds until the transport's next round, 0 when none follows |
| `session_end` | `{binding, code, params}` | a session ended, with the refusal that ended it, if any |
| a frame | `{frame, binding}` | each frame from the hub, `pong` included: the client sets `rtt_ms` from the `pong` whose `nonce` is its last `ping` ([protocol.md](protocol.md), "The control stream") |
| `forward_end` | `{listen, protocol, code, params}` | a listener stopped: a UDP forward whose one stream the hub or the agent closed with a code ends with that code, `permission_denied`, `agent_offline` and `port_not_published` among them, and the client starts it again when it wants it; a TCP forward's refused stream closes that one connection and ends nothing. A listener that cannot start is the answer to its `forward_start`, `port_taken {port}` among the codes |

## Streams on the connection

A client names an entry by its id. The hub takes the host and the port from
the entry, and reads the secret a service needs from its own store. The
hub checks each stream against the client's permission: the kind and the
machine the table names, or the entry's row where the permission sets one
([protocol.md](protocol.md), `/api/hub/client`).

| Kind | The client opens on its own machine | On the connection | The hub checks | The service is reached by |
| --- | --- | --- | --- | --- |
| Files | Linux and macOS: a loopback port and a system mount. Windows: the file network card and a drive letter. Android and iOS: nothing, the app reads the share itself. | a `service` frame for the share's user and password where a Samba module serves it, then one `connect` for each SMB connection | the `file` kind and the machine | the agent, at the machine's loopback port 445; the hub itself for a declared host |
| Web pages | a loopback port, and the browser | a `service` frame for the token where the page has one, then one `connect` for each connection | the `web` kind and the machine | the agent, at the page's loopback port; the hub itself for a declared page |
| Ports | a loopback port, TCP or UDP as the entry states | one `connect` for each TCP connection, or one for a UDP entry | the `port` kind and the machine | the agent for a container's port or Gitea's SSH server; the hub itself for a declared one |
| SSH | a loopback port at the entry's local port, or `nclient ssh proxy` on the standard input and output of the program that started it | a `service` frame for the account's key and the machine's host key, then one `connect` for each SSH connection | the `ssh` kind and the machine | the agent, at the account's SSH server instance on the machine's loopback, which admits the hub's key for that account alone ([agent/modules/ssh_server.md](agent/modules/ssh_server.md)) |
| The panel | a loopback port, and the browser | a `service` frame for a sign-in token, then one `connect` for each connection | the `panel` kind | the hub, at the panel's loopback HTTP port |
| Remote desktops | a loopback port, and the viewer | a `service` frame for the seat password, then one `connect` for each connection | the `rdp` kind, the machine, and that the machine reports the share, which it does only while its Remote desktop switch is on | the agent, at the viewer port on the machine's loopback |
| Terminals | a terminal in the client's window | one `shell`, a `resize` record for each resize, and a `persist` or `stop_session` frame for each persist, share and end | the `terminal` kind and the machine | the agent, which keeps the session and runs the shell as the enabled account the open names, never root |
| Commands | `nclient terminal exec`, its stdin, stdout and stderr | one `exec`, and a `resize` record for each resize with `--tty` | the `terminal` kind and the machine, as for a terminal | the agent, which runs the command once as the enabled account the open names, never root, and keeps nothing |
| The AI gateway | a loopback port the AI tools point at | a `service` frame for the client's key, then one `connect` for each connection | the `ai` kind | the hub, at the gateway's loopback port |

## What an admitted client reaches

| Rule | Reason |
| --- | --- |
| A stream names an entry id, the panel, or a machine for a shell or a command. The host and the port come from the hub's own records. | A stolen client binding reaches what the hub publishes to that client. |
| The hub's transport asks the hub's Python about every `open`, which judges it against the client's permission, its kinds, each kind's machines and its rows ([protocol.md](protocol.md), `/api/hub/client`); the transport then dials. | A permission changed on the **Clients** page holds for the next stream without a reconnect. |
| An agent dials a port only while its machine publishes that port, and closes any other with `port_not_published {port}`. | The agent makes the check itself, so a fault in the hub's check opens no port the machine does not publish. |
| Switching a client off, deleting it, or taking a kind, a machine or a row from it immediately closes what the change covers: the session, through `session_close`, or the shells, the commands and the `connect` streams of that kind, through `streams_close`, and the panel sessions of that kind ("The local channel"). | A person switches a client off because the device is lost. A shell that stays open is the access they meant to end. |
| The panel is a kind like the others: the **Clients** page sets it in the default and for each client. A new hub's default has it off. A client with it receives a sign-in token of 32 random bytes that holds 60 seconds for one use. | The panel changes the hub itself, so a person turns it on for the devices that are their own. |
| A client joins a terminal session that is its own or is shared, on a machine its `terminal` kind includes. A `shell` or a `persist` on any other session is refused `session_not_owned {session_id}`. | A session is a shell as one of the machine's accounts, with its output on screen. A session that stops being shared closes to every viewer but its owner. |
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
| A small request waits behind the bytes a bulk transfer on the same session has already queued. Measured on 2026-10-26 at a 100 ms round trip: a 3 KB request took 102 ms on an idle session and 200 ms, at most 300, while a file copy ran on it. | A page or a terminal is slower while a file copies, by up to a few round trips. 0.6.0 accepts this and opens no second connection for file streams. |
| A datagram in a stream keeps its boundary and loses its timing. It arrives late where plain UDP loses it. | UDP over the connection suits request and reply traffic: DNS, time, discovery, a small game server. Voice, video and fast games need a direct path. |
| The hub's uplink and its transport bound the speed of every stream. Through the relay or a frp node that server's bandwidth bounds it too. | Terminals, editors, a desktop and ordinary file copies fit inside that bound. A transfer that needs the line's full speed uses a direct path. |
| A direct path is a subnet route the person sets up in the overlay's own console. The hub lists the served networks for it and manages no route there. | That path is outside the connection. It reaches a machine's own ports under each service's own login, with no kind and no entry in between. |
