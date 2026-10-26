//go:build linux || darwin

package session

import (
	"fmt"
	"os"
	"os/exec"
	"syscall"
	"time"
	"unsafe"

	"golang.org/x/crypto/ssh"
)

// terminalProcess is a shell or a command on a pseudo-terminal, the
// session leader with the terminal as its controlling terminal.
type terminalProcess struct {
	cmd    *exec.Cmd
	master *os.File
	// outputDone is closed once the terminal's output reached its end.
	outputDone chan struct{}
}

// terminalSize is the kernel's struct winsize.
type terminalSize struct {
	rows    uint16
	columns uint16
	xPixels uint16
	yPixels uint16
}

// startTerminalProcess starts cmd on a new pseudo-terminal of the
// requested type and size: the channel's data to the terminal's input and
// the terminal's output to the channel's data. It returns the terminal's or
// the start's error, with nothing left running.
func startTerminalProcess(cmd *exec.Cmd, channel ssh.Channel, terminal terminalRequest) (*terminalProcess, error) {
	master, slave, err := openTerminal()
	if err != nil {
		return nil, err
	}
	if err := setTerminalSize(master, terminal.columns, terminal.rows); err != nil {
		closeFiles(master, slave)
		return nil, err
	}
	cmd.Env = withVariables(cmd.Env, []string{"TERM=" + terminal.term, "SSH_TTY=" + slave.Name()})
	cmd.Stdin, cmd.Stdout, cmd.Stderr = slave, slave, slave
	cmd.SysProcAttr = &syscall.SysProcAttr{Setsid: true, Setctty: true, Ctty: 0}
	err = cmd.Start()
	slave.Close()
	if err != nil {
		master.Close()
		return nil, fmt.Errorf("start %s: %w", cmd.Path, err)
	}
	process := &terminalProcess{cmd: cmd, master: master, outputDone: make(chan struct{})}
	go func() {
		defer close(process.outputDone)
		copyStream(channel, master)
	}()
	go copyStream(master, channel)
	return process, nil
}

// wait returns once the process ended and the terminal's output reached
// its end, or SessionTerminalDrain after the process ended while a process
// it left behind holds the terminal; the terminal is then closed.
func (p *terminalProcess) wait() exitStatus {
	p.cmd.Wait()
	timer := time.NewTimer(SessionTerminalDrain)
	select {
	case <-p.outputDone:
	case <-timer.C:
	}
	timer.Stop()
	p.master.Close()
	return statusOf(p.cmd.ProcessState)
}

// resize sets the terminal's size; a failure leaves the size it had.
func (p *terminalProcess) resize(columns, rows uint32) {
	setTerminalSize(p.master, columns, rows)
}

// abandon closes the terminal once the channel is gone, which hangs up the
// session's processes.
func (p *terminalProcess) abandon() {
	p.master.Close()
}

// setTerminalSize sets a terminal's size in characters, each bounded to
// what the kernel holds. It returns the ioctl's error.
func setTerminalSize(master *os.File, columns, rows uint32) error {
	size := terminalSize{rows: boundedCells(rows, SessionDefaultRows), columns: boundedCells(columns, SessionDefaultColumns)}
	if err := ioctl(master, syscall.TIOCSWINSZ, unsafe.Pointer(&size)); err != nil {
		return fmt.Errorf("set terminal size: %w", err)
	}
	return nil
}

// ioctl runs one ioctl on file without taking the file out of the
// runtime's poller. It returns the system's error.
func ioctl(file *os.File, request uintptr, argument unsafe.Pointer) error {
	conn, err := file.SyscallConn()
	if err != nil {
		return err
	}
	var errno syscall.Errno
	err = conn.Control(func(descriptor uintptr) {
		_, _, errno = syscall.Syscall(syscall.SYS_IOCTL, descriptor, request, uintptr(argument))
	})
	if err != nil {
		return err
	}
	if errno != 0 {
		return errno
	}
	return nil
}

// boundedCells returns a size in cells that a uint16 holds, fallback for 0.
func boundedCells(value uint32, fallback uint16) uint16 {
	if value == 0 {
		return fallback
	}
	if value > 0xFFFF {
		return 0xFFFF
	}
	return uint16(value)
}
