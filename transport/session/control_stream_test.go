package session

import (
	"bytes"
	"errors"
	"io"
	"net"
	"testing"
)

func TestControlStreamLines(t *testing.T) {
	near, far := net.Pipe()
	writer := NewControlStream(near)
	reader := NewControlStream(far)
	big := MakeFrame(FrameState, map[string]any{"blob": string(bytes.Repeat([]byte{'s'}, 3*RecordBytesMax))})
	frames := [][]byte{[]byte(`{"type":"hello","id":"b1"}`), big, []byte(`{"type":"ping","nonce":"1"}`)}
	go func() {
		for _, frame := range frames {
			if err := writer.WriteFrame(frame); err != nil {
				t.Error(err)
				return
			}
		}
		_ = writer.WriteRaw(EncodeRecord(RecordResize, []byte(`{"cols":1}`)))
		_ = writer.WriteRaw(CloseRecord("", nil))
	}()
	for _, want := range frames {
		got, err := reader.ReadFrame()
		if err != nil {
			t.Fatal(err)
		}
		if !bytes.Equal(got, want) {
			t.Fatalf("frame of %d bytes, want %d", len(got), len(want))
		}
	}
	if _, err := reader.ReadFrame(); !errors.Is(err, io.EOF) {
		t.Fatalf("after the close: %v", err)
	}
}

func TestControlStreamFrameCap(t *testing.T) {
	near, far := net.Pipe()
	writer := NewControlStream(near)
	reader := NewControlStream(far)
	if err := writer.WriteFrame(make([]byte, ControlFrameBytesMax)); !errors.Is(err, ErrFrameTooLarge) {
		t.Fatalf("write: %v", err)
	}
	go func() {
		line := bytes.Repeat([]byte{'x'}, ControlFrameBytesMax+1)
		for len(line) > 0 {
			chunk := min(len(line), RecordBytesMax)
			if err := WriteRecord(near, RecordData, line[:chunk]); err != nil {
				return
			}
			line = line[chunk:]
		}
	}()
	if _, err := reader.ReadFrame(); !errors.Is(err, ErrFrameTooLarge) {
		t.Fatalf("read: %v", err)
	}
	near.Close()
}

func TestControlStreamAnswer(t *testing.T) {
	near, far := net.Pipe()
	go func() {
		_, _ = near.Write(AcceptRecord())
		_, _ = near.Write(CloseRecord(CodeHelloInvalid, nil))
	}()
	reader := NewControlStream(far)
	if refusal, err := reader.ReadAnswer(); err != nil || refusal != nil {
		t.Fatalf("accept: %v %v", refusal, err)
	}
	if refusal, err := reader.ReadAnswer(); err != nil || refusal.Code != CodeHelloInvalid {
		t.Fatalf("close: %v %v", refusal, err)
	}
}
