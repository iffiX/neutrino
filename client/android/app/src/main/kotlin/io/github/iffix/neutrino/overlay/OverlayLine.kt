package io.github.iffix.neutrino.overlay

import io.github.iffix.neutrino.channel.ChannelResult

/**
 * One hub's virtual network as its row draws it.
 *
 * @property state Where this phone stands on it.
 * @property network The engine running or last run, empty before the first connect.
 * @property address This phone's address on the network, empty until the engine has one.
 * @property error The last failure, kept while [state] is [OverlayState.OFF] until the next press or a refresh.
 * @property job What the network's button is doing.
 */
data class OverlayLine(
    val state: OverlayState = OverlayState.OFF,
    val network: String = "",
    val address: String = "",
    val error: ChannelResult.Refused? = null,
    val job: OverlayJob = OverlayJob.NONE,
)
