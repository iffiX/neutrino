package control

import (
	"net"
	"strings"
)

// IsPipePath reports whether a path names a Windows named pipe.
func IsPipePath(path string) bool {
	return strings.HasPrefix(path, ControlPipePrefix)
}

// Listen opens the local channel's listener at path: a Unix socket, mode
// 0600 in a directory made with mode 0700 when missing, or a Windows named
// pipe whose access list isPrivate narrows to the owner alone.
func Listen(path string, isPrivate bool) (net.Listener, error) {
	if IsPipePath(path) {
		return listenPipe(path, isPrivate)
	}
	return listenUnix(path)
}
