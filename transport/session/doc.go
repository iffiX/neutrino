// Package session is one admitted connection between a peer and the hub
// after the handshake: the Noise transport messages that carry it, the
// go-yamux session on top of them with its windows and its keepalive, the
// records every stream carries, the control stream's JSON lines, the memory
// the hub holds for its streams, and the dial of one address from a peer,
// knock and handshake included. Every timing of the channel is a constant
// here.
package session
