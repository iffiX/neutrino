package relay

import (
	"crypto/rand"
	"errors"
	"io"
	"net"
	"sync"
	"sync/atomic"
	"syscall"
	"testing"
	"time"

	"github.com/pion/stun/v3"

	"github.com/iffiX/neutrino/transport/gate"
	"github.com/iffiX/neutrino/transport/handshake"
	"github.com/iffiX/neutrino/transport/knock"
	"github.com/iffiX/neutrino/transport/session"
)

const (
	// probeWrite is how long a probe waits for the door to read one byte.
	probeWrite = 200 * time.Millisecond
	// answerUnpaddedBytes is message 2 with no payload: an ephemeral key and
	// an empty payload's tag.
	answerUnpaddedBytes = 32 + 16
	// wsaConnReset is WSAECONNRESET, what Winsock answers for a reset.
	wsaConnReset = syscall.Errno(10054)
)

// isReset reports whether a read's error is the peer's reset.
func isReset(err error) bool {
	return errors.Is(err, syscall.ECONNRESET) || errors.Is(err, wsaConnReset)
}

func randomBytes(n int) []byte {
	data := make([]byte, n)
	_, _ = rand.Read(data)
	data[0] = 0x55
	return data
}

// wrongMacKnock is a knock under hubPublic whose message 1 has size bytes
// and whose mac1 is wrong.
func wrongMacKnock(t *testing.T, hubPublic []byte, size int) []byte {
	t.Helper()
	raw, err := knock.Encode(randomBytes(size), hubPublic, nil)
	if err != nil {
		t.Fatal(err)
	}
	raw[len(raw)-2*knock.KnockMacBytes] ^= 0xff
	return raw
}

// stunProbe is a Binding Request frame whose USERNAME names ufrag, with a
// PRIORITY before its integrity, and the byte its USERNAME ends at.
func stunProbe(t *testing.T, ufrag string) ([]byte, int) {
	t.Helper()
	message, err := stun.Build(stun.TransactionID, stun.BindingRequest,
		stun.NewUsername(ufrag+":browser"), stun.RawAttribute{Type: stun.AttrPriority, Value: []byte{1, 2, 3, 4}},
		stun.NewShortTermIntegrity(guestPassword), stun.Fingerprint)
	if err != nil {
		t.Fatal(err)
	}
	frame := append([]byte{0, byte(len(message.Raw))}, message.Raw...)
	usernameEnd := gate.GateFrameLengthBytes + gate.GateStunHeaderBytes + gate.GateStunAttributeHeaderBytes + len(ufrag+":browser")
	return frame, usernameEnd
}

// bytesRead writes data to a door on a pipe one byte at a time and returns
// how many bytes the door read before it stopped reading.
func bytesRead(t *testing.T, hub *Hub, data []byte) int {
	t.Helper()
	server, client := net.Pipe()
	t.Cleanup(func() { client.Close() })
	go hub.ServeConn(server, RelayListenerMain)
	for i := range data {
		_ = client.SetWriteDeadline(time.Now().Add(probeWrite))
		if _, err := client.Write(data[i : i+1]); err != nil {
			return i
		}
	}
	return len(data)
}

// refusalOf dials address, writes data and waits for the hub's close. It
// returns the bytes the hub wrote, the time from the dial to the close and
// the read's error.
func refusalOf(t *testing.T, address string, data []byte) (int, time.Duration, error) {
	t.Helper()
	started := time.Now()
	conn, err := net.Dial("tcp", address)
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	if len(data) > 0 {
		if _, err := conn.Write(data); err != nil {
			t.Fatal(err)
		}
	}
	_ = conn.SetReadDeadline(time.Now().Add(5 * time.Second))
	n, err := conn.Read(make([]byte, 64))
	return n, time.Since(started), err
}

func TestRefusedConnectionsAreHeldThenReset(t *testing.T) {
	hub := newTestHub(t)
	hostPort, _ := session.ParseAddress(hub.listen(t))
	magic := knock.Magic(hub.key.Public)
	stunFrame, _ := stunProbe(t, guestUfrag)
	cases := []struct {
		name  string
		bytes []byte
	}{
		{"an empty connection", nil},
		{"4 random bytes", randomBytes(4)},
		{"200 random bytes", randomBytes(200)},
		{"an HTTP GET", []byte("GET / HTTP/1.1\r\nHost: hub\r\n\r\n")},
		{"a TLS record", append([]byte{0x16, 0x03, 0x01, 0x00, 0x60, 0x01}, randomBytes(90)...)},
		{"the magic and a version the hub does not speak", append(append([]byte{}, magic...), 0, 9, 1, 0, 0, 40)},
		{"a knock with a wrong mac1", wrongMacKnock(t, hub.key.Public, 120)},
		{"a Binding Request while no share is live", stunFrame},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			n, elapsed, err := refusalOf(t, hostPort, c.bytes)
			if n != 0 || !isReset(err) {
				t.Fatalf("read %d bytes, %v; want nothing and a reset", n, err)
			}
			if elapsed < testHold-50*time.Millisecond || elapsed > testHold+2*time.Second {
				t.Fatalf("reset after %v, want the hold of %v", elapsed, testHold)
			}
		})
	}
	deadline := time.Now().Add(2 * time.Second)
	for hub.hub.Ledger().Waiting() != 0 && time.Now().Before(deadline) {
		time.Sleep(10 * time.Millisecond)
	}
	if hub.hub.Ledger().Waiting() != 0 {
		t.Fatalf("%d connections still counted", hub.hub.Ledger().Waiting())
	}
}

func TestRefusalPastTheHoldDeadlineResetsAtOnce(t *testing.T) {
	hub := newTestHubWith(t, fixedDraws(knock.DoorReadBytesMax, 0), nil)
	hostPort, _ := session.ParseAddress(hub.listen(t))
	n, elapsed, err := refusalOf(t, hostPort, randomBytes(40))
	if n != 0 || !isReset(err) || elapsed > time.Second {
		t.Fatalf("read %d bytes, %v after %v; want a reset at once", n, err, elapsed)
	}
}

// TestDoorReadsToTheDrawnLength checks how far the door reads before it
// stops: the drawn length on a wrong first byte or a wrong version, a whole
// knock and no further when the knock is longer, and the later of the drawn
// length and the USERNAME's end on the guest path.
func TestDoorReadsToTheDrawnLength(t *testing.T) {
	certificate, err := gate.LoadOrCreateCertificate(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	key, _ := handshake.GenerateKey()
	magic := knock.Magic(key.Public)
	longKnock := wrongMacKnock(t, key.Public, 120)
	shortKnock := wrongMacKnock(t, key.Public, 20)
	probe, usernameEnd := stunProbe(t, "nobody0123456789abcdef01")
	cases := []struct {
		name      string
		readBytes int
		bytes     []byte
		want      int
	}{
		{"a wrong first byte", 37, randomBytes(120), 37},
		{"the magic and a wrong version", 37, append(append([]byte{}, magic...), append([]byte{0, 9}, randomBytes(100)...)...), 37},
		{"a knock longer than the drawn length", knock.DoorReadBytesMin, append(longKnock, randomBytes(50)...), len(longKnock)},
		{"a knock shorter than the drawn length", knock.DoorReadBytesMax, append(shortKnock, randomBytes(120)...), knock.DoorReadBytesMax},
		{"a guest's unknown ufrag before the drawn length", knock.DoorReadBytesMin, append(probe, randomBytes(50)...), usernameEnd},
		{"a guest's unknown ufrag after the drawn length", knock.DoorReadBytesMax, append(probe, randomBytes(50)...), knock.DoorReadBytesMax},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			hub, err := NewHub(HubConfig{Key: key, Certificate: &certificate, Draws: fixedDraws(c.readBytes, 5*time.Second)}, newFakePython())
			if err != nil {
				t.Fatal(err)
			}
			defer hub.Close()
			hub.SetShares([]gate.Share{{Ufrag: guestUfrag, Password: guestPassword}})
			if got := bytesRead(t, hub, c.bytes); got != c.want {
				t.Fatalf("the door read %d bytes, want %d", got, c.want)
			}
		})
	}
}

// TestRefusedConnectionsAreClosedFirst fills every unadmitted place with
// refused connections and checks that a bound peer still gets in, one
// refused connection reset to make room.
func TestRefusedConnectionsAreClosedFirst(t *testing.T) {
	hub := newTestHubWith(t, fixedDraws(knock.DoorReadBytesMin, 20*time.Second), nil)
	address := hub.listen(t)
	hostPort, _ := session.ParseAddress(address)
	var held []net.Conn
	for i := 0; i < knock.UnadmittedMax; i++ {
		conn, err := net.Dial("tcp", hostPort)
		if err != nil {
			t.Fatal(err)
		}
		t.Cleanup(func() { conn.Close() })
		if _, err := conn.Write(randomBytes(knock.DoorReadBytesMin)); err != nil {
			t.Fatal(err)
		}
		held = append(held, conn)
	}
	deadline := time.Now().Add(5 * time.Second)
	for hub.hub.Ledger().Waiting() < knock.UnadmittedMax && time.Now().Before(deadline) {
		time.Sleep(10 * time.Millisecond)
	}
	time.Sleep(100 * time.Millisecond)
	agent := newPeer(t, hub, "dev5", "agent")
	started := time.Now()
	agent.admit(t, hub, address, "dev5")
	if elapsed := time.Since(started); elapsed > 2*time.Second {
		t.Fatalf("the peer took %v to get in", elapsed)
	}
	// The ledger lists the held connections in the order their goroutines
	// reached it. That order can differ from the dial order. A read after
	// the shared deadline returns no reset, so every connection is read at
	// once.
	readUntil := time.Now().Add(time.Second)
	var resets atomic.Int32
	var reads sync.WaitGroup
	for _, conn := range held {
		reads.Go(func() {
			_ = conn.SetReadDeadline(readUntil)
			if _, err := conn.Read(make([]byte, 1)); isReset(err) {
				resets.Add(1)
			}
		})
	}
	reads.Wait()
	if count := resets.Load(); count != 1 {
		t.Fatalf("%d refused connections reset, want the one the peer's place took", count)
	}
}

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
