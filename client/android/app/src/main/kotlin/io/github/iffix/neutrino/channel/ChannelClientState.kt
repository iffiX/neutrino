package io.github.iffix.neutrino.channel

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * What a hub says is to be true for this phone: the `state` frame's sections.
 *
 * @property hash What the next report names back.
 * @property isDisabled Whether the hub switched this client off.
 * @property services The published list, resolved for the address this socket came from.
 * @property urls Every address the hub answers the channel on.
 * @property overlays What this phone joins each of the hub's virtual networks with, preferred first.
 * @property terminals The managed machines this phone may open a shell on.
 */
@Serializable
data class ChannelClientState(
    val hash: String,
    @SerialName("is_disabled") val isDisabled: Boolean = false,
    val services: List<ChannelServiceEntry> = emptyList(),
    val urls: List<String> = emptyList(),
    val overlays: List<ChannelOverlay> = emptyList(),
    val terminals: List<ChannelTerminal> = emptyList(),
)
