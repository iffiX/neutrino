package control

import (
	"context"
	"encoding/json"
	"net"
	"sync"
	"time"

	"github.com/libp2p/go-yamux/v4"

	"github.com/iffiX/neutrino/transport/relay"
	"github.com/iffiX/neutrino/transport/session"
)

// ClientControl is the client's local channel: one session to every hub the
// client is bound to, each named by its binding, and the client's commands.
type ClientControl struct {
	peerBase
	timings session.Timings
	ctx     context.Context
	cancel  context.CancelFunc

	// linkMu guards links and forwards.
	linkMu   sync.Mutex
	links    map[string]*clientLink
	forwards map[string]*relay.Forward
}

// clientDialCommand is the client's dial, with its candidates.
type clientDialCommand struct {
	dialCommand
	Binding    string      `json:"binding"`
	Candidates []candidate `json:"candidates"`
}

// NewClientControl makes the client's local channel on listener.
func NewClientControl(listener net.Listener, secret string, timings session.Timings, log relay.EventFunc) *ClientControl {
	ctx, cancel := context.WithCancel(context.Background())
	if timings.KeepAliveInterval == 0 {
		timings = session.DefaultTimings
	}
	return &ClientControl{
		peerBase: newPeerBase(listener, secret, log),
		timings:  timings,
		ctx:      ctx,
		cancel:   cancel,
		links:    make(map[string]*clientLink),
		forwards: make(map[string]*relay.Forward),
	}
}

// Serve accepts local connections until Close.
func (c *ClientControl) Serve() {
	c.serve(c.handleLine, c.handleOpen)
}

// Close ends every session, every forward and the listener.
func (c *ClientControl) Close() {
	c.cancel()
	c.linkMu.Lock()
	links := c.links
	c.links = make(map[string]*clientLink)
	forwards := c.forwards
	c.forwards = make(map[string]*relay.Forward)
	c.linkMu.Unlock()
	for _, link := range links {
		link.stop()
	}
	for _, forward := range forwards {
		forward.Stop()
	}
	c.close()
}

func (c *ClientControl) handleLine(line *LineConnection, parsed peerLine) {
	if len(parsed.Frame) > 0 {
		link := c.link(parsed.Binding)
		if link == nil {
			return
		}
		if err := link.writeFrame(parsed.Frame); err != nil {
			c.log("frame_dropped", "binding", parsed.Binding, "error", err.Error())
		}
		return
	}
	switch parsed.Command {
	case CommandDial:
		var command clientDialCommand
		if err := json.Unmarshal(parsed.raw, &command); err != nil {
			c.answer(line, parsed.ID, session.NewRefusal(CodeBodyInvalid, nil), nil)
			return
		}
		if command.Role == "" {
			command.Role = RoleClient
		}
		settings, refusal := settingsOf(command.dialCommand, false, c.timings)
		if refusal != nil {
			c.answer(line, parsed.ID, refusal, nil)
			return
		}
		candidates := command.Candidates
		for _, address := range command.Addresses {
			candidates = append(candidates, candidate{Address: address})
		}
		c.dial(command.Binding, settings, candidates)
		c.answer(line, parsed.ID, nil, nil)
	case CommandUndial:
		c.linkMu.Lock()
		link, ok := c.links[parsed.Binding]
		delete(c.links, parsed.Binding)
		c.linkMu.Unlock()
		if ok {
			link.stop()
		}
		c.answer(line, parsed.ID, nil, nil)
	case CommandRound:
		link := c.link(parsed.Binding)
		if link == nil {
			c.answer(line, parsed.ID, session.NewRefusal(CodeBindingUnknown, map[string]any{"binding": parsed.Binding}), nil)
			return
		}
		link.roundNow()
		c.answer(line, parsed.ID, nil, nil)
	case CommandJoin, CommandLeave:
		go c.joinOrLeave(line, parsed)
	case CommandForwardStart:
		var command forwardCommand
		if err := json.Unmarshal(parsed.raw, &command); err != nil {
			c.answer(line, parsed.ID, session.NewRefusal(CodeBodyInvalid, nil), nil)
			return
		}
		listen, refusal := c.startForward(command)
		c.answer(line, parsed.ID, refusal, map[string]any{"listen": listen})
	case CommandForwardStop:
		var command forwardCommand
		_ = json.Unmarshal(parsed.raw, &command)
		c.answer(line, parsed.ID, c.stopForward(command.Listen, command.Protocol), nil)
	default:
		c.answer(line, parsed.ID, session.NewRefusal(CodeCommandUnknown, map[string]any{"command": parsed.Command}), nil)
	}
}

// handleOpen opens a stream of the client's own on a hub's live session.
func (c *ClientControl) handleOpen(line *LineConnection, first *FirstLine) {
	link := c.link(first.Binding)
	if link == nil {
		line.Close()
		return
	}
	peer := link.session()
	if peer == nil {
		line.Close()
		return
	}
	stream, err := peer.OpenRaw(c.ctx, first.Open)
	if err != nil {
		line.Close()
		return
	}
	serveOpened(line.StreamConn(), stream, first.Open)
}

func (c *ClientControl) link(binding string) *clientLink {
	c.linkMu.Lock()
	defer c.linkMu.Unlock()
	return c.links[binding]
}

// dial starts a link for a binding, or gives an existing one new candidates
// and keeps its live session.
func (c *ClientControl) dial(binding string, settings dialSettings, candidates []candidate) {
	c.linkMu.Lock()
	link, ok := c.links[binding]
	if ok {
		link.replaceCandidates(settings, candidates)
		c.linkMu.Unlock()
		return
	}
	link = newClientLink(c, binding, settings, candidates)
	c.links[binding] = link
	c.linkMu.Unlock()
	go link.run()
}

// joinOrLeave dials a round at once and sends the one join or leave frame on
// its winner.
func (c *ClientControl) joinOrLeave(line *LineConnection, parsed peerLine) {
	var command clientDialCommand
	if err := json.Unmarshal(parsed.raw, &command); err != nil {
		c.answer(line, parsed.ID, session.NewRefusal(CodeBodyInvalid, nil), nil)
		return
	}
	if command.Role == "" {
		command.Role = RoleClient
	}
	isJoin := parsed.Command == CommandJoin
	settings, refusal := settingsOf(command.dialCommand, isJoin, c.timings)
	if refusal != nil {
		c.answer(line, parsed.ID, refusal, nil)
		return
	}
	candidates := command.Candidates
	for _, address := range command.Addresses {
		candidates = append(candidates, candidate{Address: address})
	}
	result := dialAtOnce(c.ctx, candidates, settings)
	if result.refusal != nil {
		c.answer(line, parsed.ID, result.refusal, nil)
		return
	}
	extra, refusal := sendJoinOrLeave(result.session, parsed.raw, isJoin)
	c.answer(line, parsed.ID, refusal, extra)
}

func (c *ClientControl) startForward(command forwardCommand) (string, *session.Refusal) {
	link := c.link(command.Binding)
	if link == nil {
		return "", session.NewRefusal(CodeBindingUnknown, map[string]any{"binding": command.Binding})
	}
	protocol := command.Protocol
	if protocol == "" {
		protocol = session.ProtocolTCP
	}
	onEnd := func(forward *relay.Forward, refusal *session.Refusal) {
		c.linkMu.Lock()
		delete(c.forwards, forwardKey(forward.Listen, protocol))
		c.linkMu.Unlock()
		code, params := refusalFields(refusal)
		c.event(EventForwardEnd, map[string]any{"listen": forward.Listen, "protocol": protocol, "code": code, "params": params})
	}
	forward, refusal, err := relay.StartForward(c.ctx, command.Listen, protocol, command.Open, link, onEnd)
	if err != nil {
		return "", session.NewRefusal(CodeBodyInvalid, map[string]any{"detail": err.Error()})
	}
	if refusal != nil {
		return "", refusal
	}
	key := forwardKey(forward.Listen, protocol)
	c.linkMu.Lock()
	if earlier, ok := c.forwards[key]; ok {
		earlier.Stop()
	}
	c.forwards[key] = forward
	c.linkMu.Unlock()
	return forward.Listen, nil
}

func (c *ClientControl) stopForward(listen, protocol string) *session.Refusal {
	key := forwardKey(listen, protocol)
	c.linkMu.Lock()
	forward, ok := c.forwards[key]
	delete(c.forwards, key)
	c.linkMu.Unlock()
	if !ok {
		return session.NewRefusal(CodeForwardUnknown, map[string]any{"listen": listen})
	}
	forward.Stop()
	return nil
}

// clientLink is one binding's dialling loop: rounds at once, the redial
// rule, and the move to a better path when a round beside the live session
// wins.
type clientLink struct {
	control *ClientControl
	binding string
	ctx     context.Context
	cancel  context.CancelFunc
	wake    chan struct{}

	// mu guards settings, candidates, current and ready.
	mu         sync.Mutex
	settings   dialSettings
	candidates []candidate
	current    *PeerSession
	ready      chan struct{}
}

func newClientLink(control *ClientControl, binding string, settings dialSettings, candidates []candidate) *clientLink {
	ctx, cancel := context.WithCancel(control.ctx)
	return &clientLink{control: control, binding: binding, ctx: ctx, cancel: cancel, wake: make(chan struct{}, 1), settings: settings, candidates: candidates, ready: make(chan struct{})}
}

func (l *clientLink) replaceCandidates(settings dialSettings, candidates []candidate) {
	l.mu.Lock()
	l.settings = settings
	l.candidates = candidates
	l.mu.Unlock()
}

// roundNow asks for a round at once: it ends a wait, or runs beside the live
// session.
func (l *clientLink) roundNow() {
	select {
	case l.wake <- struct{}{}:
	default:
	}
}

func (l *clientLink) snapshot() (dialSettings, []candidate) {
	l.mu.Lock()
	defer l.mu.Unlock()
	return l.settings, append([]candidate(nil), l.candidates...)
}

// run dials rounds until stopped, by the redial rule.
func (l *clientLink) run() {
	wait := newBackoff()
	isWaitingForPerson := false
	for l.ctx.Err() == nil {
		if isWaitingForPerson {
			select {
			case <-l.ctx.Done():
				return
			case <-l.wake:
				isWaitingForPerson = false
			}
		}
		settings, candidates := l.snapshot()
		result := dialAtOnce(l.ctx, candidates, settings)
		if l.ctx.Err() != nil {
			return
		}
		if result.session == nil {
			refusal := result.refusal
			var next time.Duration
			switch {
			case isFinal(refusal):
				isWaitingForPerson = true
			case refusal.Code == session.CodeHubUnreachable:
				next = wait.take()
			case refusal.Code == session.CodeHubUntrusted:
				next = session.RedialBackoffMax
			default:
				next = waitAfterRefusal(refusal)
			}
			l.control.event(EventRoundEnd, map[string]any{"binding": l.binding, "code": refusal.Code, "params": refusal.Params, "next_round_s": next.Seconds()})
			if isWaitingForPerson {
				continue
			}
			select {
			case <-l.ctx.Done():
				return
			case <-time.After(next):
			case <-l.wake:
				wait.reset()
			}
			continue
		}
		wait.reset()
		live := result.session
		l.setSession(live)
		l.announce(live)
		refusal := l.serveLive(live)
		if l.ctx.Err() != nil {
			return
		}
		switch {
		case refusal == nil:
			continue
		case isFinal(refusal):
			isWaitingForPerson = true
		default:
			select {
			case <-l.ctx.Done():
				return
			case <-time.After(waitAfterRefusal(refusal)):
			case <-l.wake:
			}
		}
	}
}

// announce tells the client a session is open and starts serving it.
func (l *clientLink) announce(live *PeerSession) {
	l.control.log("session_open", "binding", l.binding, "address", live.Address, "path", live.Path)
	l.control.event(EventSessionOpen, map[string]any{
		"binding": l.binding, "address": live.Address, "path": live.Path,
		"handshake_ms": live.HandshakeTime.Milliseconds(),
	})
	go l.readFrames(live)
	go l.closeStreams(live)
}

// serveLive waits on the live session, running a round beside it on each
// wake and moving to a better winner, until the channel's session ends. It
// returns the refusal that ended it, if any.
func (l *clientLink) serveLive(live *PeerSession) *session.Refusal {
	winners := make(chan *PeerSession, 1)
	isRoundRunning := false
	for {
		select {
		case <-l.ctx.Done():
			live.Close()
			return nil
		case <-live.CloseChan():
			refusal := live.Refusal()
			l.setSession(nil)
			live.Close()
			code, params := refusalFields(refusal)
			l.control.log("session_end", "binding", l.binding, "code", code)
			l.control.event(EventSessionEnd, map[string]any{"binding": l.binding, "code": code, "params": params})
			return refusal
		case <-l.wake:
			if isRoundRunning {
				continue
			}
			isRoundRunning = true
			settings, candidates := l.snapshot()
			go func() {
				result := dialAtOnce(l.ctx, candidates, settings)
				winners <- result.session
			}()
		case winner := <-winners:
			isRoundRunning = false
			if winner == nil {
				continue
			}
			if !isBetter(winner, live) {
				winner.Close()
				continue
			}
			old := live
			old.MarkMoved()
			live = winner
			l.setSession(live)
			l.control.log("session_moved", "binding", l.binding, "address", live.Address, "path", live.Path)
			l.announce(live)
			go func() {
				select {
				case <-live.HubFrames():
					time.Sleep(ControlMoveGrace)
				case <-old.CloseChan():
				case <-time.After(session.HelloTimeout):
				}
				old.Close()
			}()
		}
	}
}

// readFrames passes every frame from the hub to the client, dropping those
// of a session moved off.
func (l *clientLink) readFrames(peer *PeerSession) {
	for {
		frame, err := peer.ReadFrame()
		if err != nil {
			return
		}
		if peer.IsMoved() {
			continue
		}
		l.control.frame(frame, "binding", l.binding)
	}
}

// closeStreams closes every stream the hub opens on a client, which takes
// none.
func (l *clientLink) closeStreams(peer *PeerSession) {
	for {
		stream, err := peer.AcceptStream()
		if err != nil {
			return
		}
		go func(stream *yamux.Stream) {
			_, _ = stream.Write(session.CloseRecord(session.CodeKindUnknown, nil))
			stream.Close()
		}(stream)
	}
}

func (l *clientLink) setSession(peer *PeerSession) {
	l.mu.Lock()
	defer l.mu.Unlock()
	wasLive := l.current != nil
	l.current = peer
	if peer != nil && !wasLive {
		close(l.ready)
	} else if peer == nil && wasLive {
		l.ready = make(chan struct{})
	}
}

func (l *clientLink) session() *PeerSession {
	l.mu.Lock()
	defer l.mu.Unlock()
	return l.current
}

func (l *clientLink) writeFrame(frame []byte) error {
	peer := l.session()
	if peer == nil {
		return relay.ErrNoSession
	}
	return peer.WriteFrame(frame)
}

func (l *clientLink) stop() {
	l.cancel()
	if peer := l.session(); peer != nil {
		peer.Close()
	}
}

// OpenStream opens a stream on the live session for a forward.
func (l *clientLink) OpenStream(ctx context.Context, open json.RawMessage) (*relay.RecordStream, *session.Refusal, error) {
	peer := l.session()
	if peer == nil {
		return nil, nil, relay.ErrNoSession
	}
	return peer.OpenStream(ctx, open)
}

// Ready is closed while a session is live.
func (l *clientLink) Ready() <-chan struct{} {
	l.mu.Lock()
	defer l.mu.Unlock()
	return l.ready
}
