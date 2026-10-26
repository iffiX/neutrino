//go:build !windows

package relay

import (
	"errors"
	"syscall"
)

// isRefused reports whether a dial's error is a closed port's refusal.
func isRefused(err error) bool {
	return errors.Is(err, syscall.ECONNREFUSED)
}
