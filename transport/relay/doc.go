// Package relay moves the bytes of streams. It holds the hub's service on
// the agent port, from the knock through admission to every relayed stream,
// and what the peers' transports share with it: the splice of two byte
// streams, the copy of records under the record cap, the far end of a
// connect stream over TCP or UDP, the local forward of a listener into
// streams, and the hand-off of a stream to the Python beside the transport.
package relay
