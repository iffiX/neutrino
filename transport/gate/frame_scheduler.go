package gate

import (
	"encoding/binary"
	"fmt"
	"sync"
	"time"
)

// channelWriter is the data channel as the scheduler writes to it.
type channelWriter interface {
	WriteDataChannel(p []byte, isString bool) (int, error)
	BufferedAmount() uint64
	SetBufferedAmountLowThreshold(threshold uint64)
	OnBufferedAmountLow(f func())
}

// frameScheduler sends the yamux frames written to a guest's channel. Each
// stream's frames wait in that stream's queue, and one writer sends a frame
// of each stream in turn, only while the channel holds less than
// GateBufferedBytesMax not yet acknowledged. A frame with no data and no FIN
// goes before every queued frame. A stream's reset drops that stream's
// queued frames.
type frameScheduler struct {
	channel channelWriter
	// closed ends the writer.
	closed <-chan struct{}
	// wake and low each hold one signal: a frame queued, and the channel's
	// buffered amount falling to the bound.
	wake chan struct{}
	low  chan struct{}

	// mu guards every field below it.
	mu sync.Mutex
	// partial holds the start of a frame not yet written whole.
	partial []byte
	urgent  [][]byte
	// queues holds each stream's frames in the order written, by stream id.
	queues map[uint32][][]byte
	// turns holds the ids of the streams with queued frames, the next to
	// send first.
	turns []uint32
	// queued counts the bytes of every queued frame.
	queued int
	err    error
}

func newFrameScheduler(channel channelWriter, closed <-chan struct{}) *frameScheduler {
	s := &frameScheduler{
		channel: channel,
		closed:  closed,
		wake:    make(chan struct{}, 1),
		low:     make(chan struct{}, 1),
		queues:  map[uint32][][]byte{},
	}
	channel.SetBufferedAmountLowThreshold(GateBufferedBytesMax)
	channel.OnBufferedAmountLow(func() { signal(s.low) })
	return s
}

// write queues the whole frames p completes. It returns the writer's error
// once a send failed, and ErrYamuxFrameMalformed for bytes that are not a
// yamux frame of at most GateMessageBytesMax.
func (s *frameScheduler) write(p []byte) (int, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.err != nil {
		return 0, s.err
	}
	s.partial = append(s.partial, p...)
	for len(s.partial) >= yamuxHeaderBytes {
		header := s.partial[:yamuxHeaderBytes]
		if header[0] != yamuxVersion {
			s.err = fmt.Errorf("%w: version %d", ErrYamuxFrameMalformed, header[0])
			return 0, s.err
		}
		size := yamuxHeaderBytes
		if header[1] == yamuxTypeData {
			size += int(binary.BigEndian.Uint32(header[8:]))
		}
		if size > GateMessageBytesMax {
			s.err = fmt.Errorf("%w: %d bytes", ErrYamuxFrameMalformed, size)
			return 0, s.err
		}
		if len(s.partial) < size {
			break
		}
		frame := make([]byte, size)
		copy(frame, s.partial)
		s.partial = s.partial[size:]
		s.queue(frame)
	}
	if len(s.partial) == 0 {
		s.partial = nil
	}
	signal(s.wake)
	return len(p), nil
}

// queue puts one whole frame in its place. The caller holds mu.
func (s *frameScheduler) queue(frame []byte) {
	frameType, flags := frame[1], binary.BigEndian.Uint16(frame[2:])
	id := binary.BigEndian.Uint32(frame[4:])
	if frameType == yamuxTypeWindowUpdate && flags&yamuxFlagRST != 0 {
		s.drop(id)
	}
	if frameType != yamuxTypeData && flags&yamuxFlagFIN == 0 {
		s.urgent = append(s.urgent, frame)
		s.queued += len(frame)
		return
	}
	if len(s.queues[id]) == 0 {
		s.turns = append(s.turns, id)
	}
	s.queues[id] = append(s.queues[id], frame)
	s.queued += len(frame)
}

// drop forgets every queued frame of one stream. The caller holds mu.
func (s *frameScheduler) drop(id uint32) {
	frames, ok := s.queues[id]
	if !ok {
		return
	}
	for _, frame := range frames {
		s.queued -= len(frame)
	}
	delete(s.queues, id)
	for i, turn := range s.turns {
		if turn == id {
			s.turns = append(s.turns[:i], s.turns[i+1:]...)
			break
		}
	}
}

// run sends the queued frames until the channel closes or a send fails.
func (s *frameScheduler) run() {
	for {
		if !s.waitForRoom() {
			return
		}
		frame, ok := s.next()
		if !ok {
			return
		}
		if _, err := s.channel.WriteDataChannel(frame, false); err != nil {
			s.mu.Lock()
			s.err = fmt.Errorf("data channel: %w", err)
			s.mu.Unlock()
			return
		}
	}
}

// waitForRoom waits until the channel holds less than GateBufferedBytesMax.
// It returns false once the channel closed.
func (s *frameScheduler) waitForRoom() bool {
	for s.channel.BufferedAmount() >= GateBufferedBytesMax {
		select {
		case <-s.closed:
			return false
		case <-s.low:
		case <-time.After(GateBufferedPoll):
		}
	}
	return true
}

// next takes the next frame to send, waiting for one: an urgent frame
// first, else the next stream's oldest frame. It returns false once the
// channel closed.
func (s *frameScheduler) next() ([]byte, bool) {
	for {
		s.mu.Lock()
		if len(s.urgent) > 0 {
			frame := s.urgent[0]
			s.urgent = s.urgent[1:]
			s.queued -= len(frame)
			s.mu.Unlock()
			return frame, true
		}
		if len(s.turns) > 0 {
			id := s.turns[0]
			s.turns = s.turns[1:]
			frames := s.queues[id]
			frame := frames[0]
			if len(frames) > 1 {
				s.queues[id] = frames[1:]
				s.turns = append(s.turns, id)
			} else {
				delete(s.queues, id)
			}
			s.queued -= len(frame)
			s.mu.Unlock()
			return frame, true
		}
		s.mu.Unlock()
		select {
		case <-s.closed:
			return nil, false
		case <-s.wake:
		}
	}
}

// pending counts the bytes written and not yet handed to the channel.
func (s *frameScheduler) pending() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.queued + len(s.partial)
}

// signal puts one signal in a channel that holds one, dropping it when one
// is already there.
func signal(ch chan struct{}) {
	select {
	case ch <- struct{}{}:
	default:
	}
}
