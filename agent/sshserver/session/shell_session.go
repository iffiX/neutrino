package session

import (
	"context"
	"fmt"

	"github.com/pkg/sftp"
	"golang.org/x/crypto/ssh"
)

// runningProcess is a started shell or command.
type runningProcess interface {
	// wait returns how the process ended, once it ended and its output was
	// passed on.
	wait() exitStatus
	// resize sets the terminal's size; a process with no terminal ignores it.
	resize(columns, rows uint32)
	// abandon stops passing input and output once the channel is gone.
	abandon()
}

// terminalRequest is what a pty-req asked for.
type terminalRequest struct {
	term    string
	columns uint32
	rows    uint32
}

// ShellSession serves one session channel.
type ShellSession struct {
	channel  ssh.Channel
	requests <-chan *ssh.Request
	account  Account
	peer     []string
	// The fields below are read and written by Serve's goroutine alone.
	kind        string
	terminal    *terminalRequest
	environment []string
	process     runningProcess
}

// NewShellSession returns the session of channel, whose requests arrive on
// requests; its processes start as account with peer's SSH_CLIENT and
// SSH_CONNECTION.
func NewShellSession(channel ssh.Channel, requests <-chan *ssh.Request, account Account, peer []string) *ShellSession {
	return &ShellSession{channel: channel, requests: requests, account: account, peer: peer}
}

// Serve answers the channel's requests until the channel or ctx ends. It
// returns what the session ran, SessionKindShell, SessionKindExec,
// SessionKindSFTP or empty, and ctx's error when ctx ended first.
func (s *ShellSession) Serve(ctx context.Context) (string, error) {
	defer s.abandon()
	for {
		select {
		case <-ctx.Done():
			return s.kind, ctx.Err()
		case request, ok := <-s.requests:
			if !ok {
				return s.kind, nil
			}
			s.answer(request)
		}
	}
}

// answer handles one request and replies to it where the client asked.
func (s *ShellSession) answer(request *ssh.Request) {
	isAccepted := false
	switch request.Type {
	case SessionRequestTerminal:
		isAccepted = s.takeTerminal(request.Payload)
	case SessionRequestEnvironment:
		isAccepted = s.takeVariable(request.Payload)
	case SessionRequestWindowChange:
		isAccepted = s.takeWindowChange(request.Payload)
	case SessionRequestShell:
		if s.kind == "" && len(request.Payload) == 0 {
			reply(request, true)
			s.start(SessionKindShell, "", true)
			return
		}
	case SessionRequestExec:
		var payload struct{ Command string }
		if s.kind == "" && ssh.Unmarshal(request.Payload, &payload) == nil {
			reply(request, true)
			s.start(SessionKindExec, payload.Command, false)
			return
		}
	case SessionRequestSubsystem:
		var payload struct{ Name string }
		if s.kind == "" && ssh.Unmarshal(request.Payload, &payload) == nil && payload.Name == SessionSubsystemSFTP {
			reply(request, true)
			s.kind = SessionKindSFTP
			go s.serveSFTP()
			return
		}
	}
	reply(request, isAccepted)
}

// takeTerminal keeps a pty-req made before the session started.
func (s *ShellSession) takeTerminal(payload []byte) bool {
	var request struct {
		Term    string
		Columns uint32
		Rows    uint32
		Width   uint32
		Height  uint32
		Modes   string
	}
	if s.kind != "" || ssh.Unmarshal(payload, &request) != nil {
		return false
	}
	s.terminal = &terminalRequest{term: request.Term, columns: request.Columns, rows: request.Rows}
	return true
}

// takeVariable keeps a locale variable named before the session started.
func (s *ShellSession) takeVariable(payload []byte) bool {
	var request struct {
		Name  string
		Value string
	}
	if s.kind != "" || ssh.Unmarshal(payload, &request) != nil {
		return false
	}
	if !isAcceptedVariable(request.Name) || len(s.environment) >= SessionEnvironmentLimit {
		return false
	}
	s.environment = append(s.environment, request.Name+"="+request.Value)
	return true
}

// takeWindowChange resizes the terminal of a running process, or the one
// asked for before it starts.
func (s *ShellSession) takeWindowChange(payload []byte) bool {
	var request struct {
		Columns uint32
		Rows    uint32
		Width   uint32
		Height  uint32
	}
	if ssh.Unmarshal(payload, &request) != nil || s.terminal == nil {
		return false
	}
	s.terminal.columns, s.terminal.rows = request.Columns, request.Rows
	if s.process != nil {
		s.process.resize(request.Columns, request.Rows)
	}
	return true
}

// start runs the account's shell, as a login shell or with command, on the
// terminal asked for or on pipes; a process that cannot start ends the
// session with its error on the extended data and SessionExitUnstartable.
func (s *ShellSession) start(kind, command string, isLogin bool) {
	s.kind = kind
	cmd := shellCommand(s.account, command, isLogin)
	cmd.Env = withVariables(withVariables(append([]string{}, s.account.Environment...), s.peer), s.environment)
	var process runningProcess
	var err error
	if s.terminal != nil {
		process, err = startTerminalProcess(cmd, s.channel, *s.terminal)
	} else {
		process, err = startPipeProcess(cmd, s.channel)
	}
	if err != nil {
		fmt.Fprintf(s.channel.Stderr(), "neutrino_ssh_server: %v\r\n", err)
		s.finish(exitStatus{code: SessionExitUnstartable})
		return
	}
	s.process = process
	go func() {
		s.finish(process.wait())
	}()
}

// serveSFTP serves the sftp subsystem from the account's home until the
// client ends it.
func (s *ShellSession) serveSFTP() {
	server, err := sftp.NewServer(s.channel, sftp.WithServerWorkingDirectory(sftpDirectory(s.account.Home)))
	if err != nil {
		fmt.Fprintf(s.channel.Stderr(), "neutrino_ssh_server: %v\r\n", err)
		s.finish(exitStatus{code: SessionExitUnstartable})
		return
	}
	code := uint32(0)
	if err := server.Serve(); err != nil {
		code = 1
	}
	s.finish(exitStatus{code: code})
}

// finish reports how the session's work ended and closes the channel.
func (s *ShellSession) finish(status exitStatus) {
	status.send(s.channel)
	s.channel.CloseWrite()
	s.channel.Close()
}

// abandon lets the running process go once the channel is gone.
func (s *ShellSession) abandon() {
	if s.process != nil {
		s.process.abandon()
	}
}

// reply answers a request that asked for an answer.
func reply(request *ssh.Request, isAccepted bool) {
	if request.WantReply {
		request.Reply(isAccepted, nil)
	}
}
