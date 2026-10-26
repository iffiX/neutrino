package knock

import "time"

// PROTOCOL is the channel number this build speaks. One number has one name
// in every package, so it carries no prefix.
const PROTOCOL = 4

const (
	// KnockVersion is the first byte of a knock and of the hub's answer.
	KnockVersion = 4
	// KnockBytesMax bounds a whole knock: the version, the length, message 1
	// and the two macs.
	KnockBytesMax = 1024
	// KnockHeaderBytes is the version byte and the big-endian u16 length.
	KnockHeaderBytes = 3
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
	// KnockLegacyTLSByte is the first byte of a TLS handshake, which a 0.5
	// peer sends and the hub hands to its legacy listener.
	KnockLegacyTLSByte = 22
)

const (
	// KnockFirstByteTimeout bounds a connection that has sent no byte.
	KnockFirstByteTimeout = 3 * time.Second
	// HandshakeTimeout bounds the knock and the hub's answer, from the accept.
	HandshakeTimeout = 10 * time.Second
	// AdmissionTimeout bounds the time from the accept to an admitted hello.
	AdmissionTimeout = 30 * time.Second
	// UnadmittedMax is how many connections may wait for admission at once.
	UnadmittedMax = 128
	// HandshakesInFlightMax is how many knocks may have their message 1 open
	// or their question pending at once.
	HandshakesInFlightMax = 64
	// CookieLoadThreshold is the number of knocks in flight above which the
	// hub is under load and asks for mac2.
	CookieLoadThreshold = 16
	// CookieSecretLifetime is the life of the cookie secret and of a cookie.
	CookieSecretLifetime = 120 * time.Second // scan: allow
)

const (
	// CookieReplyByte is the first byte of a cookie reply.
	CookieReplyByte = 0x84
	// CookieNonceBytes is the XChaCha20-Poly1305 nonce in a cookie reply.
	CookieNonceBytes = 24
	// CookieSealedBytes is the cookie with its authentication tag.
	CookieSealedBytes = KnockMacBytes + 16
	// CookieReplyBytes is the whole reply.
	CookieReplyBytes = 1 + CookieNonceBytes + CookieSealedBytes
	// CookieSecretBytes is the size of the hub's cookie secret.
	CookieSecretBytes = 32
)
