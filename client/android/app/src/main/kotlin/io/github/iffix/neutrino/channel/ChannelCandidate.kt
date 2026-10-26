package io.github.iffix.neutrino.channel

/**
 * One address a round dials, with the way it reaches the hub.
 *
 * @property address `tcp://<host>:<port>`, an IPv6 host in brackets.
 * @property path The path's word, one of [ChannelPath]'s.
 */
data class ChannelCandidate(val address: String, val path: String)
