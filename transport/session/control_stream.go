package session

import (
	"bufio"
	"bytes"
	"fmt"
	"io"
	"sync"
)

// ControlStream is a session's control stream: JSON lines, one frame each,
// carried as data records split at any byte.
type ControlStream struct {
	stream io.ReadWriteCloser
	reader *bufio.Reader

	// pending holds the bytes of a line not yet complete.
	pending []byte
	// isClosed is set by the first close record read.
	isClosed bool

	// writeMu keeps frames whole in the record order.
	writeMu sync.Mutex
}

// NewControlStream wraps a stream whose open record has been read or written.
func NewControlStream(stream io.ReadWriteCloser) *ControlStream {
	return &ControlStream{stream: stream, reader: bufio.NewReaderSize(stream, RecordBytesMax+RecordHeaderBytes)}
}

// ReadFrame returns the next frame. A record of another type than data is
// dropped, a close record ends the stream with io.EOF, and a line past
// ControlFrameBytesMax is ErrFrameTooLarge.
func (c *ControlStream) ReadFrame() ([]byte, error) {
	for {
		if i := bytes.IndexByte(c.pending, '\n'); i >= 0 {
			frame := append([]byte(nil), c.pending[:i]...)
			c.pending = c.pending[i+1:]
			if len(frame) > 0 {
				return frame, nil
			}
			continue
		}
		if c.isClosed {
			return nil, io.EOF
		}
		record, err := ReadRecord(c.reader)
		if err != nil {
			return nil, err
		}
		switch record.Type {
		case RecordData:
			if len(c.pending)+len(record.Payload) > ControlFrameBytesMax {
				return nil, fmt.Errorf("%w: %d bytes", ErrFrameTooLarge, len(c.pending)+len(record.Payload))
			}
			c.pending = append(c.pending, record.Payload...)
		case RecordClose:
			c.isClosed = true
		}
	}
}

// ReadAnswer reads the record that answers the open: nil for an accept, a
// refusal for a refusing close.
func (c *ControlStream) ReadAnswer() (*Refusal, error) {
	return ReadAnswer(c.reader)
}

// WriteFrame writes one frame as a line, in data records of at most
// RecordBytesMax. It returns ErrFrameTooLarge past ControlFrameBytesMax.
func (c *ControlStream) WriteFrame(frame []byte) error {
	if len(frame)+1 > ControlFrameBytesMax {
		return fmt.Errorf("%w: %d bytes", ErrFrameTooLarge, len(frame))
	}
	line := make([]byte, 0, len(frame)+1)
	line = append(line, frame...)
	line = append(line, '\n')
	c.writeMu.Lock()
	defer c.writeMu.Unlock()
	for len(line) > 0 {
		chunk := min(len(line), RecordBytesMax)
		if err := WriteRecord(c.stream, RecordData, line[:chunk]); err != nil {
			return err
		}
		line = line[chunk:]
	}
	return nil
}

// WriteRaw writes a record already encoded, an accept or a close.
func (c *ControlStream) WriteRaw(record []byte) error {
	c.writeMu.Lock()
	defer c.writeMu.Unlock()
	_, err := c.stream.Write(record)
	return err
}

// CloseWrite ends the stream's writing side, so the other side reads what
// was written and then an end of file; a stream with no half-close is closed.
func (c *ControlStream) CloseWrite() error {
	if half, ok := c.stream.(interface{ CloseWrite() error }); ok {
		return half.CloseWrite()
	}
	return c.stream.Close()
}

// Close closes the stream.
func (c *ControlStream) Close() error {
	return c.stream.Close()
}
