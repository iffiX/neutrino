// Package gate is the WebRTC gate of the hub's agent port: the path a
// browser takes to the hub with nothing installed. On one TCP connection
// framed as RFC 4571 it answers the browser's ICE connectivity checks under
// the ice-pwd of the share the ice-ufrag names, runs the DTLS handshake under
// the hub's long-lived certificate, the SCTP association and the negotiated
// data channel 0, and hands the channel back as a net.Conn that carries the
// guest's session. It reads the guest's first message, the share ticket, and
// writes the hub's answer to it. It is built on pion's stun, dtls, sctp and
// datachannel packages and on no ICE agent: the hub is ICE-lite with one
// passive TCP candidate and never reads the browser's answer.
package gate
