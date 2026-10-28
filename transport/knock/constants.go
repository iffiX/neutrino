package knock

import "time"

// PROTOCOL is the channel number this build speaks. One number has one name
// in every package, so it carries no prefix.
const PROTOCOL = 4

const (
	// KnockVersion is the version every message of the member path carries,
	// a big-endian u16 after the magic; it picks the handshake.
	KnockVersion = 4
	// KnockMagicBytes is the size of the magic that opens every message of
	// the member path.
	KnockMagicBytes = 4
	// KnockMagicLabel keys the magic together with the hub's public key.
	KnockMagicLabel = "magic---"
	// KnockMagicForbiddenStun and KnockMagicForbiddenTLS are the first bytes
	// a magic never has: a browser's STUN frame's and a TLS record's.
	KnockMagicForbiddenStun = 0x00
	KnockMagicForbiddenTLS  = 0x16
	// KnockHeaderBytes is the header before every message of the member
	// path: the magic, the version, the type and a reserved byte.
	KnockHeaderBytes = 8
	// KnockLengthBytes is the big-endian u16 length after a knock's and an
	// answer's header.
	KnockLengthBytes = 2
	// KnockTypeKnock, KnockTypeAnswer and KnockTypeCookieReply are the
	// message types the header names.
	KnockTypeKnock       = 1
	KnockTypeAnswer      = 2
	KnockTypeCookieReply = 3
	// KnockPaddingBytesMax bounds the random padding after message 1's JSON
	// and in message 2's payload.
	KnockPaddingBytesMax = 64
	// KnockBytesMax bounds a whole knock: the header, the length, message 1
	// with its padding and the two macs.
	KnockBytesMax = 1024 + KnockPaddingBytesMax
	// KnockMacBytes is the size of mac1, of mac2 and of a cookie.
	KnockMacBytes = 16
	// KnockMac1Label keys mac1 together with the hub's public key.
	KnockMac1Label = "mac1----"
	// KnockCookieLabel keys the cookie reply together with the hub's public key.
	KnockCookieLabel = "cookie--"
	// KnockReplayKeysMax is how many static keys the replay window remembers.
	KnockReplayKeysMax = 65536
	// KnockRoleAgent and KnockRoleClient are the two roles a knock names.
	KnockRoleAgent  = "agent"
	KnockRoleClient = "client"
)

const (
	// DoorReadBytesMin and DoorReadBytesMax bound the length the door reads
	// of a connection before it refuses it, drawn for each connection.
	DoorReadBytesMin = 20
	DoorReadBytesMax = 100
	// DoorHoldMin and DoorHoldMax bound a connection's hold deadline after
	// the accept, drawn for each connection.
	DoorHoldMin = 5 * time.Second
	DoorHoldMax = 30 * time.Second
	// HandshakeTimeout bounds the knock and the hub's answer, from the accept.
	HandshakeTimeout = 10 * time.Second
	// AdmissionTimeout bounds the time from the accept to an admitted hello.
	AdmissionTimeout = 30 * time.Second
	// UnadmittedMax is how many connections may wait for admission at once.
	UnadmittedMax = 128
	// HandshakesInFlightMax is how many knocks may have their message 1 open
	// or their question pending, and guests their handshake running, at once.
	HandshakesInFlightMax = 64
	// CookieLoadThreshold is the number of knocks in flight above which the
	// hub is under load and asks for mac2.
	CookieLoadThreshold = 16
	// CookieSecretLifetime is the life of the cookie secret and of a cookie.
	CookieSecretLifetime = 120 * time.Second // scan: allow
)

const (
	// CookieNonceBytes is the XChaCha20-Poly1305 nonce in a cookie reply.
	CookieNonceBytes = 24
	// CookieSealedBytes is the cookie with its authentication tag.
	CookieSealedBytes = KnockMacBytes + 16
	// CookieReplyBytes is the whole reply: the header, the nonce and the
	// sealed cookie.
	CookieReplyBytes = KnockHeaderBytes + CookieNonceBytes + CookieSealedBytes
	// CookieSecretBytes is the size of the hub's cookie secret.
	CookieSecretBytes = 32
)
