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
 * @property isWaiting Whether the engine is registered with a console that has assigned no network yet.
 * @property stage Which of the connect's stages runs while [state] is [OverlayState.CONNECTING].
 * @property stageStartedAtMillis When [stage] started, in the wall clock's milliseconds; the page counts the seconds from it.
 */
data class OverlayLine(
    val state: OverlayState = OverlayState.OFF,
    val network: String = "",
    val address: String = "",
    val error: ChannelResult.Refused? = null,
    val job: OverlayJob = OverlayJob.NONE,
    val isWaiting: Boolean = false,
    val stage: OverlayStage = OverlayStage.NONE,
    val stageStartedAtMillis: Long = 0,
)
