package control

import (
	"context"
	"encoding/json"
	"fmt"
	"net"
	"strconv"
	"sync"

	"github.com/iffiX/neutrino/transport/gate"
	"github.com/iffiX/neutrino/transport/relay"
	"github.com/iffiX/neutrino/transport/session"
)

// HubControl is the hub's local channel: it serves the Python's control,
// attach and open connections, and is the Python the relay asks.
type HubControl struct {
	secret   string
	keyDir   string
	listener net.Listener
	log      relay.EventFunc

	// hub is set once the relay exists, before Serve.
	hub *relay.Hub

	// mu guards control, pending, nextID and forwards.
	mu      sync.Mutex
	control *LineConnection
	pending map[string]chan map[string]any
	nextID  uint64
	// forwards holds each forward on the hub's loopback by its key, with the
	// control connection that started it.
	forwards map[string]hubForward
}

// hubForward is one forward_start's listener and the control connection
// whose end stops it.
type hubForward struct {
	forward *relay.Forward
	line    *LineConnection
}

// NewHubControl makes the hub's local channel on listener, admitting
// connections that open with secret; keyDir is where keys_reload reads.
func NewHubControl(listener net.Listener, secret, keyDir string, log relay.EventFunc) *HubControl {
	if log == nil {
		log = func(string, ...string) {}
	}
	return &HubControl{secret: secret, keyDir: keyDir, listener: listener, log: log, pending: make(map[string]chan map[string]any), forwards: make(map[string]hubForward)}
}

// SetHub binds the relay the commands and connections act on.
func (c *HubControl) SetHub(hub *relay.Hub) {
	c.hub = hub
}

// Serve accepts local connections until the listener closes.
func (c *HubControl) Serve() {
	for {
		conn, err := c.listener.Accept()
		if err != nil {
			return
		}
		go c.serve(conn)
	}
}

// Close closes the listener, the control connection and every forward.
func (c *HubControl) Close() {
	c.listener.Close()
	c.mu.Lock()
	control := c.control
	forwards := c.forwards
	c.forwards = make(map[string]hubForward)
	c.mu.Unlock()
	if control != nil {
		control.Close()
	}
	for _, held := range forwards {
		held.forward.Stop()
	}
}

func (c *HubControl) serve(conn net.Conn) {
	line := NewLineConnection(conn)
	first, err := line.ReadFirstLine(c.secret)
	if err != nil {
		conn.Close()
		return
	}
	switch first.Op {
	case OpControl:
		c.serveControl(line)
	case OpAttach:
		stream, err := c.hub.Attach(first.Stream)
		if err != nil {
			conn.Close()
			return
		}
		serveAttached(line.StreamConn(), stream)
	case OpOpen:
		stream, err := c.hub.OpenStream(first.Session, first.Open)
		if err != nil {
			conn.Close()
			return
		}
		serveOpened(line.StreamConn(), stream, first.Open)
	}
}

// serveControl takes a control connection, replacing the one before it, and
// tells it every live session.
func (c *HubControl) serveControl(line *LineConnection) {
	c.mu.Lock()
	earlier := c.control
	c.control = line
	pending := c.pending
	c.pending = make(map[string]chan map[string]any)
	c.mu.Unlock()
	if earlier != nil {
		earlier.Close()
	}
	for _, channel := range pending {
		close(channel)
	}
	c.log("control_connected")
	for _, rs := range c.hub.LiveSessions() {
		c.Event(EventSessionOpen, rs.OpenEvent())
		if hello := rs.Hello(); hello != nil {
			c.Frame(rs.ID, hello)
		}
	}
	for {
		raw, err := line.ReadLine()
		if err != nil {
			break
		}
		c.handleLine(line, raw)
	}
	c.mu.Lock()
	if c.control == line {
		c.control = nil
	}
	c.mu.Unlock()
	line.Close()
	c.stopForwardsOf(line)
	c.log("control_disconnected")
}

// controlLine is a line from the Python: an answer, a command or a frame.
type controlLine struct {
	ID        string          `json:"id"`
	Command   string          `json:"command"`
	Frame     json.RawMessage `json:"frame"`
	Session   string          `json:"session"`
	IsLast    bool            `json:"is_last"`
	Code      string          `json:"code"`
	Params    map[string]any  `json:"params"`
	BindingID string          `json:"binding_id"`
	Kind      string          `json:"kind"`
	DeviceID  string          `json:"device_id"`
	Key       string          `json:"key"`
	SessionID string          `json:"session_id"`
	Shares    []gate.Share    `json:"shares"`
	Listen    string          `json:"listen"`
	Protocol  string          `json:"protocol"`
	Open      json.RawMessage `json:"open"`
}

func (c *HubControl) handleLine(line *LineConnection, raw []byte) {
	var parsed controlLine
	if err := json.Unmarshal(raw, &parsed); err != nil {
		return
	}
	switch {
	case len(parsed.Frame) > 0:
		if err := c.hub.WriteFrame(parsed.Session, parsed.Frame, parsed.IsLast); err != nil {
			c.log("frame_dropped", "session", parsed.Session, "error", err.Error())
		}
	case parsed.Command == CommandForwardStart:
		listen, refusal := c.startForward(line, parsed)
		fields := map[string]any{}
		if refusal == nil {
			fields["listen"] = listen
		}
		c.answerWith(line, parsed.ID, fields, refusal)
	case parsed.Command == CommandForwardStop:
		c.answer(line, parsed.ID, c.stopForward(parsed.Listen, parsed.Protocol))
	case parsed.Command != "":
		c.answer(line, parsed.ID, c.runCommand(parsed))
	case parsed.ID != "":
		var answer map[string]any
		if err := json.Unmarshal(raw, &answer); err != nil {
			return
		}
		c.mu.Lock()
		channel, ok := c.pending[parsed.ID]
		delete(c.pending, parsed.ID)
		c.mu.Unlock()
		if ok {
			channel <- answer
		}
	}
}

// runCommand runs one of the four commands with no fields to answer and
// returns its refusal, if any.
func (c *HubControl) runCommand(parsed controlLine) *session.Refusal {
	switch parsed.Command {
	case CommandSessionClose:
		if err := c.hub.SessionClose(parsed.Session, parsed.Code, parsed.Params); err != nil {
			return session.NewRefusal(CodeSessionUnknown, map[string]any{"session": parsed.Session})
		}
	case CommandStreamsClose:
		c.hub.StreamsClose(parsed.BindingID, parsed.Kind, parsed.DeviceID, parsed.Key, parsed.SessionID, parsed.Code, parsed.Params)
	case CommandKeysReload:
		if err := c.hub.KeysReload(c.keyDir); err != nil {
			return session.NewRefusal("keys_unreadable", map[string]any{"detail": err.Error()})
		}
	case CommandSharesSet:
		c.hub.SetShares(parsed.Shares)
	default:
		return session.NewRefusal(CodeCommandUnknown, map[string]any{"command": parsed.Command})
	}
	return nil
}

func (c *HubControl) answer(line *LineConnection, id string, refusal *session.Refusal) {
	c.answerWith(line, id, nil, refusal)
}

// answerWith writes a command's answer: its fields, or its refusal.
func (c *HubControl) answerWith(line *LineConnection, id string, fields map[string]any, refusal *session.Refusal) {
	reply := map[string]any{"id": id}
	if refusal != nil {
		reply["code"] = refusal.Code
		reply["params"] = refusal.Params
	} else {
		for key, value := range fields {
			reply[key] = value
		}
	}
	_ = line.WriteObject(reply)
}

// startForward binds a forward on the hub's loopback whose connections each
// open a stream on the binding's session; it accepts nothing while the
// binding has no session, and the end of line stops it.
func (c *HubControl) startForward(line *LineConnection, parsed controlLine) (string, *session.Refusal) {
	protocol := parsed.Protocol
	if protocol == "" {
		protocol = session.ProtocolTCP
	}
	if protocol != session.ProtocolTCP || parsed.BindingID == "" || len(parsed.Open) == 0 {
		return "", session.NewRefusal(CodeBodyInvalid, map[string]any{"detail": "forward_start takes binding_id, open and protocol tcp"})
	}
	forward, refusal, err := relay.StartForward(context.Background(), parsed.Listen, protocol, parsed.Open, c.hub.BindingOpener(parsed.BindingID), nil)
	if err != nil {
		return "", session.NewRefusal(CodeBodyInvalid, map[string]any{"detail": err.Error()})
	}
	if refusal != nil {
		return "", refusal
	}
	key := forwardKey(forward.Listen, protocol)
	c.mu.Lock()
	earlier, hadEarlier := c.forwards[key]
	c.forwards[key] = hubForward{forward: forward, line: line}
	c.mu.Unlock()
	if hadEarlier {
		earlier.forward.Stop()
	}
	c.log("forward_started", "listen", forward.Listen, "binding", parsed.BindingID)
	return forward.Listen, nil
}

// stopForward closes one forward and its streams.
func (c *HubControl) stopForward(listen, protocol string) *session.Refusal {
	key := forwardKey(listen, protocol)
	c.mu.Lock()
	held, ok := c.forwards[key]
	delete(c.forwards, key)
	c.mu.Unlock()
	if !ok {
		return session.NewRefusal(CodeForwardUnknown, map[string]any{"listen": listen})
	}
	held.forward.Stop()
	return nil
}

// stopForwardsOf closes every forward a control connection started.
func (c *HubControl) stopForwardsOf(line *LineConnection) {
	c.mu.Lock()
	var ended []*relay.Forward
	for key, held := range c.forwards {
		if held.line == line {
			ended = append(ended, held.forward)
			delete(c.forwards, key)
		}
	}
	c.mu.Unlock()
	for _, forward := range ended {
		forward.Stop()
	}
}

// Ask sends a question on the control connection and waits for its answer
// until ctx ends. It returns a *session.Refusal for an answer with a code
// and relay.ErrControlUnavailable when no connection is open or no answer
// comes in time.
func (c *HubControl) Ask(ctx context.Context, question string, fields map[string]any) (map[string]any, error) {
	c.mu.Lock()
	control := c.control
	if control == nil {
		c.mu.Unlock()
		return nil, relay.ErrControlUnavailable
	}
	c.nextID++
	id := "q" + strconv.FormatUint(c.nextID, 10)
	channel := make(chan map[string]any, 1)
	c.pending[id] = channel
	c.mu.Unlock()
	line := make(map[string]any, len(fields)+2)
	for key, value := range fields {
		line[key] = value
	}
	line["id"] = id
	line["question"] = question
	if err := control.WriteObject(line); err != nil {
		c.forget(id)
		return nil, relay.ErrControlUnavailable
	}
	select {
	case answer, ok := <-channel:
		if !ok {
			return nil, relay.ErrControlUnavailable
		}
		if code, has := answer["code"].(string); has && code != "" {
			params, _ := answer["params"].(map[string]any)
			return nil, session.NewRefusal(code, params)
		}
		return answer, nil
	case <-ctx.Done():
		c.forget(id)
		return nil, fmt.Errorf("%w: %s", relay.ErrControlUnavailable, question)
	}
}

func (c *HubControl) forget(id string) {
	c.mu.Lock()
	defer c.mu.Unlock()
	delete(c.pending, id)
}

// Event sends one event line.
func (c *HubControl) Event(event string, fields map[string]any) {
	c.mu.Lock()
	control := c.control
	c.mu.Unlock()
	if control == nil {
		return
	}
	line := make(map[string]any, len(fields)+1)
	for key, value := range fields {
		line[key] = value
	}
	line["event"] = event
	_ = control.WriteObject(line)
}

// Frame passes one frame of a session to the Python.
func (c *HubControl) Frame(sessionID string, frame []byte) {
	c.mu.Lock()
	control := c.control
	c.mu.Unlock()
	if control == nil {
		return
	}
	_ = control.WriteFrameLine(frame, "session", sessionID)
}

// IsConnected reports whether a control connection is open.
func (c *HubControl) IsConnected() bool {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.control != nil
}

var _ relay.Python = (*HubControl)(nil)
