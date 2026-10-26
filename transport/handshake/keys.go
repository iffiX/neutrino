package handshake

import (
	"crypto/rand"
	"encoding/hex"
	"fmt"

	"github.com/flynn/noise"
	"golang.org/x/crypto/curve25519"
)

// Suite is the one cipher suite the channel speaks.
var Suite = noise.NewCipherSuite(noise.DH25519, noise.CipherChaChaPoly, noise.HashBLAKE2s)

// ZeroPsk is the psk of a join and of every refusal.
var ZeroPsk = make([]byte, HandshakeKeyBytes)

// GenerateKey makes a fresh Curve25519 static key pair.
func GenerateKey() (noise.DHKey, error) {
	key, err := Suite.GenerateKeypair(rand.Reader)
	if err != nil {
		return noise.DHKey{}, fmt.Errorf("generate key: %w", err)
	}
	return key, nil
}

// KeyFromPrivate makes the pair of a private key given as 64 hex characters.
// It returns ErrKeyInvalid for any other text.
func KeyFromPrivate(privateHex string) (noise.DHKey, error) {
	private, err := DecodeKey(privateHex)
	if err != nil {
		return noise.DHKey{}, err
	}
	public, err := curve25519.X25519(private, curve25519.Basepoint)
	if err != nil {
		return noise.DHKey{}, fmt.Errorf("%w: %w", ErrKeyInvalid, err)
	}
	return noise.DHKey{Private: private, Public: public}, nil
}

// DecodeKey reads 64 hex characters as 32 bytes: a key, a psk or a digest.
// It returns ErrKeyInvalid for any other text.
func DecodeKey(text string) ([]byte, error) {
	key, err := hex.DecodeString(text)
	if err != nil || len(key) != HandshakeKeyBytes {
		return nil, fmt.Errorf("%w: %d characters", ErrKeyInvalid, len(text))
	}
	return key, nil
}

// EncodeKey writes 32 bytes as 64 lowercase hex characters.
func EncodeKey(key []byte) string {
	return hex.EncodeToString(key)
}
