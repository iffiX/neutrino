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
// first and the session once there is one, until it is disarmed. A close
// before the hub's first byte is a reset.
type doorCloser struct {
	conn net.Conn
	// done is closed by the close.
	done chan struct{}

	// mu guards target, isArmed, isClosed and isWritten.
	mu        sync.Mutex
	target    io.Closer
	isArmed   bool
	isClosed  bool
	isWritten bool
}

func newDoorCloser(conn net.Conn) *doorCloser {
	return &doorCloser{conn: conn, target: conn, isArmed: true, done: make(chan struct{})}
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

// markWritten records the hub's first byte, written right after it.
func (c *doorCloser) markWritten() {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.isWritten = true
}

// fire closes the target while armed, with a reset while the hub has
// written nothing; it returns whether it closed.
func (c *doorCloser) fire() bool {
	c.mu.Lock()
	defer c.mu.Unlock()
	if !c.isArmed || c.isClosed {
		return false
	}
	c.isClosed = true
	if !c.isWritten {
		resetOnClose(c.conn)
	}
	c.target.Close()
	close(c.done)
	return true
}

// doorReader reads a connection for the door, no further than each read
// asks, and counts the bytes read.
type doorReader struct {
	conn net.Conn
	read int
}

func (r *doorReader) Read(p []byte) (int, error) {
	n, err := r.conn.Read(p)
	r.read += n
	return n, err
}

// door is one accepted connection's place at the door: its ledger entry,
// the closer that ends it, the admission timer, and its two draws.
type door struct {
	entry        *knock.Unadmitted
	closer       *doorCloser
	reader       *doorReader
	admission    *time.Timer
	acceptedAt   time.Time
	holdUntil    time.Time
	readBytes    int
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
// admission or its end: the knock or the gate, the control stream and the
// first frame. The first four bytes pick the path: the hub's magic is a
// member's, and a frame length's zero byte is a browser's while a share is
// live. Every other connection, and every failed check before the hub's
// first byte, is refused: held unread and unwritten to its hold deadline,
// then reset.
func (h *Hub) ServeConn(conn net.Conn, listenerName string) {
	acceptedAt := h.now()
	entry, victim := h.ledger.Accept(acceptedAt)
	closer := newDoorCloser(conn)
	h.mu.Lock()
	h.unadmitted[entry] = closer
	victimCloser := h.unadmitted[victim]
	h.mu.Unlock()
	if victimCloser != nil {
		victimCloser.fire()
	}
	d := &door{
		entry: entry, closer: closer, reader: &doorReader{conn: conn}, acceptedAt: acceptedAt,
		holdUntil: acceptedAt.Add(h.draws.Hold()), readBytes: h.draws.ReadBytes(),
	}
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
	_ = conn.SetReadDeadline(d.holdUntil)
	head := make([]byte, knock.KnockMagicBytes)
	if _, err := io.ReadFull(d.reader, head); err != nil {
		h.hold(d)
		return
	}
	key, jar := h.currentKey()
	isRefused := true
	switch {
	case bytes.Equal(head, knock.Magic(key.Public)):
		isRefused = h.serveKnock(d, conn, head, key, jar, address, listenerName)
	case head[0] == gate.GateFrameFirstByte && h.gate != nil && h.gate.HasShares():
		isRefused = h.serveGuest(d, conn, head, address, listenerName)
	}
	if isRefused {
		h.hold(d)
	}
}

// hold keeps a refused connection open to its hold deadline: it reads on to
// the drawn length while the peer sends, then reads and writes nothing. The
// close that follows is a reset.
func (h *Hub) hold(d *door) {
	h.ledger.Refuse(d.entry)
	if rest := d.readBytes - d.reader.read; rest > 0 {
		_ = d.reader.conn.SetReadDeadline(d.holdUntil)
		_, _ = io.ReadFull(d.reader, make([]byte, rest))
	}
	wait := time.NewTimer(d.holdUntil.Sub(h.now()))
	defer wait.Stop()
	select {
	case <-wait.C:
	case <-d.closer.done:
	}
}

// serveKnock runs the member path after the magic in head: the knock, the
// handshake and the admission. It returns whether the door refuses the
// connection.
func (h *Hub) serveKnock(d *door, conn net.Conn, head []byte, key noise.DHKey, jar *knock.CookieJar, address net.IP, listenerName string) bool {
	_ = conn.SetReadDeadline(earliest(d.holdUntil, d.acceptedAt.Add(knock.HandshakeTimeout)))
	header := make([]byte, knock.KnockHeaderBytes)
	copy(header, head)
	if _, err := io.ReadFull(d.reader, header[len(head):]); err != nil {
		return true
	}
	parsedHeader, err := knock.ParseHeader(header, key.Public)
	if err != nil || parsedHeader.Type != knock.KnockTypeKnock {
		return true
	}
	parsed, err := knock.ReadBody(d.reader, header)
	if err != nil {
		return true
	}
	if !parsed.VerifyMac1(key.Public) {
		return true
	}
	if !h.ledger.BeginHandshake() {
		return false
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
			d.closer.markWritten()
			_, _ = conn.Write(reply)
		}
		return false
	}
	responder, err := handshake.NewResponder(key)
	if err != nil {
		return false
	}
	if err := responder.Read(parsed.Message1); err != nil {
		return true
	}
	payload, err := knock.ParsePayload(responder.Payload)
	if err != nil {
		return true
	}
	if !h.replay.Accept(responder.PeerStatic, payload.Time) {
		return true
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
	message2, keys, err := responder.Answer(psk, knock.Padding())
	if err != nil {
		return false
	}
	answer := bytes.NewBuffer(knock.EncodeHeader(key.Public, knock.KnockTypeAnswer))
	if err := session.WriteLengthPrefixed(answer, message2); err != nil {
		return false
	}
	d.closer.markWritten()
	if _, err := conn.Write(answer.Bytes()); err != nil {
		return false
	}
	endHandshake()
	h.ledger.HandshakeDone(d.entry)
	_ = conn.SetReadDeadline(time.Time{})
	reader := bufio.NewReaderSize(conn, 2*session.NoiseMessageMax)
	h.admit(d, session.NewNoiseConn(conn, reader, keys), peerFacts{
		bindingID: bindingID, role: role, protocol: payload.Protocol,
		address: peerAddress, localAddress: FormatIP(PeerIP(conn.LocalAddr())), listener: listenerName,
		publicKey: publicKey, isJoin: payload.IsJoin, refusal: refusal,
	})
	return false
}

// serveGuest runs the guest path after the frame's first bytes in head: the
// gate's first check, the gate, the guest's open record with the share
// ticket, the Python's answer to it, and the admission on the data channel.
// It returns whether the door refuses the connection.
func (h *Hub) serveGuest(d *door, conn net.Conn, head []byte, address net.IP, listenerName string) bool {
	peerAddress := FormatIP(address)
	gateDeadline := d.acceptedAt.Add(gate.GateHandshakeTimeout)
	_ = conn.SetReadDeadline(earliest(d.holdUntil, gateDeadline))
	check, err := h.gate.ReadFirstCheck(io.MultiReader(bytes.NewReader(head), d.reader))
	if err != nil {
		h.log("gate_closed", "address", peerAddress, "listener", listenerName, "error", err.Error())
		return true
	}
	if !h.ledger.BeginHandshake() {
		return false
	}
	handshakeEnded := false
	endHandshake := func() {
		if !handshakeEnded {
			handshakeEnded = true
			h.ledger.EndHandshake()
		}
	}
	// The guest counts among the handshakes in flight from its first check
	// passing until its open record is answered.
	defer endHandshake()
	d.closer.markWritten()
	ctx, cancel := context.WithDeadline(context.Background(), gateDeadline)
	channel, share, err := h.gate.Open(ctx, conn, check)
	cancel()
	if err != nil {
		h.log("gate_closed", "address", peerAddress, "listener", listenerName, "error", err.Error())
		return false
	}
	h.log("gate_open", "address", peerAddress, "listener", listenerName, "share", share,
		"frame_bytes", strconv.Itoa(check.Decision.FrameBytes), "decided_at_byte", strconv.Itoa(check.Decision.UsernameEndByte))
	d.closer.set(channel)
	_ = channel.SetReadDeadline(gateDeadline)
	message := make([]byte, gate.GateGuestOpenBytesMax)
	n, err := channel.ReadMessage(message)
	if err != nil {
		return false
	}
	open, err := gate.ParseGuestOpen(message[:n])
	if err != nil {
		return false
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
		return false
	}
	if _, err := channel.Write(gate.GuestAcceptRecord(bindingID)); err != nil {
		return false
	}
	h.ledger.HandshakeDone(d.entry)
	_ = channel.SetReadDeadline(time.Time{})
	h.admit(d, channel, peerFacts{
		bindingID: bindingID, role: RelayRoleGuest, protocol: open.Protocol,
		address: peerAddress, localAddress: FormatIP(PeerIP(conn.LocalAddr())), listener: listenerName,
	})
	return false
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

// earliest returns the earlier of two times.
func earliest(a, b time.Time) time.Time {
	if a.Before(b) {
		return a
	}
	return b
}

// resetOnClose makes a TCP connection's close a reset, SO_LINGER 0.
func resetOnClose(conn net.Conn) {
	if tcp, ok := conn.(*net.TCPConn); ok {
		_ = tcp.SetLinger(0)
	}
}
