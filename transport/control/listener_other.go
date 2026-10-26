//go:build !windows

package control

import (
	"fmt"
	"net"
)

// listenPipe is a Windows named pipe, which this system has none of.
func listenPipe(path string, isPrivate bool) (net.Listener, error) {
	return nil, fmt.Errorf("listen on %s: named pipes exist on Windows alone", path)
}
