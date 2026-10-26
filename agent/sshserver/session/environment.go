package session

import (
	"net"
	"runtime"
	"strings"
)

// PeerEnvironment returns SSH_CLIENT and SSH_CONNECTION for a connection
// from remote to local, as OpenSSH sets them.
func PeerEnvironment(remote, local net.Addr) []string {
	remoteHost, remotePort := splitAddress(remote)
	localHost, localPort := splitAddress(local)
	return []string{
		"SSH_CLIENT=" + remoteHost + " " + remotePort + " " + localPort,
		"SSH_CONNECTION=" + remoteHost + " " + remotePort + " " + localHost + " " + localPort,
	}
}

// isAcceptedVariable returns whether a client may set a variable by name:
// the locale's alone, LANG, LANGUAGE and LC_*.
func isAcceptedVariable(name string) bool {
	if name == "" || strings.ContainsAny(name, "=\x00") {
		return false
	}
	return name == "LANG" || name == "LANGUAGE" || strings.HasPrefix(name, "LC_")
}

// withVariable returns environment with name set to value, in place of
// what it held.
func withVariable(environment []string, name, value string) []string {
	result := make([]string, 0, len(environment)+1)
	for _, entry := range environment {
		if !isVariable(entry, name) {
			result = append(result, entry)
		}
	}
	return append(result, name+"="+value)
}

// withVariables returns environment with each NAME=value entry of added
// set in turn.
func withVariables(environment []string, added []string) []string {
	for _, entry := range added {
		name, value, _ := strings.Cut(entry, "=")
		environment = withVariable(environment, name, value)
	}
	return environment
}

// lookupVariable returns a variable's value in environment.
func lookupVariable(environment []string, name string) (string, bool) {
	for _, entry := range environment {
		if isVariable(entry, name) {
			_, value, _ := strings.Cut(entry, "=")
			return value, true
		}
	}
	return "", false
}

// isVariable returns whether a NAME=value entry names name, ignoring case
// on Windows.
func isVariable(entry, name string) bool {
	held, _, _ := strings.Cut(entry, "=")
	if runtime.GOOS == "windows" {
		return strings.EqualFold(held, name)
	}
	return held == name
}

// splitAddress returns an address's host and port, the host without
// brackets.
func splitAddress(address net.Addr) (string, string) {
	if address == nil {
		return "", ""
	}
	host, port, err := net.SplitHostPort(address.String())
	if err != nil {
		return address.String(), ""
	}
	return host, port
}
