package relay

import (
	"bytes"
	"io"
	"net"
	"sync"
	"testing"
	"time"

	"github.com/iffiX/neutrino/transport/session"
)

// slowWriter takes one record every pause and counts them.
type slowWriter struct {
	pause time.Duration
	mu    sync.Mutex
	count int
}

func (w *slowWriter) Write(p []byte) (int, error) {
	time.Sleep(w.pause)
	w.mu.Lock()
	w.count++
	w.mu.Unlock()
	return len(p), nil
}

func (w *slowWriter) written() int {
	w.mu.Lock()
	defer w.mu.Unlock()
	return w.count
}

func TestDroppingWriterDropsWithoutWaiting(t *testing.T) {
	slow := &slowWriter{pause: 20 * time.Millisecond}
	writer := newDroppingWriter(slow)
	started := time.Now()
	for i := 0; i < 50; i++ {
		writer.write(session.EncodeRecord(session.RecordDatagram, []byte{0, 1, byte(i)}))
	}
	if time.Since(started) > 100*time.Millisecond {
		t.Fatal("writes waited on the slow side")
	}
	time.Sleep(100 * time.Millisecond)
	writer.stop()
	if written := slow.written(); written >= 50 || written < 1 {
		t.Fatalf("%d of 50 records written", written)
	}
}

func TestRelayRecordsEndsOnClose(t *testing.T) {
	aNear, aFar := net.Pipe()
	bNear, bFar := net.Pipe()
	done := make(chan bool)
	go func() {
		isClosePassed, _ := RelayRecords(NewRecordStream(aFar), NewRecordStream(bNear), false)
		aFar.Close()
		bNear.Close()
		done <- isClosePassed
	}()
	go func() {
		_, _ = aNear.Write(session.EncodeRecord(session.RecordData, []byte("one")))
		_, _ = aNear.Write(session.CloseRecord("", map[string]any{"exit_code": 0}))
	}()
	reader := NewRecordStream(bFar)
	first, err := session.ReadRecord(reader.Reader)
	if err != nil || string(first.Payload) != "one" {
		t.Fatalf("first %v %v", first, err)
	}
	second, err := session.ReadRecord(reader.Reader)
	if err != nil || second.Type != session.RecordClose {
		t.Fatalf("second %v %v", second, err)
	}
	select {
	case isClosePassed := <-done:
		if !isClosePassed {
			t.Fatal("the close record was not seen")
		}
	case <-time.After(5 * time.Second):
		t.Fatal("the relay did not end after the close")
	}
	if _, err := reader.Reader.ReadByte(); err == nil {
		t.Fatal("b's end stayed open")
	}
}

func TestHeldDatagrams(t *testing.T) {
	held := &HeldDatagrams{}
	for i := 0; i < session.UdpHeldDatagramsMax+3; i++ {
		kept := held.Hold([]byte{byte(i)})
		if kept != (i < session.UdpHeldDatagramsMax) {
			t.Fatalf("datagram %d kept %v", i, kept)
		}
	}
	var out bytes.Buffer
	if err := held.Release(&out); err != nil {
		t.Fatal(err)
	}
	if out.Len() != session.UdpHeldDatagramsMax || out.Bytes()[0] != 0 || out.Bytes()[15] != 15 {
		t.Fatalf("released %x", out.Bytes())
	}
	if held.Hold([]byte{9}) {
		t.Fatal("a datagram was held after the release")
	}
}

func TestSpliceAndCopyRecords(t *testing.T) {
	aNear, aFar := net.Pipe()
	bNear, bFar := net.Pipe()
	done := make(chan struct{})
	go func() {
		Splice(aFar, bNear)
		close(done)
	}()
	go func() {
		_, _ = aNear.Write([]byte("to b"))
	}()
	buffer := make([]byte, 4)
	if _, err := io.ReadFull(bFar, buffer); err != nil || string(buffer) != "to b" {
		t.Fatalf("%q %v", buffer, err)
	}
	go func() {
		_, _ = bFar.Write([]byte("to a"))
	}()
	if _, err := io.ReadFull(aNear, buffer); err != nil || string(buffer) != "to a" {
		t.Fatalf("%q %v", buffer, err)
	}
	aNear.Close()
	select {
	case <-done:
	case <-time.After(5 * time.Second):
		t.Fatal("the splice did not end")
	}

	var out bytes.Buffer
	records := append(session.EncodeRecord(session.RecordData, []byte("x")), session.AcceptRecord()...)
	err := CopyRecords(&out, recordReader(bytes.NewReader(records)))
	if err != io.EOF || !bytes.Equal(out.Bytes(), records) {
		t.Fatalf("copy %v %x", err, out.Bytes())
	}
	tooLarge := session.EncodeRecord(session.RecordData, nil)
	tooLarge[1], tooLarge[2] = 0, 2
	out.Reset()
	if err := CopyRecords(&out, recordReader(bytes.NewReader(tooLarge))); err == nil || out.Len() != 0 {
		t.Fatalf("too large: %v, %d bytes written", err, out.Len())
	}
}

func TestHandOff(t *testing.T) {
	handOff := NewHandOff(50 * time.Millisecond)
	near, far := net.Pipe()
	handOff.Announce("t1", NewRecordStream(far))
	taken, err := handOff.Take("t1")
	if err != nil || taken.Stream != far {
		t.Fatalf("take %v %v", taken, err)
	}
	if _, err := handOff.Take("t1"); err != ErrStreamUnknown {
		t.Fatalf("second take %v", err)
	}
	handOff.Announce("t2", NewRecordStream(far))
	record, err := session.ReadRecord(recordReader(near))
	if err != nil || record.Type != session.RecordClose {
		t.Fatalf("expired stream read %v %v", record, err)
	}
	if closed, _ := session.ParseClose(record.Payload); closed.Code != session.CodeControlUnavailable {
		t.Fatalf("close %v", closed)
	}
	if handOff.Waiting() != 0 {
		t.Fatalf("%d waiting", handOff.Waiting())
	}
}
