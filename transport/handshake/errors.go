package handshake

import "errors"

var (
	// ErrHubUntrusted is a message 2 that opens under neither the peer's psk
	// nor the zero psk.
	ErrHubUntrusted = errors.New("hub untrusted")
	// ErrMessage1Invalid is a message 1 that does not open under the hub's
	// static key.
	ErrMessage1Invalid = errors.New("message 1 invalid")
	// ErrKeyInvalid is a key that is not 32 bytes or 64 hex characters.
	ErrKeyInvalid = errors.New("key invalid")
)
