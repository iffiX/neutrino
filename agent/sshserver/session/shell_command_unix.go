//go:build linux || darwin

package session

import (
	"os/exec"
	"path/filepath"
)

// shellCommand returns how the account's shell starts: as a login shell,
// argv[0] being "-" and its name, or with -c and command.
func shellCommand(account Account, command string, isLogin bool) *exec.Cmd {
	name := filepath.Base(account.Shell)
	cmd := &exec.Cmd{Path: account.Shell, Dir: workingDirectory(account.Home)}
	if isLogin {
		cmd.Args = []string{"-" + name}
	} else {
		cmd.Args = []string{name, "-c", command}
	}
	return cmd
}

// sftpDirectory returns the directory sftp's relative paths start from, in
// the form pkg/sftp takes on this system.
func sftpDirectory(home string) string {
	return workingDirectory(home)
}
