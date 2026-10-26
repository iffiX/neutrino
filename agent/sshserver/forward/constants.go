package forward

import "time"

const (
	// ForwardDialTimeout bounds one dial of a forwarded port.
	ForwardDialTimeout = 10 * time.Second

	// ForwardCopyBufferBytes is the size of one copy buffer.
	ForwardCopyBufferBytes = 32 * 1024
)
