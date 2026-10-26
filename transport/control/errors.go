package control

import "errors"

var (
	// ErrSecretInvalid is a first line whose secret is not the transport's.
	ErrSecretInvalid = errors.New("control secret invalid")
	// ErrLineTooLong is a line past ControlLineLimit.
	ErrLineTooLong = errors.New("control line too long")
	// ErrOpUnknown is a first line naming no connection kind.
	ErrOpUnknown = errors.New("control op unknown")
	// ErrListenerClosed is a listener closed under an Accept.
	ErrListenerClosed = errors.New("control listener closed")
)
