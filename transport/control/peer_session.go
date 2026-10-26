package control

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"sync"
	"time"

	"github.com/flynn/noise"
	"github.com/libp2p/go-yamux/v4"

	"github.com/iffiX/neutrino/transport/handshake"
	"github.com/iffiX/neutrino/transport/relay"
	"github.com/iffiX/neutrino/transport/session"
)

// PeerSession is one live session a peer's transport holds to the hub.
type PeerSession struct {
	// Address is the hub address dialled, with its scheme.
	Address string
	// LocalAddress is the connection's own address.
	LocalAddress string
	// Path is the client's path for the address, empty on the agent.
	Path string
	// HandshakeTime is the time from the connect to message 2.
	HandshakeTime time.Duration

	session *session.Session
	control *session.ControlStream

	// mu guards refusal, isMoved, isEnded and hubFrames.
	mu        sync.Mutex
	refusal   *session.Refusal
	isMoved   bool
	isEnded   bool
	hubFrames chan struct{}
	ended     chan struct{}
}

// dialSettings is what every dial of the hub shares.
type dialSettings struct {
	static    noise.DHKey
	hubPublic []byte
	psk       []byte
	protocol  int
	role      string
	isJoin    bool
	timings   session.Timings
}

// connectSession dials one address, runs the handshake and opens the control
// stream. It returns the session, or the refusal the hub said under the zero
// psk, or the dial's error, handshake.ErrHubUntrusted among them.
func connectSession(ctx context.Context, address, path string, settings dialSettings) (*PeerSession, *session.Refusal, error) {
	result, err := session.Dial(ctx, address, session.DialOptions{
		Static: settings.static, HubPublic: settings.hubPublic, Psk: settings.psk,
		Protocol: settings.protocol, Role: settings.role, IsJoin: settings.isJoin,
	})
	if err != nil {
		return nil, nil, err
	}
	timings := settings.timings
	if timings.KeepAliveInterval == 0 {
		timings = session.DefaultTimings
	}
	sess, err := session.NewPeerSession(result.Conn, timings)
	if err != nil {
		result.Conn.Close()
		return nil, nil, err
	}
	stream, err := sess.OpenStream(ctx)
	if err != nil {
		sess.Close()
		return nil, nil, err
	}
	if _, err := stream.Write(session.OpenRecord(session.KindControl, nil)); err != nil {
		sess.Close()
		return nil, nil, fmt.Errorf("open control stream: %w", err)
	}
	control := session.NewControlStream(stream)
	_ = stream.SetReadDeadline(time.Now().Add(session.HelloTimeout))
	answer, err := control.ReadAnswer()
	if err != nil {
		sess.Close()
		return nil, nil, fmt.Errorf("control stream: %w", err)
	}
	if answer != nil {
		sess.Close()
		return nil, answer, nil
	}
	if result.IsRefusal {
		frame, err := control.ReadFrame()
		sess.Close()
		if err != nil {
			return nil, nil, fmt.Errorf("refusal: %w", err)
		}
		return nil, session.ParseRefused(frame), nil
	}
	_ = stream.SetReadDeadline(time.Time{})
	return &PeerSession{
		Address:       address,
		LocalAddress:  localAddress(result.Conn.LocalAddr()),
		Path:          path,
		HandshakeTime: result.HandshakeTime,
		session:       sess,
		control:       control,
		hubFrames:     make(chan struct{}),
		ended:         make(chan struct{}),
	}, nil, nil
}

func localAddress(address net.Addr) string {
	if tcp, ok := address.(*net.TCPAddr); ok {
		return tcp.IP.String()
	}
	host, _, err := net.SplitHostPort(address.String())
	if err != nil {
		return address.String()
	}
	return host
}

// WriteFrame writes one frame of the Python's on the control stream.
func (p *PeerSession) WriteFrame(frame []byte) error {
	return p.control.WriteFrame(frame)
}

// ReadFrame returns the next frame from the hub, recording a refused frame's
// code; it returns the stream's error when the session ends.
func (p *PeerSession) ReadFrame() ([]byte, error) {
	frame, err := p.control.ReadFrame()
	if err != nil {
		return nil, err
	}
	p.mu.Lock()
	select {
	case <-p.hubFrames:
	default:
		close(p.hubFrames)
	}
	p.mu.Unlock()
	if frameType, _ := session.FrameType(frame); frameType == session.FrameRefused {
		p.mu.Lock()
		p.refusal = session.ParseRefused(frame)
		p.mu.Unlock()
	}
	return frame, nil
}

// HubFrames is closed once the first frame from the hub was read.
func (p *PeerSession) HubFrames() <-chan struct{} {
	return p.hubFrames
}

// Refusal is the refused frame's code, nil when none came.
func (p *PeerSession) Refusal() *session.Refusal {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.refusal
}

// MarkMoved marks the session as moved off: its frames are dropped and its
// end reported to nobody.
func (p *PeerSession) MarkMoved() {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.isMoved = true
}

// IsMoved reports whether the session was moved off.
func (p *PeerSession) IsMoved() bool {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.isMoved
}

// AcceptStream returns the next stream the hub opened.
func (p *PeerSession) AcceptStream() (*yamux.Stream, error) {
	return p.session.AcceptStream()
}

// OpenStream opens a stream on the session with an open record and reads
// its answer.
func (p *PeerSession) OpenStream(ctx context.Context, open json.RawMessage) (*relay.RecordStream, *session.Refusal, error) {
	stream, err := p.session.OpenStream(ctx)
	if err != nil {
		return nil, nil, err
	}
	return relay.OpenOn(stream, open)
}

// OpenRaw opens a stream and writes the open record, leaving the answer to
// the caller.
func (p *PeerSession) OpenRaw(ctx context.Context, open json.RawMessage) (*yamux.Stream, error) {
	stream, err := p.session.OpenStream(ctx)
	if err != nil {
		return nil, err
	}
	if _, err := stream.Write(session.EncodeRecord(session.RecordOpen, open)); err != nil {
		stream.Close()
		return nil, err
	}
	return stream, nil
}

// Close ends the session.
func (p *PeerSession) Close() {
	p.mu.Lock()
	if p.isEnded {
		p.mu.Unlock()
		return
	}
	p.isEnded = true
	close(p.ended)
	p.mu.Unlock()
	_ = p.session.Close()
}

// Ended is closed once Close was called.
func (p *PeerSession) Ended() <-chan struct{} {
	return p.ended
}

// CloseChan is closed once the yamux session ended.
func (p *PeerSession) CloseChan() <-chan struct{} {
	return p.session.CloseChan()
}

// pathRank orders a client's paths, best first; an unknown path ranks last.
func pathRank(path string) int {
	switch path {
	case PathLan:
		return 1
	case PathDirect:
		return 2
	case PathNetbird, PathEasytier:
		return 3
	case PathSshRelay, PathSakuraFrp, PathOpenFrp:
		return 4
	}
	return 5
}

// isBetter reports whether a round's winner takes the channel from the live
// session: a better path, or the same path with a shorter handshake.
func isBetter(winner, live *PeerSession) bool {
	winnerRank, liveRank := pathRank(winner.Path), pathRank(live.Path)
	if winnerRank != liveRank {
		return winnerRank < liveRank
	}
	return winner.HandshakeTime < live.HandshakeTime
}

// isRefusedConnection reports whether a dial met a host that is up with the
// port closed.
func isRefusedConnection(err error) bool {
	var operr *net.OpError
	if !errors.As(err, &operr) {
		return false
	}
	return relay.ConnectFailed(err).Params["reason"] == session.ReasonRefused
}

// backoff is the wait between failed rounds: RedialBackoffMin doubling to
// RedialBackoffMax, put back at the floor by a round that wins.
type backoff struct {
	next time.Duration
}

func newBackoff() *backoff {
	return &backoff{next: session.RedialBackoffMin}
}

// take returns the wait before the next round and doubles it for the one
// after.
func (b *backoff) take() time.Duration {
	wait := b.next
	b.next = min(b.next*2, session.RedialBackoffMax)
	return wait
}

func (b *backoff) reset() {
	b.next = session.RedialBackoffMin
}

// hubUnreachable is the refusal of a round no address answered.
func hubUnreachable(err error) *session.Refusal {
	return session.NewRefusal(session.CodeHubUnreachable, map[string]any{"detail": relay.ErrorText(err)})
}

// isUntrusted reports whether a dial's error is a message 2 under neither psk.
func isUntrusted(err error) bool {
	return errors.Is(err, handshake.ErrHubUntrusted)
}
