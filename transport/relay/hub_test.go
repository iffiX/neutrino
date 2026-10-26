package relay

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"net"
	"sync"
	"testing"
	"time"

	"github.com/flynn/noise"

	"github.com/iffiX/neutrino/transport/handshake"
	"github.com/iffiX/neutrino/transport/knock"
	"github.com/iffiX/neutrino/transport/session"
)

// fakePython answers the hub's questions from tables and records its events.
type fakePython struct {
	mu       sync.Mutex
	bindings map[string]binding // by public key hex
	tickets  map[string]string  // ticket -> binding id
	entries  map[string]entryAnswer
	events   chan map[string]any
	frames   chan frameEvent
	isSilent bool
}

type binding struct {
	id   string
	role string
	psk  string
}

type entryAnswer struct {
	refusal *session.Refusal
	answer  map[string]any
}

type frameEvent struct {
	session string
	frame   []byte
}

func newFakePython() *fakePython {
	return &fakePython{
		bindings: make(map[string]binding),
		tickets:  make(map[string]string),
		entries:  make(map[string]entryAnswer),
		events:   make(chan map[string]any, 64),
		frames:   make(chan frameEvent, 64),
	}
}

func (p *fakePython) Ask(ctx context.Context, question string, fields map[string]any) (map[string]any, error) {
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.isSilent {
		<-ctx.Done()
		return nil, ErrControlUnavailable
	}
	switch question {
	case "peer":
		found, ok := p.bindings[fields["public_key"].(string)]
		if !ok {
			return nil, session.NewRefusal(session.CodeBindingUnknown, nil)
		}
		if found.role != fields["role"].(string) {
			return nil, session.NewRefusal("role_mismatch", nil)
		}
		return map[string]any{"binding_id": found.id, "role": found.role, "psk": found.psk}, nil
	case "ticket":
		id, ok := p.tickets[fields["ticket"].(string)]
		if !ok {
			return nil, session.NewRefusal("ticket_spent", nil)
		}
		delete(p.tickets, fields["ticket"].(string))
		p.bindings[fields["public_key"].(string)] = binding{id: id, role: fields["role"].(string), psk: hex.EncodeToString(make([]byte, 32))}
		return map[string]any{"binding_id": id, "token": "tok-" + id}, nil
	case "entry":
		open := fields["open"].(json.RawMessage)
		var body struct {
			ID   string `json:"id"`
			Kind string `json:"kind"`
		}
		_ = json.Unmarshal(open, &body)
		answer, ok := p.entries[body.Kind+":"+body.ID]
		if !ok {
			return nil, session.NewRefusal("service_unknown", map[string]any{"service_id": body.ID})
		}
		if answer.refusal != nil {
			return nil, answer.refusal
		}
		return answer.answer, nil
	case "token":
		return map[string]any{"params": map[string]any{"token": "material"}}, nil
	}
	return nil, errors.New("unknown question")
}

func (p *fakePython) Event(event string, fields map[string]any) {
	fields["event"] = event
	p.events <- fields
}

func (p *fakePython) Frame(sessionID string, frame []byte) {
	p.frames <- frameEvent{session: sessionID, frame: frame}
}

func (p *fakePython) waitEvent(t *testing.T, event string) map[string]any {
	t.Helper()
	for {
		select {
		case got := <-p.events:
			if got["event"] == event {
				return got
			}
		case <-time.After(5 * time.Second):
			t.Fatalf("no %s event", event)
		}
	}
}

func (p *fakePython) waitFrame(t *testing.T, frameType string) frameEvent {
	t.Helper()
	for {
		select {
		case got := <-p.frames:
			if kind, _ := session.FrameType(got.frame); kind == frameType {
				return got
			}
		case <-time.After(5 * time.Second):
			t.Fatalf("no %s frame", frameType)
		}
	}
}

// testHub is a hub on loopback with a fake Python.
type testHub struct {
	hub    *Hub
	python *fakePython
	key    noise.DHKey
}

func newTestHub(t *testing.T, legacyPort int) *testHub {
	t.Helper()
	key, _ := handshake.GenerateKey()
	python := newFakePython()
	hub, err := NewHub(HubConfig{Key: key, ListenPort: 0, LegacyTLSPort: legacyPort, Timings: session.Timings{KeepAliveInterval: time.Second, KeepAliveTimeout: 5 * time.Second}}, python)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(hub.Close)
	return &testHub{hub: hub, python: python, key: key}
}

// listen opens one loopback listener served by the hub's door.
func (h *testHub) listen(t *testing.T) string {
	t.Helper()
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { listener.Close() })
	go func() {
		for {
			conn, err := listener.Accept()
			if err != nil {
				return
			}
			go h.hub.ServeConn(conn, RelayListenerMain)
		}
	}()
	return session.AddressScheme + listener.Addr().String()
}

// peer is one bound or joining peer of the tests.
type peer struct {
	key   noise.DHKey
	role  string
	token string
}

func newPeer(t *testing.T, hub *testHub, id, role string) *peer {
	t.Helper()
	key, _ := handshake.GenerateKey()
	token := "token-" + id
	sum := sha256.Sum256([]byte(token))
	hub.python.mu.Lock()
	hub.python.bindings[hex.EncodeToString(key.Public)] = binding{id: id, role: role, psk: hex.EncodeToString(sum[:])}
	hub.python.mu.Unlock()
	return &peer{key: key, role: role, token: token}
}

func (p *peer) psk() []byte {
	sum := sha256.Sum256([]byte(p.token))
	return sum[:]
}

// connected is a peer's live session with its control stream.
type connected struct {
	session *session.Session
	control *session.ControlStream
	result  *session.DialResult
}

// connect dials the hub, opens the control stream and reads its accept.
func (p *peer) connect(t *testing.T, address string, hubPublic []byte, psk []byte, isJoin bool) *connected {
	t.Helper()
	result, err := session.Dial(context.Background(), address, session.DialOptions{
		Static: p.key, HubPublic: hubPublic, Psk: psk, Protocol: knock.PROTOCOL, Role: p.role, IsJoin: isJoin,
	})
	if err != nil {
		t.Fatal(err)
	}
	sess, err := session.NewPeerSession(result.Conn, session.Timings{KeepAliveInterval: time.Second, KeepAliveTimeout: 5 * time.Second})
	if err != nil {
		t.Fatal(err)
	}
	stream, err := sess.OpenStream(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if _, err := stream.Write(session.OpenRecord(session.KindControl, nil)); err != nil {
		t.Fatal(err)
	}
	control := session.NewControlStream(stream)
	if refusal, err := control.ReadAnswer(); err != nil || refusal != nil {
		t.Fatalf("control stream answer: %v %v", refusal, err)
	}
	t.Cleanup(func() { sess.Close() })
	return &connected{session: sess, control: control, result: result}
}

func (c *connected) hello(t *testing.T, id string, role string) {
	t.Helper()
	frame := session.MakeFrame(session.FrameHello, map[string]any{"id": id, "protocol": knock.PROTOCOL, "role": role, "name": "n", "software": "neutrino_agent/0.6.0"})
	if err := c.control.WriteFrame(frame); err != nil {
		t.Fatal(err)
	}
}

func (c *connected) readFrame(t *testing.T) (string, []byte) {
	t.Helper()
	frame, err := c.control.ReadFrame()
	if err != nil {
		t.Fatal(err)
	}
	kind, _ := session.FrameType(frame)
	return kind, frame
}

// admit connects a bound peer and walks it through hello and welcome.
func (p *peer) admit(t *testing.T, hub *testHub, address, id string) (*connected, string) {
	t.Helper()
	c := p.connect(t, address, hub.key.Public, p.psk(), false)
	if c.result.IsRefusal {
		t.Fatal("a bound peer's handshake read as a refusal")
	}
	c.hello(t, id, p.role)
	opened := hub.python.waitEvent(t, "session_open")
	sessionID := opened["session"].(string)
	if opened["address"] != "127.0.0.1" || opened["local_address"] != "127.0.0.1" || opened["listener"] != RelayListenerMain {
		t.Fatalf("session_open %v", opened)
	}
	hub.python.waitFrame(t, session.FrameHello)
	welcome := session.MakeFrame(session.FrameWelcome, map[string]any{"id": "hub", "protocol": knock.PROTOCOL, "role": "hub", "name": "h", "software": "neutrino_hub/0.6.0", "time": 1.5})
	if err := hub.hub.WriteFrame(sessionID, welcome, false); err != nil {
		t.Fatal(err)
	}
	if kind, _ := c.readFrame(t); kind != session.FrameWelcome {
		t.Fatalf("first frame %s, want welcome", kind)
	}
	return c, sessionID
}

func TestAdmissionAndFrames(t *testing.T) {
	hub := newTestHub(t, 0)
	address := hub.listen(t)
	agent := newPeer(t, hub, "dev1", "agent")
	c, sessionID := agent.admit(t, hub, address, "dev1")

	_ = c.control.WriteFrame(session.MakeFrame(session.FramePing, map[string]any{"nonce": "abc"}))
	kind, frame := c.readFrame(t)
	if kind != session.FramePong || string(frame) != `{"nonce":"abc","type":"pong"}` {
		t.Fatalf("pong %s %s", kind, frame)
	}
	_ = c.control.WriteFrame(session.MakeFrame(session.FrameReport, map[string]any{"state_hash": "x"}))
	report := hub.python.waitFrame(t, session.FrameReport)
	if report.session != sessionID {
		t.Fatalf("report on %s, want %s", report.session, sessionID)
	}
	if err := hub.hub.WriteFrame(sessionID, session.MakeFrame(session.FrameState, map[string]any{"hash": "y"}), false); err != nil {
		t.Fatal(err)
	}
	if kind, _ := c.readFrame(t); kind != session.FrameState {
		t.Fatalf("frame %s, want state", kind)
	}
	if err := hub.hub.SessionClose(sessionID, "binding_unknown", nil); err != nil {
		t.Fatal(err)
	}
	kind, frame = c.readFrame(t)
	if kind != session.FrameRefused || session.ParseRefused(frame).Code != "binding_unknown" {
		t.Fatalf("frame %s %s", kind, frame)
	}
	ended := hub.python.waitEvent(t, "session_end")
	if ended["session"] != sessionID {
		t.Fatalf("ended %v", ended)
	}
	if _, err := hub.hub.Session(sessionID); !errors.Is(err, ErrSessionUnknown) {
		t.Fatal("the ended session is still held")
	}
}

func TestRefusalsAtTheDoor(t *testing.T) {
	hub := newTestHub(t, 0)
	address := hub.listen(t)
	unknown := &peer{role: "client"}
	unknown.key, _ = handshake.GenerateKey()
	token := make([]byte, 32)
	token[0] = 1
	c := unknown.connect(t, address, hub.key.Public, token, false)
	if !c.result.IsRefusal {
		t.Fatal("an unknown key's message 2 did not open under the zero psk")
	}
	kind, frame := c.readFrame(t)
	if kind != session.FrameRefused || session.ParseRefused(frame).Code != session.CodeBindingUnknown {
		t.Fatalf("frame %s %s", kind, frame)
	}

	agent := newPeer(t, hub, "dev2", "agent")
	c = agent.connect(t, address, hub.key.Public, agent.psk(), false)
	c.hello(t, "another", "agent")
	kind, frame = c.readFrame(t)
	if kind != session.FrameRefused || session.ParseRefused(frame).Code != session.CodeHelloInvalid {
		t.Fatalf("hello naming another binding: %s %s", kind, frame)
	}

	c = agent.connect(t, address, hub.key.Public, agent.psk(), false)
	_ = c.control.WriteFrame(session.MakeFrame(session.FrameReport, nil))
	kind, frame = c.readFrame(t)
	if kind != session.FrameRefused || session.ParseRefused(frame).Code != session.CodeHelloInvalid {
		t.Fatalf("a report as the first frame: %s %s", kind, frame)
	}

	hub.python.mu.Lock()
	hub.python.isSilent = true
	hub.python.mu.Unlock()
	hub.hub.handOff.timeout = 100 * time.Millisecond
	quiet, _ := NewHub(HubConfig{Key: hub.key, Timings: session.Timings{KeepAliveInterval: time.Second, KeepAliveTimeout: 5 * time.Second}}, hub.python)
	defer quiet.Close()
	quietListener, _ := net.Listen("tcp", "127.0.0.1:0")
	defer quietListener.Close()
	go func() {
		conn, err := quietListener.Accept()
		if err == nil {
			quiet.ServeConn(conn, RelayListenerMain)
		}
	}()
	started := time.Now()
	c = agent.connect(t, session.AddressScheme+quietListener.Addr().String(), hub.key.Public, agent.psk(), false)
	if !c.result.IsRefusal {
		t.Fatal("a silent Python did not give a refusal under the zero psk")
	}
	kind, frame = c.readFrame(t)
	if kind != session.FrameRefused || session.ParseRefused(frame).Code != session.CodeControlUnavailable {
		t.Fatalf("silent python: %s %s", kind, frame)
	}
	if time.Since(started) < ControlQuestionTimeout {
		t.Fatal("control_unavailable came before the question's timeout")
	}
}

func TestSilenceForWrongKnocks(t *testing.T) {
	hub := newTestHub(t, 0)
	address := hub.listen(t)
	hostPort, _ := session.ParseAddress(address)
	cases := []struct {
		name  string
		bytes []byte
	}{
		{"a TLS byte while the legacy listener is off", []byte{22, 3, 1, 0, 5, 1, 2, 3, 4, 5}},
		{"an unknown version", []byte{5, 0, 3, 1, 2, 3}},
		{"a knock with a wrong mac1", func() []byte {
			other, _ := handshake.GenerateKey()
			raw, _ := knock.Encode([]byte("message"), other.Public, nil)
			return raw
		}()},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			conn, err := net.Dial("tcp", hostPort)
			if err != nil {
				t.Fatal(err)
			}
			defer conn.Close()
			_, _ = conn.Write(c.bytes)
			_ = conn.SetReadDeadline(time.Now().Add(3 * time.Second))
			buffer := make([]byte, 1)
			n, err := conn.Read(buffer)
			if n != 0 || !errors.Is(err, io.EOF) {
				t.Fatalf("read %d bytes, %v; want silence and a close", n, err)
			}
		})
	}
	if hub.hub.Ledger().Waiting() != 0 {
		t.Fatalf("%d connections still counted", hub.hub.Ledger().Waiting())
	}
}

func TestReplayedKnockIsSilence(t *testing.T) {
	hub := newTestHub(t, 0)
	address := hub.listen(t)
	agent := newPeer(t, hub, "dev3", "agent")
	fixed := time.Unix(1700000000, 0)
	options := session.DialOptions{Static: agent.key, HubPublic: hub.key.Public, Psk: agent.psk(), Protocol: knock.PROTOCOL, Role: "agent", Timeout: 2 * time.Second, Now: func() time.Time { return fixed }}
	first, err := session.Dial(context.Background(), address, options)
	if err != nil {
		t.Fatal(err)
	}
	first.Conn.Close()
	if _, err := session.Dial(context.Background(), address, options); err == nil || errors.Is(err, handshake.ErrHubUntrusted) {
		t.Fatalf("a replayed time was answered: %v", err)
	}
	options.Now = func() time.Time { return fixed.Add(time.Second) }
	later, err := session.Dial(context.Background(), address, options)
	if err != nil {
		t.Fatal(err)
	}
	later.Conn.Close()
}

func TestJoin(t *testing.T) {
	hub := newTestHub(t, 0)
	address := hub.listen(t)
	hub.python.mu.Lock()
	hub.python.tickets["ticket-1"] = "dev9"
	hub.python.mu.Unlock()
	joiner := &peer{role: "agent"}
	joiner.key, _ = handshake.GenerateKey()
	c := joiner.connect(t, address, hub.key.Public, handshake.ZeroPsk, true)
	join := session.MakeFrame(session.FrameJoin, map[string]any{"ticket": "ticket-1", "role": "agent", "protocol": knock.PROTOCOL, "machine_id": "m", "name": "n", "software": "neutrino_agent/0.6.0", "platform": map[string]any{"os": "linux"}})
	_ = c.control.WriteFrame(join)
	kind, frame := c.readFrame(t)
	if kind != session.FrameJoined {
		t.Fatalf("frame %s %s", kind, frame)
	}
	var joined struct {
		ID    string `json:"id"`
		Token string `json:"token"`
	}
	_ = json.Unmarshal(frame, &joined)
	if joined.ID != "dev9" || joined.Token != "tok-dev9" {
		t.Fatalf("joined %+v", joined)
	}
	select {
	case <-c.session.CloseChan():
	case <-time.After(5 * time.Second):
		t.Fatal("the session stayed open after joined")
	}

	c = joiner.connect(t, address, hub.key.Public, handshake.ZeroPsk, true)
	_ = c.control.WriteFrame(join)
	kind, frame = c.readFrame(t)
	if kind != session.FrameRefused || session.ParseRefused(frame).Code != "ticket_spent" {
		t.Fatalf("second join: %s %s", kind, frame)
	}
}

func TestLegacyHandOff(t *testing.T) {
	legacy, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer legacy.Close()
	go func() {
		conn, err := legacy.Accept()
		if err != nil {
			return
		}
		defer conn.Close()
		buffer := make([]byte, 5)
		if _, err := io.ReadFull(conn, buffer); err == nil {
			_, _ = conn.Write(append([]byte("tls:"), buffer...))
		}
	}()
	hub := newTestHub(t, legacy.Addr().(*net.TCPAddr).Port)
	address := hub.listen(t)
	hostPort, _ := session.ParseAddress(address)
	conn, err := net.Dial("tcp", hostPort)
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	_, _ = conn.Write([]byte{22, 3, 1, 0, 1})
	buffer := make([]byte, 9)
	if _, err := io.ReadFull(conn, buffer); err != nil || string(buffer) != "tls:\x16\x03\x01\x00\x01" {
		t.Fatalf("legacy answer %q %v", buffer, err)
	}
}

func TestReplacedByASecondSession(t *testing.T) {
	hub := newTestHub(t, 0)
	address := hub.listen(t)
	agent := newPeer(t, hub, "dev4", "agent")
	first, firstID := agent.admit(t, hub, address, "dev4")
	_, secondID := agent.admit(t, hub, address, "dev4")
	kind, frame := first.readFrame(t)
	if kind != session.FrameRefused || session.ParseRefused(frame).Code != session.CodeReplaced {
		t.Fatalf("first session got %s %s", kind, frame)
	}
	ended := hub.python.waitEvent(t, "session_end")
	if ended["session"] != firstID || ended["reason"] != EndReplaced {
		t.Fatalf("ended %v", ended)
	}
	if _, err := hub.hub.Session(secondID); err != nil {
		t.Fatal("the second session is gone")
	}
}
