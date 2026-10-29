package session

import "time"

// The windows, limits and timings of the channel.
const (
	// StreamWindowInitialBytes is a stream's window when it opens.
	StreamWindowInitialBytes = 256 * 1024
	// StreamWindowMaxBytes is the largest window a stream grows to.
	StreamWindowMaxBytes = 16 * 1024 * 1024
	// TransportMemoryMaxBytes bounds the windows the hub's transport holds
	// for every stream together: 16 streams at the largest window.
	TransportMemoryMaxBytes = 256 * 1024 * 1024
	// StreamOpenPriority is the priority go-yamux reserves a stream's first
	// window at.
	StreamOpenPriority = 255
	// RecordBytesMax bounds one record's payload.
	RecordBytesMax = 64 * 1024
	// RecordHeaderBytes is a record's type and big-endian u32 length.
	RecordHeaderBytes = 5
	// ControlFrameBytesMax bounds one frame on a control stream.
	ControlFrameBytesMax = 2 * 1024 * 1024
	// KeepAliveInterval is the time between yamux pings.
	KeepAliveInterval = 20 * time.Second
	// KeepAliveTimeout is the wait for a ping's answer.
	KeepAliveTimeout = 60 * time.Second
	// HelloTimeout bounds a session's first frame, from the answer.
	HelloTimeout = 10 * time.Second
	// DialTimeout bounds a dial and the handshake on it.
	DialTimeout = 10 * time.Second
	// RedialBackoffMin and RedialBackoffMax bound the wait between rounds.
	RedialBackoffMin = 5 * time.Second
	RedialBackoffMax = 60 * time.Second
	// RedialInterval is a peer's redial of an address refused within a round.
	RedialInterval = time.Second
	// ConnectDialTimeout bounds dialling the far end of a connect stream.
	ConnectDialTimeout = 10 * time.Second
	// ConnectStreamsMax bounds the open connect streams on one client session.
	ConnectStreamsMax = 256
	// UdpIdleTimeout closes a UDP source's socket with no datagram either way.
	UdpIdleTimeout = 60 * time.Second
	// UdpSourcesMax bounds the sources one UDP stream's far end keeps.
	UdpSourcesMax = 64
	// UdpHeldDatagramsMax bounds the datagrams held before a stream's accept.
	UdpHeldDatagramsMax = 16
	// SessionsMax bounds the admitted sessions on the hub.
	SessionsMax = 512
	// SessionStreamsMax bounds the streams a peer may have open on one session.
	SessionStreamsMax = 1024
	// SessionAcceptBacklog is how many opened streams wait for an accept.
	SessionAcceptBacklog = 256
	// SessionReadBufferBytes is yamux's read buffer over the Noise connection.
	SessionReadBufferBytes = 64 * 1024
	// PingNonceCharsMax is how much of a ping's nonce a pong echoes.
	PingNonceCharsMax = 64
)

// The Noise transport message layout.
const (
	// NoiseMessageMax is the largest Noise transport message, tag included.
	NoiseMessageMax = 65535
	// NoiseTagBytes is the authentication tag of one message.
	NoiseTagBytes = 16
	// NoisePlainMax is the plaintext one message carries; one yamux frame
	// fits one message.
	NoisePlainMax = NoiseMessageMax - NoiseTagBytes
	// NoiseLengthBytes is the big-endian u16 before every message.
	NoiseLengthBytes = 2
)

// The record types.
const (
	RecordOpen     byte = 1
	RecordAccept   byte = 2
	RecordData     byte = 3
	RecordStderr   byte = 4
	RecordEof      byte = 5
	RecordResize   byte = 6
	RecordDatagram byte = 7
	RecordClose    byte = 8
)

// The stream kinds.
const (
	KindControl = "control"
	KindShell   = "shell"
	KindExec    = "exec"
	KindFile    = "file"
	KindCommand = "command"
	KindPackage = "package"
	KindLog     = "log"
	KindConnect = "connect"
)

// The protocols a connect stream names.
const (
	ProtocolTCP = "tcp"
	ProtocolUDP = "udp"
)

// The frames, each named by its type key.
const (
	FrameTypeKey     = "type"
	FrameHello       = "hello"
	FrameWelcome     = "welcome"
	FrameJoin        = "join"
	FrameJoined      = "joined"
	FrameLeave       = "leave"
	FrameLeft        = "left"
	FrameRefused     = "refused"
	FrameState       = "state"
	FrameReport      = "report"
	FramePing        = "ping"
	FramePong        = "pong"
	FrameService     = "service"
	FramePersist     = "persist"
	FrameStopSession = "stop_session"
	FrameReply       = "reply"
)

// The codes the transport says itself.
const (
	CodeControlUnavailable = "control_unavailable"
	CodeChannelFull        = "channel_full"
	CodeHelloInvalid       = "hello_invalid"
	CodeReplaced           = "replaced"
	CodeConnectLimit       = "connect_limit"
	CodeConnectFailed      = "connect_failed"
	CodeKindUnknown        = "kind_unknown"
	CodeHubUnreachable     = "hub_unreachable"
	CodeHubUntrusted       = "hub_untrusted"
	CodeBindingUnknown     = "binding_unknown"
	CodeAgentOffline       = "agent_offline"
	CodePortTaken          = "port_taken"
	CodeSchemeUnknown      = "scheme_unknown"
)

// The reasons a connect_failed names.
const (
	ReasonRefused     = "refused"
	ReasonTimeout     = "timeout"
	ReasonUnreachable = "unreachable"
)

// AddressScheme is the one scheme every address carries.
const AddressScheme = "tcp://"
