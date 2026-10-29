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
	// LocalAddress is the hub-side address the peer's connection reached.
	LocalAddress string
	Listener     string
	PublicKey    string

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

// isClientOrGuest reports whether the session opens connect streams of its
// own and asks for material: a client's or a guest's.
func (rs *RelaySession) isClientOrGuest() bool {
	return rs.Role == RelayRoleClient || rs.Role == RelayRoleGuest
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
		"address": rs.Address, "local_address": rs.LocalAddress, "listener": rs.Listener,
	}
}

// OpenEvent is the session_open event's fields, for a new control connection.
func (rs *RelaySession) OpenEvent() map[string]any {
	return rs.openEvent()
}

// writeRefusedAndEnd writes a refused frame as the first frame and ends the
// session after the peer had time to read it.
func (rs *RelaySession) writeRefusedAndEnd(refusal *session.Refusal) {
	rs.hub.logRefused("refused", refusal, "address", rs.Address)
	_ = rs.control.WriteFrame(session.RefusedFrame(refusal))
	rs.endSoon(EndClosedByHub)
}

// refuse sends refused {code, params} on a live session and ends it.
func (rs *RelaySession) refuse(refusal *session.Refusal, reason string) {
	_ = rs.control.WriteFrame(session.RefusedFrame(refusal))
	rs.endSoon(reason)
}

// endSoon closes the session's relayed streams and ends the session once the
// peer closed it, or RelayEndGrace after the peer acknowledged every byte
// written to it, with reason whatever ends it first. The wait for the
// acknowledgement ends at the session's keepalive timeout.
func (rs *RelaySession) endSoon(reason string) {
	rs.mu.Lock()
	if rs.endReason == "" {
		rs.endReason = reason
	}
	streams := make([]*relayStream, 0, len(rs.streams))
	for stream := range rs.streams {
		streams = append(streams, stream)
	}
	rs.mu.Unlock()
	_ = rs.control.CloseWrite()
	for _, stream := range streams {
		stream.closeWith(nil)
	}
	go func() {
		flushed := make(chan struct{})
		go func() {
			rs.session.Flush(rs.hub.timings.KeepAliveTimeout)
			close(flushed)
		}()
		select {
		case <-rs.session.CloseChan():
		case <-flushed:
			select {
			case <-rs.session.CloseChan():
			case <-time.After(RelayEndGrace):
			}
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
		case frameType == session.FrameService && rs.isClientOrGuest():
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
	case rs.isClientOrGuest() && kind == session.KindConnect:
		rs.relayConnect(record, open.Payload)
	case rs.Role == RelayRoleClient && (kind == session.KindShell || kind == session.KindExec):
		rs.relayRecords(record, open.Payload)
	case rs.Role == RelayRoleAgent && kind == session.KindConnect:
		rs.relayConnect(record, open.Payload)
	case rs.Role == RelayRoleAgent && (kind == session.KindLog || kind == session.KindPackage):
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
	Key      string `json:"key"`
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
		return nil, controlUnavailable()
	}
	var target entryTarget
	if err := json.Unmarshal(encoded, &target); err != nil {
		return nil, controlUnavailable()
	}
	return &target, nil
}

// relayConnect joins a connect stream to its far end: an agent's stream or a
// socket the hub dials itself.
func (rs *RelaySession) relayConnect(record *RecordStream, open []byte) {
	stream := record.Stream
	if rs.isClientOrGuest() && !rs.takeConnect() {
		_, _ = stream.Write(session.CloseRecord(session.CodeConnectLimit, map[string]any{"limit": session.ConnectStreamsMax}))
		stream.Close()
		return
	}
	if rs.isClientOrGuest() {
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
	relayed := rs.addStream(streamTags{kind: target.Kind, deviceID: target.DeviceID, key: target.Key}, target.Target.Session, stream)
	defer rs.removeStream(relayed)
	if target.Target.Session != "" {
		far, err := rs.hub.Session(target.Target.Session)
		if err != nil {
			relayed.closeWith(session.NewRefusal(session.CodeAgentOffline, map[string]any{"device": target.DeviceID}))
			return
		}
		farStream, err := far.openFar(target.Target.Open)
		if err != nil {
			relayed.endUnopened(err)
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
			rs.endRelayed(relayed, isClosePassed, isFarEnded)
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
	relayed := rs.addStream(streamTags{kind: target.Kind, deviceID: target.DeviceID, key: target.Key, shellSessionID: openSessionID(open)}, target.Target.Session, stream)
	defer rs.removeStream(relayed)
	far, err := rs.hub.Session(target.Target.Session)
	if err != nil {
		relayed.closeWith(session.NewRefusal(session.CodeAgentOffline, map[string]any{"device": target.DeviceID}))
		return
	}
	farStream, err := far.openFar(target.Target.Open)
	if err != nil {
		relayed.endUnopened(err)
		return
	}
	relayed.setFar(farStream.Stream)
	isClosePassed, isFarEnded := RelayRecords(record, farStream, false)
	rs.endRelayed(relayed, isClosePassed, isFarEnded)
}

// endRelayed closes a relayed record stream after the relay ended: with
// agent_offline when the far side ended the stream with no close of its
// own. A peer closes every stream it serves with a close record, so a far
// end without one is the agent gone, whether or not its session has been
// marked ended yet.
func (rs *RelaySession) endRelayed(relayed *relayStream, isClosePassed, isFarEnded bool) {
	if !isClosePassed && isFarEnded {
		relayed.closeWith(session.NewRefusal(session.CodeAgentOffline, map[string]any{"device": relayed.deviceID}))
		return
	}
	relayed.closeWith(nil)
}

// openFar opens a stream on this session with an open record the Python
// gave, as the far end of a relayed stream. It returns ErrMemoryExhausted
// when the memory cap refuses the stream, and an agent_offline refusal when
// the session is gone.
func (rs *RelaySession) openFar(open json.RawMessage) (*RecordStream, error) {
	ctx, cancel := context.WithTimeout(context.Background(), session.ConnectDialTimeout)
	defer cancel()
	stream, err := rs.session.OpenStream(ctx)
	if errors.Is(err, session.ErrMemoryExhausted) {
		return nil, err
	}
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

func (rs *RelaySession) addStream(tags streamTags, farSession string, peer io.ReadWriteCloser) *relayStream {
	stream := &relayStream{streamTags: tags, farSession: farSession, peer: peer}
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

// streamsOf are the relayed streams under the filter's kind, on its device,
// under its row and on its kept shell where each is named.
func (rs *RelaySession) streamsOf(filter streamTags) []*relayStream {
	rs.mu.Lock()
	defer rs.mu.Unlock()
	var matched []*relayStream
	for stream := range rs.streams {
		if stream.kind != filter.kind {
			continue
		}
		if filter.deviceID != "" && stream.deviceID != filter.deviceID {
			continue
		}
		if filter.key != "" && stream.key != filter.key {
			continue
		}
		if filter.shellSessionID != "" && stream.shellSessionID != filter.shellSessionID {
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

// streamTags is what streams_close picks a relayed stream by: the
// permission kind it falls under, the machine it reaches, its row in a
// permission and the kept shell it is attached to.
type streamTags struct {
	kind           string
	deviceID       string
	key            string
	shellSessionID string
}

// relayStream is one stream the hub relays for a client or an agent, kept
// for streams_close and for the end of the session it rides.
type relayStream struct {
	streamTags
	farSession string
	peer       io.ReadWriteCloser

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

// endUnopened ends the stream whose far end did not open: with a reset when
// the memory cap refused the far stream, and with the refusal's close record
// otherwise.
func (s *relayStream) endUnopened(err error) {
	var refusal *session.Refusal
	if errors.As(err, &refusal) {
		s.closeWith(refusal)
		return
	}
	s.once.Do(func() {
		if resetter, ok := s.peer.(interface{ Reset() error }); ok {
			_ = resetter.Reset()
		} else {
			s.peer.Close()
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
