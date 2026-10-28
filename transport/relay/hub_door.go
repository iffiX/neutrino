package relay

import (
	"bufio"
	"bytes"
	"context"
	"encoding/hex"
	"encoding/json"
	"io"
	"net"
	"strconv"
	"sync"
	"time"

	"github.com/flynn/noise"

	"github.com/iffiX/neutrino/transport/gate"
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

// door is one accepted connection's place at the door: its ledger entry,
// the closer that ends it and the admission timer.
type door struct {
	entry        *knock.Unadmitted
	closer       *doorCloser
	admission    *time.Timer
	acceptedAt   time.Time
	isHandedOver bool
}

// peerFacts is what the door learned about a peer before its session: the
// binding the Python named, the role, where it came from, and the refusal
// to write first, if any.
type peerFacts struct {
	bindingID    string
	role         string
	protocol     int
	address      string
	localAddress string
	listener     string
	publicKey    string
	isJoin       bool
	refusal      *session.Refusal
}

// ServeConn runs one accepted connection from its first bytes to its
// admission or its end: the legacy hand-off, the knock or the gate, the
// control stream and the first frame. The first four bytes pick the path:
// the hub's magic is a member's, a frame length's zero byte is a browser's
// while a share is live, a TLS handshake record's two bytes are a 0.5
// peer's while the legacy listener is on, and anything else is closed with
// no byte written.
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
	d := &door{entry: entry, closer: closer, acceptedAt: acceptedAt}
	d.admission = time.AfterFunc(knock.AdmissionTimeout, func() { closer.fire() })
	defer func() {
		h.ledger.Leave(entry)
		h.mu.Lock()
		delete(h.unadmitted, entry)
		h.mu.Unlock()
		if !d.isHandedOver {
			d.admission.Stop()
			closer.fire()
		}
	}()

	address := PeerIP(conn.RemoteAddr())
	reader := bufio.NewReaderSize(conn, 2*session.NoiseMessageMax)
	_ = conn.SetReadDeadline(acceptedAt.Add(knock.KnockFirstByteTimeout))
	head, err := reader.Peek(knock.KnockMagicBytes)
	if err != nil {
		return
	}
	key, jar := h.currentKey()
	switch {
	case bytes.Equal(head, knock.Magic(key.Public)):
		h.serveKnock(d, conn, reader, key, jar, address, listenerName)
	case head[0] == knock.KnockLegacyTLSByte && head[1] == knock.KnockLegacyTLSVersionByte && h.legacy != 0:
		h.ledger.Leave(entry)
		d.admission.Stop()
		closer.disarm()
		d.isHandedOver = true
		_ = conn.SetReadDeadline(time.Time{})
		h.handOffLegacy(conn, reader)
	case head[0] == gate.GateFrameFirstByte && h.gate != nil && h.gate.HasShares():
		h.serveGuest(d, &bufferedConn{Conn: conn, reader: reader}, address, listenerName)
	}
}

// serveKnock runs the member path: the knock, the handshake and the
// admission.
func (h *Hub) serveKnock(d *door, conn net.Conn, reader *bufio.Reader, key noise.DHKey, jar *knock.CookieJar, address net.IP, listenerName string) {
	_ = conn.SetReadDeadline(d.acceptedAt.Add(knock.HandshakeTimeout))
	header := make([]byte, knock.KnockHeaderBytes)
	if _, err := io.ReadFull(reader, header); err != nil {
		return
	}
	parsedHeader, err := knock.ParseHeader(header, key.Public)
	if err != nil || parsedHeader.Type != knock.KnockTypeKnock {
		return
	}
	parsed, err := knock.ReadBody(reader, header)
	if err != nil {
		return
	}
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
	if _, err := conn.Write(knock.EncodeHeader(key.Public, knock.KnockTypeAnswer)); err != nil {
		return
	}
	if err := session.WriteLengthPrefixed(conn, message2); err != nil {
		return
	}
	endHandshake()
	h.ledger.HandshakeDone(d.entry)
	_ = conn.SetReadDeadline(time.Time{})
	h.admit(d, session.NewNoiseConn(conn, reader, keys), peerFacts{
		bindingID: bindingID, role: role, protocol: payload.Protocol,
		address: peerAddress, localAddress: FormatIP(PeerIP(conn.LocalAddr())), listener: listenerName,
		publicKey: publicKey, isJoin: payload.IsJoin, refusal: refusal,
	})
}

// serveGuest runs the guest path: the gate, the guest's open record with
// the share ticket, the Python's answer to it, and the admission on the
// data channel.
func (h *Hub) serveGuest(d *door, conn net.Conn, address net.IP, listenerName string) {
	peerAddress := FormatIP(address)
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
	// The guest counts among the handshakes in flight from its first check
	// until its open record is answered.
	defer endHandshake()
	_ = conn.SetReadDeadline(d.acceptedAt.Add(gate.GateHandshakeTimeout))
	ctx, cancel := context.WithDeadline(context.Background(), d.acceptedAt.Add(gate.GateHandshakeTimeout))
	channel, share, decision, err := h.gate.Open(ctx, conn)
	cancel()
	if err != nil {
		h.log("gate_closed", "address", peerAddress, "listener", listenerName, "error", err.Error())
		return
	}
	h.log("gate_open", "address", peerAddress, "listener", listenerName, "share", share,
		"frame_bytes", strconv.Itoa(decision.FrameBytes), "decided_at_byte", strconv.Itoa(decision.UsernameEndByte))
	d.closer.set(channel)
	_ = channel.SetReadDeadline(d.acceptedAt.Add(gate.GateHandshakeTimeout))
	message := make([]byte, gate.GateGuestOpenBytesMax)
	n, err := channel.ReadMessage(message)
	if err != nil {
		return
	}
	open, err := gate.ParseGuestOpen(message[:n])
	if err != nil {
		return
	}
	answer, refusal := h.ask("guest", map[string]any{
		"ticket": open.Ticket, "share": share, "protocol": open.Protocol,
		"address": peerAddress, "listener": listenerName,
	})
	endHandshake()
	bindingID := ""
	if refusal == nil {
		bindingID = stringField(answer, "binding_id")
		if bindingID == "" {
			refusal = session.NewRefusal(session.CodeControlUnavailable, nil)
		}
	}
	if refusal != nil {
		h.log("guest_refused", "address", peerAddress, "share", share, "code", refusal.Code)
		_, _ = channel.Write(gate.GuestRefuseRecord(refusal))
		channel.Flush(RelayEndGrace)
		return
	}
	if _, err := channel.Write(gate.GuestAcceptRecord(bindingID)); err != nil {
		return
	}
	h.ledger.HandshakeDone(d.entry)
	_ = channel.SetReadDeadline(time.Time{})
	h.admit(d, channel, peerFacts{
		bindingID: bindingID, role: RelayRoleGuest, protocol: open.Protocol,
		address: peerAddress, localAddress: FormatIP(PeerIP(conn.LocalAddr())), listener: listenerName,
	})
}

// admit runs a session from its connection: the control stream, the first
// frame and the registration, or the refusal the door decided on.
func (h *Hub) admit(d *door, conn net.Conn, facts peerFacts) {
	sess, err := session.NewHubSession(conn, h.memory, h.timings)
	if err != nil {
		return
	}
	d.closer.set(sess)
	hello := time.AfterFunc(session.HelloTimeout, func() { d.closer.fire() })
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
		ID: h.newSessionID(), BindingID: facts.bindingID, Role: facts.role, Protocol: facts.protocol,
		Address: facts.address, LocalAddress: facts.localAddress, Listener: facts.listener, PublicKey: facts.publicKey,
		hub: h, session: sess, control: control, streams: make(map[*relayStream]struct{}),
	}
	// From here the session ends itself: the admission timer closes it when
	// the hello is late, and a refusal ends it after the peer read it.
	d.isHandedOver = true
	if facts.refusal != nil {
		rs.writeRefusedAndEnd(facts.refusal)
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
	if facts.isJoin {
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
		if rs.Role == RelayRoleGuest {
			rs.writeRefusedAndEnd(session.NewRefusal(session.CodeHelloInvalid, nil))
			return
		}
	default:
		rs.writeRefusedAndEnd(session.NewRefusal(session.CodeHelloInvalid, nil))
		return
	}
	if !h.register(rs) {
		rs.writeRefusedAndEnd(session.NewRefusal(session.CodeChannelFull, map[string]any{"limit": session.SessionsMax}))
		return
	}
	d.admission.Stop()
	d.closer.disarm()
	rs.hello = frame
	h.log("session_open", "session", rs.ID, "binding", facts.bindingID, "role", facts.role, "address", facts.address, "listener", facts.listener)
	h.python.Event("session_open", rs.openEvent())
	h.python.Frame(rs.ID, frame)
	go rs.readFrames()
	go rs.acceptStreams()
	go rs.watchEnd()
}

// handOffLegacy passes a connection whose first byte is a TLS handshake's to
// the legacy listener on loopback, the bytes the reader holds first.
func (h *Hub) handOffLegacy(conn net.Conn, reader *bufio.Reader) {
	target := TargetAddress(RelayLegacyLoopback, h.legacy)
	legacy, err := net.DialTimeout("tcp", target, RelayLegacyDialLimit)
	if err != nil {
		h.log("legacy_unreachable", "address", target, "error", err.Error())
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

// isHelloValid checks a hello against the door: its id is the binding's,
// and its protocol and role are the ones the door admitted.
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
