// Package forward serves a local forward, a direct-tcpip channel: it dials
// the requested port when the destination is 127.0.0.1, ::1 or localhost,
// refuses every other destination without dialing, and relays bytes both
// ways until both sides end.
package forward
