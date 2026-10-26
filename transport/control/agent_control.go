package control

import (
	"context"
	"encoding/json"
	"net"
	"sync"
	"time"

	"github.com/libp2p/go-yamux/v4"

	"github.com/iffiX/neutrino/transport/handshake"
	"github.com/iffiX/neutrino/transport/relay"
	"github.com/iffiX/neutrino/transport/session"
)

// AgentControl is the agent's local channel: it keeps the agent's one
// session to its hub and serves the agent's commands and questions.
type AgentControl struct {
	peerBase
	timings session.Timings
	ctx     context.Context
	cancel  context.CancelFunc

	// linkMu guards link, forwards and ready.
	linkMu   sync.Mutex
	link     *agentLink
	forwards map[string]*relay.Forward
	// ready is closed while the link holds a session.
	ready chan struct{}
}

// dialCommand is the agent's dial, leave and join: the keys, the addresses
// and what a join carries.
type dialCommand struct {
	HubKey     string   `json:"hub_key"`
	PrivateKey string   `json:"private_key"`
	Psk        string   `json:"psk"`
	Role       string   `json:"role"`
	Protocol   int      `json:"protocol"`
	Addresses  []string `json:"addresses"`
}

// forwardCommand is forward_start and forward_stop.
type forwardCommand struct {
	Listen   string          `json:"listen"`
	Protocol string          `json:"protocol"`
	Open     json.RawMessage `json:"open"`
	Binding  string          `json:"binding"`
}

// NewAgentControl makes the agent's local channel on listener.
func NewAgentControl(listener net.Listener, secret string, timings session.Timings, log relay.EventFunc) *AgentControl {
	ctx, cancel := context.WithCancel(context.Background())
	if timings.KeepAliveInterval == 0 {
		timings = session.DefaultTimings
	}
	return &AgentControl{
		peerBase: newPeerBase(listener, secret, log),
		timings:  timings,
		ctx:      ctx,
		cancel:   cancel,
		forwards: make(map[string]*relay.Forward),
		ready:    make(chan struct{}),
	}
}

// OpenStream opens a stream on the live session for a forward. It returns
// relay.ErrNoSession while the agent has none.
func (a *AgentControl) OpenStream(ctx context.Context, open json.RawMessage) (*relay.RecordStream, *session.Refusal, error) {
	link := a.currentLink()
	if link == nil {
		return nil, nil, relay.ErrNoSession
	}
	return link.OpenStream(ctx, open)
}

// Ready is closed while a session is live, so a forward accepts nothing
// before the first session and between sessions.
func (a *AgentControl) Ready() <-chan struct{} {
	a.linkMu.Lock()
	defer a.linkMu.Unlock()
	return a.ready
}

// setLive records whether link, when it is the current one, holds a session.
func (a *AgentControl) setLive(link *agentLink, isLive bool) {
	a.linkMu.Lock()
	defer a.linkMu.Unlock()
	if a.link != link {
		return
	}
	select {
	case <-a.ready:
		if !isLive {
			a.ready = make(chan struct{})
		}
	default:
		if isLive {
			close(a.ready)
		}
	}
}

// Serve accepts local connections until Close.
func (a *AgentControl) Serve() {
	a.serve(a.handleLine, a.handleOpen)
}

// Close ends the session, every forward and the listener.
func (a *AgentControl) Close() {
	a.cancel()
	a.linkMu.Lock()
	link := a.link
	a.link = nil
	forwards := a.forwards
	a.forwards = make(map[string]*relay.Forward)
	a.linkMu.Unlock()
	if link != nil {
		link.stop()
	}
	for _, forward := range forwards {
		forward.Stop()
	}
	a.close()
}

func (a *AgentControl) handleLine(line *LineConnection, parsed peerLine) {
	if len(parsed.Frame) > 0 {
		link := a.currentLink()
		if link == nil {
			return
		}
		if err := link.writeFrame(parsed.Frame); err != nil {
			a.log("frame_dropped", "error", err.Error())
		}
		return
	}
	switch parsed.Command {
	case CommandDial:
		var command dialCommand
		if err := json.Unmarshal(parsed.raw, &command); err != nil {
			a.answer(line, parsed.ID, session.NewRefusal(CodeBodyInvalid, nil), nil)
			return
		}
		settings, refusal := settingsOf(command, false, a.timings)
		if refusal != nil {
			a.answer(line, parsed.ID, refusal, nil)
			return
		}
		a.startLink(settings, command.Addresses)
		a.answer(line, parsed.ID, nil, nil)
	case CommandUndial:
		a.linkMu.Lock()
		link := a.link
		a.link = nil
		a.linkMu.Unlock()
		if link != nil {
			link.stop()
		}
		a.answer(line, parsed.ID, nil, nil)
	case CommandJoin, CommandLeave:
		go a.joinOrLeave(line, parsed)
	case CommandForwardStart:
		var command forwardCommand
		if err := json.Unmarshal(parsed.raw, &command); err != nil {
			a.answer(line, parsed.ID, session.NewRefusal(CodeBodyInvalid, nil), nil)
			return
		}
		listen, refusal := a.startForward(command)
		a.answer(line, parsed.ID, refusal, map[string]any{"listen": listen})
	case CommandForwardStop:
		var command forwardCommand
		_ = json.Unmarshal(parsed.raw, &command)
		a.answer(line, parsed.ID, a.stopForward(command.Listen, command.Protocol), nil)
	default:
		a.answer(line, parsed.ID, session.NewRefusal(CodeCommandUnknown, map[string]any{"command": parsed.Command}), nil)
	}
}

// handleOpen opens a stream of the agent's Python on the live session.
func (a *AgentControl) handleOpen(line *LineConnection, first *FirstLine) {
	link := a.currentLink()
	if link == nil {
		line.Close()
		return
	}
	peer := link.session()
	if peer == nil {
		line.Close()
		return
	}
	stream, err := peer.OpenRaw(a.ctx, first.Open)
	if err != nil {
		line.Close()
		return
	}
	serveOpened(line.StreamConn(), stream, first.Open)
}

func (a *AgentControl) currentLink() *agentLink {
	a.linkMu.Lock()
	defer a.linkMu.Unlock()
	return a.link
}

// startLink replaces the link with one dialling addresses under settings.
func (a *AgentControl) startLink(settings dialSettings, addresses []string) {
	link := newAgentLink(a, settings, addresses)
	a.linkMu.Lock()
	earlier := a.link
	a.link = link
	select {
	case <-a.ready:
		a.ready = make(chan struct{})
	default:
	}
	a.linkMu.Unlock()
	if earlier != nil {
		earlier.stop()
	}
	go link.run()
}

// settingsOf reads a dial command's keys. It returns body_invalid for a key
// that is not 64 hex characters.
func settingsOf(command dialCommand, isJoin bool, timings session.Timings) (dialSettings, *session.Refusal) {
	static, err := handshake.KeyFromPrivate(command.PrivateKey)
	if err != nil {
		return dialSettings{}, session.NewRefusal(CodeBodyInvalid, map[string]any{"field": "private_key"})
	}
	hubPublic, err := handshake.DecodeKey(command.HubKey)
	if err != nil {
		return dialSettings{}, session.NewRefusal(CodeBodyInvalid, map[string]any{"field": "hub_key"})
	}
	psk := handshake.ZeroPsk
	if !isJoin {
		psk, err = handshake.DecodeKey(command.Psk)
		if err != nil {
			return dialSettings{}, session.NewRefusal(CodeBodyInvalid, map[string]any{"field": "psk"})
		}
	}
	role := command.Role
	if role == "" {
		role = RoleAgent
	}
	return dialSettings{static: static, hubPublic: hubPublic, psk: psk, protocol: command.Protocol, role: role, isJoin: isJoin, timings: timings}, nil
}

// joinOrLeave dials a round and sends the one join or leave frame on its
// winner, answering with the hub's word.
func (a *AgentControl) joinOrLeave(line *LineConnection, parsed peerLine) {
	var command dialCommand
	if err := json.Unmarshal(parsed.raw, &command); err != nil {
		a.answer(line, parsed.ID, session.NewRefusal(CodeBodyInvalid, nil), nil)
		return
	}
	isJoin := parsed.Command == CommandJoin
	settings, refusal := settingsOf(command, isJoin, a.timings)
	if refusal != nil {
		a.answer(line, parsed.ID, refusal, nil)
		return
	}
	result := dialInOrder(a.ctx, command.Addresses, settings)
	if result.refusal != nil {
		a.answer(line, parsed.ID, result.refusal, nil)
		return
	}
	extra, refusal := sendJoinOrLeave(result.session, parsed.raw, isJoin)
	a.answer(line, parsed.ID, refusal, extra)
}

// sendJoinOrLeave writes the join or leave frame on a fresh session and reads
// the hub's answer, then closes the session. It returns the join's
// {binding_id, token}, or the refusal.
func sendJoinOrLeave(peer *PeerSession, raw []byte, isJoin bool) (map[string]any, *session.Refusal) {
	defer peer.Close()
	var fields map[string]any
	_ = json.Unmarshal(raw, &fields)
	for _, key := range []string{"id", "command", "hub_key", "private_key", "psk", "addresses", "candidates", "binding"} {
		delete(fields, key)
	}
	frameType := session.FrameLeave
	if isJoin {
		frameType = session.FrameJoin
	} else {
		fields = map[string]any{}
	}
	if err := peer.WriteFrame(session.MakeFrame(frameType, fields)); err != nil {
		return nil, hubUnreachable(err)
	}
	frame, err := peer.ReadFrame()
	if err != nil {
		return nil, hubUnreachable(err)
	}
	kind, _ := session.FrameType(frame)
	switch kind {
	case session.FrameJoined:
		var joined struct {
			ID    string `json:"id"`
			Token string `json:"token"`
		}
		_ = json.Unmarshal(frame, &joined)
		return map[string]any{"binding_id": joined.ID, "token": joined.Token}, nil
	case session.FrameLeft:
		return nil, nil
	case session.FrameRefused:
		return nil, session.ParseRefused(frame)
	}
	return nil, session.NewRefusal(session.CodeHelloInvalid, nil)
}

// startForward binds a forward, before or after a dial; it accepts nothing
// until a session is live.
func (a *AgentControl) startForward(command forwardCommand) (string, *session.Refusal) {
	protocol := command.Protocol
	if protocol == "" {
		protocol = session.ProtocolTCP
	}
	onEnd := func(forward *relay.Forward, refusal *session.Refusal) {
		a.linkMu.Lock()
		delete(a.forwards, forwardKey(forward.Listen, protocol))
		a.linkMu.Unlock()
		code, params := refusalFields(refusal)
		a.event(EventForwardEnd, map[string]any{"listen": forward.Listen, "protocol": protocol, "code": code, "params": params})
	}
	forward, refusal, err := relay.StartForward(a.ctx, command.Listen, protocol, command.Open, a, onEnd)
	if err != nil {
		return "", session.NewRefusal(CodeBodyInvalid, map[string]any{"detail": err.Error()})
	}
	if refusal != nil {
		return "", refusal
	}
	key := forwardKey(forward.Listen, protocol)
	a.linkMu.Lock()
	if earlier, ok := a.forwards[key]; ok {
		earlier.Stop()
	}
	a.forwards[key] = forward
	a.linkMu.Unlock()
	return forward.Listen, nil
}

func (a *AgentControl) stopForward(listen, protocol string) *session.Refusal {
	key := forwardKey(listen, protocol)
	a.linkMu.Lock()
	forward, ok := a.forwards[key]
	delete(a.forwards, key)
	a.linkMu.Unlock()
	if !ok {
		return session.NewRefusal(CodeForwardUnknown, map[string]any{"listen": listen})
	}
	forward.Stop()
	return nil
}

// agentLink is the agent's one dialling loop: it keeps a session to the hub
// across the rounds and the redial rule.
type agentLink struct {
	control   *AgentControl
	settings  dialSettings
	addresses []string
	ctx       context.Context
	cancel    context.CancelFunc

	// mu guards current.
	mu      sync.Mutex
	current *PeerSession
}

func newAgentLink(control *AgentControl, settings dialSettings, addresses []string) *agentLink {
	ctx, cancel := context.WithCancel(control.ctx)
	return &agentLink{control: control, settings: settings, addresses: addresses, ctx: ctx, cancel: cancel}
}

// run dials rounds until stopped: at once after a drop, then backing off
// while rounds fail; after a refusal, a minute later; after replaced or
// binding_unknown, no more.
func (l *agentLink) run() {
	wait := newBackoff()
	for l.ctx.Err() == nil {
		result := dialInOrder(l.ctx, l.addresses, l.settings)
		if l.ctx.Err() != nil {
			return
		}
		if result.session == nil {
			refusal := result.refusal
			isFinalRefusal := isFinal(refusal)
			var next time.Duration
			switch {
			case isFinalRefusal:
			case refusal.Code == session.CodeHubUnreachable || refusal.Code == session.CodeHubUntrusted:
				next = wait.take()
			default:
				next = waitAfterRefusal(refusal)
			}
			l.control.event(EventRoundEnd, map[string]any{"code": refusal.Code, "params": refusal.Params, "next_round_s": next.Seconds()})
			if isFinalRefusal {
				return
			}
			select {
			case <-l.ctx.Done():
				return
			case <-time.After(next):
			}
			continue
		}
		wait.reset()
		peer := result.session
		l.setSession(peer)
		l.control.log("session_open", "address", peer.Address)
		l.control.event(EventSessionOpen, map[string]any{"address": peer.Address, "local_address": peer.LocalAddress})
		go l.acceptStreams(peer)
		l.readFrames(peer)
		l.setSession(nil)
		refusal := peer.Refusal()
		peer.Close()
		code, params := refusalFields(refusal)
		l.control.log("session_end", "address", peer.Address, "code", code)
		l.control.event(EventSessionEnd, map[string]any{"code": code, "params": params})
		if refusal == nil {
			continue
		}
		if isFinal(refusal) {
			return
		}
		select {
		case <-l.ctx.Done():
			return
		case <-time.After(waitAfterRefusal(refusal)):
		}
	}
}

// readFrames passes every frame from the hub to the agent until the session
// ends.
func (l *agentLink) readFrames(peer *PeerSession) {
	for {
		frame, err := peer.ReadFrame()
		if err != nil {
			return
		}
		l.control.frame(frame, "", "")
	}
}

// acceptStreams serves the streams the hub opens: a connect is dialled after
// the port question, every other kind handed to the agent.
func (l *agentLink) acceptStreams(peer *PeerSession) {
	for {
		stream, err := peer.AcceptStream()
		if err != nil {
			return
		}
		go l.handleStream(stream)
	}
}

func (l *agentLink) handleStream(stream *yamux.Stream) {
	record := relay.NewRecordStream(stream)
	_ = stream.SetReadDeadline(time.Now().Add(relay.RelayOpenRecordTimeout))
	open, err := session.ReadRecord(record.Reader)
	_ = stream.SetReadDeadline(time.Time{})
	if err != nil || open.Type != session.RecordOpen {
		stream.Reset()
		return
	}
	kind, err := session.OpenKind(open.Payload)
	if err != nil {
		_, _ = stream.Write(session.CloseRecord(session.CodeKindUnknown, nil))
		stream.Close()
		return
	}
	if kind != session.KindConnect {
		id := "t" + time.Now().Format("150405.000000000")
		l.control.handOff.Announce(id, record)
		l.control.event(EventStream, map[string]any{"stream": id, "open": json.RawMessage(open.Payload)})
		return
	}
	l.serveConnect(record, open.Payload)
}

// serveConnect asks the agent whether a port is published and dials it.
func (l *agentLink) serveConnect(record *relay.RecordStream, open []byte) {
	stream := record.Stream
	var fields struct {
		Port     int    `json:"port"`
		Protocol string `json:"protocol"`
	}
	_ = json.Unmarshal(open, &fields)
	if fields.Protocol == "" {
		fields.Protocol = session.ProtocolTCP
	}
	ctx, cancel := context.WithTimeout(l.ctx, ControlQuestionTimeout)
	answer, err := l.control.ask(ctx, QuestionPort, map[string]any{"port": fields.Port, "protocol": fields.Protocol})
	cancel()
	if err != nil {
		refusal, ok := err.(*session.Refusal)
		if !ok {
			refusal = session.NewRefusal(session.CodeControlUnavailable, nil)
		}
		_, _ = stream.Write(session.CloseRecord(refusal.Code, refusal.Params))
		stream.Close()
		return
	}
	address, _ := answer["address"].(string)
	if address == "" {
		address = "127.0.0.1"
	}
	if fields.Protocol == session.ProtocolUDP {
		farEnd, refusal := relay.NewUdpFarEnd(stream, address, fields.Port)
		if refusal != nil {
			_, _ = stream.Write(session.CloseRecord(refusal.Code, refusal.Params))
			stream.Close()
			return
		}
		if _, err := stream.Write(session.AcceptRecord()); err != nil {
			farEnd.Close()
			return
		}
		farEnd.Serve()
		return
	}
	conn, refusal := relay.DialFarEnd(l.ctx, address, fields.Port)
	if refusal != nil {
		_, _ = stream.Write(session.CloseRecord(refusal.Code, refusal.Params))
		stream.Close()
		return
	}
	if _, err := stream.Write(session.AcceptRecord()); err != nil {
		conn.Close()
		stream.Close()
		return
	}
	relay.Splice(&readerConn{Conn: stream, reader: record.Reader}, conn)
}

func (l *agentLink) setSession(peer *PeerSession) {
	l.mu.Lock()
	l.current = peer
	l.mu.Unlock()
	l.control.setLive(l, peer != nil)
}

func (l *agentLink) session() *PeerSession {
	l.mu.Lock()
	defer l.mu.Unlock()
	return l.current
}

func (l *agentLink) writeFrame(frame []byte) error {
	peer := l.session()
	if peer == nil {
		return relay.ErrNoSession
	}
	return peer.WriteFrame(frame)
}

func (l *agentLink) stop() {
	l.cancel()
	if peer := l.session(); peer != nil {
		peer.Close()
	}
}

// OpenStream opens a stream on the live session.
func (l *agentLink) OpenStream(ctx context.Context, open json.RawMessage) (*relay.RecordStream, *session.Refusal, error) {
	peer := l.session()
	if peer == nil {
		return nil, nil, relay.ErrNoSession
	}
	return peer.OpenStream(ctx, open)
}
