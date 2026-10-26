package server

import (
	"context"
	"errors"
	"fmt"
	"net"
	"sync"
	"time"

	"golang.org/x/crypto/ssh"

	"github.com/iffiX/neutrino/agent/sshserver/forward"
	"github.com/iffiX/neutrino/agent/sshserver/session"
)

// EventFunc receives one event: a short verb and key=value pairs, written
// as given.
type EventFunc func(verb string, pairs ...string)

// AccountServer serves SSH connections for the account the process runs as.
type AccountServer struct {
	config  *ssh.ServerConfig
	account session.Account
	onEvent EventFunc
}

// NewAccountServer returns a server that answers as hostKey, admits
// authorizedKey alone and starts the account's sessions with account's
// shell, home and environment. onEvent receives every event the server
// reports.
func NewAccountServer(hostKey ssh.Signer, authorizedKey ssh.PublicKey, account session.Account, onEvent EventFunc) *AccountServer {
	config := &ssh.ServerConfig{
		PublicKeyCallback: newKeyAuthenticator(authorizedKey).check,
		MaxAuthTries:      ServerMaxAuthTries,
		ServerVersion:     ServerVersion,
	}
	config.AddHostKey(hostKey)
	return &AccountServer{config: config, account: account, onEvent: onEvent}
}

// Serve accepts connections on listener until ctx ends, then closes the
// listener and every connection and returns nil once they ended. It
// returns the listener's error when the listener fails for any reason but
// its closing.
func (s *AccountServer) Serve(ctx context.Context, listener net.Listener) error {
	ctx, cancel := context.WithCancel(ctx)
	defer cancel()
	var connections sync.WaitGroup
	defer connections.Wait()
	go func() {
		<-ctx.Done()
		listener.Close()
	}()
	for {
		conn, err := listener.Accept()
		if err != nil {
			if ctx.Err() != nil || errors.Is(err, net.ErrClosed) {
				return nil
			}
			s.onEvent("accept_failed", "error", err.Error())
			select {
			case <-ctx.Done():
				return nil
			case <-time.After(ServerAcceptRetryDelay):
			}
			continue
		}
		connections.Add(1)
		go func() {
			defer connections.Done()
			s.serveConnection(ctx, conn)
		}()
	}
}

// serveConnection runs one connection from its handshake to its end.
func (s *AccountServer) serveConnection(ctx context.Context, conn net.Conn) {
	remote := conn.RemoteAddr().String()
	if err := conn.SetDeadline(time.Now().Add(ServerHandshakeTimeout)); err != nil {
		conn.Close()
		return
	}
	sshConn, channels, requests, err := ssh.NewServerConn(conn, s.config)
	if err != nil {
		conn.Close()
		s.onEvent("connection_refused", "remote", remote, "error", err.Error())
		return
	}
	conn.SetDeadline(time.Time{})
	ctx, cancel := context.WithCancel(ctx)
	defer cancel()
	go func() {
		<-ctx.Done()
		sshConn.Close()
	}()
	s.onEvent("connection_opened", "remote", remote, "key", sshConn.Permissions.Extensions["fingerprint"])
	var handlers sync.WaitGroup
	handlers.Add(1)
	go func() {
		defer handlers.Done()
		s.refuseGlobalRequests(remote, requests)
	}()
	peer := session.PeerEnvironment(conn.RemoteAddr(), conn.LocalAddr())
	for request := range channels {
		handlers.Add(1)
		go func() {
			defer handlers.Done()
			s.serveChannel(ctx, remote, request, peer)
		}()
	}
	cancel()
	handlers.Wait()
	s.onEvent("connection_closed", "remote", remote)
}

// serveChannel answers one channel the client opens.
func (s *AccountServer) serveChannel(ctx context.Context, remote string, request ssh.NewChannel, peer []string) {
	switch request.ChannelType() {
	case ServerChannelSession:
		channel, requests, err := request.Accept()
		if err != nil {
			return
		}
		kind, err := session.NewShellSession(channel, requests, s.account, peer).Serve(ctx)
		if err != nil && !errors.Is(err, context.Canceled) {
			s.onEvent("session_failed", "remote", remote, "kind", kind, "error", err.Error())
		}
	case ServerChannelDirectTCPIP:
		if err := forward.Serve(ctx, request); err != nil {
			s.onEvent("forward_refused", "remote", remote, "error", err.Error())
		}
	default:
		request.Reject(ssh.UnknownChannelType, fmt.Sprintf("channel type %q is not served", request.ChannelType()))
		s.onEvent("channel_refused", "remote", remote, "type", request.ChannelType())
	}
}

// refuseGlobalRequests answers every global request with a failure until
// the connection ends; a remote forward among them is reported.
func (s *AccountServer) refuseGlobalRequests(remote string, requests <-chan *ssh.Request) {
	for request := range requests {
		if request.Type == ServerRequestRemoteForward {
			s.onEvent("remote_forward_refused", "remote", remote)
		}
		if request.WantReply {
			request.Reply(false, nil)
		}
	}
}

// Listen opens the loopback listener at address. It returns
// ErrListenNotLoopback for an address whose host is not a loopback IP, and
// the system's error when the port cannot be bound.
func Listen(address string) (net.Listener, error) {
	host, _, err := net.SplitHostPort(address)
	if err != nil {
		return nil, fmt.Errorf("listen address %q: %w", address, err)
	}
	ip := net.ParseIP(host)
	if ip == nil || !ip.IsLoopback() {
		return nil, fmt.Errorf("listen address %q: %w", address, ErrListenNotLoopback)
	}
	listener, err := net.Listen("tcp", address)
	if err != nil {
		return nil, fmt.Errorf("listen on %s: %w", address, err)
	}
	return listener, nil
}

// Run serves the account until ctx ends: it reads the host key and the
// authorized key, listens on the loopback address listen, and starts each
// session with shell. It returns the first error that keeps it from
// serving, and nil once ctx ended.
func Run(ctx context.Context, listen, hostKeyPath, authorizedKeyPath, shell string, onEvent EventFunc) error {
	hostKey, err := ReadHostKey(hostKeyPath)
	if err != nil {
		return err
	}
	authorizedKey, err := ReadAuthorizedKey(authorizedKeyPath)
	if err != nil {
		return err
	}
	listener, err := Listen(listen)
	if err != nil {
		return err
	}
	onEvent("listening", "address", listener.Addr().String(), "authorized_key", ssh.FingerprintSHA256(authorizedKey))
	server := NewAccountServer(hostKey, authorizedKey, session.CurrentAccount(shell), onEvent)
	return server.Serve(ctx, listener)
}
