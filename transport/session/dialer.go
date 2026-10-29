package session

import (
	"bufio"
	"context"
	"errors"
	"fmt"
	"io"
	"net"
	"strings"
	"time"

	"github.com/flynn/noise"

	"github.com/iffiX/neutrino/transport/handshake"
	"github.com/iffiX/neutrino/transport/knock"
)

// DialOptions is what one dial of the hub needs.
type DialOptions struct {
	// Static is the peer's own key pair.
	Static noise.DHKey
	// HubPublic is the hub's static public key, the link's or the binding's.
	HubPublic []byte
	// Psk is the token's SHA-256, or handshake.ZeroPsk for a join.
	Psk []byte
	// Protocol, Role and IsJoin fill message 1's payload.
	Protocol int
	Role     string
	IsJoin   bool
	// Timeout bounds the connect and the handshake together; DialTimeout
	// when zero.
	Timeout time.Duration
	// Now reads the clock for the knock's time; time.Now when nil.
	Now func() time.Time
}

// DialResult is a connection whose handshake completed.
type DialResult struct {
	// Conn carries the session.
	Conn *NoiseConn
	// IsRefusal says message 2 opened under the zero psk while the peer's
	// psk was another: the first frame is a refusal.
	IsRefusal bool
	// HandshakeTime is the time from the connect to message 2.
	HandshakeTime time.Duration
}

// ParseAddress reads tcp://host:port as host:port. It returns
// ErrSchemeUnknown for another scheme; an address with no scheme is taken
// as host:port.
func ParseAddress(address string) (string, error) {
	if strings.HasPrefix(address, AddressScheme) {
		return address[len(AddressScheme):], nil
	}
	if scheme, _, ok := strings.Cut(address, "://"); ok {
		return "", fmt.Errorf("%w: %s", ErrSchemeUnknown, scheme)
	}
	return address, nil
}

// Dial connects to address, knocks and runs the handshake, knocking again
// on a new connection when the hub answers with a cookie. It returns the
// connection with the session's keys, handshake.ErrHubUntrusted when message
// 2 opens under neither psk, ErrSchemeUnknown for an address it cannot
// dial, and the connection's own error otherwise, context.DeadlineExceeded
// and context.Canceled among them.
func Dial(ctx context.Context, address string, options DialOptions) (*DialResult, error) {
	hostPort, err := ParseAddress(address)
	if err != nil {
		return nil, err
	}
	timeout := options.Timeout
	if timeout == 0 {
		timeout = DialTimeout
	}
	ctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	var cookie []byte
	for attempt := 0; attempt < 2; attempt++ {
		result, newCookie, err := dialOnce(ctx, hostPort, options, cookie)
		if err != nil {
			return nil, err
		}
		if newCookie == nil {
			return result, nil
		}
		cookie = newCookie
	}
	return nil, fmt.Errorf("dial %s: %w", address, ErrAnswerMalformed)
}

// dialOnce makes one connection and one knock. It returns the result, or
// the cookie the hub answered with, or an error.
func dialOnce(ctx context.Context, hostPort string, options DialOptions, cookie []byte) (*DialResult, []byte, error) {
	now := options.Now
	if now == nil {
		now = time.Now
	}
	started := time.Now()
	var dialer net.Dialer
	conn, err := dialer.DialContext(ctx, "tcp", hostPort)
	if err != nil {
		return nil, nil, fmt.Errorf("dial %s: %w", hostPort, err)
	}
	isDone := false
	defer func() {
		if !isDone {
			conn.Close()
		}
	}()
	if deadline, ok := ctx.Deadline(); ok {
		_ = conn.SetDeadline(deadline)
	}
	stop := context.AfterFunc(ctx, func() { _ = conn.SetDeadline(time.Now()) })
	defer stop()
	payload := knock.Payload{Protocol: options.Protocol, Role: options.Role, IsJoin: options.IsJoin, Time: now().UnixNano()}
	initiator, err := handshake.NewInitiator(options.Static, options.HubPublic, options.Psk, append(payload.Marshal(), knock.Padding()...))
	if err != nil {
		return nil, nil, err
	}
	raw, err := knock.Encode(initiator.Message1, options.HubPublic, cookie)
	if err != nil {
		return nil, nil, err
	}
	if _, err := conn.Write(raw); err != nil {
		return nil, nil, fmt.Errorf("write knock: %w", deadlineError(ctx, err))
	}
	reader := bufio.NewReaderSize(conn, 2*NoiseMessageMax)
	header := make([]byte, knock.KnockHeaderBytes)
	if _, err := io.ReadFull(reader, header); err != nil {
		return nil, nil, fmt.Errorf("read answer: %w", deadlineError(ctx, err))
	}
	parsedHeader, err := knock.ParseHeader(header, options.HubPublic)
	if err != nil {
		return nil, nil, fmt.Errorf("%w: %w", ErrAnswerMalformed, err)
	}
	switch parsedHeader.Type {
	case knock.KnockTypeCookieReply:
		reply := make([]byte, knock.CookieReplyBytes)
		copy(reply, header)
		if _, err := io.ReadFull(reader, reply[knock.KnockHeaderBytes:]); err != nil {
			return nil, nil, fmt.Errorf("read cookie reply: %w", deadlineError(ctx, err))
		}
		parsed, err := knock.Parse(raw)
		if err != nil {
			return nil, nil, err
		}
		newCookie, err := knock.OpenReply(reply, options.HubPublic, parsed.Mac1)
		if err != nil {
			return nil, nil, err
		}
		return nil, newCookie, nil
	case knock.KnockTypeAnswer:
	default:
		return nil, nil, fmt.Errorf("%w: type %d", ErrAnswerMalformed, parsedHeader.Type)
	}
	message2, err := ReadLengthPrefixed(reader)
	if err != nil {
		return nil, nil, fmt.Errorf("read message 2: %w", deadlineError(ctx, err))
	}
	keys, isRefusal, err := initiator.Open(message2)
	if err != nil {
		return nil, nil, err
	}
	if !stop() {
		return nil, nil, fmt.Errorf("handshake %s: %w", hostPort, ctx.Err())
	}
	_ = conn.SetDeadline(time.Time{})
	isDone = true
	return &DialResult{
		Conn:          NewNoiseConn(conn, reader, keys),
		IsRefusal:     isRefusal,
		HandshakeTime: time.Since(started),
	}, nil, nil
}

// deadlineError turns the connection's deadline, the context's own, into
// context.DeadlineExceeded.
func deadlineError(ctx context.Context, err error) error {
	if ctx.Err() != nil {
		return ctx.Err()
	}
	var netErr net.Error
	if errors.As(err, &netErr) && netErr.Timeout() {
		return context.DeadlineExceeded
	}
	return err
}
