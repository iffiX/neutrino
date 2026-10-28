package tests

import (
	"bufio"
	"bytes"
	"context"
	"crypto/rand"
	"errors"
	"io"
	"net"
	"testing"
	"time"

	"github.com/iffiX/neutrino/transport/gate"
	"github.com/iffiX/neutrino/transport/knock"
	"github.com/iffiX/neutrino/transport/session"
)

const (
	shareUfrag    = "0123456789abcdef01234567"         // scan: allow
	sharePassword = "0123456789abcdef0123456789abcdef" // scan: allow
	shareTicket   = "share-ticket-1"
	shareID       = "share-1"
)

// guestSide is one browser's session as the test drives it: the channel,
// the yamux session on it and the control stream.
type guestSide struct {
	conn    *gate.ChannelConn
	session *session.Session
	control *session.ControlStream
}

// dialGuest runs the guest path up to the hub's answer to the open record,
// and on an accept the control stream through welcome.
func dialGuest(t *testing.T, hub *hubSide, ufrag, password, ticket string) (*guestSide, *session.Refusal) {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	conn, err := gate.Dial(ctx, net.JoinHostPort("127.0.0.1", itoa(hub.port)), gate.DialOptions{Ufrag: ufrag, Password: password, Fingerprint: hub.hub.Fingerprint()})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := conn.Write(gate.GuestOpenRecord(gate.GuestOpen{Protocol: knock.PROTOCOL, Ticket: ticket})); err != nil {
		t.Fatal(err)
	}
	message := make([]byte, 1024)
	_ = conn.SetReadDeadline(time.Now().Add(5 * time.Second))
	n, err := conn.ReadMessage(message)
	if err != nil {
		t.Fatal(err)
	}
	_ = conn.SetReadDeadline(time.Time{})
	id, refusal, err := gate.ParseGuestAnswer(message[:n])
	if err != nil {
		t.Fatal(err)
	}
	if refusal != nil {
		conn.Close()
		return nil, refusal
	}
	if id != shareID {
		t.Fatalf("accepted as %q", id)
	}
	sess, err := session.NewPeerSession(conn, timings)
	if err != nil {
		t.Fatal(err)
	}
	stream, err := sess.OpenStream(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := stream.Write(session.OpenRecord(session.KindControl, nil)); err != nil {
		t.Fatal(err)
	}
	control := session.NewControlStream(stream)
	if answer, err := control.ReadAnswer(); err != nil || answer != nil {
		t.Fatalf("control stream answer %v: %v", answer, err)
	}
	hello := session.MakeFrame(session.FrameHello, map[string]any{"id": id, "protocol": knock.PROTOCOL, "role": "guest", "name": "guest", "software": "neutrino_web/0.6.0"})
	if err := control.WriteFrame(hello); err != nil {
		t.Fatal(err)
	}
	sessionID, bindingID := hub.serveHello(t)
	if bindingID != shareID {
		t.Fatalf("the hub admitted the guest as %q on %s", bindingID, sessionID)
	}
	welcome, err := control.ReadFrame()
	if err != nil {
		t.Fatal(err)
	}
	if frameType, _ := session.FrameType(welcome); frameType != session.FrameWelcome {
		t.Fatalf("first frame %s", welcome)
	}
	guest := &guestSide{conn: conn, session: sess, control: control}
	t.Cleanup(func() { conn.Close() })
	return guest, nil
}

// open opens a stream of kind with args and returns it with its answer.
func (g *guestSide) open(t *testing.T, kind string, args map[string]any) (io.ReadWriteCloser, *bufio.Reader, *session.Refusal) {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	stream, err := g.session.OpenStream(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := stream.Write(session.OpenRecord(kind, args)); err != nil {
		t.Fatal(err)
	}
	reader := bufio.NewReader(stream)
	_ = stream.SetReadDeadline(time.Now().Add(5 * time.Second))
	refusal, err := session.ReadAnswer(reader)
	_ = stream.SetReadDeadline(time.Time{})
	if err != nil {
		t.Fatal(err)
	}
	return stream, reader, refusal
}

// echo relays a megabyte through the echo entry and back.
func (g *guestSide) echo(t *testing.T) {
	t.Helper()
	stream, reader, refusal := g.open(t, session.KindConnect, map[string]any{"id": "echo"})
	if refusal != nil {
		t.Fatalf("echo refused: %v", refusal)
	}
	defer stream.Close()
	payload := make([]byte, 1<<20)
	_, _ = rand.Read(payload)
	go func() { _, _ = stream.Write(payload) }()
	got := make([]byte, len(payload))
	if _, err := io.ReadFull(reader, got); err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(got, payload) {
		t.Fatal("the relayed bytes differ")
	}
}

func TestGuestThroughTheGate(t *testing.T) {
	dir := shortTempDir(t)
	port := freePort(t)
	hub := startHub(t, dir, port)
	echoPort := echoServer(t)
	hub.records.mu.Lock()
	hub.records.tickets["ticket-agent"] = "dev-1"
	hub.records.entries["echo"] = map[string]any{"kind": "web", "device_id": "dev-1", "target": map[string]any{"open": map[string]any{"kind": "connect", "port": echoPort, "protocol": "tcp"}}}
	hub.records.entries["other"] = map[string]any{"kind": "web", "device_id": "dev-1", "target": map[string]any{"open": map[string]any{"kind": "connect", "port": echoPort, "protocol": "tcp"}}}
	hub.records.shares[shareUfrag] = shareRecord{id: shareID, ticket: shareTicket, entry: "echo"}
	hub.records.mu.Unlock()
	agent := startAgent(t, dir, echoPort)
	agentBinding, agentPsk := agent.join(t, hub, "ticket-agent", "dev-1")
	agent.dial(t, hub, agentBinding, agentPsk)
	agent.hello(t, hub, agentBinding)

	address := net.JoinHostPort("127.0.0.1", itoa(port))
	shortCtx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	if _, err := gate.Dial(shortCtx, address, gate.DialOptions{Ufrag: shareUfrag, Password: sharePassword, Fingerprint: hub.hub.Fingerprint()}); !errors.Is(err, gate.ErrStunRefused) {
		t.Fatalf("with no live share: %v, want the connection closed", err)
	}

	if answer := hub.python.command("shares_set", map[string]any{"shares": []map[string]any{{"ufrag": shareUfrag, "pwd": sharePassword}}}); answer["code"] != nil {
		t.Fatalf("shares_set %v", answer)
	}
	if _, refusal := dialGuest(t, hub, shareUfrag, sharePassword, "wrong-ticket"); refusal == nil || refusal.Code != "ticket_invalid" {
		t.Fatalf("a wrong ticket: %v", refusal)
	}

	first, refusal := dialGuest(t, hub, shareUfrag, sharePassword, shareTicket)
	if refusal != nil {
		t.Fatalf("refused %v", refusal)
	}
	first.echo(t)

	first.control.WriteFrame(session.MakeFrame(session.FrameService, map[string]any{"request": "r1", "id": "echo"}))
	reply, err := first.control.ReadFrame()
	if err != nil {
		t.Fatal(err)
	}
	if parsed := session.ParseRefused(reply); parsed.Code != "" || parsed.Params["token"] != "material" {
		t.Fatalf("reply %s", reply)
	}

	second, refusal := dialGuest(t, hub, shareUfrag, sharePassword, shareTicket)
	if refusal != nil {
		t.Fatalf("second guest refused %v", refusal)
	}
	second.echo(t)
	first.echo(t)
	time.Sleep(knock.KnockFirstByteTimeout + 500*time.Millisecond)
	first.echo(t)

	if _, _, refusal := first.open(t, session.KindConnect, map[string]any{"id": "other"}); refusal == nil || refusal.Code != "permission_denied" {
		t.Fatalf("another entry: %v", refusal)
	}
	if _, _, refusal := first.open(t, session.KindShell, map[string]any{"id": "echo"}); refusal == nil || refusal.Code != "kind_unknown" {
		t.Fatalf("a shell: %v", refusal)
	}

	plain, err := net.Dial("tcp", address)
	if err != nil {
		t.Fatal(err)
	}
	defer plain.Close()
	_, _ = plain.Write([]byte("GET / HTTP/1.1\r\nHost: hub\r\n\r\n"))
	_ = plain.SetReadDeadline(time.Now().Add(3 * time.Second))
	if n, err := plain.Read(make([]byte, 64)); n != 0 || err == nil {
		t.Fatalf("the hub wrote %d bytes to a plain connection: %v", n, err)
	}

	hub.python.command("shares_set", map[string]any{"shares": []map[string]any{}})
	shortCtx2, cancel2 := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel2()
	if _, err := gate.Dial(shortCtx2, address, gate.DialOptions{Ufrag: shareUfrag, Password: sharePassword, Fingerprint: hub.hub.Fingerprint()}); !errors.Is(err, gate.ErrStunRefused) {
		t.Fatalf("after the share ended: %v, want the connection closed", err)
	}
	first.echo(t)
}
