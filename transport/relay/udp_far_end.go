package relay

import (
	"encoding/binary"
	"io"
	"net"
	"sync"
	"time"

	"github.com/iffiX/neutrino/transport/session"
)

// UdpFarEnd is the far end of a UDP connect stream: one connected socket to
// the target for each source the stream's records name, at most
// UdpSourcesMax, each closed after UdpIdleTimeout with no datagram.
type UdpFarEnd struct {
	target *net.UDPAddr
	stream io.ReadWriteCloser
	writer *droppingWriter
	now    func() time.Time

	// mu guards sources and isClosed.
	mu       sync.Mutex
	sources  map[uint16]*udpSource
	isClosed bool
	done     chan struct{}
}

type udpSource struct {
	conn     *net.UDPConn
	lastSeen time.Time
}

// NewUdpFarEnd makes the far end of stream towards address:port. It returns
// the connect_failed refusal when the first socket cannot be opened.
func NewUdpFarEnd(stream io.ReadWriteCloser, address string, port int) (*UdpFarEnd, *session.Refusal) {
	target, err := net.ResolveUDPAddr("udp", TargetAddress(address, port))
	if err != nil {
		return nil, ConnectFailed(err)
	}
	probe, err := net.DialUDP("udp", nil, target)
	if err != nil {
		return nil, ConnectFailed(err)
	}
	probe.Close()
	return &UdpFarEnd{
		target:  target,
		stream:  stream,
		writer:  newDroppingWriter(stream),
		now:     time.Now,
		sources: make(map[uint16]*udpSource),
		done:    make(chan struct{}),
	}, nil
}

// Serve reads datagram records from the stream and sends each to the target
// from its source's socket, writing replies back as records, until the
// stream ends. It closes every socket when it returns.
func (f *UdpFarEnd) Serve() {
	go f.sweep()
	reader := recordReader(f.stream)
	for {
		record, err := session.ReadRecord(reader)
		if err != nil {
			break
		}
		if record.Type == session.RecordClose {
			break
		}
		if record.Type != session.RecordDatagram || len(record.Payload) < RelayDatagramSourceBytes {
			continue
		}
		source := binary.BigEndian.Uint16(record.Payload)
		conn := f.socket(source)
		if conn == nil {
			continue
		}
		_, _ = conn.Write(record.Payload[RelayDatagramSourceBytes:])
	}
	f.Close()
}

// Close closes the stream and every socket.
func (f *UdpFarEnd) Close() {
	f.mu.Lock()
	if f.isClosed {
		f.mu.Unlock()
		return
	}
	f.isClosed = true
	close(f.done)
	sources := f.sources
	f.sources = nil
	f.mu.Unlock()
	for _, source := range sources {
		source.conn.Close()
	}
	f.writer.stop()
	f.stream.Close()
}

// socket is the socket of one source, made when it is new, the one idle the
// longest giving way past UdpSourcesMax.
func (f *UdpFarEnd) socket(source uint16) *net.UDPConn {
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.isClosed {
		return nil
	}
	if existing, ok := f.sources[source]; ok {
		existing.lastSeen = f.now()
		return existing.conn
	}
	if len(f.sources) >= session.UdpSourcesMax {
		var oldestKey uint16
		var oldest *udpSource
		for key, candidate := range f.sources {
			if oldest == nil || candidate.lastSeen.Before(oldest.lastSeen) {
				oldestKey, oldest = key, candidate
			}
		}
		oldest.conn.Close()
		delete(f.sources, oldestKey)
	}
	conn, err := net.DialUDP("udp", nil, f.target)
	if err != nil {
		return nil
	}
	entry := &udpSource{conn: conn, lastSeen: f.now()}
	f.sources[source] = entry
	go f.readReplies(source, entry)
	return conn
}

// readReplies writes each datagram the target sends to one source's socket
// as a record with that source in front, until the socket closes.
func (f *UdpFarEnd) readReplies(source uint16, entry *udpSource) {
	buffer := make([]byte, RelayDatagramSourceBytes+RelayDatagramMaxBytes)
	binary.BigEndian.PutUint16(buffer, source)
	for {
		n, err := entry.conn.Read(buffer[RelayDatagramSourceBytes:])
		if err != nil {
			return
		}
		f.mu.Lock()
		entry.lastSeen = f.now()
		f.mu.Unlock()
		f.writer.write(session.EncodeRecord(session.RecordDatagram, buffer[:RelayDatagramSourceBytes+n]))
	}
}

// sweep closes the sockets idle past UdpIdleTimeout.
func (f *UdpFarEnd) sweep() {
	ticker := time.NewTicker(RelayUdpSweepInterval)
	defer ticker.Stop()
	for {
		select {
		case <-f.done:
			return
		case <-ticker.C:
			f.mu.Lock()
			for key, source := range f.sources {
				if f.now().Sub(source.lastSeen) >= session.UdpIdleTimeout {
					source.conn.Close()
					delete(f.sources, key)
				}
			}
			f.mu.Unlock()
		}
	}
}

// SourceCount is the number of sources with a socket.
func (f *UdpFarEnd) SourceCount() int {
	f.mu.Lock()
	defer f.mu.Unlock()
	return len(f.sources)
}
