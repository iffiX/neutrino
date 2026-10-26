package relay

import "errors"

var (
	// ErrSessionUnknown is a session id the hub holds no session for.
	ErrSessionUnknown = errors.New("session unknown")
	// ErrStreamUnknown is a stream id no announced stream waits under.
	ErrStreamUnknown = errors.New("stream unknown")
	// ErrControlUnavailable is a question the Python did not answer in time,
	// or asked while no control connection is open.
	ErrControlUnavailable = errors.New("control unavailable")
	// ErrNoSession is a stream opened while the peer has no session.
	ErrNoSession = errors.New("no session")
	// ErrForwardStopped is a forward's listener closed by forward_stop.
	ErrForwardStopped = errors.New("forward stopped")
	// ErrProtocolUnknown is a connect protocol that is neither tcp nor udp.
	ErrProtocolUnknown = errors.New("protocol unknown")
)
