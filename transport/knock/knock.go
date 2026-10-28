package knock

import (
	"bytes"
	"crypto/hmac"
	"encoding/binary"
	"fmt"
	"io"

	"golang.org/x/crypto/blake2s"
)

// Header is the eight bytes that open every message of the member path: the
// hub's magic, the version, the message type and a reserved byte.
type Header struct {
	Magic   []byte
	Version uint16
	Type    byte
}

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

// Magic is the four bytes a hub's members open every message with. For the
// counter c = 0, 1, 2, ... it is the first four bytes of BLAKE2s-256 of
// KnockMagicLabel, the hub's public key and the one byte c, taken at the
// first c whose first byte is neither KnockMagicForbiddenStun nor
// KnockMagicForbiddenTLS. A member knows it from the link's key; a share
// link carries no key.
func Magic(hubPublic []byte) []byte {
	input := make([]byte, 0, len(KnockMagicLabel)+len(hubPublic)+1)
	input = append(input, KnockMagicLabel...)
	input = append(input, hubPublic...)
	for counter := 0; counter < 256; counter++ {
		sum := blake2s.Sum256(append(input, byte(counter)))
		if sum[0] != KnockMagicForbiddenStun && sum[0] != KnockMagicForbiddenTLS {
			return sum[:KnockMagicBytes]
		}
	}
	panic("no magic for the key")
}

// EncodeHeader writes the header of a message of messageType under hubPublic.
func EncodeHeader(hubPublic []byte, messageType byte) []byte {
	header := make([]byte, 0, KnockHeaderBytes)
	header = append(header, Magic(hubPublic)...)
	header = binary.BigEndian.AppendUint16(header, KnockVersion)
	header = append(header, messageType, 0)
	return header
}

// ParseHeader reads the eight bytes of a header under hubPublic. It returns
// ErrKnockMalformed when the bytes are too few, the magic is another hub's,
// the version is not KnockVersion or the type is none of the three.
func ParseHeader(raw, hubPublic []byte) (Header, error) {
	if len(raw) < KnockHeaderBytes {
		return Header{}, fmt.Errorf("%w: header of %d bytes", ErrKnockMalformed, len(raw))
	}
	if !bytes.Equal(raw[:KnockMagicBytes], Magic(hubPublic)) {
		return Header{}, fmt.Errorf("%w: magic", ErrKnockMalformed)
	}
	version := binary.BigEndian.Uint16(raw[KnockMagicBytes:])
	if version != KnockVersion {
		return Header{}, fmt.Errorf("%w: version %d", ErrKnockMalformed, version)
	}
	messageType := raw[KnockMagicBytes+2]
	if messageType < KnockTypeKnock || messageType > KnockTypeCookieReply {
		return Header{}, fmt.Errorf("%w: type %d", ErrKnockMalformed, messageType)
	}
	return Header{Magic: raw[:KnockMagicBytes], Version: version, Type: messageType}, nil
}

// Encode writes a knock for message 1: the header, the length, message 1,
// mac1 under hubPublic and mac2 under cookie, or 16 zero bytes when cookie
// is nil. It returns ErrKnockMalformed when the knock would exceed
// KnockBytesMax.
func Encode(message1, hubPublic, cookie []byte) ([]byte, error) {
	size := KnockHeaderBytes + KnockLengthBytes + len(message1) + 2*KnockMacBytes
	if size > KnockBytesMax {
		return nil, fmt.Errorf("%w: %d bytes", ErrKnockMalformed, size)
	}
	raw := make([]byte, 0, size)
	raw = append(raw, EncodeHeader(hubPublic, KnockTypeKnock)...)
	raw = binary.BigEndian.AppendUint16(raw, uint16(len(message1)))
	raw = append(raw, message1...)
	raw = append(raw, Mac1(hubPublic, raw)...)
	raw = append(raw, Mac2(cookie, raw)...)
	return raw, nil
}

// ReadBody reads the rest of a knock after its header, the eight bytes
// already read, and returns the whole knock parsed. It returns
// ErrKnockMalformed for a length past KnockBytesMax and the reader's error
// when the bytes end.
func ReadBody(r io.Reader, header []byte) (*Knock, error) {
	if len(header) != KnockHeaderBytes {
		return nil, fmt.Errorf("%w: header of %d bytes", ErrKnockMalformed, len(header))
	}
	var length [KnockLengthBytes]byte
	if _, err := io.ReadFull(r, length[:]); err != nil {
		return nil, fmt.Errorf("read knock length: %w", err)
	}
	size := KnockHeaderBytes + KnockLengthBytes + int(binary.BigEndian.Uint16(length[:])) + 2*KnockMacBytes
	if size > KnockBytesMax {
		return nil, fmt.Errorf("%w: %d bytes", ErrKnockMalformed, size)
	}
	raw := make([]byte, size)
	copy(raw, header)
	copy(raw[KnockHeaderBytes:], length[:])
	if _, err := io.ReadFull(r, raw[KnockHeaderBytes+KnockLengthBytes:]); err != nil {
		return nil, fmt.Errorf("read knock: %w", err)
	}
	return Parse(raw)
}

// Parse splits a whole knock into its parts. It returns ErrKnockMalformed
// when the version, the type or the length does not fit the bytes; the
// magic is covered by mac1, which VerifyMac1 checks.
func Parse(raw []byte) (*Knock, error) {
	if len(raw) < KnockHeaderBytes+KnockLengthBytes+2*KnockMacBytes || len(raw) > KnockBytesMax {
		return nil, fmt.Errorf("%w: %d bytes", ErrKnockMalformed, len(raw))
	}
	if version := binary.BigEndian.Uint16(raw[KnockMagicBytes:]); version != KnockVersion {
		return nil, fmt.Errorf("%w: version %d", ErrKnockMalformed, version)
	}
	if raw[KnockMagicBytes+2] != KnockTypeKnock {
		return nil, fmt.Errorf("%w: type %d", ErrKnockMalformed, raw[KnockMagicBytes+2])
	}
	length := int(binary.BigEndian.Uint16(raw[KnockHeaderBytes:]))
	if KnockHeaderBytes+KnockLengthBytes+length+2*KnockMacBytes != len(raw) {
		return nil, fmt.Errorf("%w: length %d in %d bytes", ErrKnockMalformed, length, len(raw))
	}
	mac1Start := KnockHeaderBytes + KnockLengthBytes + length
	return &Knock{
		Raw:      raw,
		Message1: raw[KnockHeaderBytes+KnockLengthBytes : mac1Start],
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
