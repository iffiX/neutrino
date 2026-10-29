package gate

import "time"

// The bytes that tell a browser's connection from a peer's.
const (
	// GateFrameFirstByte is the first byte of a browser's first RFC 4571
	// frame: the high byte of a STUN Binding Request's length. A knock's
	// version byte is never 0, so the two paths never collide.
	GateFrameFirstByte = 0x00
	// GatePeekBytes is how many bytes decide the path: the two-byte frame
	// length, the STUN type and length, and the magic cookie.
	GatePeekBytes = 10
	// GateStunMagicCookie is the fixed word at bytes 4 to 8 of every STUN
	// message.
	GateStunMagicCookie = 0x2112A442
	// GateStunHeaderBytes is a STUN message's header.
	GateStunHeaderBytes = 20
	// GateStunBindingRequestType is the STUN type of a Binding Request.
	GateStunBindingRequestType = 0x0001
	// GateStunAttributeHeaderBytes is an attribute's type and length.
	GateStunAttributeHeaderBytes = 4
	// GateStunUsernameType is the USERNAME attribute's type.
	GateStunUsernameType = 0x0006
	// GateFrameLengthBytes is the big-endian u16 before every frame.
	GateFrameLengthBytes = 2
	// GateFrameBytesMax is the largest frame the two-byte length allows.
	GateFrameBytesMax = 0xffff
	// GateDtlsContentTypeMin and GateDtlsContentTypeMax bound the first
	// byte of a DTLS record.
	GateDtlsContentTypeMin = 20
	GateDtlsContentTypeMax = 63
)

// The transport's sizes.
const (
	// GateMTU is the DTLS record size, under every path MTU.
	GateMTU = 1200
	// GateSctpOverheadBytes is what the SCTP common header and a DATA chunk's
	// header take off a DTLS record.
	GateSctpOverheadBytes = 28
	// GateReceiveBufferBytes is the SCTP association's receive buffer.
	GateReceiveBufferBytes = 8 * 1024 * 1024
	// GateChannelID is the one data channel, negotiated out of band.
	GateChannelID = 0
	// GateChannelLabel is the data channel's label.
	GateChannelLabel = "neutrino"
	// GateMessageBytesMax is the largest message the hub writes on the
	// channel, under every browser's receive limit.
	GateMessageBytesMax = 64 * 1024
	// GateReadBytesMax is the largest message the hub reads from the channel,
	// the receive limit its offer states.
	GateReadBytesMax = 256 * 1024
	// GateInboundFramesMax is how many DTLS records wait to be read.
	GateInboundFramesMax = 256
	// GateGuestOpenBytesMax bounds a guest's first message.
	GateGuestOpenBytesMax = 1024
	// GateFlushPoll is how often a flush looks at the buffered amount.
	GateFlushPoll = 5 * time.Millisecond
	// GateClientUfrag is the ice-ufrag the Go client names for itself; the
	// hub reads only the share's half.
	GateClientUfrag = "guest"
	// GateDialTimeout bounds a dial of the gate and the handshakes on it.
	GateDialTimeout = 10 * time.Second
	// GateHandshakeTimeout bounds a guest's first check, DTLS, SCTP, the
	// data channel and its open record, from the accept.
	GateHandshakeTimeout = 20 * time.Second
)

// The DTLS certificate's files under the hub's configuration, beside the
// static key.
const (
	GateCertificateFile    = "dtls_certificate.pem"
	GateCertificateKeyFile = "dtls_key.pem"
	GateFingerprintFile    = "dtls_fingerprint"
	GateCertificateDirMode = 0o700
	GateCertificateMode    = 0o644
	GateCertificateKeyMode = 0o600
	GateFingerprintMode    = 0o644
	// GateCertificateName is the certificate's common name.
	GateCertificateName = "neutrino-hub"
	// GateCertificateLifetime is how long a certificate stays valid. A link
	// holds its fingerprint, so a new certificate ends every link.
	GateCertificateLifetime = 10 * 365 * 24 * time.Hour
	// GateCertificateBackdate is how far a new certificate's start lies
	// behind the clock, for a browser whose clock runs behind.
	GateCertificateBackdate = 24 * time.Hour
	// GateSerialBits is the size of a certificate's random serial number.
	GateSerialBits = 128
)

// The XOR-MAPPED-ADDRESS of a peer at a loopback, link-local or unspecified
// address, with the peer's port.
const (
	// GateMappedIPv4 is the address for an IPv4 peer, from the documentation
	// block of RFC 5737.
	GateMappedIPv4 = "192.0.2.1"
	// GateMappedIPv6 is the address for an IPv6 peer, from the documentation
	// block of RFC 3849.
	GateMappedIPv6 = "2001:db8::1"
)
