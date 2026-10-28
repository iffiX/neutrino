package session

import (
	"bufio"
	"context"
	"errors"
	"io"
	"net"
	"testing"
	"time"

	"github.com/flynn/noise"

	"github.com/iffiX/neutrino/transport/handshake"
	"github.com/iffiX/neutrino/transport/knock"
)

// fakeHub answers knocks on loopback: a cookie reply to the first knock of a
// connection without mac2 while isUnderLoad, else message 2 under psk.
type fakeHub struct {
	listener    net.Listener
	key         noise.DHKey
	psk         []byte
	isUnderLoad bool
	isSilent    bool
	jar         *knock.CookieJar
	knocks      chan *knock.Knock
}

func newFakeHub(t *testing.T) *fakeHub {
	t.Helper()
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	key, _ := handshake.GenerateKey()
	jar, _ := knock.NewCookieJar(key.Public, time.Now)
	hub := &fakeHub{listener: listener, key: key, psk: handshake.ZeroPsk, jar: jar, knocks: make(chan *knock.Knock, 8)}
	go hub.serve()
	t.Cleanup(func() { listener.Close() })
	return hub
}

func (h *fakeHub) address() string {
	return AddressScheme + h.listener.Addr().String()
}

func (h *fakeHub) serve() {
	for {
		conn, err := h.listener.Accept()
		if err != nil {
			return
		}
		go h.answer(conn)
	}
}

func (h *fakeHub) answer(conn net.Conn) {
	defer conn.Close()
	reader := bufio.NewReader(conn)
	header := make([]byte, knock.KnockHeaderBytes)
	if _, err := io.ReadFull(reader, header); err != nil {
		return
	}
	if parsedHeader, err := knock.ParseHeader(header, h.key.Public); err != nil || parsedHeader.Type != knock.KnockTypeKnock {
		return
	}
	parsed, err := knock.ReadBody(reader, header)
	if err != nil || !parsed.VerifyMac1(h.key.Public) {
		return
	}
	h.knocks <- parsed
	if h.isSilent {
		time.Sleep(time.Second)
		return
	}
	address := conn.RemoteAddr().(*net.TCPAddr).IP
	if h.isUnderLoad && !h.jar.IsMac2Valid(parsed, address) {
		reply, _ := h.jar.Reply(parsed, address)
		_, _ = conn.Write(reply)
		return
	}
	responder, _ := handshake.NewResponder(h.key)
	if err := responder.Read(parsed.Message1); err != nil {
		return
	}
	message2, keys, err := responder.Answer(h.psk, knock.Padding())
	if err != nil {
		return
	}
	_, _ = conn.Write(knock.EncodeHeader(h.key.Public, knock.KnockTypeAnswer))
	if err := WriteLengthPrefixed(conn, message2); err != nil {
		return
	}
	noiseConn := NewNoiseConn(conn, reader, keys)
	_, _ = io.Copy(noiseConn, noiseConn)
}

func TestDialHandshake(t *testing.T) {
	hub := newFakeHub(t)
	peer, _ := handshake.GenerateKey()
	options := DialOptions{Static: peer, HubPublic: hub.key.Public, Psk: handshake.ZeroPsk, Protocol: knock.PROTOCOL, Role: knock.KnockRoleAgent, IsJoin: true}
	result, err := Dial(context.Background(), hub.address(), options)
	if err != nil {
		t.Fatal(err)
	}
	defer result.Conn.Close()
	if result.IsRefusal || result.HandshakeTime <= 0 {
		t.Fatalf("refusal %v, handshake %v", result.IsRefusal, result.HandshakeTime)
	}
	knocked := <-hub.knocks
	if len(knocked.Raw) > knock.KnockBytesMax {
		t.Fatalf("knock of %d bytes", len(knocked.Raw))
	}
	if _, err := result.Conn.Write([]byte("echo")); err != nil {
		t.Fatal(err)
	}
	buffer := make([]byte, 4)
	if _, err := io.ReadFull(result.Conn, buffer); err != nil || string(buffer) != "echo" {
		t.Fatalf("echo %q %v", buffer, err)
	}
}

func TestDialUnderLoadKnocksAgainWithTheCookie(t *testing.T) {
	hub := newFakeHub(t)
	hub.isUnderLoad = true
	peer, _ := handshake.GenerateKey()
	options := DialOptions{Static: peer, HubPublic: hub.key.Public, Psk: handshake.ZeroPsk, Protocol: knock.PROTOCOL, Role: knock.KnockRoleClient, IsJoin: true}
	result, err := Dial(context.Background(), hub.address(), options)
	if err != nil {
		t.Fatal(err)
	}
	result.Conn.Close()
	first := <-hub.knocks
	second := <-hub.knocks
	if first.VerifyMac2(hub.jar.Cookie(net.ParseIP("127.0.0.1"))) {
		t.Fatal("the first knock already carried a cookie")
	}
	if !second.VerifyMac2(hub.jar.Cookie(net.ParseIP("127.0.0.1"))) {
		t.Fatal("the second knock carries no valid mac2")
	}
}

func TestDialRefusalAndUntrusted(t *testing.T) {
	hub := newFakeHub(t)
	peer, _ := handshake.GenerateKey()
	token := make([]byte, 32)
	token[0] = 1
	options := DialOptions{Static: peer, HubPublic: hub.key.Public, Psk: token, Protocol: knock.PROTOCOL, Role: knock.KnockRoleAgent}
	result, err := Dial(context.Background(), hub.address(), options)
	if err != nil {
		t.Fatal(err)
	}
	result.Conn.Close()
	if !result.IsRefusal {
		t.Fatal("a message 2 under the zero psk did not read as a refusal")
	}
	<-hub.knocks
	other := make([]byte, 32)
	other[0] = 2
	hub.psk = other
	if _, err := Dial(context.Background(), hub.address(), options); !errors.Is(err, handshake.ErrHubUntrusted) {
		t.Fatalf("err %v, want hub untrusted", err)
	}
	<-hub.knocks
}

func TestDialSilenceAndSchemes(t *testing.T) {
	hub := newFakeHub(t)
	hub.isSilent = true
	peer, _ := handshake.GenerateKey()
	options := DialOptions{Static: peer, HubPublic: hub.key.Public, Psk: handshake.ZeroPsk, Protocol: knock.PROTOCOL, Role: knock.KnockRoleAgent, IsJoin: true, Timeout: 300 * time.Millisecond}
	if _, err := Dial(context.Background(), hub.address(), options); !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("err %v, want deadline exceeded", err)
	}
	if _, err := Dial(context.Background(), "quic://127.0.0.1:1", options); !errors.Is(err, ErrSchemeUnknown) {
		t.Fatalf("err %v, want scheme unknown", err)
	}
	hostPort, err := ParseAddress("tcp://[::1]:8443")
	if err != nil || hostPort != "[::1]:8443" {
		t.Fatalf("%q %v", hostPort, err)
	}
	if _, err := Dial(context.Background(), "tcp://127.0.0.1:1", options); err == nil {
		t.Fatal("a closed port dialled")
	}
}

// TestKnockIsPadded checks that message 1 carries 0 to KnockPaddingBytesMax
// bytes of padding after its JSON, drawn for each dial, and that the hub
// reads the JSON through it.
func TestKnockIsPadded(t *testing.T) {
	hub := newFakeHub(t)
	peer, _ := handshake.GenerateKey()
	sizes := map[int]bool{}
	smallest, largest := knock.KnockBytesMax, 0
	for i := 0; i < 40; i++ {
		options := DialOptions{Static: peer, HubPublic: hub.key.Public, Psk: handshake.ZeroPsk, Protocol: knock.PROTOCOL, Role: knock.KnockRoleAgent, IsJoin: true}
		result, err := Dial(context.Background(), hub.address(), options)
		if err != nil {
			t.Fatal(err)
		}
		result.Conn.Close()
		knocked := <-hub.knocks
		responder, _ := handshake.NewResponder(hub.key)
		if err := responder.Read(knocked.Message1); err != nil {
			t.Fatal(err)
		}
		payload, err := knock.ParsePayload(responder.Payload)
		if err != nil || payload.Role != knock.KnockRoleAgent || !payload.IsJoin {
			t.Fatalf("payload %+v: %v", payload, err)
		}
		sizes[len(knocked.Raw)] = true
		smallest, largest = min(smallest, len(knocked.Raw)), max(largest, len(knocked.Raw))
	}
	if len(sizes) < 5 || largest-smallest > knock.KnockPaddingBytesMax {
		t.Fatalf("%d knock sizes from %d to %d bytes", len(sizes), smallest, largest)
	}
}
