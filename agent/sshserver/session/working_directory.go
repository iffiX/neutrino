package session

import "os"

// workingDirectory returns home when it is a directory, else the system's
// root on Linux and macOS and the server's own on Windows, by an empty
// string there.
func workingDirectory(home string) string {
	if info, err := os.Stat(home); err == nil && info.IsDir() {
		return home
	}
	if os.PathSeparator == '/' {
		return "/"
	}
	return ""
}
