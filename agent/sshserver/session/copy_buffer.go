package session

import (
	"io"
	"sync"
)

// copyBuffers holds the buffers every copy of a session borrows.
var copyBuffers = sync.Pool{
	New: func() any {
		buffer := make([]byte, SessionCopyBufferBytes)
		return &buffer
	},
}

// copyStream copies source to target until either ends, with a pooled
// buffer. It returns the error io.CopyBuffer returns.
func copyStream(target io.Writer, source io.Reader) error {
	buffer := copyBuffers.Get().(*[]byte)
	defer copyBuffers.Put(buffer)
	_, err := io.CopyBuffer(target, source, *buffer)
	return err
}
