package io.github.iffix.neutrino.channel

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * A managed machine this phone may open a shell on.
 *
 * @property deviceId What a `shell` stream names.
 * @property name The machine's name.
 * @property isOnline Whether its agent is connected now.
 * @property sessions The shell sessions it holds.
 */
@Serializable
data class ChannelTerminal(
    @SerialName("device_id") val deviceId: String,
    val name: String,
    @SerialName("is_online") val isOnline: Boolean = false,
    val sessions: List<ChannelShellSession> = emptyList(),
)
