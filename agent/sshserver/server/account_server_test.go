package server

import (
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"errors"
	"io"
	"net"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"

	"golang.org/x/crypto/ssh"

	"github.com/iffiX/neutrino/agent/sshserver/session"
)

// testServer is one account server on loopback, its home a temporary
// directory, and the key it admits.
type testServer struct {
	address string
	home    string
	hostKey ssh.PublicKey
	key     ssh.Signer
	events  *eventRecorder
}

// eventRecorder keeps the verbs the server reported.
type eventRecorder struct {
	// mutex guards verbs.
	mutex sync.Mutex
	verbs []string
}

func (r *eventRecorder) record(verb string, pairs ...string) {
	r.mutex.Lock()
	defer r.mutex.Unlock()
	r.verbs = append(r.verbs, verb)
}

func (r *eventRecorder) has(verb string) bool {
	r.mutex.Lock()
	defer r.mutex.Unlock()
	for _, held := range r.verbs {
		if held == verb {
			return true
		}
	}
	return false
}

// startServer runs an account server whose shell is /bin/sh until the
// test ends.
func startServer(t *testing.T) *testServer {
	t.Helper()
	directory := t.TempDir()
	home := filepath.Join(directory, "home")
	if err := os.Mkdir(home, 0o700); err != nil {
		t.Fatal(err)
	}
	hostKeyPath := filepath.Join(directory, "host_key")
	if _, err := MakeHostKey(hostKeyPath); err != nil {
		t.Fatal(err)
	}
	hostKey, err := ReadHostKey(hostKeyPath)
	if err != nil {
		t.Fatal(err)
	}
	key := newSigner(t)
	account := session.Account{
		Shell:       "/bin/sh",
		Home:        home,
		Environment: []string{"HOME=" + home, "PATH=" + session.SessionDefaultPath},
	}
	events := &eventRecorder{}
	server := NewAccountServer(hostKey, key.PublicKey(), account, events.record)
	listener, err := Listen("127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	served := make(chan error, 1)
	go func() { served <- server.Serve(ctx, listener) }()
	t.Cleanup(func() {
		cancel()
		if err := <-served; err != nil {
			t.Errorf("Serve: %v", err)
		}
	})
	return &testServer{
		address: listener.Addr().String(),
		home:    home,
		hostKey: hostKey.PublicKey(),
		key:     key,
		events:  events,
	}
}

func newSigner(t *testing.T) ssh.Signer {
	t.Helper()
	_, private, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	signer, err := ssh.NewSignerFromKey(private)
	if err != nil {
		t.Fatal(err)
	}
	return signer
}

// dial connects with methods as the given user, checking the host key.
func (s *testServer) dial(t *testing.T, methods ...ssh.AuthMethod) (*ssh.Client, error) {
	t.Helper()
	return ssh.Dial("tcp", s.address, &ssh.ClientConfig{
		User:            "account",
		Auth:            methods,
		HostKeyCallback: ssh.FixedHostKey(s.hostKey),
		Timeout:         5 * time.Second,
	})
}

// connect connects with the authorized key.
func (s *testServer) connect(t *testing.T) *ssh.Client {
	t.Helper()
	client, err := s.dial(t, ssh.PublicKeys(s.key))
	if err != nil {
		t.Fatalf("dial with the authorized key: %v", err)
	}
	t.Cleanup(func() { client.Close() })
	return client
}

func newSession(t *testing.T, client *ssh.Client) *ssh.Session {
	t.Helper()
	opened, err := client.NewSession()
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { opened.Close() })
	return opened
}

func TestOnlyTheAuthorizedKeyIsAdmitted(t *testing.T) {
	server := startServer(t)
	other := newSigner(t)
	cases := []struct {
		name       string
		method     ssh.AuthMethod
		isAdmitted bool
	}{
		{"the authorized key", ssh.PublicKeys(server.key), true},
		{"another key", ssh.PublicKeys(other), false},
		{"the authorized key after another", ssh.PublicKeys(other, server.key), true},
		{"a password", ssh.Password("secret"), false},
		{"keyboard-interactive", ssh.KeyboardInteractive(func(string, string, []string, []bool) ([]string, error) {
			return []string{"secret"}, nil
		}), false},
	}
	for _, test := range cases {
		t.Run(test.name, func(t *testing.T) {
			client, err := server.dial(t, test.method)
			if test.isAdmitted {
				if err != nil {
					t.Fatalf("refused: %v", err)
				}
				client.Close()
				return
			}
			if err == nil {
				client.Close()
				t.Fatal("admitted")
			}
		})
	}
	if !server.events.has("connection_refused") {
		t.Error("no connection_refused event")
	}
}

func TestPasswordAndKeyboardInteractiveAreNotOffered(t *testing.T) {
	server := startServer(t)
	_, err := server.dial(t, ssh.Password("secret"))
	if err == nil || !strings.Contains(err.Error(), "no supported methods remain") {
		t.Fatalf("got %v, want no supported methods", err)
	}
}

func TestAnAdmittedConnectionRunsACommand(t *testing.T) {
	command := newSession(t, startServer(t).connect(t))
	output, err := command.Output("echo through the server")
	if err != nil || string(output) != "through the server\n" {
		t.Fatalf("got %q, %v", output, err)
	}
}

func TestLocalForwardReachesLoopbackAlone(t *testing.T) {
	echo, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer echo.Close()
	go func() {
		for {
			conn, err := echo.Accept()
			if err != nil {
				return
			}
			go func() {
				io.Copy(conn, conn)
				conn.Close()
			}()
		}
	}()
	port := strconv.Itoa(echo.Addr().(*net.TCPAddr).Port)
	client := startServer(t).connect(t)
	cases := []struct {
		name        string
		destination string
		isReached   bool
	}{
		{"127.0.0.1", "127.0.0.1:" + port, true},
		{"localhost", "localhost:" + port, true},
		{"a LAN address", "192.168.1.1:" + port, false},
		{"a name", "example.com:80", false},
		{"another loopback address", "127.0.0.2:" + port, false},
	}
	for _, test := range cases {
		t.Run(test.name, func(t *testing.T) {
			conn, err := client.Dial("tcp", test.destination)
			if !test.isReached {
				var refusal *ssh.OpenChannelError
				if !errors.As(err, &refusal) || refusal.Reason != ssh.Prohibited {
					t.Fatalf("got %v, want a prohibited refusal", err)
				}
				return
			}
			if err != nil {
				t.Fatal(err)
			}
			defer conn.Close()
			io.WriteString(conn, "through the forward")
			got := make([]byte, len("through the forward"))
			if _, err := io.ReadFull(conn, got); err != nil || string(got) != "through the forward" {
				t.Fatalf("echo %q, %v", got, err)
			}
		})
	}
}

func TestEveryOtherChannelAndGlobalRequestIsRefused(t *testing.T) {
	server := startServer(t)
	client := server.connect(t)

	t.Run("a remote forward", func(t *testing.T) {
		if _, err := client.Listen("tcp", "127.0.0.1:0"); err == nil {
			t.Fatal("remote forward accepted")
		}
		if !server.events.has("remote_forward_refused") {
			t.Error("no remote_forward_refused event")
		}
	})
	for _, channelType := range []string{"x11", "auth-agent@openssh.com", "direct-streamlocal@openssh.com", "forwarded-tcpip"} {
		t.Run("a "+channelType+" channel", func(t *testing.T) {
			_, _, err := client.OpenChannel(channelType, nil)
			var refusal *ssh.OpenChannelError
			if !errors.As(err, &refusal) || refusal.Reason != ssh.UnknownChannelType {
				t.Fatalf("got %v, want an unknown channel type refusal", err)
			}
		})
	}
}

func TestListenRefusesAnAddressOffLoopback(t *testing.T) {
	for _, address := range []string{"0.0.0.0:0", "[::]:0", "localhost:0"} {
		t.Run(address, func(t *testing.T) {
			listener, err := Listen(address)
			if err == nil {
				listener.Close()
			}
			if !errors.Is(err, ErrListenNotLoopback) {
				t.Fatalf("got %v, want ErrListenNotLoopback", err)
			}
		})
	}
}
