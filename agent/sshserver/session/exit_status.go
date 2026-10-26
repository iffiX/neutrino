package session

import (
	"golang.org/x/crypto/ssh"
)

// exitStatus is how a process ended: its exit code, or the signal that
// ended it.
type exitStatus struct {
	code   uint32
	signal string
}

// send reports the status on channel as OpenSSH does: exit-signal for a
// signal, exit-status otherwise. It returns the channel's error.
func (s exitStatus) send(channel ssh.Channel) error {
	if s.signal != "" {
		payload := ssh.Marshal(struct {
			Signal     string
			CoreDumped bool
			Error      string
			Language   string
		}{Signal: s.signal})
		_, err := channel.SendRequest("exit-signal", false, payload)
		return err
	}
	_, err := channel.SendRequest("exit-status", false, ssh.Marshal(struct{ Status uint32 }{s.code}))
	return err
}
