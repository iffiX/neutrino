// Package handshake is the Noise_IKpsk2_25519_ChaChaPoly_BLAKE2s handshake
// between a peer and the hub: the peer's message 1, the hub's message 2
// written under the psk the hub's Python named, and the peer's two tries at
// opening it, under its own psk and under the zero psk a refusal is said
// under.
package handshake
