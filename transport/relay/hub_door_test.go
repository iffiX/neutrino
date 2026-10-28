package relay

import (
	"io"
	"net"
	"testing"
	"time"

	"github.com/iffiX/neutrino/transport/handshake"
	"github.com/iffiX/neutrino/transport/knock"
	"github.com/iffiX/neutrino/transport/session"
)

// answerUnpaddedBytes is message 2 with no payload: an ephemeral key and an
// empty payload's tag.
const answerUnpaddedBytes = 32 + 16

// TestAnswerIsPadded checks that the hub's answer carries 0 to
// KnockPaddingBytesMax bytes of padding in message 2, drawn for each knock.
func TestAnswerIsPadded(t *testing.T) {
	hub := newTestHub(t)
	hostPort, _ := session.ParseAddress(hub.listen(t))
	payload := knock.Payload{Protocol: knock.PROTOCOL, Role: knock.KnockRoleAgent, IsJoin: true}
	sizes := map[int]bool{}
	for i := 0; i < 40; i++ {
		peer, _ := handshake.GenerateKey()
		payload.Time = time.Now().UnixNano()
		initiator, err := handshake.NewInitiator(peer, hub.key.Public, handshake.ZeroPsk, payload.Marshal())
		if err != nil {
			t.Fatal(err)
		}
		raw, _ := knock.Encode(initiator.Message1, hub.key.Public, nil)
		conn, err := net.Dial("tcp", hostPort)
		if err != nil {
			t.Fatal(err)
		}
		_, _ = conn.Write(raw)
		_ = conn.SetReadDeadline(time.Now().Add(3 * time.Second))
		header := make([]byte, knock.KnockHeaderBytes)
		if _, err := io.ReadFull(conn, header); err != nil {
			t.Fatal(err)
		}
		message2, err := session.ReadLengthPrefixed(conn)
		conn.Close()
		if err != nil {
			t.Fatal(err)
		}
		if _, _, err := initiator.Open(message2); err != nil {
			t.Fatalf("message 2 of %d bytes: %v", len(message2), err)
		}
		padding := len(message2) - answerUnpaddedBytes
		if padding < 0 || padding > knock.KnockPaddingBytesMax {
			t.Fatalf("message 2 of %d bytes", len(message2))
		}
		sizes[len(message2)] = true
	}
	if len(sizes) < 5 {
		t.Fatalf("%d sizes of message 2 in 40 answers", len(sizes))
	}
}
