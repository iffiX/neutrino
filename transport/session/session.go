package session

import (
	"context"
	"fmt"
	"io"
	"net"
	"time"

	"github.com/libp2p/go-yamux/v4"
)

// Timings are the keepalive settings a session runs on; the defaults are
// the channel's, and a test shortens them.
type Timings struct {
	KeepAliveInterval time.Duration
	KeepAliveTimeout  time.Duration
}

// DefaultTimings are the channel's own.
var DefaultTimings = Timings{KeepAliveInterval: KeepAliveInterval, KeepAliveTimeout: KeepAliveTimeout}

// Session is one go-yamux session over a Noise connection.
type Session struct {
	yamux  *yamux.Session
	conn   net.Conn
	memory *TransportMemory
}

// NewHubSession starts the hub's side, yamux's server, so the hub's streams
// take even ids. Windows reserve from memory, or from no cap when it is nil.
func NewHubSession(conn net.Conn, memory *TransportMemory, timings Timings) (*Session, error) {
	spans := func() (yamux.MemoryManager, error) { return nil, nil }
	if memory != nil {
		spans = memory.Spans()
	}
	inner, err := yamux.Server(conn, config(timings), spans)
	if err != nil {
		return nil, fmt.Errorf("yamux server: %w", err)
	}
	return &Session{yamux: inner, conn: conn, memory: memory}, nil
}

// NewPeerSession starts a peer's side, yamux's client, so its streams take
// odd ids.
func NewPeerSession(conn net.Conn, timings Timings) (*Session, error) {
	inner, err := yamux.Client(conn, config(timings), nil)
	if err != nil {
		return nil, fmt.Errorf("yamux client: %w", err)
	}
	return &Session{yamux: inner, conn: conn}, nil
}

// OpenStream opens a stream to the other side. It returns the session's
// error when it is gone. It resets a stream whose first window takes the
// memory cap's total past the cap and returns ErrMemoryExhausted.
func (s *Session) OpenStream(ctx context.Context) (*yamux.Stream, error) {
	stream, err := s.yamux.OpenStream(ctx)
	if err != nil {
		return nil, fmt.Errorf("open stream: %w", err)
	}
	if s.memory != nil && s.memory.IsPastCap() {
		_ = stream.Reset()
		return nil, fmt.Errorf("open stream: %w", ErrMemoryExhausted)
	}
	return stream, nil
}

// AcceptStream returns the next stream the other side opened, or the
// session's error once it ended. It resets a stream whose first window
// takes the memory cap's total past the cap and waits for the next.
func (s *Session) AcceptStream() (*yamux.Stream, error) {
	for {
		stream, err := s.yamux.AcceptStream()
		if err != nil {
			return nil, fmt.Errorf("accept stream: %w", err)
		}
		if s.memory == nil || !s.memory.IsPastCap() {
			return stream, nil
		}
		_ = stream.Reset()
	}
}

// Close ends the session and every stream on it.
func (s *Session) Close() error {
	return s.yamux.Close()
}

// CloseChan is closed once the session ended.
func (s *Session) CloseChan() <-chan struct{} {
	return s.yamux.CloseChan()
}

// IsClosed reports whether the session ended.
func (s *Session) IsClosed() bool {
	return s.yamux.IsClosed()
}

// Flush waits until the peer acknowledged every byte written to the
// connection, the connection closed, or timeout passed. On a connection
// with no flush of its own, a Noise connection, it returns at once.
func (s *Session) Flush(timeout time.Duration) {
	if flusher, ok := s.conn.(interface{ Flush(time.Duration) }); ok {
		flusher.Flush(timeout)
	}
}

// RemoteAddr is the connection's peer address.
func (s *Session) RemoteAddr() net.Addr {
	return s.conn.RemoteAddr()
}

// LocalAddr is the connection's own address.
func (s *Session) LocalAddr() net.Addr {
	return s.conn.LocalAddr()
}

// NumStreams is the number of streams open on the session.
func (s *Session) NumStreams() int {
	return s.yamux.NumStreams()
}

// config is go-yamux's configuration for every session: the channel's
// windows, one yamux frame per Noise message, and the keepalive.
func config(timings Timings) *yamux.Config {
	c := yamux.DefaultConfig()
	c.AcceptBacklog = SessionAcceptBacklog
	c.EnableKeepAlive = true
	c.KeepAliveInterval = timings.KeepAliveInterval
	c.ConnectionWriteTimeout = timings.KeepAliveTimeout
	c.MaxIncomingStreams = SessionStreamsMax
	c.InitialStreamWindowSize = StreamWindowInitialBytes
	c.MaxStreamWindowSize = StreamWindowMaxBytes
	c.LogOutput = io.Discard
	c.ReadBufSize = SessionReadBufferBytes
	c.MaxMessageSize = NoisePlainMax
	return c
}
