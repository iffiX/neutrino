package forward

import (
	"context"
	"fmt"
	"io"
	"net"
	"strconv"
	"strings"
	"sync"

	"golang.org/x/crypto/ssh"
)

// copyBuffers holds the buffers every relay borrows.
var copyBuffers = sync.Pool{
	New: func() any {
		buffer := make([]byte, ForwardCopyBufferBytes)
		return &buffer
	},
}

// directTCPIP is the payload of a direct-tcpip channel request.
type directTCPIP struct {
	Host       string
	Port       uint32
	OriginHost string
	OriginPort uint32
}

// Serve answers one direct-tcpip channel request: it dials a loopback
// destination and relays it until both sides end or ctx ends. It returns
// an error wrapping ErrDestinationRefused for a destination off loopback,
// and the dial's error for a port nothing answers on; the channel is
// rejected in both cases.
func Serve(ctx context.Context, request ssh.NewChannel) error {
	var payload directTCPIP
	if err := ssh.Unmarshal(request.ExtraData(), &payload); err != nil {
		request.Reject(ssh.ConnectionFailed, "unreadable forward request")
		return fmt.Errorf("read forward request: %w", ErrDestinationRefused)
	}
	destination := net.JoinHostPort(payload.Host, strconv.FormatUint(uint64(payload.Port), 10))
	hosts := loopbackHosts(payload.Host)
	if len(hosts) == 0 || payload.Port == 0 || payload.Port > 0xFFFF {
		request.Reject(ssh.Prohibited, "only a port on loopback can be forwarded")
		return fmt.Errorf("forward to %s: %w", destination, ErrDestinationRefused)
	}
	conn, err := dialFirst(ctx, hosts, payload.Port)
	if err != nil {
		request.Reject(ssh.ConnectionFailed, "the port does not answer")
		return fmt.Errorf("forward to %s: %w", destination, err)
	}
	channel, requests, err := request.Accept()
	if err != nil {
		conn.Close()
		return fmt.Errorf("accept forward to %s: %w", destination, err)
	}
	go ssh.DiscardRequests(requests)
	relay(ctx, channel, conn)
	return nil
}

// loopbackHosts returns the addresses a destination host is dialed at:
// 127.0.0.1 and ::1 as given, localhost as 127.0.0.1 and then ::1, and none
// for any other host.
func loopbackHosts(host string) []string {
	switch {
	case host == "127.0.0.1":
		return []string{"127.0.0.1"}
	case host == "::1":
		return []string{"::1"}
	case strings.EqualFold(host, "localhost"):
		return []string{"127.0.0.1", "::1"}
	}
	return nil
}

// dialFirst returns a connection to port on the first of hosts that
// answers, or the last dial's error.
func dialFirst(ctx context.Context, hosts []string, port uint32) (net.Conn, error) {
	dialer := net.Dialer{Timeout: ForwardDialTimeout}
	var err error
	for _, host := range hosts {
		var conn net.Conn
		conn, err = dialer.DialContext(ctx, "tcp", net.JoinHostPort(host, strconv.FormatUint(uint64(port), 10)))
		if err == nil {
			return conn, nil
		}
	}
	return nil, err
}

// relay copies between channel and conn both ways, each side's end of
// input passed to the other, and closes both once both directions ended or
// ctx ended.
func relay(ctx context.Context, channel ssh.Channel, conn net.Conn) {
	ctx, cancel := context.WithCancel(ctx)
	defer cancel()
	go func() {
		<-ctx.Done()
		channel.Close()
		conn.Close()
	}()
	var directions sync.WaitGroup
	directions.Add(2)
	go func() {
		defer directions.Done()
		copyStream(conn, channel)
		if half, ok := conn.(interface{ CloseWrite() error }); ok {
			half.CloseWrite()
		}
	}()
	go func() {
		defer directions.Done()
		copyStream(channel, conn)
		channel.CloseWrite()
	}()
	directions.Wait()
}

// copyStream copies source to target until either ends, with a pooled
// buffer.
func copyStream(target io.Writer, source io.Reader) {
	buffer := copyBuffers.Get().(*[]byte)
	defer copyBuffers.Put(buffer)
	io.CopyBuffer(target, source, *buffer)
}
