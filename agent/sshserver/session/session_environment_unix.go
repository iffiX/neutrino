//go:build linux || darwin

package session

// sessionEnvironment returns the environment a shell or a command starts
// from: the account's, as the server started with it.
func sessionEnvironment(account Account) []string {
	return append([]string{}, account.Environment...)
}
