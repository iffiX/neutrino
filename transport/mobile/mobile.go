package mobile

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sync"

	"github.com/iffiX/neutrino/transport/control"
	"github.com/iffiX/neutrino/transport/session"
)

const (
	// MobileSocketName is the socket's file name in the directory given.
	MobileSocketName = "transport.sock"
	// MobileSocketPathMax is the longest socket path every system binds: one
	// below Darwin's sun_path.
	MobileSocketPathMax = 103
	// MobileFallbackDirMode is the mode of the directory made under the
	// system's temporary directory when the given path is too long.
	MobileFallbackDirMode = 0o700
)

var (
	// mu guards running.
	mu      sync.Mutex
	running *control.ClientControl
	// ErrAlreadyRunning is a Start while the transport runs.
	ErrAlreadyRunning = errors.New("transport already running")
)

// Start runs the client's local channel on transport.sock in directory,
// admitting connections that open with secret, and returns the socket's
// path: in directory when the path fits the system's socket path limit, else
// in a directory of the library's own under the system's temporary
// directory. It returns ErrAlreadyRunning while a Start holds, and an error
// when the socket cannot be bound.
func Start(directory, secret string) (string, error) {
	mu.Lock()
	defer mu.Unlock()
	if running != nil {
		return "", ErrAlreadyRunning
	}
	if len(secret) != control.ControlSecretChars {
		return "", fmt.Errorf("secret: %d characters, want %d", len(secret), control.ControlSecretChars)
	}
	path, err := socketPath(directory)
	if err != nil {
		return "", err
	}
	listener, err := control.Listen(path, true)
	if err != nil {
		return "", err
	}
	client := control.NewClientControl(listener, secret, session.DefaultTimings, nil)
	running = client
	go client.Serve()
	return path, nil
}

// Stop ends the local channel and every session; it does nothing while none
// runs.
func Stop() {
	mu.Lock()
	client := running
	running = nil
	mu.Unlock()
	if client != nil {
		client.Close()
	}
}

// IsRunning reports whether Start holds.
func IsRunning() bool {
	mu.Lock()
	defer mu.Unlock()
	return running != nil
}

// socketPath picks where the socket is bound.
func socketPath(directory string) (string, error) {
	path := filepath.Join(directory, MobileSocketName)
	if len(path) <= MobileSocketPathMax {
		return path, nil
	}
	fallback, err := os.MkdirTemp("", "neutrino_")
	if err != nil {
		return "", fmt.Errorf("fallback directory: %w", err)
	}
	if err := os.Chmod(fallback, MobileFallbackDirMode); err != nil {
		return "", fmt.Errorf("fallback directory: %w", err)
	}
	path = filepath.Join(fallback, MobileSocketName)
	if len(path) > MobileSocketPathMax {
		return "", fmt.Errorf("socket path too long: %s", path)
	}
	return path, nil
}
