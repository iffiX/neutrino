package handshake

const (
	// HandshakePrologue is the Noise prologue of every handshake.
	HandshakePrologue = "neutrino transport 4"
	// HandshakeKeyBytes is the size of a Curve25519 key and of a psk.
	HandshakeKeyBytes = 32
	// HandshakePskPlacement is where the psk token sits: in message 2.
	HandshakePskPlacement = 2
	// HandshakeMessage2Bytes is the hub's answer: an ephemeral key and an
	// empty payload's tag.
	HandshakeMessage2Bytes = 48
)
