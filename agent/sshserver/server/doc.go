// Package server is one account's SSH server: it listens on loopback,
// admits the one authorized key the hub made for the account, refuses every
// global request and every channel type but a session and a local forward,
// and hands each accepted channel to the session or the forward package. The
// process runs as the account, so nothing here changes identity.
package server
