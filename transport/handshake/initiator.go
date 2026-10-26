package handshake

import (
	"bytes"
	"crypto/rand"
	"fmt"
	"io"

	"github.com/flynn/noise"
)

// Keys are the two cipher states a finished handshake leaves: one for each
// direction.
type Keys struct {
	Send    *noise.CipherState
	Receive *noise.CipherState
}

// Initiator is the peer's side of one handshake. It holds two handshake
// states made from one ephemeral key, one under the peer's psk and one under
// the zero psk, so a refusal the hub says under the zero psk still opens.
type Initiator struct {
	expected *noise.HandshakeState
	zero     *noise.HandshakeState
	// Message1 is the message the peer sends, the knock's payload.
	Message1 []byte
}

// NewInitiator starts a handshake from static to hubPublic under psk, with
// payload inside message 1. A psk equal to ZeroPsk is a join's. It returns
// an error when a key has the wrong size.
func NewInitiator(static noise.DHKey, hubPublic, psk, payload []byte) (*Initiator, error) {
	seed := make([]byte, HandshakeKeyBytes)
	if _, err := rand.Read(seed); err != nil {
		return nil, fmt.Errorf("ephemeral key: %w", err)
	}
	return newInitiator(static, seed, hubPublic, psk, payload, []byte(HandshakePrologue))
}

// newInitiator makes the two states, each drawing the same ephemeral private
// key from seed.
func newInitiator(static noise.DHKey, seed, hubPublic, psk, payload, prologue []byte) (*Initiator, error) {
	expected, err := newState(true, static, bytes.NewReader(seed), hubPublic, psk, prologue)
	if err != nil {
		return nil, err
	}
	message1, _, _, err := expected.WriteMessage(nil, payload)
	if err != nil {
		return nil, fmt.Errorf("message 1: %w", err)
	}
	initiator := &Initiator{expected: expected, Message1: message1}
	if !bytes.Equal(psk, ZeroPsk) {
		zero, err := newState(true, static, bytes.NewReader(seed), hubPublic, ZeroPsk, prologue)
		if err != nil {
			return nil, err
		}
		if _, _, _, err := zero.WriteMessage(nil, payload); err != nil {
			return nil, fmt.Errorf("message 1: %w", err)
		}
		initiator.zero = zero
	}
	return initiator, nil
}

// Open reads the hub's message 2. It returns the session's keys and whether
// the message opened under the zero psk while the peer's psk was another,
// which means the frame after it is a refusal. It returns ErrHubUntrusted
// when the message opens under neither psk.
func (i *Initiator) Open(message2 []byte) (*Keys, bool, error) {
	if _, send, receive, err := i.expected.ReadMessage(nil, message2); err == nil {
		return &Keys{Send: send, Receive: receive}, false, nil
	}
	if i.zero != nil {
		if _, send, receive, err := i.zero.ReadMessage(nil, message2); err == nil {
			return &Keys{Send: send, Receive: receive}, true, nil
		}
	}
	return nil, false, ErrHubUntrusted
}

// newState makes one handshake state whose ephemeral key is drawn from
// random when its message is written.
func newState(isInitiator bool, static noise.DHKey, random io.Reader, peerStatic, psk, prologue []byte) (*noise.HandshakeState, error) {
	state, err := noise.NewHandshakeState(noise.Config{
		CipherSuite:           Suite,
		Random:                random,
		Pattern:               noise.HandshakeIK,
		Initiator:             isInitiator,
		Prologue:              prologue,
		StaticKeypair:         static,
		PeerStatic:            peerStatic,
		PresharedKey:          psk,
		PresharedKeyPlacement: HandshakePskPlacement,
	})
	if err != nil {
		return nil, fmt.Errorf("handshake state: %w", err)
	}
	return state, nil
}
