package gate

import (
	"bytes"
	"context"
	"crypto/rand"
	"errors"
	"io"
	"net"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/pion/stun/v3"
)

const (
	testUfrag    = "0123456789abcdef01234567"         // scan: allow
	testPassword = "0123456789abcdef0123456789abcdef" // scan: allow
)

// openResult is what the hub's side of one connection ended with.
type openResult struct {
	conn     *ChannelConn
	ufrag    string
	decision Decision
	err      error
}

// serveGate accepts connections on loopback and runs the gate on each.
func serveGate(t *testing.T, g *Gate) (string, chan openResult) {
	t.Helper()
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { listener.Close() })
	results := make(chan openResult, 8)
	go func() {
		for {
			conn, err := listener.Accept()
			if err != nil {
				return
			}
			go func() {
				ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
				defer cancel()
				_ = conn.SetReadDeadline(time.Now().Add(5 * time.Second))
				check, err := g.ReadFirstCheck(conn)
				if err != nil {
					conn.Close()
					results <- openResult{err: err}
					return
				}
				channel, ufrag, err := g.Open(ctx, conn, check)
				results <- openResult{conn: channel, ufrag: ufrag, decision: check.Decision, err: err}
			}()
		}
	}()
	return listener.Addr().String(), results
}

func testGate(t *testing.T) *Gate {
	t.Helper()
	certificate, err := LoadOrCreateCertificate(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	g := New(certificate)
	g.SetShares([]Share{{Ufrag: testUfrag, Password: testPassword}})
	return g
}

func TestCertificateFiles(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "transport")
	first, err := LoadOrCreateCertificate(dir)
	if err != nil {
		t.Fatal(err)
	}
	second, err := LoadOrCreateCertificate(dir)
	if err != nil {
		t.Fatal(err)
	}
	if Fingerprint(first) != Fingerprint(second) || Fingerprint(first) == "" {
		t.Fatalf("the certificate changed between reads: %s, %s", Fingerprint(first), Fingerprint(second))
	}
	if len(Fingerprint(first)) != 32*3-1 {
		t.Fatalf("fingerprint %q", Fingerprint(first))
	}
	written, err := os.ReadFile(filepath.Join(dir, GateFingerprintFile))
	if err != nil || string(written) != Fingerprint(first)+"\n" {
		t.Fatalf("fingerprint file %q: %v", written, err)
	}
	info, err := os.Stat(filepath.Join(dir, GateCertificateKeyFile))
	if err != nil || info.Mode().Perm() != GateCertificateKeyMode {
		t.Fatalf("key file mode %v: %v", info.Mode(), err)
	}
	if first.Leaf.NotAfter.Before(time.Now().Add(9 * 365 * 24 * time.Hour)) {
		t.Fatalf("certificate ends at %v", first.Leaf.NotAfter)
	}
}

func TestChannelCarriesBytesBothWays(t *testing.T) {
	g := testGate(t)
	address, results := serveGate(t, g)
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	client, err := Dial(ctx, address, DialOptions{Ufrag: testUfrag, Password: testPassword, Fingerprint: g.Fingerprint()})
	if err != nil {
		t.Fatal(err)
	}
	defer client.Close()
	result := <-results
	if result.err != nil {
		t.Fatal(result.err)
	}
	defer result.conn.Close()
	if result.ufrag != testUfrag {
		t.Fatalf("share %q", result.ufrag)
	}
	if result.decision.FrameBytes < GatePeekBytes || result.decision.UsernameEndByte <= GateFrameLengthBytes+GateStunHeaderBytes || result.decision.UsernameEndByte > result.decision.FrameBytes {
		t.Fatalf("decision %+v", result.decision)
	}
	if _, err := client.Write([]byte("ping")); err != nil {
		t.Fatal(err)
	}
	buffer := make([]byte, 16)
	n, err := result.conn.Read(buffer)
	if err != nil || string(buffer[:n]) != "ping" {
		t.Fatalf("hub read %q: %v", buffer[:n], err)
	}
	large := make([]byte, 3*GateMessageBytesMax+17)
	_, _ = rand.Read(large)
	go func() { _, _ = result.conn.Write(large) }()
	got := make([]byte, len(large))
	_ = client.SetReadDeadline(time.Now().Add(5 * time.Second))
	if _, err := io.ReadFull(client, got); err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(got, large) {
		t.Fatal("the bytes differ")
	}
	result.conn.Close()
	_ = client.SetReadDeadline(time.Now().Add(5 * time.Second))
	if _, err := client.Read(buffer); err == nil {
		t.Fatal("the client's read survived the hub's close")
	}
}

func TestFirstCheckCutOffs(t *testing.T) {
	g := testGate(t)
	address, results := serveGate(t, g)
	cases := []struct {
		name    string
		options DialOptions
		raw     []byte
		hubErr  error
	}{
		{"a frame that is not STUN", DialOptions{}, []byte("GET / HTTP/1.1\r\n\r\n"), ErrNotStun},
		{"a frame with another first byte", DialOptions{}, []byte{0x01, 0x60, 0x00, 0x01, 0x00, 0x4c, 0x21, 0x12, 0xa4, 0x42}, ErrNotStun},
		{"a binding request with no username", DialOptions{}, stunFrame(t, stun.BindingRequest, stun.Fingerprint), ErrNotStun},
		{"a ufrag no live share holds", DialOptions{Ufrag: "nobody", Password: testPassword}, nil, ErrShareUnknown},
		{"a wrong password", DialOptions{Ufrag: testUfrag, Password: "fedcba9876543210fedcba9876543210"}, nil, ErrStunRefused}, // scan: allow
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
			defer cancel()
			if c.raw != nil {
				conn, err := net.Dial("tcp", address)
				if err != nil {
					t.Fatal(err)
				}
				defer conn.Close()
				if _, err := conn.Write(c.raw); err != nil {
					t.Fatal(err)
				}
				_ = conn.SetReadDeadline(time.Now().Add(3 * time.Second))
				n, err := conn.Read(make([]byte, 64))
				if n != 0 || err == nil {
					t.Fatalf("the hub wrote %d bytes before closing: %v", n, err)
				}
			} else {
				c.options.Fingerprint = g.Fingerprint()
				if _, err := Dial(ctx, address, c.options); !errors.Is(err, ErrStunRefused) {
					t.Fatalf("dial: %v, want a refused check", err)
				}
			}
			result := <-results
			if !errors.Is(result.err, c.hubErr) {
				t.Fatalf("hub: %v, want %v", result.err, c.hubErr)
			}
		})
	}
}

// TestFirstCheckReadsNoFurther checks that the first check reads a frame
// for an unknown ufrag only through its USERNAME, and a good frame only to
// its end.
func TestFirstCheckReadsNoFurther(t *testing.T) {
	g := testGate(t)
	unknown := stunFrame(t, stun.BindingRequest, stun.NewUsername("nobody0123456789abcdef01:browser"), stun.NewShortTermIntegrity(testPassword), stun.Fingerprint)
	_, usernameEnd, _ := usernameOf(unknown[GateFrameLengthBytes:])
	reader := bytes.NewReader(append(unknown, 0xee))
	if _, err := g.ReadFirstCheck(reader); !errors.Is(err, ErrShareUnknown) {
		t.Fatalf("unknown ufrag: %v", err)
	}
	if read := len(unknown) + 1 - reader.Len(); read != GateFrameLengthBytes+usernameEnd {
		t.Fatalf("read %d bytes, want %d", read, GateFrameLengthBytes+usernameEnd)
	}
	good := stunFrame(t, stun.BindingRequest, stun.NewUsername(testUfrag+":browser"), stun.NewShortTermIntegrity(testPassword), stun.Fingerprint)
	reader = bytes.NewReader(append(good, 0xee))
	check, err := g.ReadFirstCheck(reader)
	if err != nil {
		t.Fatal(err)
	}
	if reader.Len() != 1 || check.Decision.FrameBytes != len(good) {
		t.Fatalf("%d bytes left, decision %+v", reader.Len(), check.Decision)
	}
}

func TestWrongFingerprintFailsTheHandshake(t *testing.T) {
	g := testGate(t)
	address, results := serveGate(t, g)
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	other := "00:" + g.Fingerprint()[3:]
	if _, err := Dial(ctx, address, DialOptions{Ufrag: testUfrag, Password: testPassword, Fingerprint: other}); err == nil {
		t.Fatal("a wrong fingerprint opened the channel")
	}
	if result := <-results; result.err == nil {
		result.conn.Close()
		t.Fatal("the hub opened a channel under a wrong fingerprint")
	}
}

func TestNoLiveShareClosesAtOnce(t *testing.T) {
	certificate, err := LoadOrCreateCertificate(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	g := New(certificate)
	if g.HasShares() {
		t.Fatal("a new gate has a share")
	}
	g.SetShares([]Share{{Ufrag: testUfrag, Password: testPassword}})
	if !g.HasShares() {
		t.Fatal("the share was not set")
	}
	g.SetShares(nil)
	if g.HasShares() {
		t.Fatal("the shares were not cleared")
	}
}

func TestLaterChecksAreAnswered(t *testing.T) {
	var written [][]byte
	answerer := &stunAnswerer{ufrag: testUfrag, password: testPassword, peer: &net.TCPAddr{IP: net.IPv4(203, 0, 113, 9), Port: 4242}, write: func(frame []byte) error {
		written = append(written, frame)
		return nil
	}}
	good := stunFrame(t, stun.BindingRequest, stun.NewUsername(testUfrag+":browser"), stun.NewShortTermIntegrity(testPassword), stun.Fingerprint)[GateFrameLengthBytes:]
	otherShare := stunFrame(t, stun.BindingRequest, stun.NewUsername("other:browser"), stun.NewShortTermIntegrity(testPassword), stun.Fingerprint)[GateFrameLengthBytes:]
	wrongPassword := stunFrame(t, stun.BindingRequest, stun.NewUsername(testUfrag+":browser"), stun.NewShortTermIntegrity("x"), stun.Fingerprint)[GateFrameLengthBytes:]
	answerer.handle(otherShare)
	answerer.handle(wrongPassword)
	if len(written) != 0 {
		t.Fatalf("%d answers to checks that do not verify", len(written))
	}
	answerer.handle(good)
	if len(written) != 1 {
		t.Fatalf("%d answers to one good check", len(written))
	}
	answer := &stun.Message{Raw: written[0]}
	if err := answer.Decode(); err != nil || answer.Type != stun.BindingSuccess {
		t.Fatalf("answer %v: %v", answer.Type, err)
	}
	var mapped stun.XORMappedAddress
	if err := mapped.GetFrom(answer); err != nil || mapped.Port != 4242 || !mapped.IP.Equal(net.IPv4(203, 0, 113, 9)) {
		t.Fatalf("mapped address %v: %v", mapped, err)
	}
	if err := stun.NewShortTermIntegrity(testPassword).Check(answer); err != nil {
		t.Fatalf("answer integrity: %v", err)
	}
	ufrag, end, isFound := usernameOf(good)
	if !isFound || ufrag != testUfrag || end <= GateStunHeaderBytes {
		t.Fatalf("username %q at %d, %v", ufrag, end, isFound)
	}
}

// stunFrame builds one STUN message's bytes.
func stunFrame(t *testing.T, messageType stun.MessageType, setters ...stun.Setter) []byte {
	t.Helper()
	all := append([]stun.Setter{stun.TransactionID, messageType}, setters...)
	message, err := stun.Build(all...)
	if err != nil {
		t.Fatal(err)
	}
	frame := make([]byte, GateFrameLengthBytes+len(message.Raw))
	frame[1] = byte(len(message.Raw))
	copy(frame[GateFrameLengthBytes:], message.Raw)
	return frame
}
