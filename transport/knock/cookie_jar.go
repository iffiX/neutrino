package knock

import (
	"crypto/cipher"
	"crypto/rand"
	"fmt"
	"net"
	"sync"
	"time"

	"golang.org/x/crypto/blake2s"
	"golang.org/x/crypto/chacha20poly1305"
)

// CookieJar makes and checks the cookies the hub asks for under load. A
// cookie is BLAKE2s-128 keyed by the jar's secret over the peer's address,
// and the secret is made afresh every CookieSecretLifetime.
type CookieJar struct {
	aead   cipher.AEAD
	now    func() time.Time
	header []byte

	// mu guards secret and madeAt.
	mu     sync.Mutex
	secret []byte
	madeAt time.Time
}

// NewCookieJar makes a jar sealing its replies under hubPublic, reading the
// clock from now. It returns an error only when the random source fails.
func NewCookieJar(hubPublic []byte, now func() time.Time) (*CookieJar, error) {
	aead, err := chacha20poly1305.NewX(cookieKey(hubPublic))
	if err != nil {
		return nil, fmt.Errorf("cookie cipher: %w", err)
	}
	jar := &CookieJar{aead: aead, now: now, header: EncodeHeader(hubPublic, KnockTypeCookieReply)}
	if err := jar.rotate(); err != nil {
		return nil, err
	}
	return jar, nil
}

// Cookie is the cookie for one peer address under the current secret.
func (j *CookieJar) Cookie(address net.IP) []byte {
	j.mu.Lock()
	defer j.mu.Unlock()
	if j.now().Sub(j.madeAt) >= CookieSecretLifetime {
		if err := j.rotate(); err != nil {
			panic(err)
		}
	}
	return keyedMac(j.secret, addressBytes(address))
}

// IsMac2Valid reports whether the knock's mac2 was made under the cookie of
// address under the current secret.
func (j *CookieJar) IsMac2Valid(knock *Knock, address net.IP) bool {
	return knock.VerifyMac2(j.Cookie(address))
}

// Reply is the cookie reply to a knock from address: the header with the
// cookie reply's type, a nonce, and the cookie sealed with the knock's mac1
// as associated data.
func (j *CookieJar) Reply(knock *Knock, address net.IP) ([]byte, error) {
	reply := make([]byte, KnockHeaderBytes+CookieNonceBytes, CookieReplyBytes)
	copy(reply, j.header)
	if _, err := rand.Read(reply[KnockHeaderBytes:]); err != nil {
		return nil, fmt.Errorf("cookie nonce: %w", err)
	}
	return j.aead.Seal(reply, reply[KnockHeaderBytes:], j.Cookie(address), knock.Mac1), nil
}

func (j *CookieJar) rotate() error {
	secret := make([]byte, CookieSecretBytes)
	if _, err := rand.Read(secret); err != nil {
		return fmt.Errorf("cookie secret: %w", err)
	}
	j.secret = secret
	j.madeAt = j.now()
	return nil
}

// OpenReply opens a cookie reply the hub wrote under hubPublic to a knock
// whose mac1 was mac1, and returns the cookie. It returns ErrNotCookieReply
// when the header is not a cookie reply's under hubPublic and
// ErrCookieReplyMalformed when the reply does not open.
func OpenReply(reply, hubPublic, mac1 []byte) ([]byte, error) {
	header, err := ParseHeader(reply, hubPublic)
	if err != nil || header.Type != KnockTypeCookieReply {
		return nil, ErrNotCookieReply
	}
	if len(reply) != CookieReplyBytes {
		return nil, fmt.Errorf("%w: %d bytes", ErrCookieReplyMalformed, len(reply))
	}
	aead, err := chacha20poly1305.NewX(cookieKey(hubPublic))
	if err != nil {
		return nil, fmt.Errorf("cookie cipher: %w", err)
	}
	nonceEnd := KnockHeaderBytes + CookieNonceBytes
	cookie, err := aead.Open(nil, reply[KnockHeaderBytes:nonceEnd], reply[nonceEnd:], mac1)
	if err != nil {
		return nil, fmt.Errorf("%w: %w", ErrCookieReplyMalformed, err)
	}
	return cookie, nil
}

func cookieKey(hubPublic []byte) []byte {
	sum := blake2s.Sum256(append([]byte(KnockCookieLabel), hubPublic...))
	return sum[:]
}

// addressBytes is the address as the cookie hashes it: 4 bytes for an IPv4
// address, mapped or not, and 16 for any other.
func addressBytes(address net.IP) []byte {
	if four := address.To4(); four != nil {
		return four
	}
	return address.To16()
}
