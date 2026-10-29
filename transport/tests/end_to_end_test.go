package tests

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"net"
	"os"
	"path/filepath"
	"strconv"
	"sync"
	"syscall"
	"testing"
	"time"

	"github.com/iffiX/neutrino/transport/control"
	"github.com/iffiX/neutrino/transport/gate"
	"github.com/iffiX/neutrino/transport/handshake"
	"github.com/iffiX/neutrino/transport/knock"
	"github.com/iffiX/neutrino/transport/relay"
	"github.com/iffiX/neutrino/transport/session"
)

const (
	hubSecret    = "0000000000000000000000000000000000000000000000000000000000000001"
	agentSecret  = "0000000000000000000000000000000000000000000000000000000000000002"
	clientSecret = "0000000000000000000000000000000000000000000000000000000000000003"
)

var timings = session.Timings{KeepAliveInterval: time.Second, KeepAliveTimeout: 5 * time.Second}

// doorHold is the hold deadline of the tests' hubs.
const doorHold = 300 * time.Millisecond

// wsaConnReset is WSAECONNRESET, what Winsock answers for a reset.
const wsaConnReset = syscall.Errno(10054)

// isReset reports whether a read's error is the peer's reset.
func isReset(err error) bool {
	return errors.Is(err, syscall.ECONNRESET) || errors.Is(err, wsaConnReset)
}

// doorDraws are the tests' door draws: the longest read and doorHold.
var doorDraws = knock.DoorDraws{
	ReadBytes: func() int { return knock.DoorReadBytesMax },
	Hold:      func() time.Duration { return doorHold },
}

// shareRecord is one Web share as the faked hub Python keeps it: its id,
// its ticket and the one entry it opens.
type shareRecord struct {
	id     string
	ticket string
	entry  string
}

// hubRecords is the faked hub Python's memory: bindings by key, tickets,
// the entries it publishes and the shares by ufrag.
type hubRecords struct {
	mu       sync.Mutex
	bindings map[string]map[string]any
	tickets  map[string]string
	entries  map[string]map[string]any
	sessions map[string]string // binding id -> session id
	shares   map[string]shareRecord
}

func newHubRecords() *hubRecords {
	return &hubRecords{
		bindings: make(map[string]map[string]any),
		tickets:  make(map[string]string),
		entries:  make(map[string]map[string]any),
		sessions: make(map[string]string),
		shares:   make(map[string]shareRecord),
	}
}

// shareOf is the share a binding id names, if any.
func (r *hubRecords) shareOf(bindingID string) (shareRecord, bool) {
	for _, share := range r.shares {
		if share.id == bindingID {
			return share, true
		}
	}
	return shareRecord{}, false
}

func (r *hubRecords) answer(question string, fields map[string]any) map[string]any {
	r.mu.Lock()
	defer r.mu.Unlock()
	switch question {
	case "peer":
		key, _ := fields["public_key"].(string)
		found, ok := r.bindings[key]
		if !ok {
			return map[string]any{"code": "binding_unknown", "params": map[string]any{}}
		}
		return map[string]any{"binding_id": found["id"], "role": found["role"], "psk": found["psk"]}
	case "ticket":
		ticket, _ := fields["ticket"].(string)
		id, ok := r.tickets[ticket]
		if !ok {
			return map[string]any{"code": "ticket_spent", "params": map[string]any{}}
		}
		delete(r.tickets, ticket)
		token := "token-" + id
		sum := sha256.Sum256([]byte(token))
		key, _ := fields["public_key"].(string)
		r.bindings[key] = map[string]any{"id": id, "role": fields["role"], "psk": hex.EncodeToString(sum[:])}
		return map[string]any{"binding_id": id, "token": token}
	case "guest":
		ufrag, _ := fields["share"].(string)
		share, ok := r.shares[ufrag]
		if !ok {
			return map[string]any{"code": "share_unknown", "params": map[string]any{}}
		}
		if protocol, _ := fields["protocol"].(float64); int(protocol) != knock.PROTOCOL {
			return map[string]any{"code": "protocol_unsupported", "params": map[string]any{"protocol": protocol}}
		}
		if ticket, _ := fields["ticket"].(string); ticket != share.ticket {
			return map[string]any{"code": "ticket_invalid", "params": map[string]any{}}
		}
		return map[string]any{"binding_id": share.id}
	case "entry":
		open, _ := fields["open"].(map[string]any)
		id, _ := open["id"].(string)
		entry, ok := r.entries[id]
		if !ok {
			return map[string]any{"code": "service_unknown", "params": map[string]any{"service_id": id}}
		}
		bindingID, _ := fields["binding_id"].(string)
		if share, isShare := r.shareOf(bindingID); isShare && share.entry != id {
			return map[string]any{"code": "permission_denied", "params": map[string]any{"kind": entry["kind"]}}
		}
		answer := map[string]any{"kind": entry["kind"], "device_id": entry["device_id"]}
		target := map[string]any{}
		for key, value := range entry["target"].(map[string]any) {
			target[key] = value
		}
		if device, ok := entry["device_id"].(string); ok && device != "" {
			sessionID, online := r.sessions[device]
			if !online {
				return map[string]any{"code": "agent_offline", "params": map[string]any{"device": device}}
			}
			target["session"] = sessionID
		}
		answer["target"] = target
		return answer
	case "token":
		return map[string]any{"params": map[string]any{"token": "material"}}
	}
	return map[string]any{"code": "question_unknown", "params": map[string]any{}}
}

// hubSide is a hub transport with its faked Python.
type hubSide struct {
	hub     *relay.Hub
	control *control.HubControl
	python  *pythonSide
	records *hubRecords
	port    int
	keyHex  string
}

func startHub(t *testing.T, dir string, port int) *hubSide {
	t.Helper()
	keyDir := filepath.Join(dir, "transport")
	key, err := relay.LoadOrCreateKey(keyDir)
	if err != nil {
		t.Fatal(err)
	}
	socket := filepath.Join(dir, "hub.sock")
	listener, err := control.Listen(socket, false)
	if err != nil {
		t.Fatal(err)
	}
	certificate, err := gate.LoadOrCreateCertificate(keyDir)
	if err != nil {
		t.Fatal(err)
	}
	hubControl := control.NewHubControl(listener, hubSecret, keyDir, nil)
	hub, err := relay.NewHub(relay.HubConfig{Key: key, ListenPort: port, Certificate: &certificate, Timings: timings, Draws: &doorDraws}, hubControl)
	if err != nil {
		t.Fatal(err)
	}
	hubControl.SetHub(hub)
	if err := hub.Listen(); err != nil {
		t.Fatal(err)
	}
	go hubControl.Serve()
	t.Cleanup(func() {
		hub.Close()
		hubControl.Close()
	})
	records := newHubRecords()
	python := connectPython(t, socket, hubSecret, records.answer)
	return &hubSide{hub: hub, control: hubControl, python: python, records: records, port: port, keyHex: handshake.EncodeKey(key.Public)}
}

// freePort picks a port no listener holds.
func freePort(t *testing.T) int {
	t.Helper()
	listener, err := net.Listen("tcp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	port := listener.Addr().(*net.TCPAddr).Port
	listener.Close()
	return port
}

// hubAddress is the hub's address on loopback, with its scheme.
func (h *hubSide) address() string {
	return session.AddressScheme + net.JoinHostPort("127.0.0.1", itoa(h.port))
}

func itoa(n int) string {
	return strconv.Itoa(n)
}

// serveHello answers a peer's hello with welcome and records its session.
func (h *hubSide) serveHello(t *testing.T) (string, string) {
	t.Helper()
	opened := h.python.waitEvent("session_open")
	sessionID, _ := opened["session"].(string)
	bindingID, _ := opened["binding_id"].(string)
	if opened["local_address"] != "127.0.0.1" {
		t.Fatalf("session_open without the hub's address: %v", opened)
	}
	frame, line := h.python.waitFrame("hello")
	if line["session"] != sessionID || frame["id"] != bindingID {
		t.Fatalf("hello %v on %v", frame, line)
	}
	h.records.mu.Lock()
	h.records.sessions[bindingID] = sessionID
	h.records.mu.Unlock()
	h.python.frame(map[string]any{"type": "welcome", "protocol": knock.PROTOCOL, "role": "hub", "id": "hub-1", "name": "hub", "software": "neutrino_hub/0.6.0", "time": 1.0}, "session", sessionID)
	return sessionID, bindingID
}

// peerSide is an agent's or a client's transport with its faked Python.
type peerSide struct {
	python  *pythonSide
	key     string
	private string
	role    string
	// leading are the addresses an agent lists ahead of the hub's own.
	leading []string
}

func startAgent(t *testing.T, dir string, publishedPort int) *peerSide {
	t.Helper()
	socket := filepath.Join(dir, "agent.sock")
	listener, err := control.Listen(socket, false)
	if err != nil {
		t.Fatal(err)
	}
	agent := control.NewAgentControl(listener, agentSecret, timings, nil)
	go agent.Serve()
	t.Cleanup(agent.Close)
	key, _ := handshake.GenerateKey()
	answer := func(question string, fields map[string]any) map[string]any {
		if question != "port" {
			return map[string]any{"code": "question_unknown", "params": map[string]any{}}
		}
		if int(fields["port"].(float64)) != publishedPort {
			return map[string]any{"code": "port_not_published", "params": map[string]any{"port": fields["port"]}}
		}
		return map[string]any{"address": "127.0.0.1"}
	}
	return &peerSide{python: connectPython(t, socket, agentSecret, answer), key: handshake.EncodeKey(key.Public), private: handshake.EncodeKey(key.Private), role: "agent"}
}

func startClient(t *testing.T, dir string) *peerSide {
	t.Helper()
	socket := filepath.Join(dir, "client.sock")
	listener, err := control.Listen(socket, true)
	if err != nil {
		t.Fatal(err)
	}
	client := control.NewClientControl(listener, clientSecret, timings, nil)
	go client.Serve()
	t.Cleanup(client.Close)
	key, _ := handshake.GenerateKey()
	return &peerSide{python: connectPython(t, socket, clientSecret, nil), key: handshake.EncodeKey(key.Public), private: handshake.EncodeKey(key.Private), role: "client"}
}

// join enrols a peer with a ticket and returns its binding id and token psk.
func (p *peerSide) join(t *testing.T, hub *hubSide, ticket, binding string) (string, string) {
	t.Helper()
	fields := map[string]any{
		"hub_key": hub.keyHex, "private_key": p.private, "addresses": p.addresses(hub),
		"ticket": ticket, "role": p.role, "protocol": knock.PROTOCOL, "machine_id": "m-" + binding,
		"name": binding, "software": "neutrino_" + p.role + "/0.6.0", "platform": map[string]any{"os": "linux"},
	}
	if p.role == "client" {
		fields["binding"] = "pending-" + binding
	}
	answer := p.python.command("join", fields)
	if answer["code"] != nil {
		t.Fatalf("join refused: %v", answer)
	}
	token, _ := answer["token"].(string)
	id, _ := answer["binding_id"].(string)
	sum := sha256.Sum256([]byte(token))
	return id, hex.EncodeToString(sum[:])
}

// dial starts the peer's session keeping and writes hello once it opens.
func (p *peerSide) dial(t *testing.T, hub *hubSide, binding, psk string) {
	t.Helper()
	fields := map[string]any{"hub_key": hub.keyHex, "private_key": p.private, "psk": psk, "role": p.role, "protocol": knock.PROTOCOL}
	if p.role == "client" {
		fields["binding"] = binding
		fields["candidates"] = []map[string]any{{"address": hub.address(), "path": "lan"}}
	} else {
		fields["addresses"] = p.addresses(hub)
	}
	if answer := p.python.command("dial", fields); answer["code"] != nil {
		t.Fatalf("dial refused: %v", answer)
	}
}

// addresses are the addresses an agent's join and dial name.
func (p *peerSide) addresses(hub *hubSide) []string {
	return append(append([]string{}, p.leading...), hub.address())
}

// hello writes the hello once session_open came and waits for welcome.
func (p *peerSide) hello(t *testing.T, hub *hubSide, binding string) {
	t.Helper()
	opened := p.python.waitEvent("session_open")
	key := ""
	if p.role == "client" {
		key = "binding"
		if opened["binding"] != binding || opened["path"] != "lan" {
			t.Fatalf("session_open %v", opened)
		}
	} else if opened["local_address"] != "127.0.0.1" {
		t.Fatalf("session_open %v", opened)
	}
	p.python.frame(map[string]any{"type": "hello", "protocol": knock.PROTOCOL, "role": p.role, "id": binding, "name": binding, "software": "neutrino_" + p.role + "/0.6.0"}, key, binding)
	hub.serveHello(t)
	welcome, line := p.python.waitFrame("welcome")
	if welcome["id"] != "hub-1" || (p.role == "client" && line["binding"] != binding) {
		t.Fatalf("welcome %v on %v", welcome, line)
	}
}

func echoServer(t *testing.T) int {
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
			go func() {
				_, _ = io.Copy(conn, conn)
				conn.Close()
			}()
		}
	}()
	return listener.Addr().(*net.TCPAddr).Port
}

func TestEndToEnd(t *testing.T) {
	dir := shortTempDir(t)
	port := freePort(t)
	hub := startHub(t, dir, port)
	echoPort := echoServer(t)
	hub.records.mu.Lock()
	hub.records.tickets["ticket-agent"] = "dev-1"
	hub.records.tickets["ticket-client"] = "cli-1"
	hub.records.entries["echo"] = map[string]any{"kind": "port", "device_id": "dev-1", "target": map[string]any{"open": map[string]any{"kind": "connect", "port": echoPort, "protocol": "tcp"}}}
	hub.records.entries["closed"] = map[string]any{"kind": "port", "device_id": "dev-1", "target": map[string]any{"open": map[string]any{"kind": "connect", "port": 9, "protocol": "tcp"}}}
	hub.records.mu.Unlock()

	agent := startAgent(t, dir, echoPort)
	agentBinding, agentPsk := agent.join(t, hub, "ticket-agent", "dev-1")
	if agentBinding != "dev-1" {
		t.Fatalf("agent binding %q", agentBinding)
	}
	if answer := agent.python.command("join", map[string]any{"hub_key": hub.keyHex, "private_key": agent.private, "addresses": []string{hub.address()}, "ticket": "ticket-agent", "role": "agent", "protocol": knock.PROTOCOL}); answer["code"] != "ticket_spent" {
		t.Fatalf("second join %v", answer)
	}
	agent.dial(t, hub, agentBinding, agentPsk)
	agent.hello(t, hub, agentBinding)

	agent.python.frame(map[string]any{"type": "ping", "nonce": "n1"}, "", "")
	if pong, _ := agent.python.waitFrame("pong"); pong["nonce"] != "n1" {
		t.Fatalf("pong %v", pong)
	}
	agent.python.frame(map[string]any{"type": "report", "state_hash": "h"}, "", "")
	if report, _ := hub.python.waitFrame("report"); report["state_hash"] != "h" {
		t.Fatalf("report %v", report)
	}

	client := startClient(t, dir)
	clientBinding, clientPsk := client.join(t, hub, "ticket-client", "cli-1")
	client.dial(t, hub, clientBinding, clientPsk)
	client.hello(t, hub, clientBinding)

	client.python.frame(map[string]any{"type": "service", "request": "r1", "id": "echo"}, "binding", clientBinding)
	reply, _ := client.python.waitFrame("reply")
	if reply["request"] != "r1" || reply["params"].(map[string]any)["token"] != "material" {
		t.Fatalf("reply %v", reply)
	}

	forward := client.python.command("forward_start", map[string]any{"binding": clientBinding, "listen": "127.0.0.1:0", "protocol": "tcp", "open": map[string]any{"kind": "connect", "id": "echo"}})
	listen, _ := forward["listen"].(string)
	if forward["code"] != nil || listen == "" {
		t.Fatalf("forward_start %v", forward)
	}
	conn, err := net.Dial("tcp", listen)
	if err != nil {
		t.Fatal(err)
	}
	payload := make([]byte, 1<<20)
	_, _ = rand.Read(payload)
	go func() { _, _ = conn.Write(payload) }()
	got := make([]byte, len(payload))
	_ = conn.SetReadDeadline(time.Now().Add(20 * time.Second))
	if _, err := io.ReadFull(conn, got); err != nil {
		t.Fatal(err)
	}
	if string(got) != string(payload) {
		t.Fatal("the relayed bytes differ")
	}
	conn.Close()

	refusedForward := client.python.command("forward_start", map[string]any{"binding": clientBinding, "listen": "127.0.0.1:0", "protocol": "tcp", "open": map[string]any{"kind": "connect", "id": "closed"}})
	refusedConn, err := net.Dial("tcp", refusedForward["listen"].(string))
	if err != nil {
		t.Fatal(err)
	}
	_ = refusedConn.SetReadDeadline(time.Now().Add(10 * time.Second))
	if _, err := refusedConn.Read(make([]byte, 1)); err == nil {
		t.Fatal("a connection to a closed port stayed open")
	}
	refusedConn.Close()
	if answer := client.python.command("forward_stop", map[string]any{"listen": listen, "protocol": "tcp"}); answer["code"] != nil {
		t.Fatalf("forward_stop %v", answer)
	}
	if _, err := net.DialTimeout("tcp", listen, time.Second); err == nil {
		t.Fatal("the stopped forward still listens")
	}

	hub.records.mu.Lock()
	agentSession := hub.records.sessions["dev-1"]
	hub.records.mu.Unlock()
	hub.python.command("session_close", map[string]any{"session": agentSession, "code": "replaced", "params": map[string]any{}})
	ended := agent.python.waitEvent("session_end")
	if ended["code"] != "replaced" {
		t.Fatalf("session_end %v", ended)
	}
	hubEnded := hub.python.waitEvent("session_end")
	if hubEnded["session"] != agentSession {
		t.Fatalf("hub session_end %v", hubEnded)
	}
	agent.python.noEvent("session_open", 2*time.Second)

	agent.dial(t, hub, agentBinding, agentPsk)
	agent.hello(t, hub, agentBinding)
}

func TestBoundReconnectAfterAHubRestart(t *testing.T) {
	dir := shortTempDir(t)
	port := freePort(t)
	hub := startHub(t, dir, port)
	hub.records.mu.Lock()
	hub.records.tickets["ticket-agent"] = "dev-2"
	hub.records.mu.Unlock()
	agent := startAgent(t, dir, 1)
	binding, psk := agent.join(t, hub, "ticket-agent", "dev-2")
	agent.dial(t, hub, binding, psk)
	agent.hello(t, hub, binding)

	hub.records.mu.Lock()
	bindings := make(map[string]map[string]any, len(hub.records.bindings))
	for key, value := range hub.records.bindings {
		bindings[key] = value
	}
	hub.records.mu.Unlock()
	hub.hub.Close()
	hub.control.Close()
	ended := agent.python.waitEvent("session_end")
	if ended["code"] != "" {
		t.Fatalf("a dropped session ended with a code: %v", ended)
	}
	roundEnd := agent.python.waitEvent("round_end")
	if roundEnd["code"] != "hub_unreachable" || roundEnd["next_round_s"].(float64) != session.RedialBackoffMin.Seconds() {
		t.Fatalf("round_end %v", roundEnd)
	}

	restored := startHub(t, dir, port)
	if restored.keyHex != hub.keyHex {
		t.Fatal("the restarted hub lost its key")
	}
	restored.records.mu.Lock()
	restored.records.bindings = bindings
	restored.records.mu.Unlock()
	agent.hello(t, restored, binding)
}

// TestATLSRecordIsHeldThenReset checks that a 0.5 peer's TLS ClientHello
// meets silence and then a reset at the hold deadline.
func TestATLSRecordIsHeldThenReset(t *testing.T) {
	dir := shortTempDir(t)
	port := freePort(t)
	startHub(t, dir, port)
	started := time.Now()
	conn, err := net.Dial("tcp", net.JoinHostPort("127.0.0.1", itoa(port)))
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	_, _ = conn.Write([]byte{0x16, 0x03, 0x01, 0x00, 0xa5, 0x01, 0x00, 0x00, 0xa1, 0x03, 0x03})
	_ = conn.SetReadDeadline(time.Now().Add(5 * time.Second))
	n, err := conn.Read(make([]byte, 64))
	if n != 0 || !isReset(err) {
		t.Fatalf("read %d bytes, %v; want nothing and a reset", n, err)
	}
	if elapsed := time.Since(started); elapsed < doorHold-50*time.Millisecond {
		t.Fatalf("reset after %v, before the hold of %v", elapsed, doorHold)
	}
}

func TestProbe(t *testing.T) {
	dir := shortTempDir(t)
	port := freePort(t)
	hub := startHub(t, dir, port)
	static, _ := handshake.GenerateKey()
	hubPublic, _ := handshake.DecodeKey(hub.keyHex)
	result, err := session.Dial(t.Context(), hub.address(), session.DialOptions{Static: static, HubPublic: hubPublic, Psk: handshake.ZeroPsk, Protocol: knock.PROTOCOL, Role: "client", IsJoin: true, Timeout: knock.HandshakeTimeout})
	if err != nil {
		t.Fatal(err)
	}
	result.Conn.Close()
	other, _ := handshake.GenerateKey()
	if _, err := session.Dial(t.Context(), hub.address(), session.DialOptions{Static: static, HubPublic: other.Public, Psk: handshake.ZeroPsk, Protocol: knock.PROTOCOL, Role: "client", IsJoin: true, Timeout: 2 * time.Second}); err == nil {
		t.Fatal("a probe under another key was answered")
	}
}

// TestFramesAgainstTheGolden checks the frames the transport makes itself
// against the hub's golden schema.
func TestFramesAgainstTheGolden(t *testing.T) {
	data, err := os.ReadFile(filepath.Join("..", "..", "hub", "tests", "web", "channel_schema.json"))
	if err != nil {
		t.Skipf("golden schema unavailable: %v", err)
	}
	var golden struct {
		Protocol int `json:"protocol"`
		Models   map[string]struct {
			Properties map[string]any `json:"properties"`
		} `json:"models"`
	}
	if err := json.Unmarshal(data, &golden); err != nil {
		t.Fatal(err)
	}
	if golden.Protocol != knock.PROTOCOL {
		t.Fatalf("golden protocol %d, transport %d", golden.Protocol, knock.PROTOCOL)
	}
	cases := []struct {
		model string
		frame []byte
	}{
		{"ChannelPong", session.PongFrame([]byte(`{"type":"ping","nonce":"n"}`))},
		{"ChannelRefused", session.RefusedFrame(session.NewRefusal("replaced", nil))},
	}
	for _, c := range cases {
		model, ok := golden.Models[c.model]
		if !ok {
			t.Fatalf("golden has no %s", c.model)
		}
		var fields map[string]any
		_ = json.Unmarshal(c.frame, &fields)
		delete(fields, "type")
		for key := range fields {
			if _, ok := model.Properties[key]; !ok {
				t.Fatalf("%s carries %q, which %s lacks", c.frame, key, c.model)
			}
		}
	}
}

// shortTempDir is a temporary directory short enough for a Unix socket path.
func shortTempDir(t *testing.T) string {
	t.Helper()
	dir, err := os.MkdirTemp("", "nt")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { os.RemoveAll(dir) })
	return dir
}

// pendingConnection connects to a forward and checks that nothing is served
// yet: the kernel holds the connection and the transport reads nothing.
func pendingConnection(t *testing.T, listen string) net.Conn {
	t.Helper()
	conn, err := net.DialTimeout("tcp", listen, 2*time.Second)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := conn.Write([]byte("early")); err != nil {
		t.Fatal(err)
	}
	_ = conn.SetReadDeadline(time.Now().Add(500 * time.Millisecond))
	if _, err := conn.Read(make([]byte, 1)); err == nil || !errors.Is(err, os.ErrDeadlineExceeded) {
		t.Fatalf("a forward without a session served or closed the connection: %v", err)
	}
	_ = conn.SetReadDeadline(time.Time{})
	return conn
}

func TestForwardBindsBeforeTheFirstDial(t *testing.T) {
	dir := shortTempDir(t)
	port := freePort(t)
	hub := startHub(t, dir, port)
	echoPort := echoServer(t)
	hub.records.mu.Lock()
	hub.records.tickets["ticket-agent"] = "dev-3"
	hub.records.tickets["ticket-client"] = "cli-3"
	hub.records.entries["echo"] = map[string]any{"kind": "port", "device_id": "dev-3", "target": map[string]any{"open": map[string]any{"kind": "connect", "port": echoPort, "protocol": "tcp"}}}
	hub.records.mu.Unlock()

	agent := startAgent(t, dir, echoPort)
	forward := agent.python.command("forward_start", map[string]any{"listen": "127.0.0.1:0", "protocol": "tcp", "open": map[string]any{"kind": "connect", "id": "echo"}})
	agentListen, _ := forward["listen"].(string)
	if forward["code"] != nil || agentListen == "" {
		t.Fatalf("the agent's forward before any dial: %v", forward)
	}
	agentConn := pendingConnection(t, agentListen)

	client := startClient(t, dir)
	forward = client.python.command("forward_start", map[string]any{"binding": "cli-3", "listen": "127.0.0.1:0", "protocol": "tcp", "open": map[string]any{"kind": "connect", "id": "echo"}})
	clientListen, _ := forward["listen"].(string)
	if forward["code"] != nil || clientListen == "" {
		t.Fatalf("the client's forward before any dial: %v", forward)
	}
	clientConn := pendingConnection(t, clientListen)

	agentBinding, agentPsk := agent.join(t, hub, "ticket-agent", "dev-3")
	agent.dial(t, hub, agentBinding, agentPsk)
	agent.hello(t, hub, agentBinding)
	clientBinding, clientPsk := client.join(t, hub, "ticket-client", "cli-3")
	if clientBinding != "cli-3" {
		t.Fatalf("client binding %q", clientBinding)
	}
	client.dial(t, hub, clientBinding, clientPsk)
	client.hello(t, hub, clientBinding)

	for name, conn := range map[string]net.Conn{"agent": agentConn, "client": clientConn} {
		_ = conn.SetReadDeadline(time.Now().Add(10 * time.Second))
		got := make([]byte, 5)
		if _, err := io.ReadFull(conn, got); err != nil || string(got) != "early" {
			t.Fatalf("the %s's pending connection after the session: %q %v", name, got, err)
		}
		conn.Close()
	}
}
