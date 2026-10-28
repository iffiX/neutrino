package gate

import (
	"fmt"
	"io"
	"net"
	"sync"
	"time"

	"github.com/pion/datachannel"
)

// ChannelConn is data channel 0 as a net.Conn: a byte stream whose reads
// return what the channel's messages carry, in order, and whose writes
// become messages of at most GateMessageBytesMax bytes. Closing it closes
// the channel, the association, the DTLS connection and the TCP connection
// under them.
type ChannelConn struct {
	channel *datachannel.DataChannel
	tcp     net.Conn
	closers []io.Closer
	once    sync.Once

	// readBuffer holds one message and pending what a Read left of it.
	readBuffer []byte
	pending    []byte

	// writeMu keeps messages whole and in order.
	writeMu sync.Mutex
}

func newChannelConn(channel *datachannel.DataChannel, tcp net.Conn, closers ...io.Closer) *ChannelConn {
	return &ChannelConn{channel: channel, tcp: tcp, closers: closers, readBuffer: make([]byte, GateReadBytesMax)}
}

// Read returns the next bytes of the stream, at most one message's worth.
// It returns the channel's error once it ended, and ErrMessageTooLarge for
// a message past GateReadBytesMax, which ends the connection.
func (c *ChannelConn) Read(p []byte) (int, error) {
	if len(c.pending) == 0 {
		n, err := c.channel.Read(c.readBuffer)
		if err != nil {
			if isShortBuffer(err) {
				c.Close()
				return 0, fmt.Errorf("%w: over %d bytes", ErrMessageTooLarge, GateReadBytesMax)
			}
			return 0, err
		}
		c.pending = c.readBuffer[:n]
	}
	n := copy(p, c.pending)
	c.pending = c.pending[n:]
	return n, nil
}

// ReadMessage returns the next whole message into p. It returns
// ErrMessageTooLarge when p is too small for it, and the channel's error
// once it ended.
func (c *ChannelConn) ReadMessage(p []byte) (int, error) {
	if len(c.pending) > 0 {
		n := copy(p, c.pending)
		c.pending = c.pending[n:]
		return n, nil
	}
	n, err := c.channel.Read(p)
	if err != nil && isShortBuffer(err) {
		return 0, fmt.Errorf("%w: over %d bytes", ErrMessageTooLarge, len(p))
	}
	return n, err
}

// Write sends p as binary messages of at most GateMessageBytesMax bytes
// each, in order. It returns the channel's error.
func (c *ChannelConn) Write(p []byte) (int, error) {
	c.writeMu.Lock()
	defer c.writeMu.Unlock()
	written := 0
	for len(p) > 0 {
		chunk := min(len(p), GateMessageBytesMax)
		n, err := c.channel.WriteDataChannel(p[:chunk], false)
		written += n
		if err != nil {
			return written, err
		}
		p = p[chunk:]
	}
	return written, nil
}

// Flush waits until every message written has left the association's
// buffer, or timeout passes.
func (c *ChannelConn) Flush(timeout time.Duration) {
	deadline := time.Now().Add(timeout)
	for c.channel.BufferedAmount() > 0 && time.Now().Before(deadline) {
		time.Sleep(GateFlushPoll)
	}
}

// Close closes the channel and everything under it, down to the TCP
// connection, once.
func (c *ChannelConn) Close() error {
	c.once.Do(func() {
		c.channel.Close()
		for _, closer := range c.closers {
			closer.Close()
		}
	})
	return nil
}

// LocalAddr is the TCP connection's own address.
func (c *ChannelConn) LocalAddr() net.Addr {
	return c.tcp.LocalAddr()
}

// RemoteAddr is the TCP connection's peer address.
func (c *ChannelConn) RemoteAddr() net.Addr {
	return c.tcp.RemoteAddr()
}

// SetDeadline sets the read and the write deadline.
func (c *ChannelConn) SetDeadline(t time.Time) error {
	if err := c.SetReadDeadline(t); err != nil {
		return err
	}
	return c.SetWriteDeadline(t)
}

// SetReadDeadline bounds every read after it.
func (c *ChannelConn) SetReadDeadline(t time.Time) error {
	return c.channel.SetReadDeadline(t)
}

// SetWriteDeadline bounds every write after it.
func (c *ChannelConn) SetWriteDeadline(t time.Time) error {
	return c.channel.SetWriteDeadline(t)
}

// isShortBuffer reports whether a read failed because the message did not
// fit the buffer.
func isShortBuffer(err error) bool {
	return err == io.ErrShortBuffer || err.Error() == io.ErrShortBuffer.Error()
}
