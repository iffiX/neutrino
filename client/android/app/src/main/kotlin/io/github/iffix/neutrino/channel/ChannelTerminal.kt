package io.github.iffix.neutrino.channel

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * A managed machine this phone may open a shell on.
 *
 * @property deviceId What a `shell` stream names.
 * @property name The machine's name.
 * @property isOnline Whether its agent is connected now.
 * @property isShellAllowed Whether this phone may open a shell there; a machine without it is
 *   listed for its sessions alone and gets no chip.
 * @property isExecAllowed Whether this client may run one command there, which the phone does
 *   not do; read so the entry is read whole.
 * @property sessions The shell sessions it holds.
 */
@Serializable
data class ChannelTerminal(
    @SerialName("device_id") val deviceId: String,
    val name: String,
    @SerialName("is_online") val isOnline: Boolean = false,
    @SerialName("is_shell_allowed") val isShellAllowed: Boolean = false,
    @SerialName("is_exec_allowed") val isExecAllowed: Boolean = false,
    val sessions: List<ChannelTerminalSession> = emptyList(),
)
