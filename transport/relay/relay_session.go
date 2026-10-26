package relay

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"sync"
	"time"

	"github.com/libp2p/go-yamux/v4"

	"github.com/iffiX/neutrino/transport/session"
)

// The reasons a session ends with.
const (
	EndPeerClosed       = "peer_closed"
	EndKeepAliveTimeout = "keepalive_timeout"
	EndReplaced         = "replaced"
	EndClosedByHub      = "closed_by_hub"
	EndFrameTooLarge    = "frame_too_large"
	EndReadError        = "read_error"
)

// RelaySession is one admitted session on the hub: the peer's binding, its
// control stream, and the streams the hub relays for it.
type RelaySession struct {
	ID        string
	BindingID string
	Role      string
	Protocol  int
	Address   string
	Listener  string
	PublicKey string

	hub     *Hub
	session *session.Session
	control *session.ControlStream

	// mu guards hello, isWelcomed, isEnded, endReason, streams and connects.
	mu         sync.Mutex
	hello      []byte
	isWelcomed bool
	isEnded    bool
	endReason  string
	streams    map[*relayStream]struct{}
	connects   int
}

// Hello is the hello frame the session was admitted with.
func (rs *RelaySession) Hello() []byte {
	rs.mu.Lock()
	defer rs.mu.Unlock()
	return rs.hello
}

// IsWelcomed reports whether the Python sent welcome.
func (rs *RelaySession) IsWelcomed() bool {
	rs.mu.Lock()
	defer rs.mu.Unlock()
	return rs.isWelcomed
}

func (rs *RelaySession) markWelcomed() {
	rs.mu.Lock()
	defer rs.mu.Unlock()
	rs.isWelcomed = true
}

// openEvent is the session_open event's fields.
func (rs *RelaySession) openEvent() map[string]any {
	return map[string]any{
		"session": rs.ID, "binding_id": rs.BindingID, "role": rs.Role,
		"address": rs.Address, "listener": rs.Listener,
	}
}

// OpenEvent is the session_open event's fields, for a new control connection.
func (rs *RelaySession) OpenEvent() map[string]any {
	return rs.openEvent()
}

// writeRefusedAndEnd writes a refused frame as the first frame and ends the
// session after the peer had time to read it.
func (rs *RelaySession) writeRefusedAndEnd(refusal *session.Refusal) {
	rs.hub.log("refused", "address", rs.Address, "code", refusal.Code)
	_ = rs.control.WriteFrame(session.RefusedFrame(refusal))
	rs.endSoon(EndClosedByHub)
}

// refuse sends refused {code, params} on a live session and ends it.
func (rs *RelaySession) refuse(refusal *session.Refusal, reason string) {
	_ = rs.control.WriteFrame(session.RefusedFrame(refusal))
	rs.endSoon(reason)
}

// endSoon ends the session once the peer closed it or RelayEndGrace passed,
// with reason whatever ends it first.
func (rs *RelaySession) endSoon(reason string) {
	rs.mu.Lock()
	if rs.endReason == "" {
		rs.endReason = reason
	}
	rs.mu.Unlock()
	_ = rs.control.CloseWrite()
	go func() {
		select {
		case <-rs.session.CloseChan():
		case <-time.After(RelayEndGrace):
		}
		rs.end(reason)
	}()
}

// isEnding reports whether endSoon is waiting for the peer to read.
func (rs *RelaySession) isEnding() bool {
	rs.mu.Lock()
	defer rs.mu.Unlock()
	return rs.endReason != ""
}

// IsEnded reports whether the session ended.
func (rs *RelaySession) IsEnded() bool {
	rs.mu.Lock()
	defer rs.mu.Unlock()
	return rs.isEnded
}

// end closes the session and tells the Python once.
func (rs *RelaySession) end(reason string) {
	rs.mu.Lock()
	if rs.isEnded {
		rs.mu.Unlock()
		return
	}
	rs.isEnded = true
	if rs.endReason != "" {
		reason = rs.endReason
	}
	wasRegistered := rs.hello != nil
	rs.mu.Unlock()
	_ = rs.session.Close()
	if !wasRegistered {
		return
	}
	rs.hub.unregister(rs)
	if reason == EndKeepAliveTimeout {
		rs.hub.logKeepAlive(rs.Address)
	}
	rs.hub.log("session_end", "session", rs.ID, "reason", reason)
	rs.hub.python.Event("session_end", map[string]any{"session": rs.ID, "reason": reason})
}

// watchEnd ends the session when yamux ends it.
func (rs *RelaySession) watchEnd() {
	<-rs.session.CloseChan()
	rs.end(EndPeerClosed)
}

// readFrames passes the peer's frames to the Python, answering ping and a
// client's service itself, until the control stream ends.
func (rs *RelaySession) readFrames() {
	for {
		frame, err := rs.control.ReadFrame()
		if err != nil {
			if !rs.isEnding() {
				rs.end(endReason(err))
			}
			return
		}
		frameType, err := session.FrameType(frame)
		if err != nil {
			continue
		}
		switch {
		case frameType == session.FramePing:
			_ = rs.control.WriteFrame(session.PongFrame(frame))
		case frameType == session.FrameService && rs.Role == "client":
			go rs.answerService(frame)
		default:
			rs.hub.python.Frame(rs.ID, frame)
		}
	}
}

// endReason names why reading the control stream ended.
func endReason(err error) string {
	switch {
	case errors.Is(err, io.EOF), errors.Is(err, yamux.ErrSessionShutdown), errors.Is(err, yamux.ErrStreamClosed), errors.Is(err, yamux.ErrStreamReset):
		return EndPeerClosed
	case errors.Is(err, yamux.ErrKeepAliveTimeout):
		return EndKeepAliveTimeout
	case errors.Is(err, session.ErrFrameTooLarge):
		return EndFrameTooLarge
	}
	return EndReadError
}

// answerService asks the Python the token question for a client's service
// frame and writes the reply.
func (rs *RelaySession) answerService(frame []byte) {
	var body struct {
		Request string `json:"request"`
	}
	_ = json.Unmarshal(frame, &body)
	answer, refusal := rs.hub.ask("token", map[string]any{"session": rs.ID, "binding_id": rs.BindingID, "frame": json.RawMessage(frame)})
	reply := map[string]any{"request": body.Request}
	if refusal != nil {
		reply["code"] = refusal.Code
		reply["params"] = refusal.Params
	} else {
		params, ok := answer["params"]
		if !ok {
			params = map[string]any{}
		}
		reply["params"] = params
	}
	_ = rs.control.WriteFrame(session.MakeFrame(session.FrameReply, reply))
}

// acceptStreams handles every stream the peer opens after the control
// stream.
func (rs *RelaySession) acceptStreams() {
	for {
		stream, err := rs.session.AcceptStream()
		if err != nil {
			return
		}
		go rs.handleStream(stream)
	}
}

// handleStream reads a stream's open record and relays or hands the stream
// by its kind.
func (rs *RelaySession) handleStream(stream *yamux.Stream) {
	record := NewRecordStream(stream)
	_ = stream.SetReadDeadline(time.Now().Add(RelayOpenRecordTimeout))
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
	switch {
	case rs.Role == "client" && kind == session.KindConnect:
		rs.relayConnect(record, open.Payload)
	case rs.Role == "client" && (kind == session.KindShell || kind == session.KindExec):
		rs.relayRecords(record, open.Payload)
	case rs.Role == "agent" && kind == session.KindConnect:
		rs.relayConnect(record, open.Payload)
	case rs.Role == "agent" && (kind == session.KindLog || kind == session.KindPackage):
		id := rs.hub.newStreamID()
		rs.hub.handOff.Announce(id, record)
		rs.hub.python.Event("stream", map[string]any{"stream": id, "session": rs.ID, "open": json.RawMessage(open.Payload)})
	default:
		_, _ = stream.Write(session.CloseRecord(session.CodeKindUnknown, map[string]any{"kind": kind}))
		stream.Close()
	}
}

// entryTarget is the Python's answer to an entry question.
type entryTarget struct {
	Kind     string `json:"kind"`
	DeviceID string `json:"device_id"`
	Target   struct {
		Session  string          `json:"session"`
		Open     json.RawMessage `json:"open"`
		Address  string          `json:"address"`
		Port     int             `json:"port"`
		Protocol string          `json:"protocol"`
	} `json:"target"`
}

// askEntry asks the Python about an open and reads the target.
func (rs *RelaySession) askEntry(open []byte) (*entryTarget, *session.Refusal) {
	answer, refusal := rs.hub.ask("entry", map[string]any{"session": rs.ID, "binding_id": rs.BindingID, "open": json.RawMessage(open)})
	if refusal != nil {
		return nil, refusal
	}
	encoded, err := json.Marshal(answer)
	if err != nil {
		return nil, session.NewRefusal(session.CodeControlUnavailable, nil)
	}
	var target entryTarget
	if err := json.Unmarshal(encoded, &target); err != nil {
		return nil, session.NewRefusal(session.CodeControlUnavailable, nil)
	}
	return &target, nil
}

// relayConnect joins a connect stream to its far end: an agent's stream or a
// socket the hub dials itself.
func (rs *RelaySession) relayConnect(record *RecordStream, open []byte) {
	stream := record.Stream
	if rs.Role == "client" && !rs.takeConnect() {
		_, _ = stream.Write(session.CloseRecord(session.CodeConnectLimit, map[string]any{"limit": session.ConnectStreamsMax}))
		stream.Close()
		return
	}
	if rs.Role == "client" {
		defer rs.releaseConnect()
	}
	target, refusal := rs.askEntry(open)
	if refusal != nil {
		_, _ = stream.Write(session.CloseRecord(refusal.Code, refusal.Params))
		stream.Close()
		return
	}
	protocol := target.Target.Protocol
	if protocol == "" {
		protocol = openProtocol(target.Target.Open)
	}
	relayed := rs.addStream(target.Kind, target.DeviceID, "", target.Target.Session, stream)
	defer rs.removeStream(relayed)
	if target.Target.Session != "" {
		far, err := rs.hub.Session(target.Target.Session)
		if err != nil {
			relayed.closeWith(session.NewRefusal(session.CodeAgentOffline, map[string]any{"device": target.DeviceID}))
			return
		}
		farStream, refusal := far.openFar(target.Target.Open)
		if refusal != nil {
			relayed.closeWith(refusal)
			return
		}
		relayed.setFar(farStream.Stream)
		answer, err := ReadRecordAnswer(farStream)
		if err != nil {
			relayed.closeWith(session.NewRefusal(session.CodeAgentOffline, map[string]any{"device": target.DeviceID}))
			return
		}
		if answer != nil {
			relayed.closeWith(answer)
			return
		}
		if _, err := stream.Write(session.AcceptRecord()); err != nil {
			relayed.closeWith(nil)
			return
		}
		if protocol == session.ProtocolUDP {
			isClosePassed, isFarEnded := RelayRecords(record, farStream, true)
			rs.endRelayed(relayed, far, isClosePassed, isFarEnded)
			return
		}
		relayed.markRaw()
		Splice(stream, farStream.Stream)
		return
	}
	if protocol == session.ProtocolUDP {
		farEnd, refusal := NewUdpFarEnd(stream, target.Target.Address, target.Target.Port)
		if refusal != nil {
			relayed.closeWith(refusal)
			return
		}
		relayed.setFar(closerFunc(farEnd.Close))
		if _, err := stream.Write(session.AcceptRecord()); err != nil {
			farEnd.Close()
			return
		}
		farEnd.Serve()
		return
	}
	conn, refusal := DialFarEnd(context.Background(), target.Target.Address, target.Target.Port)
	if refusal != nil {
		relayed.closeWith(refusal)
		return
	}
	relayed.setFar(conn)
	if _, err := stream.Write(session.AcceptRecord()); err != nil {
		relayed.closeWith(nil)
		return
	}
	relayed.markRaw()
	Splice(stream, conn)
}

// relayRecords joins a client's shell or exec stream to the agent's own,
// records unchanged both ways.
func (rs *RelaySession) relayRecords(record *RecordStream, open []byte) {
	stream := record.Stream
	target, refusal := rs.askEntry(open)
	if refusal != nil {
		_, _ = stream.Write(session.CloseRecord(refusal.Code, refusal.Params))
		stream.Close()
		return
	}
	relayed := rs.addStream(target.Kind, target.DeviceID, openSessionID(open), target.Target.Session, stream)
	defer rs.removeStream(relayed)
	far, err := rs.hub.Session(target.Target.Session)
	if err != nil {
		relayed.closeWith(session.NewRefusal(session.CodeAgentOffline, map[string]any{"device": target.DeviceID}))
		return
	}
	farStream, refusal := far.openFar(target.Target.Open)
	if refusal != nil {
		relayed.closeWith(refusal)
		return
	}
	relayed.setFar(farStream.Stream)
	isClosePassed, isFarEnded := RelayRecords(record, farStream, false)
	rs.endRelayed(relayed, far, isClosePassed, isFarEnded)
}

// endRelayed closes a relayed record stream after the relay ended: with
// agent_offline when the far session is gone with no close of its own.
func (rs *RelaySession) endRelayed(relayed *relayStream, far *RelaySession, isClosePassed, isFarEnded bool) {
	if !isClosePassed && isFarEnded && far.IsEnded() {
		relayed.closeWith(session.NewRefusal(session.CodeAgentOffline, map[string]any{"device": relayed.deviceID}))
		return
	}
	relayed.closeWith(nil)
}

// openFar opens a stream on this session with an open record the Python
// gave, as the far end of a relayed stream.
func (rs *RelaySession) openFar(open json.RawMessage) (*RecordStream, *session.Refusal) {
	ctx, cancel := context.WithTimeout(context.Background(), session.ConnectDialTimeout)
	defer cancel()
	stream, err := rs.session.OpenStream(ctx)
	if err != nil {
		return nil, session.NewRefusal(session.CodeAgentOffline, nil)
	}
	if _, err := stream.Write(session.EncodeRecord(session.RecordOpen, open)); err != nil {
		stream.Close()
		return nil, session.NewRefusal(session.CodeAgentOffline, nil)
	}
	return NewRecordStream(stream), nil
}

func (rs *RelaySession) takeConnect() bool {
	rs.mu.Lock()
	defer rs.mu.Unlock()
	if rs.connects >= session.ConnectStreamsMax {
		return false
	}
	rs.connects++
	return true
}

func (rs *RelaySession) releaseConnect() {
	rs.mu.Lock()
	defer rs.mu.Unlock()
	rs.connects--
}

// ConnectCount is the number of connect streams open on the session.
func (rs *RelaySession) ConnectCount() int {
	rs.mu.Lock()
	defer rs.mu.Unlock()
	return rs.connects
}

func (rs *RelaySession) addStream(kind, deviceID, shellSessionID, farSession string, peer io.ReadWriteCloser) *relayStream {
	stream := &relayStream{kind: kind, deviceID: deviceID, shellSessionID: shellSessionID, farSession: farSession, peer: peer}
	rs.mu.Lock()
	defer rs.mu.Unlock()
	rs.streams[stream] = struct{}{}
	return stream
}

func (rs *RelaySession) removeStream(stream *relayStream) {
	rs.mu.Lock()
	defer rs.mu.Unlock()
	delete(rs.streams, stream)
}

// streamsOf are the relayed streams under kind, on the device and the kept
// shell when named.
func (rs *RelaySession) streamsOf(kind, deviceID, shellSessionID string) []*relayStream {
	rs.mu.Lock()
	defer rs.mu.Unlock()
	var matched []*relayStream
	for stream := range rs.streams {
		if stream.kind != kind {
			continue
		}
		if deviceID != "" && stream.deviceID != deviceID {
			continue
		}
		if shellSessionID != "" && stream.shellSessionID != shellSessionID {
			continue
		}
		matched = append(matched, stream)
	}
	return matched
}

// streamsTo are the relayed streams whose far end rides the session named.
func (rs *RelaySession) streamsTo(farSession string) []*relayStream {
	rs.mu.Lock()
	defer rs.mu.Unlock()
	var matched []*relayStream
	for stream := range rs.streams {
		if stream.farSession == farSession {
			matched = append(matched, stream)
		}
	}
	return matched
}

// StreamCount is the number of relayed streams the session holds.
func (rs *RelaySession) StreamCount() int {
	rs.mu.Lock()
	defer rs.mu.Unlock()
	return len(rs.streams)
}

// relayStream is one stream the hub relays for a client or an agent, kept
// for streams_close and for the end of the session it rides.
type relayStream struct {
	kind           string
	deviceID       string
	shellSessionID string
	farSession     string
	peer           io.ReadWriteCloser

	// mu guards far and isRaw.
	mu    sync.Mutex
	far   io.Closer
	isRaw bool
	once  sync.Once
}

func (s *relayStream) setFar(far io.Closer) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.far = far
}

func (s *relayStream) markRaw() {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.isRaw = true
}

// closeWith ends the stream: with a close record while it still carries
// records, with a reset once it carries raw bytes.
func (s *relayStream) closeWith(refusal *session.Refusal) {
	s.once.Do(func() {
		s.mu.Lock()
		far, isRaw := s.far, s.isRaw
		s.mu.Unlock()
		if !isRaw && refusal != nil {
			_, _ = s.peer.Write(session.CloseRecord(refusal.Code, refusal.Params))
		}
		if resetter, ok := s.peer.(interface{ Reset() error }); ok && isRaw {
			_ = resetter.Reset()
		} else {
			s.peer.Close()
		}
		if far != nil {
			far.Close()
		}
	})
}

type closerFunc func()

func (f closerFunc) Close() error {
	f()
	return nil
}

// openProtocol reads the protocol of an open record, tcp when it names none.
func openProtocol(open json.RawMessage) string {
	var fields struct {
		Protocol string `json:"protocol"`
	}
	_ = json.Unmarshal(open, &fields)
	if fields.Protocol == "" {
		return session.ProtocolTCP
	}
	return fields.Protocol
}

// openSessionID reads a shell open's kept session id, empty when none.
func openSessionID(open []byte) string {
	var fields struct {
		SessionID string `json:"session_id"`
	}
	_ = json.Unmarshal(open, &fields)
	return fields.SessionID
}
