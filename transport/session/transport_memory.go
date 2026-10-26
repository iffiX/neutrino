package session

import (
	"fmt"
	"sync/atomic"

	"github.com/libp2p/go-yamux/v4"
)

// TransportMemory is the one cap on the bytes the hub's transport holds for
// every stream's window together. Each stream reserves from it through a
// span go-yamux asks for at the stream's open.
type TransportMemory struct {
	max  int64
	used atomic.Int64
}

// NewTransportMemory makes a cap of max bytes.
func NewTransportMemory(max int64) *TransportMemory {
	return &TransportMemory{max: max}
}

// Used is the bytes reserved now.
func (m *TransportMemory) Used() int64 {
	return m.used.Load()
}

// Spans is the factory go-yamux calls for each stream's span.
func (m *TransportMemory) Spans() func() (yamux.MemoryManager, error) {
	return func() (yamux.MemoryManager, error) {
		return &memorySpan{memory: m}, nil
	}
}

// memorySpan is one stream's share of the cap.
type memorySpan struct {
	memory *TransportMemory
	held   atomic.Int64
}

// ReserveMemory takes size bytes when the cap has room. It returns
// ErrMemoryExhausted otherwise, which refuses a stream at its open and stops
// a window from growing.
func (s *memorySpan) ReserveMemory(size int, prio uint8) error {
	for {
		used := s.memory.used.Load()
		if used+int64(size) > s.memory.max {
			return fmt.Errorf("%w: %d of %d bytes", ErrMemoryExhausted, used, s.memory.max)
		}
		if s.memory.used.CompareAndSwap(used, used+int64(size)) {
			s.held.Add(int64(size))
			return nil
		}
	}
}

// ReleaseMemory gives size bytes back.
func (s *memorySpan) ReleaseMemory(size int) {
	released := min(int64(size), s.held.Load())
	s.held.Add(-released)
	s.memory.used.Add(-released)
}

// Done gives back everything the span still holds.
func (s *memorySpan) Done() {
	held := s.held.Swap(0)
	s.memory.used.Add(-held)
}
