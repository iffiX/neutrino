//go:build windows

package session

import (
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
)

// shellCommand returns how the account's shell starts: alone, or running
// command, the command line written whole as PowerShell, cmd.exe and a
// POSIX shell each read it.
func shellCommand(account Account, command string, isLogin bool) *exec.Cmd {
	line := syscall.EscapeArg(account.Shell)
	if !isLogin {
		switch strings.ToLower(filepath.Base(account.Shell)) {
		case "powershell.exe", "pwsh.exe":
			line += " -Command " + command
		case "cmd.exe":
			line += " /c " + command
		default:
			line += " -c " + syscall.EscapeArg(command)
		}
	}
	return &exec.Cmd{
		Path:        account.Shell,
		Args:        []string{account.Shell},
		Dir:         workingDirectory(account.Home),
		SysProcAttr: &syscall.SysProcAttr{CmdLine: line, HideWindow: true},
	}
}

// sftpDirectory returns the directory sftp's relative paths start from, in
// the form pkg/sftp takes on Windows: "/C:/Users/name".
func sftpDirectory(home string) string {
	directory := workingDirectory(home)
	if directory == "" {
		return ""
	}
	return "/" + filepath.ToSlash(directory)
}
