package relay

import (
	"bufio"
	"io"
	"sync"
	"time"

	"github.com/iffiX/neutrino/transport/session"
)

// recordReader wraps a stream in a reader sized for one record.
func recordReader(stream io.Reader) *bufio.Reader {
	return bufio.NewReaderSize(stream, session.RecordBytesMax+session.RecordHeaderBytes)
}

// HandOff holds the streams the transport announced to the Python beside it
// until the Python attaches to each, and closes one nobody attached to in
// time with control_unavailable.
type HandOff struct {
	timeout time.Duration

	// mu guards waiting.
	mu      sync.Mutex
	waiting map[string]*handedStream
}

// handedStream is one announced stream with its unread bytes.
type handedStream struct {
	stream *RecordStream
	timer  *time.Timer
}

// NewHandOff makes a hand-off closing unattached streams after timeout.
func NewHandOff(timeout time.Duration) *HandOff {
	return &HandOff{timeout: timeout, waiting: make(map[string]*handedStream)}
}

// Announce keeps a stream under id until Take or the timeout.
func (h *HandOff) Announce(id string, stream *RecordStream) {
	h.mu.Lock()
	defer h.mu.Unlock()
	entry := &handedStream{stream: stream}
	entry.timer = time.AfterFunc(h.timeout, func() { h.expire(id, entry) })
	h.waiting[id] = entry
}

// Take returns the stream announced under id, or ErrStreamUnknown.
func (h *HandOff) Take(id string) (*RecordStream, error) {
	h.mu.Lock()
	defer h.mu.Unlock()
	entry, ok := h.waiting[id]
	if !ok {
		return nil, ErrStreamUnknown
	}
	entry.timer.Stop()
	delete(h.waiting, id)
	return entry.stream, nil
}

// Waiting is the number of streams waiting for an attach.
func (h *HandOff) Waiting() int {
	h.mu.Lock()
	defer h.mu.Unlock()
	return len(h.waiting)
}

func (h *HandOff) expire(id string, entry *handedStream) {
	h.mu.Lock()
	current, ok := h.waiting[id]
	if ok && current == entry {
		delete(h.waiting, id)
	}
	h.mu.Unlock()
	if ok && current == entry {
		_, _ = entry.stream.Stream.Write(session.CloseRecord(session.CodeControlUnavailable, nil))
		entry.stream.Stream.Close()
	}
}
