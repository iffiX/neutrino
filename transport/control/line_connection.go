package control

import (
	"bufio"
	"bytes"
	"crypto/subtle"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"sync"
	"time"
)

// LineConnection is one local connection: JSON objects, one per line, both
// ways.
type LineConnection struct {
	conn   net.Conn
	reader *bufio.Reader

	// writeMu keeps lines whole.
	writeMu sync.Mutex
}

// FirstLine is what every connection opens with.
type FirstLine struct {
	Secret  string          `json:"secret"`
	Op      string          `json:"op"`
	Stream  string          `json:"stream"`
	Session string          `json:"session"`
	Binding string          `json:"binding"`
	Open    json.RawMessage `json:"open"`
}

// NewLineConnection wraps a connection.
func NewLineConnection(conn net.Conn) *LineConnection {
	return &LineConnection{conn: conn, reader: bufio.NewReaderSize(conn, 64*1024)}
}

// ReadFirstLine reads the opening line within ControlSecretTimeout and checks
// its secret. It returns ErrSecretInvalid for another secret and ErrOpUnknown
// for an op outside the three.
func (c *LineConnection) ReadFirstLine(secret string) (*FirstLine, error) {
	_ = c.conn.SetReadDeadline(time.Now().Add(ControlSecretTimeout))
	line, err := c.ReadLine()
	_ = c.conn.SetReadDeadline(time.Time{})
	if err != nil {
		return nil, err
	}
	var first FirstLine
	if err := json.Unmarshal(line, &first); err != nil {
		return nil, ErrSecretInvalid
	}
	if len(first.Secret) != len(secret) || subtle.ConstantTimeCompare([]byte(first.Secret), []byte(secret)) != 1 {
		return nil, ErrSecretInvalid
	}
	switch first.Op {
	case OpControl, OpAttach, OpOpen:
	default:
		return nil, fmt.Errorf("%w: %q", ErrOpUnknown, first.Op)
	}
	return &first, nil
}

// ReadLine returns the next line without its newline. It returns
// ErrLineTooLong past ControlLineLimit and the connection's error at its end.
func (c *LineConnection) ReadLine() ([]byte, error) {
	var line []byte
	for {
		part, isPrefix, err := c.reader.ReadLine()
		if err != nil {
			return nil, err
		}
		if len(line)+len(part) > ControlLineLimit {
			return nil, ErrLineTooLong
		}
		line = append(line, part...)
		if !isPrefix {
			return bytes.TrimSpace(line), nil
		}
	}
}

// WriteLine writes one line.
func (c *LineConnection) WriteLine(line []byte) error {
	c.writeMu.Lock()
	defer c.writeMu.Unlock()
	buffer := make([]byte, 0, len(line)+1)
	buffer = append(buffer, line...)
	buffer = append(buffer, '\n')
	_, err := c.conn.Write(buffer)
	return err
}

// WriteObject writes one object as a line.
func (c *LineConnection) WriteObject(object any) error {
	line, err := json.Marshal(object)
	if err != nil {
		return err
	}
	return c.WriteLine(line)
}

// WriteFrameLine writes a frame line, the frame's bytes unchanged, with the
// extra fields given, as `{"frame":<frame>,"<key>":"<value>"}`.
func (c *LineConnection) WriteFrameLine(frame []byte, key, value string) error {
	var buffer bytes.Buffer
	buffer.WriteString(`{"frame":`)
	buffer.Write(frame)
	if key != "" {
		buffer.WriteString(`,"`)
		buffer.WriteString(key)
		buffer.WriteString(`":`)
		encoded, _ := json.Marshal(value)
		buffer.Write(encoded)
	}
	buffer.WriteByte('}')
	return c.WriteLine(buffer.Bytes())
}

// Conn is the connection underneath, for a stream's bytes after the first
// line.
func (c *LineConnection) Conn() net.Conn {
	return c.conn
}

// Reader is the buffered reader over the connection, holding any bytes read
// past the first line.
func (c *LineConnection) Reader() *bufio.Reader {
	return c.reader
}

// Close closes the connection.
func (c *LineConnection) Close() error {
	return c.conn.Close()
}

// bufferedConn reads what the reader holds before the connection.
type bufferedConn struct {
	net.Conn
	reader io.Reader
}

func (c *bufferedConn) Read(p []byte) (int, error) {
	return c.reader.Read(p)
}

// StreamConn is the connection with its buffered bytes, for a splice.
func (c *LineConnection) StreamConn() net.Conn {
	return &bufferedConn{Conn: c.conn, reader: c.reader}
}
