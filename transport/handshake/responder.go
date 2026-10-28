package handshake

import (
	"crypto/rand"
	"fmt"
	"io"

	"github.com/flynn/noise"
)

// Responder is the hub's side of one handshake: it opens message 1 before it
// knows the psk, and writes message 2 under the psk named afterwards.
type Responder struct {
	state *noise.HandshakeState
	// PeerStatic is the peer's static public key, set once message 1 opened.
	PeerStatic []byte
	// Payload is message 1's payload, set once message 1 opened.
	Payload []byte
}

// NewResponder starts the hub's side under its static key.
func NewResponder(static noise.DHKey) (*Responder, error) {
	return newResponder(static, rand.Reader, []byte(HandshakePrologue))
}

func newResponder(static noise.DHKey, random io.Reader, prologue []byte) (*Responder, error) {
	state, err := newState(false, static, random, nil, nil, prologue)
	if err != nil {
		return nil, err
	}
	return &Responder{state: state}, nil
}

// Read opens message 1 and keeps the peer's static key and the payload. It
// returns ErrMessage1Invalid when the message does not open.
func (r *Responder) Read(message1 []byte) error {
	payload, _, _, err := r.state.ReadMessage(nil, message1)
	if err != nil {
		return fmt.Errorf("%w: %w", ErrMessage1Invalid, err)
	}
	r.PeerStatic = r.state.PeerStatic()
	r.Payload = payload
	return nil
}

// Answer writes message 2 under psk with payload inside it and returns it
// with the session's keys. It returns an error when psk is not 32 bytes.
func (r *Responder) Answer(psk, payload []byte) ([]byte, *Keys, error) {
	if err := r.state.SetPresharedKey(psk); err != nil {
		return nil, nil, fmt.Errorf("psk: %w", err)
	}
	message2, receive, send, err := r.state.WriteMessage(nil, payload)
	if err != nil {
		return nil, nil, fmt.Errorf("message 2: %w", err)
	}
	return message2, &Keys{Send: send, Receive: receive}, nil
}
