package control

import (
	"encoding/json"
	"io"
	"net"

	"github.com/iffiX/neutrino/transport/relay"
	"github.com/iffiX/neutrino/transport/session"
)

// serveAttached carries a handed stream over a local connection: the local
// side's records go to the stream unchanged, and the stream's records come
// back under the record cap. It closes both when either ends.
func serveAttached(local net.Conn, stream *relay.RecordStream) {
	done := make(chan struct{}, 2)
	go func() {
		_, _ = io.Copy(stream.Stream, local)
		done <- struct{}{}
	}()
	go func() {
		_ = relay.CopyRecords(local, stream.Reader)
		done <- struct{}{}
	}()
	<-done
	local.Close()
	stream.Stream.Close()
	<-done
}

// serveOpened carries a stream the local side opened: the far side's answer
// first, then records both ways, or for a TCP connect raw bytes after its
// accept.
func serveOpened(local net.Conn, stream io.ReadWriteCloser, open json.RawMessage) {
	record := relay.NewRecordStream(stream)
	if !isTCPConnect(open) {
		serveAttached(local, record)
		return
	}
	answer, err := session.ReadRecord(record.Reader)
	if err != nil {
		local.Close()
		stream.Close()
		return
	}
	if _, err := local.Write(session.EncodeRecord(answer.Type, answer.Payload)); err != nil || answer.Type != session.RecordAccept {
		local.Close()
		stream.Close()
		return
	}
	relay.Splice(local, &readerConn{Conn: record.Stream, reader: record.Reader})
}

// readerConn reads a stream through the reader that holds its unread bytes.
type readerConn struct {
	Conn   io.ReadWriteCloser
	reader io.Reader
}

func (c *readerConn) Read(p []byte) (int, error)  { return c.reader.Read(p) }
func (c *readerConn) Write(p []byte) (int, error) { return c.Conn.Write(p) }
func (c *readerConn) Close() error                { return c.Conn.Close() }

// isTCPConnect reports whether an open record is a connect over TCP, whose
// stream carries raw bytes after its accept.
func isTCPConnect(open json.RawMessage) bool {
	var fields struct {
		Kind     string `json:"kind"`
		Protocol string `json:"protocol"`
	}
	if err := json.Unmarshal(open, &fields); err != nil {
		return false
	}
	return fields.Kind == session.KindConnect && (fields.Protocol == "" || fields.Protocol == session.ProtocolTCP)
}
