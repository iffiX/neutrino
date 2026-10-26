package session

import (
	"fmt"
	"os"
	"os/exec"
	"sync"

	"golang.org/x/crypto/ssh"
)

// pipeProcess is a shell or a command whose standard input, output and
// error are three pipes to the channel.
type pipeProcess struct {
	cmd    *exec.Cmd
	stdin  *os.File
	stdout *os.File
	stderr *os.File
	// output is done once stdout and stderr both reached their end.
	output sync.WaitGroup
}

// startPipeProcess starts cmd on three pipes: the channel's data to its
// standard input until the client's end of input, its standard output to
// the channel's data and its standard error to the channel's extended data.
// It returns the pipe's or the start's error, with nothing left running.
func startPipeProcess(cmd *exec.Cmd, channel ssh.Channel) (*pipeProcess, error) {
	stdinRead, stdinWrite, err := os.Pipe()
	if err != nil {
		return nil, fmt.Errorf("make stdin pipe: %w", err)
	}
	stdoutRead, stdoutWrite, err := os.Pipe()
	if err != nil {
		closeFiles(stdinRead, stdinWrite)
		return nil, fmt.Errorf("make stdout pipe: %w", err)
	}
	stderrRead, stderrWrite, err := os.Pipe()
	if err != nil {
		closeFiles(stdinRead, stdinWrite, stdoutRead, stdoutWrite)
		return nil, fmt.Errorf("make stderr pipe: %w", err)
	}
	cmd.Stdin, cmd.Stdout, cmd.Stderr = stdinRead, stdoutWrite, stderrWrite
	err = cmd.Start()
	closeFiles(stdinRead, stdoutWrite, stderrWrite)
	if err != nil {
		closeFiles(stdinWrite, stdoutRead, stderrRead)
		return nil, fmt.Errorf("start %s: %w", cmd.Path, err)
	}
	process := &pipeProcess{cmd: cmd, stdin: stdinWrite, stdout: stdoutRead, stderr: stderrRead}
	process.output.Add(2)
	go func() {
		defer process.output.Done()
		copyStream(channel, stdoutRead)
	}()
	go func() {
		defer process.output.Done()
		copyStream(channel.Stderr(), stderrRead)
	}()
	go func() {
		copyStream(stdinWrite, channel)
		stdinWrite.Close()
	}()
	return process, nil
}

// wait returns once the process ended and its output reached its end, or
// was abandoned.
func (p *pipeProcess) wait() exitStatus {
	p.cmd.Wait()
	p.output.Wait()
	closeFiles(p.stdin, p.stdout, p.stderr)
	return statusOf(p.cmd.ProcessState)
}

// resize does nothing: a process on pipes has no terminal.
func (p *pipeProcess) resize(columns, rows uint32) {}

// abandon closes the server's ends of the pipes once the channel is gone;
// the process runs on, as under OpenSSH.
func (p *pipeProcess) abandon() {
	closeFiles(p.stdin, p.stdout, p.stderr)
}

// closeFiles closes each file, ignoring an error.
func closeFiles(files ...*os.File) {
	for _, file := range files {
		file.Close()
	}
}
