//go:build linux || darwin

package session

import "os"

// openPathFolders opens the path folders file for reading.
func openPathFolders(path string) (*os.File, error) {
	return os.Open(path)
}
