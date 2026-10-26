package relay

import (
	"bufio"
	"io"
	"sync"

	"github.com/iffiX/neutrino/transport/session"
)

// RecordStream is one end of a relayed record stream: its reader and the
// stream itself.
type RecordStream struct {
	Reader *bufio.Reader
	Stream io.ReadWriteCloser
}

// NewRecordStream wraps a stream for record reading.
func NewRecordStream(stream io.ReadWriteCloser) *RecordStream {
	return &RecordStream{Reader: bufio.NewReaderSize(stream, session.RecordBytesMax+session.RecordHeaderBytes), Stream: stream}
}

// RelayRecords carries records both ways between a and b, unchanged, until a
// close record passes in either direction or either stream ends. It closes
// nothing and returns whether a close record passed and whether b, the far
// end, ended first. With isDatagram, a record the other side cannot take at
// once is dropped: each direction holds one record in flight and no queue.
func RelayRecords(a, b *RecordStream, isDatagram bool) (bool, bool) {
	type ended struct {
		isClosePassed bool
		isFar         bool
	}
	done := make(chan ended, 2)
	go func() {
		done <- ended{isClosePassed: relayOneWay(b.Stream, a.Reader, isDatagram), isFar: false}
	}()
	go func() {
		done <- ended{isClosePassed: relayOneWay(a.Stream, b.Reader, isDatagram), isFar: true}
	}()
	first := <-done
	return first.isClosePassed, first.isFar
}

// relayOneWay copies records from src to dst until a close record passed, a
// record was too large or src ended. It returns whether a close record
// passed.
func relayOneWay(dst io.Writer, src *bufio.Reader, isDatagram bool) bool {
	var writer recordWriter = &directWriter{dst: dst}
	if isDatagram {
		dropper := newDroppingWriter(dst)
		defer dropper.stop()
		writer = dropper
	}
	for {
		record, err := session.ReadRecord(src)
		if err != nil {
			return false
		}
		raw := session.EncodeRecord(record.Type, record.Payload)
		if record.Type == session.RecordClose {
			_ = writeDirect(dst, raw)
			return true
		}
		if !writer.write(raw) {
			return false
		}
	}
}

type recordWriter interface {
	write(record []byte) bool
}

type directWriter struct{ dst io.Writer }

func (w *directWriter) write(record []byte) bool {
	return writeDirect(w.dst, record) == nil
}

func writeDirect(dst io.Writer, record []byte) error {
	_, err := dst.Write(record)
	return err
}

// droppingWriter writes records on a goroutine of its own and drops a record
// that arrives while the previous one is still being written.
type droppingWriter struct {
	dst    io.Writer
	slot   chan []byte
	failed chan struct{}
	once   sync.Once
}

func newDroppingWriter(dst io.Writer) *droppingWriter {
	w := &droppingWriter{dst: dst, slot: make(chan []byte, 1), failed: make(chan struct{})}
	go w.run()
	return w
}

func (w *droppingWriter) run() {
	for record := range w.slot {
		if _, err := w.dst.Write(record); err != nil {
			close(w.failed)
			for range w.slot {
			}
			return
		}
	}
}

// write queues a record, or drops it when the slot is taken. It returns
// false once a write failed.
func (w *droppingWriter) write(record []byte) bool {
	select {
	case <-w.failed:
		return false
	default:
	}
	select {
	case w.slot <- record:
	default:
	}
	return true
}

func (w *droppingWriter) stop() {
	w.once.Do(func() { close(w.slot) })
}

// HeldDatagrams holds at most UdpHeldDatagramsMax datagram records while a
// stream waits for its accept.
type HeldDatagrams struct {
	// mu guards records and isReleased.
	mu         sync.Mutex
	records    [][]byte
	isReleased bool
}

// Hold keeps a record, or drops it past the cap or once released. It
// returns whether the record was kept.
func (h *HeldDatagrams) Hold(record []byte) bool {
	h.mu.Lock()
	defer h.mu.Unlock()
	if h.isReleased || len(h.records) >= session.UdpHeldDatagramsMax {
		return false
	}
	h.records = append(h.records, append([]byte(nil), record...))
	return true
}

// Release writes every held record to dst in order and holds nothing after.
func (h *HeldDatagrams) Release(dst io.Writer) error {
	h.mu.Lock()
	records := h.records
	h.records = nil
	h.isReleased = true
	h.mu.Unlock()
	for _, record := range records {
		if _, err := dst.Write(record); err != nil {
			return err
		}
	}
	return nil
}

// Drop forgets every held record.
func (h *HeldDatagrams) Drop() {
	h.mu.Lock()
	defer h.mu.Unlock()
	h.records = nil
	h.isReleased = true
}
