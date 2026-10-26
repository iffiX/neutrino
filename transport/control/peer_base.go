package control

import (
	"context"
	"encoding/json"
	"net"
	"strconv"
	"sync"

	"github.com/iffiX/neutrino/transport/relay"
	"github.com/iffiX/neutrino/transport/session"
)

// peerBase is what the agent's and the client's local channels share: the
// listener, the one control connection, the questions in flight, the
// hand-off of streams and the writing of answers, events and frames.
type peerBase struct {
	secret   string
	listener net.Listener
	log      relay.EventFunc
	handOff  *relay.HandOff

	// mu guards control, pending and nextID.
	mu      sync.Mutex
	control *LineConnection
	pending map[string]chan map[string]any
	nextID  uint64
}

// peerLine is a line from the Python on a peer: a command, an answer or a
// frame.
type peerLine struct {
	ID      string          `json:"id"`
	Command string          `json:"command"`
	Frame   json.RawMessage `json:"frame"`
	Binding string          `json:"binding"`
	Code    string          `json:"code"`
	Params  map[string]any  `json:"params"`
	raw     []byte
}

func newPeerBase(listener net.Listener, secret string, log relay.EventFunc) peerBase {
	if log == nil {
		log = func(string, ...string) {}
	}
	return peerBase{
		secret:   secret,
		listener: listener,
		log:      log,
		handOff:  relay.NewHandOff(ControlQuestionTimeout),
		pending:  make(map[string]chan map[string]any),
	}
}

// serve accepts local connections, handing each kind to the callbacks.
func (b *peerBase) serve(onLine func(*LineConnection, peerLine), onOpen func(*LineConnection, *FirstLine)) {
	for {
		conn, err := b.listener.Accept()
		if err != nil {
			return
		}
		go func() {
			line := NewLineConnection(conn)
			first, err := line.ReadFirstLine(b.secret)
			if err != nil {
				conn.Close()
				return
			}
			switch first.Op {
			case OpControl:
				b.serveControl(line, onLine)
			case OpAttach:
				stream, err := b.handOff.Take(first.Stream)
				if err != nil {
					conn.Close()
					return
				}
				serveAttached(line.StreamConn(), stream)
			case OpOpen:
				onOpen(line, first)
			}
		}()
	}
}

// serveControl takes the control connection, replacing the one before it.
func (b *peerBase) serveControl(line *LineConnection, onLine func(*LineConnection, peerLine)) {
	b.mu.Lock()
	earlier := b.control
	b.control = line
	pending := b.pending
	b.pending = make(map[string]chan map[string]any)
	b.mu.Unlock()
	if earlier != nil {
		earlier.Close()
	}
	for _, channel := range pending {
		close(channel)
	}
	b.log("control_connected")
	for {
		raw, err := line.ReadLine()
		if err != nil {
			break
		}
		var parsed peerLine
		if err := json.Unmarshal(raw, &parsed); err != nil {
			continue
		}
		parsed.raw = raw
		if parsed.Command == "" && len(parsed.Frame) == 0 && parsed.ID != "" {
			b.deliverAnswer(parsed.ID, raw)
			continue
		}
		onLine(line, parsed)
	}
	b.mu.Lock()
	if b.control == line {
		b.control = nil
	}
	b.mu.Unlock()
	line.Close()
	b.log("control_disconnected")
}

func (b *peerBase) deliverAnswer(id string, raw []byte) {
	var answer map[string]any
	if err := json.Unmarshal(raw, &answer); err != nil {
		return
	}
	b.mu.Lock()
	channel, ok := b.pending[id]
	delete(b.pending, id)
	b.mu.Unlock()
	if ok {
		channel <- answer
	}
}

// ask sends a question and waits for its answer within ctx. It returns a
// *session.Refusal for an answer with a code and relay.ErrControlUnavailable
// when no answer comes.
func (b *peerBase) ask(ctx context.Context, question string, fields map[string]any) (map[string]any, error) {
	b.mu.Lock()
	control := b.control
	if control == nil {
		b.mu.Unlock()
		return nil, relay.ErrControlUnavailable
	}
	b.nextID++
	id := "q" + strconv.FormatUint(b.nextID, 10)
	channel := make(chan map[string]any, 1)
	b.pending[id] = channel
	b.mu.Unlock()
	line := make(map[string]any, len(fields)+2)
	for key, value := range fields {
		line[key] = value
	}
	line["id"] = id
	line["question"] = question
	if err := control.WriteObject(line); err != nil {
		b.forget(id)
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
		b.forget(id)
		return nil, relay.ErrControlUnavailable
	}
}

func (b *peerBase) forget(id string) {
	b.mu.Lock()
	defer b.mu.Unlock()
	delete(b.pending, id)
}

// answer writes a command's answer: {id} or {id, code, params}, with extra
// fields when the command gives some.
func (b *peerBase) answer(line *LineConnection, id string, refusal *session.Refusal, extra map[string]any) {
	reply := map[string]any{"id": id}
	for key, value := range extra {
		reply[key] = value
	}
	if refusal != nil {
		reply["code"] = refusal.Code
		reply["params"] = refusal.Params
	}
	_ = line.WriteObject(reply)
}

// event writes one event line.
func (b *peerBase) event(event string, fields map[string]any) {
	b.mu.Lock()
	control := b.control
	b.mu.Unlock()
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

// frame writes one frame line, with a binding when key is set.
func (b *peerBase) frame(frame []byte, key, value string) {
	b.mu.Lock()
	control := b.control
	b.mu.Unlock()
	if control == nil {
		return
	}
	_ = control.WriteFrameLine(frame, key, value)
}

// close closes the listener and the control connection.
func (b *peerBase) close() {
	b.listener.Close()
	b.mu.Lock()
	control := b.control
	b.mu.Unlock()
	if control != nil {
		control.Close()
	}
}

// refusalFields are the code and params of a refusal, or empty strings when
// there is none.
func refusalFields(refusal *session.Refusal) (string, map[string]any) {
	if refusal == nil {
		return "", map[string]any{}
	}
	return refusal.Code, refusal.Params
}

// forwardKey names a forward by its address and protocol.
func forwardKey(listen, protocol string) string {
	if protocol == "" {
		protocol = session.ProtocolTCP
	}
	return protocol + "/" + listen
}
