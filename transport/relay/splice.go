package relay

import (
	"bufio"
	"encoding/binary"
	"fmt"
	"io"
	"sync"

	"github.com/iffiX/neutrino/transport/session"
)

// copyBuffers holds the buffers every copy uses; no copy allocates per frame.
var copyBuffers = sync.Pool{New: func() any {
	buffer := make([]byte, RelayCopyBufferBytes)
	return &buffer
}}

// Splice copies a to b and b to a until either end of input, then closes
// both: everything read before the end is written first, and there is no
// half-close.
func Splice(a, b io.ReadWriteCloser) {
	done := make(chan struct{}, 2)
	go func() {
		copyBytes(b, a)
		done <- struct{}{}
	}()
	go func() {
		copyBytes(a, b)
		done <- struct{}{}
	}()
	<-done
	a.Close()
	b.Close()
	<-done
}

// copyBytes copies src to dst through a pooled buffer until src ends or dst
// fails.
func copyBytes(dst io.Writer, src io.Reader) {
	pointer := copyBuffers.Get().(*[]byte)
	defer copyBuffers.Put(pointer)
	buffer := *pointer
	for {
		n, err := src.Read(buffer)
		if n > 0 {
			if _, writeErr := dst.Write(buffer[:n]); writeErr != nil {
				return
			}
		}
		if err != nil {
			return
		}
	}
}

// CopyRecords copies records from src to dst unchanged until src ends,
// checking each record's length against RecordBytesMax. It returns
// session.ErrRecordTooLarge for a record past the cap, with nothing of that
// record written, and io.EOF at a clean end.
func CopyRecords(dst io.Writer, src *bufio.Reader) error {
	pointer := copyBuffers.Get().(*[]byte)
	defer copyBuffers.Put(pointer)
	buffer := *pointer
	for {
		header := buffer[:session.RecordHeaderBytes]
		if _, err := io.ReadFull(src, header); err != nil {
			return err
		}
		size := int(binary.BigEndian.Uint32(header[1:]))
		if size > session.RecordBytesMax {
			return fmt.Errorf("%w: %d bytes", session.ErrRecordTooLarge, size)
		}
		record := buffer[:session.RecordHeaderBytes+size]
		if _, err := io.ReadFull(src, record[session.RecordHeaderBytes:]); err != nil {
			return err
		}
		if _, err := dst.Write(record); err != nil {
			return err
		}
	}
}
