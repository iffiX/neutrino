package io.github.iffix.neutrino.overlay

import io.github.iffix.neutrino.channel.ChannelResult

/**
 * What the one running engine last said.
 *
 * @property bindingId The hub whose network it runs.
 * @property provider The network's provider, such as `easytier`.
 * @property phase Where it stands.
 * @property address This phone's address on the network with its prefix length, as `10.144.0.7/24`,
 *   empty until it has one; an address without a length counts as /32.
 * @property refusal Why it failed, null unless [phase] is [OverlayPhase.FAILED].
 */
data class OverlayStatus(
    val bindingId: String,
    val provider: String,
    val phase: OverlayPhase,
    val address: String = "",
    val refusal: ChannelResult.Refused? = null,
)
