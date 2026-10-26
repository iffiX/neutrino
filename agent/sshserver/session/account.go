package session

import (
	"os"
	"os/user"
	"runtime"
	"strings"
)

// Account is what every session of the account starts with.
type Account struct {
	// Shell is the program a shell or a command starts, an absolute path.
	Shell string
	// Home is the directory a session starts in, and the one sftp's
	// relative paths start from.
	Home string
	// Environment is the server's own environment without its own
	// variables, SHELL naming Shell.
	Environment []string
}

// CurrentAccount returns the account the process runs as, its sessions
// starting shell. On Linux and macOS a HOME, USER, LOGNAME or PATH the
// process was started without is filled in from the account database and
// SessionDefaultPath.
func CurrentAccount(shell string) Account {
	environment := []string{}
	for _, entry := range os.Environ() {
		if !strings.HasPrefix(entry, SessionServerVariablePrefix) {
			environment = append(environment, entry)
		}
	}
	home, err := os.UserHomeDir()
	if runtime.GOOS != "windows" {
		if current, lookupErr := user.Current(); lookupErr == nil {
			if err != nil || home == "" {
				home = current.HomeDir
			}
			environment = withDefault(environment, "HOME", home)
			environment = withDefault(environment, "USER", current.Username)
			environment = withDefault(environment, "LOGNAME", current.Username)
		}
		environment = withDefault(environment, "PATH", SessionDefaultPath)
	}
	environment = withVariable(environment, "SHELL", shell)
	return Account{Shell: shell, Home: home, Environment: environment}
}

// withDefault returns environment with name set to value unless it names
// it already.
func withDefault(environment []string, name, value string) []string {
	if _, found := lookupVariable(environment, name); found || value == "" {
		return environment
	}
	return append(environment, name+"="+value)
}
