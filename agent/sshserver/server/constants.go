package server

import "time"

const (
	// ServerVersion is the identification line the server sends first.
	ServerVersion = "SSH-2.0-neutrino_ssh_server"

	// ServerHandshakeTimeout bounds the time from an accepted connection to
	// its authenticated session.
	ServerHandshakeTimeout = 30 * time.Second

	// ServerMaxAuthTries is how many keys one connection may offer.
	ServerMaxAuthTries = 6

	// ServerAcceptRetryDelay is the pause after a failed accept.
	ServerAcceptRetryDelay = 100 * time.Millisecond

	// ServerChannelSession is the channel type of a shell, a command or a
	// subsystem.
	ServerChannelSession = "session"

	// ServerChannelDirectTCPIP is the channel type of a local forward.
	ServerChannelDirectTCPIP = "direct-tcpip"

	// ServerRequestRemoteForward is the global request of a remote forward.
	ServerRequestRemoteForward = "tcpip-forward"
)
