package io.github.iffix.neutrino.channel

/**
 * A virtual network of the hub's that is on: one more candidate of every round, and the path of
 * every address inside it.
 *
 * @property url The hub's address on the network, `https://address:port`.
 * @property provider The network's engine, `netbird` or `easytier`.
 * @property network This phone's address on the network with its prefix length, null when unknown.
 */
data class ChannelOverlayRoute(val url: String, val provider: String, val network: ChannelLocalNetwork?)
