package session

import (
	"bufio"
	"encoding/binary"
	"fmt"
	"io"
	"net"
	"sync"

	"github.com/iffiX/neutrino/transport/handshake"
)

// NoiseConn carries a byte stream as length-prefixed Noise transport
// messages over one TCP connection. It is a net.Conn, so a yamux session
// runs on it.
type NoiseConn struct {
	net.Conn
	reader *bufio.Reader
	keys   *handshake.Keys

	// writeMu guards writeBuffer and the order of messages written.
	writeMu     sync.Mutex
	writeBuffer []byte

	readBuffer []byte
	plain      []byte
}

// NewNoiseConn wraps conn, whose unread bytes reader holds, under keys.
func NewNoiseConn(conn net.Conn, reader *bufio.Reader, keys *handshake.Keys) *NoiseConn {
	return &NoiseConn{
		Conn:        conn,
		reader:      reader,
		keys:        keys,
		writeBuffer: make([]byte, NoiseLengthBytes+NoiseMessageMax),
		readBuffer:  make([]byte, NoiseMessageMax),
	}
}

// Read returns decrypted bytes, at most one message's worth per call. It
// returns the connection's error, or an error when a message does not open.
func (c *NoiseConn) Read(p []byte) (int, error) {
	if len(c.plain) == 0 {
		var header [NoiseLengthBytes]byte
		if _, err := io.ReadFull(c.reader, header[:]); err != nil {
			return 0, err
		}
		size := int(binary.BigEndian.Uint16(header[:]))
		if _, err := io.ReadFull(c.reader, c.readBuffer[:size]); err != nil {
			return 0, err
		}
		plain, err := c.keys.Receive.Decrypt(c.readBuffer[:0], nil, c.readBuffer[:size])
		if err != nil {
			return 0, fmt.Errorf("open noise message: %w", err)
		}
		c.plain = plain
	}
	n := copy(p, c.plain)
	c.plain = c.plain[n:]
	return n, nil
}

// Write seals p into messages of at most NoisePlainMax bytes each and writes
// them in order. It returns the connection's error.
func (c *NoiseConn) Write(p []byte) (int, error) {
	c.writeMu.Lock()
	defer c.writeMu.Unlock()
	written := 0
	for len(p) > 0 {
		chunk := min(len(p), NoisePlainMax)
		sealed, err := c.keys.Send.Encrypt(c.writeBuffer[NoiseLengthBytes:NoiseLengthBytes], nil, p[:chunk])
		if err != nil {
			return written, fmt.Errorf("seal noise message: %w", err)
		}
		binary.BigEndian.PutUint16(c.writeBuffer[:NoiseLengthBytes], uint16(len(sealed)))
		if _, err := c.Conn.Write(c.writeBuffer[:NoiseLengthBytes+len(sealed)]); err != nil {
			return written, err
		}
		written += chunk
		p = p[chunk:]
	}
	return written, nil
}

// WriteLengthPrefixed writes one message as the handshake frames it: a
// big-endian u16 length and the bytes. It returns ErrNoiseMessageTooLarge
// past NoiseMessageMax.
func WriteLengthPrefixed(w io.Writer, message []byte) error {
	if len(message) > NoiseMessageMax {
		return fmt.Errorf("%w: %d bytes", ErrNoiseMessageTooLarge, len(message))
	}
	buffer := make([]byte, NoiseLengthBytes+len(message))
	binary.BigEndian.PutUint16(buffer, uint16(len(message)))
	copy(buffer[NoiseLengthBytes:], message)
	_, err := w.Write(buffer)
	return err
}

// ReadLengthPrefixed reads one message framed by a big-endian u16 length.
func ReadLengthPrefixed(r io.Reader) ([]byte, error) {
	var header [NoiseLengthBytes]byte
	if _, err := io.ReadFull(r, header[:]); err != nil {
		return nil, err
	}
	message := make([]byte, binary.BigEndian.Uint16(header[:]))
	if _, err := io.ReadFull(r, message); err != nil {
		return nil, err
	}
	return message, nil
}
