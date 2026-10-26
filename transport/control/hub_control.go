package control

import (
	"context"
	"encoding/json"
	"fmt"
	"net"
	"strconv"
	"sync"

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

	// mu guards control, pending and nextID.
	mu      sync.Mutex
	control *LineConnection
	pending map[string]chan map[string]any
	nextID  uint64
}

// NewHubControl makes the hub's local channel on listener, admitting
// connections that open with secret; keyDir is where keys_reload reads.
func NewHubControl(listener net.Listener, secret, keyDir string, log relay.EventFunc) *HubControl {
	if log == nil {
		log = func(string, ...string) {}
	}
	return &HubControl{secret: secret, keyDir: keyDir, listener: listener, log: log, pending: make(map[string]chan map[string]any)}
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

// Close closes the listener and the control connection.
func (c *HubControl) Close() {
	c.listener.Close()
	c.mu.Lock()
	control := c.control
	c.mu.Unlock()
	if control != nil {
		control.Close()
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
	SessionID string          `json:"session_id"`
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

// runCommand runs one of the three commands and returns its refusal, if any.
func (c *HubControl) runCommand(parsed controlLine) *session.Refusal {
	switch parsed.Command {
	case CommandSessionClose:
		if err := c.hub.SessionClose(parsed.Session, parsed.Code, parsed.Params); err != nil {
			return session.NewRefusal(CodeSessionUnknown, map[string]any{"session": parsed.Session})
		}
	case CommandStreamsClose:
		c.hub.StreamsClose(parsed.BindingID, parsed.Kind, parsed.DeviceID, parsed.SessionID, parsed.Code, parsed.Params)
	case CommandKeysReload:
		if err := c.hub.KeysReload(c.keyDir); err != nil {
			return session.NewRefusal("keys_unreadable", map[string]any{"detail": err.Error()})
		}
	default:
		return session.NewRefusal(CodeCommandUnknown, map[string]any{"command": parsed.Command})
	}
	return nil
}

func (c *HubControl) answer(line *LineConnection, id string, refusal *session.Refusal) {
	reply := map[string]any{"id": id}
	if refusal != nil {
		reply["code"] = refusal.Code
		reply["params"] = refusal.Params
	}
	_ = line.WriteObject(reply)
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
