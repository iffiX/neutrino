package control

import (
	"errors"
	"fmt"
	"net"
	"os"
	"path/filepath"
)

// listenUnix opens a Unix socket at path, mode 0600, removing a stale one.
func listenUnix(path string) (net.Listener, error) {
	if err := os.MkdirAll(filepath.Dir(path), ControlSocketDirMode); err != nil {
		return nil, fmt.Errorf("socket directory: %w", err)
	}
	if err := os.Remove(path); err != nil && !errors.Is(err, os.ErrNotExist) {
		return nil, fmt.Errorf("remove stale socket: %w", err)
	}
	listener, err := net.Listen("unix", path)
	if err != nil {
		return nil, fmt.Errorf("listen on %s: %w", path, err)
	}
	if err := os.Chmod(path, ControlSocketMode); err != nil {
		listener.Close()
		return nil, fmt.Errorf("chmod %s: %w", path, err)
	}
	return listener, nil
}
