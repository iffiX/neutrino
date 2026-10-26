package session

import (
	"bufio"
	"bytes"
	"errors"
	"testing"
)

func TestRecordRoundTrip(t *testing.T) {
	cases := []struct {
		name    string
		kind    byte
		payload []byte
	}{
		{"open", RecordOpen, []byte(`{"kind":"control"}`)},
		{"accept", RecordAccept, nil},
		{"data", RecordData, bytes.Repeat([]byte{7}, RecordBytesMax)},
		{"stderr", RecordStderr, []byte("oops")},
		{"eof", RecordEof, nil},
		{"resize", RecordResize, []byte(`{"cols":80,"rows":24}`)},
		{"datagram", RecordDatagram, []byte{0x12, 0x34, 1, 2, 3}},
		{"close", RecordClose, []byte(`{"code":"x","params":{}}`)},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			var buffer bytes.Buffer
			if err := WriteRecord(&buffer, c.kind, c.payload); err != nil {
				t.Fatal(err)
			}
			if buffer.Len() != RecordHeaderBytes+len(c.payload) {
				t.Fatalf("%d bytes written", buffer.Len())
			}
			record, err := ReadRecord(bufio.NewReader(&buffer))
			if err != nil {
				t.Fatal(err)
			}
			if record.Type != c.kind || !bytes.Equal(record.Payload, c.payload) {
				t.Fatalf("read type %d with %d bytes", record.Type, len(record.Payload))
			}
		})
	}
}

func TestRecordTooLarge(t *testing.T) {
	var buffer bytes.Buffer
	if err := WriteRecord(&buffer, RecordData, make([]byte, RecordBytesMax+1)); !errors.Is(err, ErrRecordTooLarge) {
		t.Fatalf("write: %v", err)
	}
	header := EncodeRecord(RecordData, nil)
	header[1], header[2], header[3], header[4] = 0, 1, 0, 1
	if _, err := ReadRecord(bufio.NewReader(bytes.NewReader(header))); !errors.Is(err, ErrRecordTooLarge) {
		t.Fatalf("read: %v", err)
	}
}

func TestOpenAndClose(t *testing.T) {
	open := OpenRecord(KindConnect, map[string]any{"id": "e1"})
	record, _ := ReadRecord(bufio.NewReader(bytes.NewReader(open)))
	kind, err := OpenKind(record.Payload)
	if err != nil || kind != KindConnect {
		t.Fatalf("kind %q %v", kind, err)
	}
	if _, err := OpenKind([]byte(`{"id":"e1"}`)); err == nil {
		t.Fatal("an open without a kind read")
	}
	refusal, err := ReadAnswer(bufio.NewReader(bytes.NewReader(AcceptRecord())))
	if err != nil || refusal != nil {
		t.Fatalf("accept: %v %v", refusal, err)
	}
	refusal, err = ReadAnswer(bufio.NewReader(bytes.NewReader(CloseRecord("agent_offline", map[string]any{"device": "d"}))))
	if err != nil || refusal == nil || refusal.Code != "agent_offline" || refusal.Params["device"] != "d" {
		t.Fatalf("close: %+v %v", refusal, err)
	}
	result, err := ParseClose(CloseRecord("", nil)[RecordHeaderBytes:])
	if err != nil || result.Code != "" || len(result.Params) != 0 {
		t.Fatalf("result close: %+v %v", result, err)
	}
	if _, err := ReadAnswer(bufio.NewReader(bytes.NewReader(EncodeRecord(RecordData, []byte("x"))))); !errors.Is(err, ErrRecordUnexpected) {
		t.Fatalf("data before accept: %v", err)
	}
}

func TestFrames(t *testing.T) {
	frame := MakeFrame(FrameHello, map[string]any{"id": "b1", "protocol": 4})
	kind, err := FrameType(frame)
	if err != nil || kind != FrameHello {
		t.Fatalf("type %q %v", kind, err)
	}
	if _, err := FrameType([]byte(`{"id":"b1"}`)); err == nil {
		t.Fatal("a frame without a type read")
	}
	pong := PongFrame([]byte(`{"type":"ping","nonce":"` + string(bytes.Repeat([]byte{'n'}, 70)) + `"}`))
	if string(pong) != `{"nonce":"`+string(bytes.Repeat([]byte{'n'}, PingNonceCharsMax))+`","type":"pong"}` {
		t.Fatalf("pong %s", pong)
	}
	if string(PongFrame([]byte(`{"type":"ping"}`))) != `{"nonce":"","type":"pong"}` {
		t.Fatalf("pong without a nonce %s", PongFrame([]byte(`{"type":"ping"}`)))
	}
	refused := ParseRefused(RefusedFrame(NewRefusal(CodeChannelFull, map[string]any{"limit": 512})))
	if refused.Code != CodeChannelFull || refused.Params["limit"] != float64(512) {
		t.Fatalf("refused %+v", refused)
	}
	var asError error = NewRefusal(CodeHelloInvalid, nil)
	var refusal *Refusal
	if !errors.As(asError, &refusal) || refusal.Code != CodeHelloInvalid || refusal.Params == nil {
		t.Fatalf("refusal as error: %v", asError)
	}
}
