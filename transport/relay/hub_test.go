package relay

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"net"
	"slices"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/flynn/noise"

	"github.com/iffiX/neutrino/transport/gate"
	"github.com/iffiX/neutrino/transport/handshake"
	"github.com/iffiX/neutrino/transport/knock"
	"github.com/iffiX/neutrino/transport/session"
)

// A live share's ICE pair and ticket, and the share id its guest question
// returns.
const (
	guestUfrag    = "0123456789abcdef01234567"         // scan: allow
	guestPassword = "0123456789abcdef0123456789abcdef" // scan: allow
	guestTicket   = "share-ticket-1"
	guestShareID  = "share-1"
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
	isAway   bool
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
	if p.isAway {
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
	case "guest":
		if fields["ticket"] != guestTicket {
			return nil, session.NewRefusal("share_unknown", nil)
		}
		return map[string]any{"binding_id": guestShareID}, nil
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
	lines  *logLines
}

// logLines records the hub's log lines, each a verb and its key=value pairs.
type logLines struct {
	mu    sync.Mutex
	lines []string
}

func (l *logLines) add(verb string, fields ...string) {
	line := verb
	for i := 0; i+1 < len(fields); i += 2 {
		line += " " + fields[i] + "=" + fields[i+1]
	}
	l.mu.Lock()
	defer l.mu.Unlock()
	l.lines = append(l.lines, line)
}

// named returns the lines of one verb, in the order written.
func (l *logLines) named(verb string) []string {
	l.mu.Lock()
	defer l.mu.Unlock()
	var found []string
	for _, line := range l.lines {
		if line == verb || strings.HasPrefix(line, verb+" ") {
			found = append(found, line)
		}
	}
	return found
}

// testHold is the hold deadline of the tests' door.
const testHold = 300 * time.Millisecond

// fixedDraws are door draws that return readBytes and hold every time.
func fixedDraws(readBytes int, hold time.Duration) *knock.DoorDraws {
	return &knock.DoorDraws{
		ReadBytes: func() int { return readBytes },
		Hold:      func() time.Duration { return hold },
	}
}

func newTestHub(t *testing.T) *testHub {
	t.Helper()
	return newTestHubWith(t, fixedDraws(knock.DoorReadBytesMax, testHold), nil)
}

func newTestHubWith(t *testing.T, draws *knock.DoorDraws, memory *session.TransportMemory) *testHub {
	t.Helper()
	key, _ := handshake.GenerateKey()
	python := newFakePython()
	lines := &logLines{}
	hub, err := NewHub(HubConfig{Key: key, ListenPort: 0, Draws: draws, Memory: memory, Timings: session.Timings{KeepAliveInterval: time.Second, KeepAliveTimeout: 5 * time.Second}, Log: lines.add}, python)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(hub.Close)
	return &testHub{hub: hub, python: python, key: key, lines: lines}
}

// TestMemoryCapLineAtMostOnceAMinute checks that the memory cap's line is
// written at the first reset, none within the minute after, and the next one
// with the count of resets since the line before.
func TestMemoryCapLineAtMostOnceAMinute(t *testing.T) {
	key, _ := handshake.GenerateKey()
	var clock atomic.Int64
	clock.Store(time.Unix(1_000_000, 0).UnixNano())
	lines := &logLines{}
	hub, err := NewHub(HubConfig{Key: key, Now: func() time.Time { return time.Unix(0, clock.Load()) }, Log: lines.add}, newFakePython())
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(hub.Close)

	for _, step := range []time.Duration{0, 30 * time.Second, 29 * time.Second, time.Second, RelayMemoryLogInterval} {
		clock.Add(int64(step))
		hub.logMemoryRefused()
	}
	want := []string{"memory_cap_refused count=1", "memory_cap_refused count=3", "memory_cap_refused count=1"}
	if got := lines.named("memory_cap_refused"); !slices.Equal(got, want) {
		t.Fatalf("lines %q, want %q", got, want)
	}
}

// TestControlUnavailableNamesItsRetry checks that a bound peer knocking
// while the Python is away reads refused control_unavailable with
// retry_after_s 5, and is admitted once the Python is back.
func TestControlUnavailableNamesItsRetry(t *testing.T) {
	hub := newTestHub(t)
	address := hub.listen(t)
	agent := newPeer(t, hub, "dev7", "agent")
	hub.python.mu.Lock()
	hub.python.isAway = true
	hub.python.mu.Unlock()

	c := agent.connect(t, address, hub.key.Public, agent.psk(), false)
	if !c.result.IsRefusal {
		t.Fatal("an away Python did not give a refusal under the zero psk")
	}
	kind, frame := c.readFrame(t)
	refusal := session.ParseRefused(frame)
	if kind != session.FrameRefused || refusal.Code != session.CodeControlUnavailable || refusal.Params["retry_after_s"] != RelayControlRetryAfter.Seconds() {
		t.Fatalf("away python: %s %s", kind, frame)
	}

	hub.python.mu.Lock()
	hub.python.isAway = false
	hub.python.mu.Unlock()
	agent.admit(t, hub, address, "dev7")
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
	hub := newTestHub(t)
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
	hub := newTestHub(t)
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
	quiet, _ := NewHub(HubConfig{Key: hub.key, Draws: fixedDraws(knock.DoorReadBytesMax, testHold), Timings: session.Timings{KeepAliveInterval: time.Second, KeepAliveTimeout: 5 * time.Second}}, hub.python)
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

func TestReplayedKnockIsSilence(t *testing.T) {
	hub := newTestHub(t)
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
	hub := newTestHub(t)
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

func TestReplacedByASecondSession(t *testing.T) {
	hub := newTestHub(t)
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

// serveGuestAccepted runs the door's guest path on conn as for a connection
// the hub accepted age ago, with its hold deadline at knock.DoorHoldMax.
func (h *testHub) serveGuestAccepted(conn net.Conn, age time.Duration) {
	acceptedAt := time.Now().Add(-age)
	entry, _ := h.hub.ledger.Accept(acceptedAt)
	closer := newDoorCloser(conn)
	d := &door{
		entry: entry, closer: closer, reader: &doorReader{conn: conn}, acceptedAt: acceptedAt,
		holdUntil: acceptedAt.Add(knock.DoorHoldMax), readBytes: knock.DoorReadBytesMin,
	}
	d.admission = time.AfterFunc(knock.AdmissionTimeout, func() { closer.fire() })
	defer func() {
		h.hub.ledger.Leave(entry)
		if !d.isHandedOver {
			d.admission.Stop()
			closer.fire()
		}
	}()
	head := make([]byte, knock.KnockMagicBytes)
	if _, err := io.ReadFull(d.reader, head); err != nil {
		return
	}
	if h.hub.serveGuest(d, conn, head, PeerIP(conn.RemoteAddr()), RelayListenerMain) {
		h.hub.ledger.Refuse(entry)
	}
}

// TestGuestHandshakeTime checks the guest path's handshake time from the
// accept. A guest accepted past HandshakeTimeout still gets its share's
// accept, and the hub refuses a guest accepted past GateHandshakeTimeout
// with nothing written.
func TestGuestHandshakeTime(t *testing.T) {
	certificate, err := gate.LoadOrCreateCertificate(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	key, _ := handshake.GenerateKey()
	python := newFakePython()
	hub, err := NewHub(HubConfig{Key: key, Certificate: &certificate, Timings: session.Timings{KeepAliveInterval: time.Second, KeepAliveTimeout: 5 * time.Second}}, python)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(hub.Close)
	hub.SetShares([]gate.Share{{Ufrag: guestUfrag, Password: guestPassword}})
	test := &testHub{hub: hub, python: python, key: key}
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { listener.Close() })

	for _, step := range []struct {
		age    time.Duration
		isOpen bool
	}{
		{age: knock.HandshakeTimeout + 5*time.Second, isOpen: true},
		{age: gate.GateHandshakeTimeout + time.Second, isOpen: false},
	} {
		go func() {
			conn, err := listener.Accept()
			if err != nil {
				return
			}
			test.serveGuestAccepted(conn, step.age)
		}()
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		channel, err := gate.Dial(ctx, listener.Addr().String(), gate.DialOptions{Ufrag: guestUfrag, Password: guestPassword, Fingerprint: hub.Fingerprint()})
		cancel()
		if !step.isOpen {
			if !errors.Is(err, gate.ErrStunRefused) {
				t.Fatalf("accepted %s ago: %v, want the connection closed", step.age, err)
			}
			continue
		}
		if err != nil {
			t.Fatalf("accepted %s ago: %v", step.age, err)
		}
		if _, err := channel.Write(gate.GuestOpenRecord(gate.GuestOpen{Protocol: knock.PROTOCOL, Ticket: guestTicket})); err != nil {
			t.Fatal(err)
		}
		message := make([]byte, gate.GateGuestOpenBytesMax)
		_ = channel.SetReadDeadline(time.Now().Add(5 * time.Second))
		n, err := channel.ReadMessage(message)
		if err != nil {
			t.Fatalf("accepted %s ago: %v", step.age, err)
		}
		id, refusal, err := gate.ParseGuestAnswer(message[:n])
		if err != nil || refusal != nil || id != guestShareID {
			t.Fatalf("accepted %s ago: answer %q %v %v", step.age, id, refusal, err)
		}
		channel.Close()
	}
}

// slowConn writes at most bytesPerSecond, as a slow line does.
type slowConn struct {
	net.Conn
	bytesPerSecond int
}

func (c *slowConn) Write(p []byte) (int, error) {
	time.Sleep(time.Duration(len(p)) * time.Second / time.Duration(c.bytesPerSecond))
	return c.Conn.Write(p)
}

// TestSessionCloseReachesASlowGuest checks that a guest on a slow line reads
// its refused frame behind the bytes already queued for it, and that the
// session's streams close at the refusal.
func TestSessionCloseReachesASlowGuest(t *testing.T) {
	certificate, err := gate.LoadOrCreateCertificate(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	key, _ := handshake.GenerateKey()
	python := newFakePython()
	hub, err := NewHub(HubConfig{Key: key, Certificate: &certificate, Timings: session.DefaultTimings}, python)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(hub.Close)
	hub.SetShares([]gate.Share{{Ufrag: guestUfrag, Password: guestPassword}})
	test := &testHub{hub: hub, python: python, key: key}
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { listener.Close() })
	go func() {
		conn, err := listener.Accept()
		if err != nil {
			return
		}
		test.serveGuestAccepted(&slowConn{Conn: conn, bytesPerSecond: 64 * 1024}, 0)
	}()
	app, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { app.Close() })
	appClosed := make(chan time.Time, 1)
	go func() {
		conn, err := app.Accept()
		if err != nil {
			return
		}
		go func() { _, _ = conn.Write(make([]byte, 1<<20)) }()
		_, _ = io.Copy(io.Discard, conn)
		appClosed <- time.Now()
	}()
	python.mu.Lock()
	python.entries["connect:app"] = entryAnswer{answer: map[string]any{
		"kind": "web", "device_id": "",
		"target": map[string]any{"address": "127.0.0.1", "port": app.Addr().(*net.TCPAddr).Port, "protocol": "tcp"},
	}}
	python.mu.Unlock()

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	channel, err := gate.Dial(ctx, listener.Addr().String(), gate.DialOptions{Ufrag: guestUfrag, Password: guestPassword, Fingerprint: hub.Fingerprint()})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { channel.Close() })
	if _, err := channel.Write(gate.GuestOpenRecord(gate.GuestOpen{Protocol: knock.PROTOCOL, Ticket: guestTicket})); err != nil {
		t.Fatal(err)
	}
	message := make([]byte, gate.GateGuestOpenBytesMax)
	n, err := channel.ReadMessage(message)
	if err != nil {
		t.Fatal(err)
	}
	if id, refusal, err := gate.ParseGuestAnswer(message[:n]); err != nil || refusal != nil || id != guestShareID {
		t.Fatalf("answer %q %v %v", id, refusal, err)
	}
	sess, err := session.NewPeerSession(channel, session.DefaultTimings)
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
	guest := &connected{session: sess, control: session.NewControlStream(stream)}
	if refusal, err := guest.control.ReadAnswer(); err != nil || refusal != nil {
		t.Fatalf("control stream answer: %v %v", refusal, err)
	}
	guest.hello(t, guestShareID, RelayRoleGuest)
	sessionID := python.waitEvent(t, "session_open")["session"].(string)
	python.waitFrame(t, session.FrameHello)
	welcome := session.MakeFrame(session.FrameWelcome, map[string]any{"id": "hub", "protocol": knock.PROTOCOL, "role": "hub", "name": "h", "software": "neutrino_hub/0.6.0", "time": 1.5})
	if err := hub.WriteFrame(sessionID, welcome, false); err != nil {
		t.Fatal(err)
	}
	if kind, _ := guest.readFrame(t); kind != session.FrameWelcome {
		t.Fatalf("first frame %s, want welcome", kind)
	}

	record, refusal := openStream(t, guest, session.KindConnect, map[string]any{"id": "app"})
	if refusal != nil {
		t.Fatalf("refused %v", refusal)
	}
	if _, err := io.ReadFull(record.Reader, make([]byte, 1024)); err != nil {
		t.Fatal(err)
	}
	go func() { _, _ = io.Copy(io.Discard, record.Reader) }()
	closedAt := time.Now()
	if err := hub.SessionClose(sessionID, "share_unknown", nil); err != nil {
		t.Fatal(err)
	}
	kind, frame := guest.readFrame(t)
	if kind != session.FrameRefused || session.ParseRefused(frame).Code != "share_unknown" {
		t.Fatalf("got %s %s, want refused share_unknown", kind, frame)
	}
	if read := time.Since(closedAt); read < RelayEndGrace {
		t.Fatalf("the refused frame came %s after the close, before the queued bytes", read)
	}
	select {
	case at := <-appClosed:
		if at.Sub(closedAt) > time.Second {
			t.Fatalf("the app's stream closed %s after the refusal", at.Sub(closedAt))
		}
	default:
		t.Fatal("the app's stream is still open")
	}
	ended := python.waitEvent(t, "session_end")
	if ended["session"] != sessionID || ended["reason"] != EndClosedByHub {
		t.Fatalf("ended %v", ended)
	}
}
