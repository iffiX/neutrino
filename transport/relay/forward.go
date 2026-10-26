package relay

import (
	"context"
	"encoding/binary"
	"encoding/json"
	"errors"
	"io"
	"net"
	"sync"
	"syscall"

	"github.com/iffiX/neutrino/transport/session"
)

// StreamOpener opens one stream on a peer's live session with an open
// record and reads its answer: the stream after an accept, the refusal of a
// refusing close, or ErrNoSession while the peer has no session.
type StreamOpener interface {
	OpenStream(ctx context.Context, open json.RawMessage) (*RecordStream, *session.Refusal, error)
	// Ready is closed, or returns a channel closed, once a session is live.
	Ready() <-chan struct{}
}

// Forward is a listener on the peer's own machine whose connections become
// streams: one stream per TCP connection, or one stream for a UDP listener.
type Forward struct {
	// Listen is the address bound, as the forward_start answer names it.
	Listen   string
	Protocol string
	open     json.RawMessage
	opener   StreamOpener
	ctx      context.Context
	cancel   context.CancelFunc
	tcp      net.Listener
	udp      *net.UDPConn
	onEnd    func(forward *Forward, refusal *session.Refusal)
	endOnce  sync.Once
	finished chan struct{}
}

// StartForward binds listen over protocol and serves it until Stop or, for a
// UDP forward, until its stream is closed with a code, which it reports
// through onEnd. It returns port_taken when the address cannot be bound.
func StartForward(ctx context.Context, listen, protocol string, open json.RawMessage, opener StreamOpener, onEnd func(*Forward, *session.Refusal)) (*Forward, *session.Refusal, error) {
	ctx, cancel := context.WithCancel(ctx)
	forward := &Forward{Protocol: protocol, open: open, opener: opener, ctx: ctx, cancel: cancel, onEnd: onEnd, finished: make(chan struct{})}
	switch protocol {
	case session.ProtocolTCP:
		listener, err := net.Listen("tcp", listen)
		if err != nil {
			cancel()
			return nil, portTaken(listen, err), nil
		}
		forward.tcp = listener
		forward.Listen = listener.Addr().String()
		go forward.serveTCP()
	case session.ProtocolUDP:
		address, err := net.ResolveUDPAddr("udp", listen)
		if err != nil {
			cancel()
			return nil, nil, err
		}
		conn, err := net.ListenUDP("udp", address)
		if err != nil {
			cancel()
			return nil, portTaken(listen, err), nil
		}
		forward.udp = conn
		forward.Listen = conn.LocalAddr().String()
		go forward.serveUDP()
	default:
		cancel()
		return nil, nil, ErrProtocolUnknown
	}
	return forward, nil, nil
}

// Stop closes the listener and ends its streams.
func (f *Forward) Stop() {
	f.cancel()
	if f.tcp != nil {
		f.tcp.Close()
	}
	if f.udp != nil {
		f.udp.Close()
	}
	<-f.finished
}

// serveTCP accepts connections while a session is live and opens a stream
// for each.
func (f *Forward) serveTCP() {
	defer close(f.finished)
	for {
		select {
		case <-f.ctx.Done():
			return
		case <-f.opener.Ready():
		}
		conn, err := f.tcp.Accept()
		if err != nil {
			return
		}
		go f.serveConnection(conn)
	}
}

func (f *Forward) serveConnection(conn net.Conn) {
	stream, refusal, err := f.opener.OpenStream(f.ctx, f.open)
	if err != nil || refusal != nil {
		conn.Close()
		return
	}
	Splice(conn, stream.Stream)
}

// serveUDP carries the listener's datagrams on one stream per live session:
// a datagram waits for the stream's accept, at most UdpHeldDatagramsMax, and a
// stream the far side closes with a code ends the forward.
func (f *Forward) serveUDP() {
	defer close(f.finished)
	held := &HeldDatagrams{}
	var mu sync.Mutex
	var current *droppingWriter
	buffer := make([]byte, RelayDatagramSourceBytes+RelayDatagramMaxBytes)
	go func() {
		for {
			n, from, err := f.udp.ReadFromUDP(buffer[RelayDatagramSourceBytes:])
			if err != nil {
				return
			}
			binary.BigEndian.PutUint16(buffer, uint16(from.Port))
			record := session.EncodeRecord(session.RecordDatagram, buffer[:RelayDatagramSourceBytes+n])
			mu.Lock()
			writer := current
			mu.Unlock()
			if writer == nil {
				held.Hold(record)
				continue
			}
			writer.write(record)
		}
	}()
	for {
		select {
		case <-f.ctx.Done():
			return
		case <-f.opener.Ready():
		}
		stream, refusal, err := f.opener.OpenStream(f.ctx, f.open)
		if err != nil {
			if errors.Is(err, ErrNoSession) {
				continue
			}
			return
		}
		if refusal != nil {
			held.Drop()
			f.end(refusal)
			return
		}
		writer := newDroppingWriter(stream.Stream)
		mu.Lock()
		current = writer
		mu.Unlock()
		_ = held.Release(stream.Stream)
		closeCode := f.serveUDPStream(stream)
		mu.Lock()
		current = nil
		mu.Unlock()
		writer.stop()
		stream.Stream.Close()
		if closeCode != nil && closeCode.Code != "" {
			f.end(closeCode)
			return
		}
		held = &HeldDatagrams{}
	}
}

// serveUDPStream writes each datagram record from the stream to the local
// source it names, until the stream ends; it returns the close that ended it.
func (f *Forward) serveUDPStream(stream *RecordStream) *session.Refusal {
	for {
		record, err := session.ReadRecord(stream.Reader)
		if err != nil {
			return nil
		}
		switch record.Type {
		case session.RecordClose:
			refusal, err := session.ParseClose(record.Payload)
			if err != nil {
				return nil
			}
			return refusal
		case session.RecordDatagram:
			if len(record.Payload) < RelayDatagramSourceBytes {
				continue
			}
			port := int(binary.BigEndian.Uint16(record.Payload))
			_, _ = f.udp.WriteToUDP(record.Payload[RelayDatagramSourceBytes:], &net.UDPAddr{IP: net.IPv4(127, 0, 0, 1), Port: port})
		}
	}
}

func (f *Forward) end(refusal *session.Refusal) {
	f.endOnce.Do(func() {
		if f.onEnd != nil {
			f.onEnd(f, refusal)
		}
	})
}

// portTaken is the refusal for a listen address another program holds.
func portTaken(listen string, err error) *session.Refusal {
	_, portText, _ := net.SplitHostPort(listen)
	params := map[string]any{"port": portText}
	if !errors.Is(err, syscall.EADDRINUSE) {
		params["detail"] = ErrorText(err)
	}
	return session.NewRefusal(session.CodePortTaken, params)
}

// ReadRecordAnswer reads the answer to an open on a stream: nil after an
// accept, the refusal of a refusing close.
func ReadRecordAnswer(stream *RecordStream) (*session.Refusal, error) {
	return session.ReadAnswer(stream.Reader)
}

// OpenOn writes an open record on a freshly opened stream and reads its
// answer. It returns the stream after an accept, the refusal of a refusing
// close, or the stream's error.
func OpenOn(stream io.ReadWriteCloser, open json.RawMessage) (*RecordStream, *session.Refusal, error) {
	record := NewRecordStream(stream)
	if _, err := stream.Write(session.EncodeRecord(session.RecordOpen, open)); err != nil {
		stream.Close()
		return nil, nil, err
	}
	refusal, err := ReadRecordAnswer(record)
	if err != nil {
		stream.Close()
		return nil, nil, err
	}
	if refusal != nil {
		stream.Close()
		return nil, refusal, nil
	}
	return record, nil, nil
}
