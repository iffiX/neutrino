package session

import (
	"bytes"
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"errors"
	"io"
	"net"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/pkg/sftp"
	"golang.org/x/crypto/ssh"
)

// sessionPair is an SSH client whose session channels a ShellSession
// serves, the account's shell /bin/sh and its home a temporary directory.
type sessionPair struct {
	client *ssh.Client
	home   string
}

// startSessions serves every session channel of one loopback connection
// with /bin/sh until the test ends.
func startSessions(t *testing.T) *sessionPair {
	t.Helper()
	return startSessionsWithShell(t, "/bin/sh")
}

// startSessionsWithShell serves every session channel of one loopback
// connection with shell until the test ends.
func startSessionsWithShell(t *testing.T, shell string) *sessionPair {
	t.Helper()
	home := t.TempDir()
	account := Account{
		Shell:       shell,
		Home:        home,
		Environment: []string{"HOME=" + home, "PATH=" + SessionDefaultPath},
	}
	_, private, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	hostKey, err := ssh.NewSignerFromKey(private)
	if err != nil {
		t.Fatal(err)
	}
	config := &ssh.ServerConfig{NoClientAuth: true}
	config.AddHostKey(hostKey)
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	served := make(chan struct{})
	go func() {
		defer close(served)
		conn, err := listener.Accept()
		listener.Close()
		if err != nil {
			return
		}
		serverConn, channels, requests, err := ssh.NewServerConn(conn, config)
		if err != nil {
			return
		}
		defer serverConn.Close()
		go ssh.DiscardRequests(requests)
		peer := PeerEnvironment(conn.RemoteAddr(), conn.LocalAddr())
		for request := range channels {
			channel, channelRequests, err := request.Accept()
			if err != nil {
				continue
			}
			go NewShellSession(channel, channelRequests, account, peer).Serve(ctx)
		}
	}()
	client, err := ssh.Dial("tcp", listener.Addr().String(), &ssh.ClientConfig{
		User:            "account",
		HostKeyCallback: ssh.InsecureIgnoreHostKey(),
		Timeout:         5 * time.Second,
	})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		client.Close()
		cancel()
		<-served
	})
	return &sessionPair{client: client, home: home}
}

func (p *sessionPair) open(t *testing.T) *ssh.Session {
	t.Helper()
	opened, err := p.client.NewSession()
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { opened.Close() })
	return opened
}

func TestExecReturnsItsOutputAndExitStatus(t *testing.T) {
	command := startSessions(t).open(t)
	var stdout, stderr bytes.Buffer
	command.Stdout, command.Stderr = &stdout, &stderr
	err := command.Run("echo out; echo err >&2; exit 3")
	var exit *ssh.ExitError
	if !errors.As(err, &exit) || exit.ExitStatus() != 3 {
		t.Fatalf("got %v, want exit status 3", err)
	}
	if stdout.String() != "out\n" || stderr.String() != "err\n" {
		t.Fatalf("stdout %q stderr %q", stdout.String(), stderr.String())
	}
}

func TestExecRunsInTheHomeWithTheClientsInput(t *testing.T) {
	pair := startSessions(t)
	command := pair.open(t)
	command.Stdin = strings.NewReader("from the client")
	output, err := command.Output("pwd; cat")
	if err != nil {
		t.Fatal(err)
	}
	if string(output) != pair.home+"\nfrom the client" {
		t.Fatalf("got %q", output)
	}
}

func TestExecEndedBySignalReportsTheSignal(t *testing.T) {
	err := startSessions(t).open(t).Run("kill -TERM $$")
	var exit *ssh.ExitError
	if !errors.As(err, &exit) || exit.Signal() != "TERM" {
		t.Fatalf("got %v, want signal TERM", err)
	}
}

func TestAShellThatCannotStartExitsUnstartable(t *testing.T) {
	command := startSessionsWithShell(t, "/nonexistent/no_shell").open(t)
	var stderr bytes.Buffer
	command.Stderr = &stderr
	err := command.Run("true")
	var exit *ssh.ExitError
	if !errors.As(err, &exit) || exit.ExitStatus() != SessionExitUnstartable {
		t.Fatalf("got %v, want exit status %d", err, SessionExitUnstartable)
	}
	if !strings.Contains(stderr.String(), "/nonexistent/no_shell") {
		t.Fatalf("stderr %q does not name the shell", stderr.String())
	}
}

func TestExecPassesTheLocaleAndThePeerAlone(t *testing.T) {
	command := startSessions(t).open(t)
	if err := command.Setenv("LANG", "C.UTF-8"); err != nil {
		t.Fatalf("LANG refused: %v", err)
	}
	if err := command.Setenv("LD_PRELOAD", "/tmp/x.so"); err == nil {
		t.Fatal("LD_PRELOAD accepted")
	}
	output, err := command.Output(`echo "$LANG|$LD_PRELOAD|$SSH_CONNECTION|$SHELL"`)
	if err != nil {
		t.Fatal(err)
	}
	fields := strings.Split(strings.TrimSpace(string(output)), "|")
	if fields[0] != "C.UTF-8" || fields[1] != "" || !strings.HasPrefix(fields[2], "127.0.0.1 ") {
		t.Fatalf("got %q", output)
	}
}

func TestShellRunsAsALoginShellOnATerminal(t *testing.T) {
	shell := startSessions(t).open(t)
	if err := shell.RequestPty("xterm-test", 30, 100, ssh.TerminalModes{}); err != nil {
		t.Fatal(err)
	}
	input, err := shell.StdinPipe()
	if err != nil {
		t.Fatal(err)
	}
	var output bytes.Buffer
	shell.Stdout = &output
	if err := shell.Shell(); err != nil {
		t.Fatal(err)
	}
	io.WriteString(input, "echo \"term=$TERM zero=$0\"; tty; stty size; exit 4\n")
	err = shell.Wait()
	var exit *ssh.ExitError
	if !errors.As(err, &exit) || exit.ExitStatus() != 4 {
		t.Fatalf("got %v, want exit status 4; output %q", err, output.String())
	}
	for _, want := range []string{"term=xterm-test zero=-sh", "/dev/pts/", "30 100"} {
		if !strings.Contains(output.String(), want) {
			t.Errorf("output %q lacks %q", output.String(), want)
		}
	}
}

func TestExecOnATerminalReturnsItsExitStatus(t *testing.T) {
	command := startSessions(t).open(t)
	if err := command.RequestPty("xterm", 24, 80, ssh.TerminalModes{}); err != nil {
		t.Fatal(err)
	}
	output, err := command.Output("tty; exit 5")
	var exit *ssh.ExitError
	if !errors.As(err, &exit) || exit.ExitStatus() != 5 || !strings.Contains(string(output), "/dev/pts/") {
		t.Fatalf("got %v, output %q", err, output)
	}
}

func TestWindowChangeResizesTheTerminal(t *testing.T) {
	shell := startSessions(t).open(t)
	if err := shell.RequestPty("xterm", 24, 80, ssh.TerminalModes{}); err != nil {
		t.Fatal(err)
	}
	input, _ := shell.StdinPipe()
	var output bytes.Buffer
	shell.Stdout = &output
	if err := shell.Shell(); err != nil {
		t.Fatal(err)
	}
	if err := shell.WindowChange(50, 132); err != nil {
		t.Fatal(err)
	}
	io.WriteString(input, "stty size; exit 0\n")
	if err := shell.Wait(); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(output.String(), "50 132") {
		t.Fatalf("output %q lacks the new size", output.String())
	}
}

func TestSFTPServesTheHome(t *testing.T) {
	pair := startSessions(t)
	client, err := sftp.NewClient(pair.client)
	if err != nil {
		t.Fatal(err)
	}
	defer client.Close()
	directory, err := client.Getwd()
	if err != nil || directory != pair.home {
		t.Fatalf("working directory %q, %v", directory, err)
	}
	file, err := client.Create("put.txt")
	if err != nil {
		t.Fatal(err)
	}
	file.Write([]byte("put through sftp"))
	file.Close()
	held, err := os.ReadFile(filepath.Join(pair.home, "put.txt"))
	if err != nil || string(held) != "put through sftp" {
		t.Fatalf("put: %q, %v", held, err)
	}
	os.WriteFile(filepath.Join(pair.home, "get.txt"), []byte("got through sftp"), 0o600)
	read, err := client.Open("get.txt")
	if err != nil {
		t.Fatal(err)
	}
	defer read.Close()
	got, err := io.ReadAll(read)
	if err != nil || string(got) != "got through sftp" {
		t.Fatalf("get: %q, %v", got, err)
	}
}

func TestSFTPEndsWithExitStatusZero(t *testing.T) {
	channel, requests, err := startSessions(t).client.OpenChannel("session", nil)
	if err != nil {
		t.Fatal(err)
	}
	defer channel.Close()
	isAccepted, err := channel.SendRequest(SessionRequestSubsystem, true, ssh.Marshal(struct{ Name string }{SessionSubsystemSFTP}))
	if err != nil || !isAccepted {
		t.Fatalf("subsystem accepted %v, %v", isAccepted, err)
	}
	channel.CloseWrite()
	for request := range requests {
		if request.Type == "exit-status" {
			var status struct{ Status uint32 }
			if err := ssh.Unmarshal(request.Payload, &status); err != nil || status.Status != 0 {
				t.Fatalf("exit status %d, %v", status.Status, err)
			}
			return
		}
	}
	t.Fatal("the channel closed with no exit status")
}

func TestEveryOtherSessionRequestIsRefused(t *testing.T) {
	pair := startSessions(t)
	for _, request := range []struct {
		name    string
		payload []byte
	}{
		{"x11-req", ssh.Marshal(struct {
			Single   bool
			Protocol string
			Cookie   string
			Screen   uint32
		}{false, "MIT-MAGIC-COOKIE-1", "00", 0})},
		{"auth-agent-req@openssh.com", nil},
		{"subsystem", ssh.Marshal(struct{ Name string }{"netconf"})},
		{"signal", ssh.Marshal(struct{ Name string }{"KILL"})},
		{"keepalive@openssh.com", nil},
	} {
		t.Run(request.name, func(t *testing.T) {
			isAccepted, err := pair.open(t).SendRequest(request.name, true, request.payload)
			if err != nil || isAccepted {
				t.Fatalf("accepted %v, %v", isAccepted, err)
			}
		})
	}
	t.Run("a second command on one session", func(t *testing.T) {
		opened := pair.open(t)
		if err := opened.Start("sleep 1"); err != nil {
			t.Fatal(err)
		}
		isAccepted, err := opened.SendRequest("exec", true, ssh.Marshal(struct{ Command string }{"true"}))
		if err != nil || isAccepted {
			t.Fatalf("accepted %v, %v", isAccepted, err)
		}
	})
	t.Run("a terminal after the command started", func(t *testing.T) {
		opened := pair.open(t)
		if err := opened.Start("sleep 1"); err != nil {
			t.Fatal(err)
		}
		if err := opened.RequestPty("xterm", 24, 80, ssh.TerminalModes{}); err == nil {
			t.Fatal("terminal accepted")
		}
	})
}
