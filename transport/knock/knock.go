package knock

import (
	"crypto/hmac"
	"encoding/binary"
	"fmt"
	"io"

	"golang.org/x/crypto/blake2s"
)

// Knock is one parsed knock: the first bytes a peer writes on a connection.
type Knock struct {
	// Raw is the whole knock as it was on the wire.
	Raw []byte
	// Message1 is the Noise message 1 inside it.
	Message1 []byte
	// Mac1 is BLAKE2s-128 under the hub's public key over every byte before it.
	Mac1 []byte
	// Mac2 is BLAKE2s-128 under the peer's cookie, or zero while it has none.
	Mac2 []byte
}

// Encode writes a knock for message 1: the version, the length, message 1,
// mac1 under hubPublic and mac2 under cookie, or 16 zero bytes when cookie is
// nil. It returns ErrKnockMalformed when the knock would exceed KnockBytesMax.
func Encode(message1, hubPublic, cookie []byte) ([]byte, error) {
	size := KnockHeaderBytes + len(message1) + 2*KnockMacBytes
	if size > KnockBytesMax {
		return nil, fmt.Errorf("%w: %d bytes", ErrKnockMalformed, size)
	}
	raw := make([]byte, 0, size)
	raw = append(raw, KnockVersion)
	raw = binary.BigEndian.AppendUint16(raw, uint16(len(message1)))
	raw = append(raw, message1...)
	raw = append(raw, Mac1(hubPublic, raw)...)
	raw = append(raw, Mac2(cookie, raw)...)
	return raw, nil
}

// ReadBody reads the rest of a knock after its version byte and returns the
// whole knock, version byte included, parsed. It returns ErrKnockMalformed
// for a length past KnockBytesMax and the reader's error when the bytes end.
func ReadBody(r io.Reader) (*Knock, error) {
	var header [KnockHeaderBytes]byte
	header[0] = KnockVersion
	if _, err := io.ReadFull(r, header[1:]); err != nil {
		return nil, fmt.Errorf("read knock length: %w", err)
	}
	length := int(binary.BigEndian.Uint16(header[1:]))
	size := KnockHeaderBytes + length + 2*KnockMacBytes
	if size > KnockBytesMax {
		return nil, fmt.Errorf("%w: %d bytes", ErrKnockMalformed, size)
	}
	raw := make([]byte, size)
	copy(raw, header[:])
	if _, err := io.ReadFull(r, raw[KnockHeaderBytes:]); err != nil {
		return nil, fmt.Errorf("read knock: %w", err)
	}
	return Parse(raw)
}

// Parse splits a whole knock into its parts. It returns ErrKnockMalformed
// when the version or the length does not fit the bytes.
func Parse(raw []byte) (*Knock, error) {
	if len(raw) < KnockHeaderBytes+2*KnockMacBytes || len(raw) > KnockBytesMax {
		return nil, fmt.Errorf("%w: %d bytes", ErrKnockMalformed, len(raw))
	}
	if raw[0] != KnockVersion {
		return nil, fmt.Errorf("%w: version %d", ErrKnockMalformed, raw[0])
	}
	length := int(binary.BigEndian.Uint16(raw[1:3]))
	if KnockHeaderBytes+length+2*KnockMacBytes != len(raw) {
		return nil, fmt.Errorf("%w: length %d in %d bytes", ErrKnockMalformed, length, len(raw))
	}
	mac1Start := KnockHeaderBytes + length
	return &Knock{
		Raw:      raw,
		Message1: raw[KnockHeaderBytes:mac1Start],
		Mac1:     raw[mac1Start : mac1Start+KnockMacBytes],
		Mac2:     raw[mac1Start+KnockMacBytes:],
	}, nil
}

// VerifyMac1 reports whether the knock's mac1 is the one hubPublic gives.
func (k *Knock) VerifyMac1(hubPublic []byte) bool {
	return hmac.Equal(k.Mac1, Mac1(hubPublic, k.Raw[:len(k.Raw)-2*KnockMacBytes]))
}

// VerifyMac2 reports whether the knock's mac2 is the one cookie gives.
func (k *Knock) VerifyMac2(cookie []byte) bool {
	return hmac.Equal(k.Mac2, Mac2(cookie, k.Raw[:len(k.Raw)-KnockMacBytes]))
}

// Mac1Key is BLAKE2s-256 of KnockMac1Label followed by the hub's public key.
func Mac1Key(hubPublic []byte) []byte {
	sum := blake2s.Sum256(append([]byte(KnockMac1Label), hubPublic...))
	return sum[:]
}

// Mac1 is BLAKE2s-128 keyed by Mac1Key over before, the bytes before mac1.
func Mac1(hubPublic, before []byte) []byte {
	return keyedMac(Mac1Key(hubPublic), before)
}

// Mac2 is BLAKE2s-128 keyed by cookie over before, the bytes before mac2, or
// 16 zero bytes when cookie is nil.
func Mac2(cookie, before []byte) []byte {
	if cookie == nil {
		return make([]byte, KnockMacBytes)
	}
	return keyedMac(cookie, before)
}

func keyedMac(key, data []byte) []byte {
	mac, err := blake2s.New128(key)
	if err != nil {
		panic(err)
	}
	mac.Write(data)
	return mac.Sum(nil)
}
