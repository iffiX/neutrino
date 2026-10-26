// Package control is the local channel between a transport and the Python
// beside it, on the hub, the agent and the client: the listener on a Unix
// socket or a named pipe, the secret every connection opens with, the three
// connection kinds, the questions, commands, events and frames as JSON
// lines, and on the agent and the client the sessions the transport keeps
// to the hub for them: the rounds, the redial and the forwards.
package control
