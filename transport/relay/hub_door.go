package relay

import (
	"bufio"
	"encoding/hex"
	"encoding/json"
	"io"
	"net"
	"sync"
	"time"

	"github.com/iffiX/neutrino/transport/handshake"
	"github.com/iffiX/neutrino/transport/knock"
	"github.com/iffiX/neutrino/transport/session"
)

// doorCloser closes whatever a connection has become, the TCP connection
// first and the session once there is one, until it is disarmed.
type doorCloser struct {
	mu       sync.Mutex
	target   io.Closer
	isArmed  bool
	isClosed bool
}

func newDoorCloser(conn net.Conn) *doorCloser {
	return &doorCloser{target: conn, isArmed: true}
}

func (c *doorCloser) set(target io.Closer) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.target = target
}

func (c *doorCloser) disarm() {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.isArmed = false
}

// fire closes the target while armed; it returns whether it closed.
func (c *doorCloser) fire() bool {
	c.mu.Lock()
	defer c.mu.Unlock()
	if !c.isArmed || c.isClosed {
		return false
	}
	c.isClosed = true
	c.target.Close()
	return true
}

// ServeConn runs one accepted connection from its first byte to its
// admission or its end: the legacy hand-off, the knock, the handshake, the
// control stream and the first frame.
func (h *Hub) ServeConn(conn net.Conn, listenerName string) {
	acceptedAt := h.now()
	entry, victim := h.ledger.Accept(acceptedAt)
	h.mu.Lock()
	h.unadmitted[entry] = conn
	victimConn := h.unadmitted[victim]
	h.mu.Unlock()
	if victimConn != nil {
		victimConn.Close()
	}
	closer := newDoorCloser(conn)
	admission := time.AfterFunc(knock.AdmissionTimeout, func() { closer.fire() })
	isHandedOver := false
	defer func() {
		h.ledger.Leave(entry)
		h.mu.Lock()
		delete(h.unadmitted, entry)
		h.mu.Unlock()
		if !isHandedOver {
			admission.Stop()
			closer.fire()
		}
	}()

	address := PeerIP(conn.RemoteAddr())
	reader := bufio.NewReaderSize(conn, 2*session.NoiseMessageMax)
	_ = conn.SetReadDeadline(acceptedAt.Add(knock.KnockFirstByteTimeout))
	first, err := reader.ReadByte()
	if err != nil {
		return
	}
	switch first {
	case knock.KnockLegacyTLSByte:
		if h.legacy == 0 {
			return
		}
		h.ledger.Leave(entry)
		admission.Stop()
		closer.disarm()
		isHandedOver = true
		_ = conn.SetReadDeadline(time.Time{})
		h.handOffLegacy(conn, reader, first)
		return
	case knock.KnockVersion:
	default:
		return
	}

	_ = conn.SetReadDeadline(acceptedAt.Add(knock.HandshakeTimeout))
	parsed, err := knock.ReadBody(reader)
	if err != nil {
		return
	}
	key, jar := h.currentKey()
	if !parsed.VerifyMac1(key.Public) {
		return
	}
	if !h.ledger.BeginHandshake() {
		return
	}
	handshakeEnded := false
	endHandshake := func() {
		if !handshakeEnded {
			handshakeEnded = true
			h.ledger.EndHandshake()
		}
	}
	defer endHandshake()
	if h.ledger.IsUnderLoad() && !jar.IsMac2Valid(parsed, address) {
		reply, err := jar.Reply(parsed, address)
		if err == nil {
			_, _ = conn.Write(reply)
		}
		return
	}
	responder, err := handshake.NewResponder(key)
	if err != nil {
		return
	}
	if err := responder.Read(parsed.Message1); err != nil {
		return
	}
	payload, err := knock.ParsePayload(responder.Payload)
	if err != nil {
		return
	}
	if !h.replay.Accept(responder.PeerStatic, payload.Time) {
		return
	}
	publicKey := hex.EncodeToString(responder.PeerStatic)
	peerAddress := FormatIP(address)

	psk := handshake.ZeroPsk
	var refusal *session.Refusal
	bindingID, role := "", payload.Role
	if !payload.IsJoin {
		answer, refused := h.ask("peer", map[string]any{
			"public_key": publicKey, "role": payload.Role, "protocol": payload.Protocol,
			"address": peerAddress, "listener": listenerName,
		})
		if refused != nil {
			refusal = refused
		} else {
			bindingID, _ = answer["binding_id"].(string)
			if answeredRole, ok := answer["role"].(string); ok && answeredRole != "" {
				role = answeredRole
			}
			pskText, _ := answer["psk"].(string)
			decoded, err := handshake.DecodeKey(pskText)
			if err != nil || bindingID == "" {
				refusal = session.NewRefusal(session.CodeControlUnavailable, nil)
			} else {
				psk = decoded
			}
		}
	}
	message2, keys, err := responder.Answer(psk)
	if err != nil {
		return
	}
	if _, err := conn.Write([]byte{knock.KnockVersion}); err != nil {
		return
	}
	if err := session.WriteLengthPrefixed(conn, message2); err != nil {
		return
	}
	endHandshake()
	h.ledger.HandshakeDone(entry)
	_ = conn.SetReadDeadline(time.Time{})

	noiseConn := session.NewNoiseConn(conn, reader, keys)
	sess, err := session.NewHubSession(noiseConn, h.memory, h.timings)
	if err != nil {
		return
	}
	closer.set(sess)
	hello := time.AfterFunc(session.HelloTimeout, func() { closer.fire() })
	defer hello.Stop()

	stream, err := sess.AcceptStream()
	if err != nil {
		return
	}
	record := NewRecordStream(stream)
	open, err := session.ReadRecord(record.Reader)
	if err != nil || open.Type != session.RecordOpen {
		return
	}
	if kind, err := session.OpenKind(open.Payload); err != nil || kind != session.KindControl {
		_, _ = stream.Write(session.CloseRecord(session.CodeKindUnknown, nil))
		return
	}
	control := session.NewControlStream(stream)
	if err := control.WriteRaw(session.AcceptRecord()); err != nil {
		return
	}
	rs := &RelaySession{
		ID: h.newSessionID(), BindingID: bindingID, Role: role, Protocol: payload.Protocol,
		Address: peerAddress, LocalAddress: FormatIP(PeerIP(conn.LocalAddr())), Listener: listenerName, PublicKey: publicKey,
		hub: h, session: sess, control: control, streams: make(map[*relayStream]struct{}),
	}
	// From here the session ends itself: the admission timer closes it when
	// the hello is late, and a refusal ends it after the peer read it.
	isHandedOver = true
	if refusal != nil {
		rs.writeRefusedAndEnd(refusal)
		return
	}
	frame, err := control.ReadFrame()
	if err != nil {
		rs.end(EndPeerClosed)
		return
	}
	hello.Stop()
	frameType, err := session.FrameType(frame)
	if err != nil {
		rs.writeRefusedAndEnd(session.NewRefusal(session.CodeHelloInvalid, nil))
		return
	}
	if payload.IsJoin {
		if frameType != session.FrameJoin {
			rs.writeRefusedAndEnd(session.NewRefusal(session.CodeHelloInvalid, nil))
			return
		}
		rs.answerJoin(frame)
		return
	}
	switch frameType {
	case session.FrameHello:
		if !rs.isHelloValid(frame) {
			rs.writeRefusedAndEnd(session.NewRefusal(session.CodeHelloInvalid, nil))
			return
		}
	case session.FrameLeave:
	default:
		rs.writeRefusedAndEnd(session.NewRefusal(session.CodeHelloInvalid, nil))
		return
	}
	if !h.register(rs) {
		rs.writeRefusedAndEnd(session.NewRefusal(session.CodeChannelFull, map[string]any{"limit": session.SessionsMax}))
		return
	}
	admission.Stop()
	closer.disarm()
	rs.hello = frame
	h.log("session_open", "session", rs.ID, "binding", bindingID, "role", role, "address", peerAddress, "listener", listenerName)
	h.python.Event("session_open", rs.openEvent())
	h.python.Frame(rs.ID, frame)
	go rs.readFrames()
	go rs.acceptStreams()
	go rs.watchEnd()
}

// handOffLegacy passes a connection whose first byte is a TLS handshake's to
// the legacy listener on loopback, the byte first.
func (h *Hub) handOffLegacy(conn net.Conn, reader *bufio.Reader, first byte) {
	target := TargetAddress(RelayLegacyLoopback, h.legacy)
	legacy, err := net.DialTimeout("tcp", target, RelayLegacyDialLimit)
	if err != nil {
		h.log("legacy_unreachable", "address", target, "error", err.Error())
		conn.Close()
		return
	}
	if _, err := legacy.Write([]byte{first}); err != nil {
		legacy.Close()
		conn.Close()
		return
	}
	h.log("legacy_handoff", "address", FormatIP(PeerIP(conn.RemoteAddr())))
	Splice(&bufferedConn{Conn: conn, reader: reader}, legacy)
}

// bufferedConn reads what its reader already holds before the connection.
type bufferedConn struct {
	net.Conn
	reader *bufio.Reader
}

func (c *bufferedConn) Read(p []byte) (int, error) {
	return c.reader.Read(p)
}

// isHelloValid checks a hello against the knock: its id is the binding's,
// and its protocol and role are the knock's.
func (rs *RelaySession) isHelloValid(frame []byte) bool {
	var hello struct {
		ID       string `json:"id"`
		Protocol int    `json:"protocol"`
		Role     string `json:"role"`
	}
	if err := json.Unmarshal(frame, &hello); err != nil {
		return false
	}
	return hello.ID == rs.BindingID && hello.Protocol == rs.Protocol && hello.Role == rs.Role
}

// answerJoin turns a join frame into the ticket question and writes the
// joined or refused frame that answers it, then ends the session.
func (rs *RelaySession) answerJoin(frame []byte) {
	var fields map[string]any
	if err := json.Unmarshal(frame, &fields); err != nil {
		rs.writeRefusedAndEnd(session.NewRefusal(session.CodeHelloInvalid, nil))
		return
	}
	delete(fields, session.FrameTypeKey)
	fields["public_key"] = rs.PublicKey
	fields["address"] = rs.Address
	fields["listener"] = rs.Listener
	answer, refusal := rs.hub.ask("ticket", fields)
	if refusal != nil {
		rs.hub.log("join_refused", "address", rs.Address, "code", refusal.Code)
		rs.writeRefusedAndEnd(refusal)
		return
	}
	rs.hub.log("joined", "address", rs.Address, "binding", stringField(answer, "binding_id"))
	_ = rs.control.WriteFrame(session.MakeFrame(session.FrameJoined, map[string]any{"id": answer["binding_id"], "token": answer["token"]}))
	rs.endSoon(EndClosedByHub)
}

func stringField(fields map[string]any, key string) string {
	value, _ := fields[key].(string)
	return value
}
