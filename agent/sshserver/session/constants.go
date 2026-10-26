package session

import "time"

const (
	// SessionRequestTerminal asks for a pseudo-terminal before the shell or
	// the command starts.
	SessionRequestTerminal = "pty-req"
	// SessionRequestEnvironment names one environment variable.
	SessionRequestEnvironment = "env"
	// SessionRequestShell starts the account's shell.
	SessionRequestShell = "shell"
	// SessionRequestExec runs one command through the account's shell.
	SessionRequestExec = "exec"
	// SessionRequestSubsystem starts a subsystem by name.
	SessionRequestSubsystem = "subsystem"
	// SessionRequestWindowChange resizes the pseudo-terminal.
	SessionRequestWindowChange = "window-change"

	// SessionSubsystemSFTP is the one subsystem served.
	SessionSubsystemSFTP = "sftp"

	// SessionKindShell, SessionKindExec and SessionKindSFTP name what a
	// session ran.
	SessionKindShell = "shell"
	SessionKindExec  = "exec"
	SessionKindSFTP  = "sftp"

	// SessionEnvironmentLimit is how many variables a client may name.
	SessionEnvironmentLimit = 32

	// SessionDefaultColumns and SessionDefaultRows size a terminal whose
	// request names no size.
	SessionDefaultColumns = 80
	SessionDefaultRows    = 24

	// SessionTerminalDrain is how long a terminal's output is still read
	// after its process ended while a process it left behind holds the
	// terminal open, and on Windows how long the console runs on after its
	// process ended.
	SessionTerminalDrain = 200 * time.Millisecond

	// SessionConsoleDrain bounds the wait for a closed pseudo console's
	// last output on Windows.
	SessionConsoleDrain = 2 * time.Second

	// SessionExitUnstartable is the exit status of a shell or a command
	// that could not start.
	SessionExitUnstartable = 127

	// SessionServerVariablePrefix starts the names of the server's own
	// variables, which no session inherits.
	SessionServerVariablePrefix = "NEUTRINO_"

	// SessionDefaultPath is the PATH of a session on Linux and macOS whose
	// server was started without one.
	SessionDefaultPath = "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

	// SessionCopyBufferBytes is the size of one copy buffer.
	SessionCopyBufferBytes = 32 * 1024

	// SessionAttributePseudoConsole is PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE.
	SessionAttributePseudoConsole = 0x00020016
	// SessionCreateExtendedStartupInfo is EXTENDED_STARTUPINFO_PRESENT.
	SessionCreateExtendedStartupInfo = 0x00080000
	// SessionCreateUnicodeEnvironment is CREATE_UNICODE_ENVIRONMENT.
	SessionCreateUnicodeEnvironment = 0x00000400
)
