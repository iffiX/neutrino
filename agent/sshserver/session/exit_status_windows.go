//go:build windows

package session

import "os"

// statusOf returns a process's exit code.
func statusOf(state *os.ProcessState) exitStatus {
	if state == nil {
		return exitStatus{code: SessionExitUnstartable}
	}
	return exitStatus{code: uint32(state.ExitCode())}
}
