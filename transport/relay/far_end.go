package relay

import (
	"context"
	"errors"
	"fmt"
	"net"
	"os"
	"strconv"

	"github.com/iffiX/neutrino/transport/session"
)

// DialFarEnd dials the TCP far end of a connect stream within
// ConnectDialTimeout. It returns the connection, or the connect_failed
// refusal naming why: refused, timeout or unreachable.
func DialFarEnd(ctx context.Context, address string, port int) (net.Conn, *session.Refusal) {
	ctx, cancel := context.WithTimeout(ctx, session.ConnectDialTimeout)
	defer cancel()
	var dialer net.Dialer
	conn, err := dialer.DialContext(ctx, "tcp", net.JoinHostPort(address, strconv.Itoa(port)))
	if err != nil {
		return nil, ConnectFailed(err)
	}
	return conn, nil
}

// ConnectFailed is the connect_failed refusal for a dial's error.
func ConnectFailed(err error) *session.Refusal {
	return session.NewRefusal(session.CodeConnectFailed, map[string]any{"reason": connectReason(err)})
}

// connectReason names a dial's error: refused for a closed port, timeout
// for a deadline, unreachable for everything else.
func connectReason(err error) string {
	if errors.Is(err, context.DeadlineExceeded) || errors.Is(err, os.ErrDeadlineExceeded) {
		return session.ReasonTimeout
	}
	var netErr net.Error
	if errors.As(err, &netErr) && netErr.Timeout() {
		return session.ReasonTimeout
	}
	if isRefused(err) {
		return session.ReasonRefused
	}
	return session.ReasonUnreachable
}

// TargetAddress joins a host and a port as a dial address.
func TargetAddress(host string, port int) string {
	return net.JoinHostPort(host, strconv.Itoa(port))
}

// PeerIP is the IP of a connection's peer, an IPv4-mapped IPv6 address read
// as the IPv4 address.
func PeerIP(address net.Addr) net.IP {
	switch typed := address.(type) {
	case *net.TCPAddr:
		return unmap(typed.IP)
	case *net.UDPAddr:
		return unmap(typed.IP)
	}
	host, _, err := net.SplitHostPort(address.String())
	if err != nil {
		return nil
	}
	return unmap(net.ParseIP(host))
}

func unmap(ip net.IP) net.IP {
	if four := ip.To4(); four != nil {
		return four
	}
	return ip
}

// FormatIP writes an IP as the local channel carries an address.
func FormatIP(ip net.IP) string {
	if ip == nil {
		return ""
	}
	return ip.String()
}

// ErrorText is an error's text for a refusal's detail, empty for nil.
func ErrorText(err error) string {
	if err == nil {
		return ""
	}
	return fmt.Sprint(err)
}
