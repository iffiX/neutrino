//go:build windows

package relay

import (
	"errors"
	"syscall"
)

// wsaConnRefused is WSAECONNREFUSED, what Winsock answers for a closed port.
const wsaConnRefused = syscall.Errno(10061)

// isRefused reports whether a dial's error is a closed port's refusal.
func isRefused(err error) bool {
	return errors.Is(err, syscall.ECONNREFUSED) || errors.Is(err, wsaConnRefused)
}
