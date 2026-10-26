//go:build linux || darwin

package session

import (
	"os"
	"syscall"
)

// signalNames are the signals an exit-signal names, by number.
var signalNames = map[syscall.Signal]string{
	syscall.SIGABRT: "ABRT",
	syscall.SIGALRM: "ALRM",
	syscall.SIGFPE:  "FPE",
	syscall.SIGHUP:  "HUP",
	syscall.SIGILL:  "ILL",
	syscall.SIGINT:  "INT",
	syscall.SIGKILL: "KILL",
	syscall.SIGPIPE: "PIPE",
	syscall.SIGQUIT: "QUIT",
	syscall.SIGSEGV: "SEGV",
	syscall.SIGTERM: "TERM",
	syscall.SIGUSR1: "USR1",
	syscall.SIGUSR2: "USR2",
}

// statusOf returns how a process that ended did so: the signal that ended
// it by name, 128 and its number for a signal with no name, or its exit
// code.
func statusOf(state *os.ProcessState) exitStatus {
	if state == nil {
		return exitStatus{code: SessionExitUnstartable}
	}
	if wait, ok := state.Sys().(syscall.WaitStatus); ok && wait.Signaled() {
		if name, ok := signalNames[wait.Signal()]; ok {
			return exitStatus{signal: name}
		}
		return exitStatus{code: 128 + uint32(wait.Signal())}
	}
	return exitStatus{code: uint32(state.ExitCode())}
}
