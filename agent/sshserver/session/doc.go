// Package session serves one SSH session channel as the account the
// process runs as: the account's shell on a pseudo-terminal, a pseudo
// console on Windows, a command through that shell with its exit status, or
// the sftp subsystem. A session takes the first of a shell, a command or a
// subsystem and refuses every other kind of request, X11 and agent
// forwarding among them.
package session
