package gate

import (
	"encoding/binary"
	"fmt"
	"io"
	"net"
	"os"
	"sync"
	"sync/atomic"
	"time"
)

// framedConn carries RFC 4571 frames on one TCP connection and is the
// net.PacketConn DTLS runs on: a STUN frame goes to the handler, every
// other frame is one datagram for DTLS, and every datagram written becomes
// one frame.
type framedConn struct {
	conn   net.Conn
	onStun func(frame []byte)
	in     chan []byte
	closed chan struct{}
	once   sync.Once

	// writeMu keeps frames whole and in order.
	writeMu sync.Mutex
	// deadline is the read deadline, zero for none.
	deadline atomic.Pointer[time.Time]
}

func newFramedConn(conn net.Conn, onStun func(frame []byte)) *framedConn {
	framed := &framedConn{
		conn:   conn,
		onStun: onStun,
		in:     make(chan []byte, GateInboundFramesMax),
		closed: make(chan struct{}),
	}
	framed.deadline.Store(&time.Time{})
	return framed
}

// IsStunFrame reports whether a frame's bytes are a STUN message: the two
// top bits zero and the magic cookie in place.
func IsStunFrame(frame []byte) bool {
	return len(frame) >= GateStunHeaderBytes && frame[0]&0xC0 == 0 &&
		binary.BigEndian.Uint32(frame[4:8]) == GateStunMagicCookie
}

// isDtlsFrame reports whether a frame's first byte is a DTLS content type.
func isDtlsFrame(frame []byte) bool {
	return len(frame) > 0 && frame[0] >= GateDtlsContentTypeMin && frame[0] <= GateDtlsContentTypeMax
}

// run reads frames until the connection ends, then closes it.
func (f *framedConn) run() {
	defer f.Close()
	var header [GateFrameLengthBytes]byte
	for {
		if _, err := io.ReadFull(f.conn, header[:]); err != nil {
			return
		}
		frame := make([]byte, binary.BigEndian.Uint16(header[:]))
		if _, err := io.ReadFull(f.conn, frame); err != nil {
			return
		}
		switch {
		case IsStunFrame(frame):
			f.onStun(frame)
		case isDtlsFrame(frame):
			select {
			case f.in <- frame:
			case <-f.closed:
				return
			}
		}
	}
}

// WriteFrame writes one frame. It returns ErrFrameTooLarge past
// GateFrameBytesMax and the connection's error otherwise.
func (f *framedConn) WriteFrame(frame []byte) error {
	if len(frame) > GateFrameBytesMax {
		return fmt.Errorf("%w: %d bytes", ErrFrameTooLarge, len(frame))
	}
	buffer := make([]byte, GateFrameLengthBytes+len(frame))
	binary.BigEndian.PutUint16(buffer, uint16(len(frame)))
	copy(buffer[GateFrameLengthBytes:], frame)
	f.writeMu.Lock()
	defer f.writeMu.Unlock()
	_, err := f.conn.Write(buffer)
	return err
}

// ReadFrom returns the next DTLS frame as one datagram. It returns
// net.ErrClosed once the connection ended and os.ErrDeadlineExceeded when
// the read deadline passes first.
func (f *framedConn) ReadFrom(p []byte) (int, net.Addr, error) {
	var timeout <-chan time.Time
	if deadline := *f.deadline.Load(); !deadline.IsZero() {
		timer := time.NewTimer(time.Until(deadline))
		defer timer.Stop()
		timeout = timer.C
	}
	select {
	case frame := <-f.in:
		return copy(p, frame), f.conn.RemoteAddr(), nil
	case <-f.closed:
		return 0, nil, net.ErrClosed
	case <-timeout:
		return 0, nil, os.ErrDeadlineExceeded
	}
}

// WriteTo writes one datagram as one frame.
func (f *framedConn) WriteTo(p []byte, _ net.Addr) (int, error) {
	if err := f.WriteFrame(p); err != nil {
		return 0, err
	}
	return len(p), nil
}

// Close ends the connection; the read loop and every blocked read return.
func (f *framedConn) Close() error {
	f.once.Do(func() {
		close(f.closed)
		f.conn.Close()
	})
	return nil
}

// LocalAddr is the connection's own address.
func (f *framedConn) LocalAddr() net.Addr {
	return f.conn.LocalAddr()
}

// SetDeadline sets the read deadline; writes have none.
func (f *framedConn) SetDeadline(t time.Time) error {
	return f.SetReadDeadline(t)
}

// SetReadDeadline bounds every read after it.
func (f *framedConn) SetReadDeadline(t time.Time) error {
	f.deadline.Store(&t)
	return nil
}

// SetWriteDeadline is kept for net.PacketConn; writes go straight to TCP.
func (f *framedConn) SetWriteDeadline(time.Time) error {
	return nil
}
