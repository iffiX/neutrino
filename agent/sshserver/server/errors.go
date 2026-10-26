package server

import "errors"

var (
	// ErrAuthorizedKeyMissing is returned for an authorized key file that
	// holds no public key.
	ErrAuthorizedKeyMissing = errors.New("no public key in the authorized key file")

	// ErrKeyNotAuthorized is returned to the handshake for a key that is not
	// the authorized one.
	ErrKeyNotAuthorized = errors.New("public key not authorized")

	// ErrListenNotLoopback is returned for a listen address outside loopback.
	ErrListenNotLoopback = errors.New("listen address is not on loopback")
)
