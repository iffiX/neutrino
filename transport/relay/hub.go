package relay

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"strconv"
	"sync"
	"time"

	"github.com/flynn/noise"

	"github.com/iffiX/neutrino/transport/knock"
	"github.com/iffiX/neutrino/transport/session"
)

// Python is the hub's Python as the relay reaches it over the local channel:
// it answers questions and receives events and frames.
type Python interface {
	// Ask sends one question and waits for its answer. It returns a
	// *session.Refusal for an answer with a code, and ErrControlUnavailable
	// when no answer comes in time or no control connection is open.
	Ask(ctx context.Context, question string, fields map[string]any) (map[string]any, error)
	// Event sends one event line.
	Event(event string, fields map[string]any)
	// Frame passes one frame of a session on.
	Frame(sessionID string, frame []byte)
}

// EventFunc receives one log line: a verb and key-value pairs.
type EventFunc func(verb string, fields ...string)

// FrpListener is one loopback listener for a frp vendor.
type FrpListener struct {
	Port     int    `json:"port"`
	Listener string `json:"listener"`
}

// HubConfig is what the hub's service reads at its start.
type HubConfig struct {
	// Key is the hub's static key pair.
	Key noise.DHKey
	// ListenPort is the agent port.
	ListenPort int
	// FrpListeners are the loopback listeners, one per vendor.
	FrpListeners []FrpListener
	// LegacyTLSPort is the legacy listener's loopback port, 0 while off.
	LegacyTLSPort int
	// Timings are the session's keepalive settings; the defaults when zero.
	Timings session.Timings
	// Memory caps the stream windows; TransportMemoryMaxBytes when nil.
	Memory *session.TransportMemory
	// Now reads the clock; time.Now when nil.
	Now func() time.Time
	// Log receives one line per event; nil logs nothing.
	Log EventFunc
}

// Hub is the hub's service on the agent port: it admits peers and relays
// their streams, asking python for every decision.
type Hub struct {
	python  Python
	timings session.Timings
	memory  *session.TransportMemory
	now     func() time.Time
	log     EventFunc
	legacy  int
	ledger  *knock.KnockLedger
	replay  *knock.ReplayWindow
	handOff *HandOff

	// keyMu guards key and jar.
	keyMu sync.RWMutex
	key   noise.DHKey
	jar   *knock.CookieJar

	// mu guards sessions, byBinding, unadmitted, nextSession, nextStream,
	// listeners and keepAliveLogged.
	mu              sync.Mutex
	sessions        map[string]*RelaySession
	byBinding       map[string]*RelaySession
	unadmitted      map[*knock.Unadmitted]io.Closer
	nextSession     uint64
	nextStream      uint64
	listeners       []net.Listener
	keepAliveLogged map[string]time.Time
	config          HubConfig
}

// NewHub makes the service from config, answering to python.
func NewHub(config HubConfig, python Python) (*Hub, error) {
	if len(config.Key.Private) != noise.DH25519.DHLen() {
		return nil, fmt.Errorf("hub key: %d bytes", len(config.Key.Private))
	}
	now := config.Now
	if now == nil {
		now = time.Now
	}
	timings := config.Timings
	if timings.KeepAliveInterval == 0 {
		timings = session.DefaultTimings
	}
	memory := config.Memory
	if memory == nil {
		memory = session.NewTransportMemory(session.TransportMemoryMaxBytes)
	}
	logger := config.Log
	if logger == nil {
		logger = func(string, ...string) {}
	}
	jar, err := knock.NewCookieJar(config.Key.Public, now)
	if err != nil {
		return nil, err
	}
	return &Hub{
		python:          python,
		timings:         timings,
		memory:          memory,
		now:             now,
		log:             logger,
		legacy:          config.LegacyTLSPort,
		ledger:          knock.NewKnockLedger(),
		replay:          knock.NewReplayWindow(knock.KnockReplayKeysMax),
		handOff:         NewHandOff(ControlQuestionTimeout),
		key:             config.Key,
		jar:             jar,
		sessions:        make(map[string]*RelaySession),
		byBinding:       make(map[string]*RelaySession),
		unadmitted:      make(map[*knock.Unadmitted]io.Closer),
		keepAliveLogged: make(map[string]time.Time),
		config:          config,
	}, nil
}

// ControlQuestionTimeout is the wait for the Python's answer to a question.
const ControlQuestionTimeout = 5 * time.Second

// PublicKey is the hub's static public key.
func (h *Hub) PublicKey() []byte {
	h.keyMu.RLock()
	defer h.keyMu.RUnlock()
	return h.key.Public
}

// Listen opens the agent port on IPv4 and IPv6 and each frp loopback
// listener. It returns an error when the agent port cannot be opened on
// either family; a frp listener another program holds is one log line.
func (h *Hub) Listen() error {
	var listeners []net.Listener
	var names []string
	port := strconv.Itoa(h.config.ListenPort)
	v4, err4 := net.Listen("tcp4", net.JoinHostPort("0.0.0.0", port))
	if err4 == nil {
		listeners = append(listeners, v4)
		names = append(names, RelayListenerMain)
		h.log("listen", "listener", RelayListenerMain, "address", v4.Addr().String())
	}
	v6, err6 := net.Listen("tcp6", net.JoinHostPort("::", port))
	if err6 == nil {
		listeners = append(listeners, v6)
		names = append(names, RelayListenerMain)
		h.log("listen", "listener", RelayListenerMain, "address", v6.Addr().String())
	}
	if err4 != nil && err6 != nil {
		return fmt.Errorf("listen on port %s: %w", port, err4)
	}
	for _, frp := range h.config.FrpListeners {
		listener, err := net.Listen("tcp4", net.JoinHostPort(RelayLegacyLoopback, strconv.Itoa(frp.Port)))
		if err != nil {
			h.log("listen_failed", "listener", frp.Listener, "port", strconv.Itoa(frp.Port), "error", err.Error())
			continue
		}
		listeners = append(listeners, listener)
		names = append(names, frp.Listener)
		h.log("listen", "listener", frp.Listener, "address", listener.Addr().String())
	}
	h.mu.Lock()
	h.listeners = listeners
	h.mu.Unlock()
	for i, listener := range listeners {
		go h.accept(listener, names[i])
	}
	return nil
}

// Addrs are the addresses the listeners hold.
func (h *Hub) Addrs() []net.Addr {
	h.mu.Lock()
	defer h.mu.Unlock()
	var addrs []net.Addr
	for _, listener := range h.listeners {
		addrs = append(addrs, listener.Addr())
	}
	return addrs
}

// Close closes every listener and ends every session.
func (h *Hub) Close() {
	h.mu.Lock()
	listeners := h.listeners
	h.listeners = nil
	sessions := make([]*RelaySession, 0, len(h.sessions))
	for _, rs := range h.sessions {
		sessions = append(sessions, rs)
	}
	h.mu.Unlock()
	for _, listener := range listeners {
		listener.Close()
	}
	for _, rs := range sessions {
		rs.end(EndClosedByHub)
	}
}

func (h *Hub) accept(listener net.Listener, name string) {
	for {
		conn, err := listener.Accept()
		if err != nil {
			return
		}
		go h.ServeConn(conn, name)
	}
}

// Session is the live session with id, or ErrSessionUnknown.
func (h *Hub) Session(id string) (*RelaySession, error) {
	h.mu.Lock()
	defer h.mu.Unlock()
	rs, ok := h.sessions[id]
	if !ok {
		return nil, ErrSessionUnknown
	}
	return rs, nil
}

// LiveSessions are the sessions that passed hello, for a new control
// connection to be told about.
func (h *Hub) LiveSessions() []*RelaySession {
	h.mu.Lock()
	defer h.mu.Unlock()
	live := make([]*RelaySession, 0, len(h.sessions))
	for _, rs := range h.sessions {
		live = append(live, rs)
	}
	return live
}

// WriteFrame writes a frame of the Python's on a session's control stream. A
// welcome admits the session and replaces an earlier session of the same
// binding with refused replaced; isLast ends the session once the frame is
// written. It returns ErrSessionUnknown for an id no session has.
func (h *Hub) WriteFrame(sessionID string, frame []byte, isLast bool) error {
	rs, err := h.Session(sessionID)
	if err != nil {
		return err
	}
	frameType, err := session.FrameType(frame)
	if err != nil {
		return err
	}
	if frameType == session.FrameWelcome {
		h.welcome(rs)
	}
	if err := rs.control.WriteFrame(frame); err != nil {
		return fmt.Errorf("write frame: %w", err)
	}
	if isLast {
		rs.endSoon(EndClosedByHub)
	}
	return nil
}

// welcome records a session as admitted and ends the earlier session of its
// binding with refused replaced.
func (h *Hub) welcome(rs *RelaySession) {
	h.mu.Lock()
	earlier := h.byBinding[rs.BindingID]
	h.byBinding[rs.BindingID] = rs
	h.mu.Unlock()
	rs.markWelcomed()
	if earlier != nil && earlier != rs {
		earlier.refuse(session.NewRefusal(session.CodeReplaced, nil), EndReplaced)
	}
}

// SessionClose sends refused {code, params} on a session and ends it. It
// returns ErrSessionUnknown for an id no session has.
func (h *Hub) SessionClose(sessionID, code string, params map[string]any) error {
	rs, err := h.Session(sessionID)
	if err != nil {
		return err
	}
	rs.refuse(session.NewRefusal(code, params), EndClosedByHub)
	return nil
}

// StreamsClose closes every stream of a binding under kind, on the device
// and the kept shell named when they are not empty, with close {code,
// params}; a raw TCP connect is reset.
func (h *Hub) StreamsClose(bindingID, kind, deviceID, shellSessionID, code string, params map[string]any) {
	for _, rs := range h.LiveSessions() {
		if rs.BindingID != bindingID {
			continue
		}
		for _, stream := range rs.streamsOf(kind, deviceID, shellSessionID) {
			stream.closeWith(session.NewRefusal(code, params))
		}
	}
}

// KeysReload reads the static key again from dir, making a new pair when
// the file is missing, writes the public half, and ends every session.
func (h *Hub) KeysReload(dir string) error {
	key, err := LoadOrCreateKey(dir)
	if err != nil {
		return err
	}
	jar, err := knock.NewCookieJar(key.Public, h.now)
	if err != nil {
		return err
	}
	h.keyMu.Lock()
	h.key = key
	h.jar = jar
	h.keyMu.Unlock()
	for _, rs := range h.LiveSessions() {
		rs.end(EndClosedByHub)
	}
	h.log("keys_reloaded", "public_key", fmt.Sprintf("%x", key.Public))
	return nil
}

// OpenStream opens a stream of the Python's on a session with the open record
// given, and returns the stream, whose answer the Python reads itself. It
// returns ErrSessionUnknown for an id no session has.
func (h *Hub) OpenStream(sessionID string, open json.RawMessage) (io.ReadWriteCloser, error) {
	rs, err := h.Session(sessionID)
	if err != nil {
		return nil, err
	}
	ctx, cancel := context.WithTimeout(context.Background(), session.ConnectDialTimeout)
	defer cancel()
	stream, err := rs.session.OpenStream(ctx)
	if err != nil {
		return nil, err
	}
	if _, err := stream.Write(session.EncodeRecord(session.RecordOpen, open)); err != nil {
		stream.Close()
		return nil, fmt.Errorf("write open: %w", err)
	}
	return stream, nil
}

// Attach returns the stream announced under id, or ErrStreamUnknown.
func (h *Hub) Attach(streamID string) (*RecordStream, error) {
	return h.handOff.Take(streamID)
}

// Memory is the cap on the stream windows.
func (h *Hub) Memory() *session.TransportMemory {
	return h.memory
}

// Ledger counts the unadmitted connections and the knocks in flight.
func (h *Hub) Ledger() *knock.KnockLedger {
	return h.ledger
}

func (h *Hub) currentKey() (noise.DHKey, *knock.CookieJar) {
	h.keyMu.RLock()
	defer h.keyMu.RUnlock()
	return h.key, h.jar
}

func (h *Hub) newSessionID() string {
	h.mu.Lock()
	defer h.mu.Unlock()
	h.nextSession++
	return "s" + strconv.FormatUint(h.nextSession, 10)
}

func (h *Hub) newStreamID() string {
	h.mu.Lock()
	defer h.mu.Unlock()
	h.nextStream++
	return "t" + strconv.FormatUint(h.nextStream, 10)
}

// register adds a session that passed hello or sent leave. It returns false
// at SessionsMax.
func (h *Hub) register(rs *RelaySession) bool {
	h.mu.Lock()
	defer h.mu.Unlock()
	if len(h.sessions) >= session.SessionsMax {
		return false
	}
	h.sessions[rs.ID] = rs
	return true
}

// unregister forgets an ended session and closes the streams other sessions
// relay to it with agent_offline.
func (h *Hub) unregister(rs *RelaySession) {
	h.mu.Lock()
	delete(h.sessions, rs.ID)
	if h.byBinding[rs.BindingID] == rs {
		delete(h.byBinding, rs.BindingID)
	}
	others := make([]*RelaySession, 0, len(h.sessions))
	for _, other := range h.sessions {
		others = append(others, other)
	}
	h.mu.Unlock()
	for _, other := range others {
		for _, stream := range other.streamsTo(rs.ID) {
			stream.closeWith(session.NewRefusal(session.CodeAgentOffline, map[string]any{"device": stream.deviceID}))
		}
	}
}

// logKeepAlive writes the keepalive line for an address at most once a
// minute.
func (h *Hub) logKeepAlive(address string) {
	h.mu.Lock()
	last, ok := h.keepAliveLogged[address]
	now := h.now()
	if ok && now.Sub(last) < RelayKeepAliveLogInterval {
		h.mu.Unlock()
		return
	}
	h.keepAliveLogged[address] = now
	h.mu.Unlock()
	h.log("keepalive_lost", "address", address)
}

// ask asks the Python one question within ControlQuestionTimeout. It returns
// the answer, or the refusal to write: the Python's own, or
// control_unavailable.
func (h *Hub) ask(question string, fields map[string]any) (map[string]any, *session.Refusal) {
	ctx, cancel := context.WithTimeout(context.Background(), ControlQuestionTimeout)
	defer cancel()
	answer, err := h.python.Ask(ctx, question, fields)
	if err != nil {
		var refusal *session.Refusal
		if errors.As(err, &refusal) {
			return nil, refusal
		}
		return nil, session.NewRefusal(session.CodeControlUnavailable, nil)
	}
	return answer, nil
}
