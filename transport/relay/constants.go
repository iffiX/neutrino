package relay

import "time"

const (
	// RelayCopyBufferBytes is the buffer one direction of a splice copies
	// through, the size of a stream's initial window.
	RelayCopyBufferBytes = 256 * 1024
	// RelayOpenRecordTimeout bounds the wait for a stream's open record.
	RelayOpenRecordTimeout = 10 * time.Second
	// RelayEndGrace is the wait for a peer to read a refusal before the
	// session is closed under it.
	RelayEndGrace = 2 * time.Second
	// RelayUdpSweepInterval is how often idle UDP sources are closed.
	RelayUdpSweepInterval = 5 * time.Second
	// RelayKeepAliveLogInterval is the least time between two log lines for
	// a lost keepalive from one peer address.
	RelayKeepAliveLogInterval = time.Minute
	// RelayMemoryLogInterval is the least time between two log lines for
	// streams the memory cap reset.
	RelayMemoryLogInterval = time.Minute
	// RelayControlRetryAfter is the retry_after_s of every
	// control_unavailable the hub's transport makes.
	RelayControlRetryAfter = 5 * time.Second
	// RelayLoopback is the address the frp listeners listen on.
	RelayLoopback = "127.0.0.1"
	// RelayListenerMain names the agent port's own listener.
	RelayListenerMain = "main"
	// RelayDatagramSourceBytes is the source port in front of a datagram.
	RelayDatagramSourceBytes = 2
	// RelayDatagramMaxBytes is the largest datagram one record carries.
	RelayDatagramMaxBytes = 65507
)

// The roles a relay session runs under: the knock's two and the gate's one.
const (
	RelayRoleAgent  = "agent"
	RelayRoleClient = "client"
	RelayRoleGuest  = "guest"
)

// The static key's files under the hub's configuration.
const (
	RelayStaticKeyFile = "static_key"
	RelayPublicKeyFile = "public_key"
	RelayKeyDirMode    = 0o700
	RelayStaticKeyMode = 0o600
	RelayPublicKeyMode = 0o644
)
