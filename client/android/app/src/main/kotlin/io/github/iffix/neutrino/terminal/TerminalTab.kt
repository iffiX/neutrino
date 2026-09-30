package io.github.iffix.neutrino.terminal

import io.github.iffix.neutrino.channel.ChannelResult
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.Transient

/**
 * One terminal tab: a shell on a managed machine, named by the session id this phone made.
 *
 * @property sessionId The shell's session id, a uuid this phone generated; also the tab's id.
 * @property bindingId The hub the machine is managed by.
 * @property deviceId The machine.
 * @property name The machine's name.
 * @property isPersistent Whether the shell runs on when its stream closes.
 * @property phase Where the shell stands; not kept.
 * @property note Why the shell ended or the stream dropped; not kept.
 */
@Serializable
data class TerminalTab(
    @SerialName("session_id") val sessionId: String,
    @SerialName("binding_id") val bindingId: String,
    @SerialName("device_id") val deviceId: String,
    val name: String,
    @SerialName("is_persistent") val isPersistent: Boolean = false,
    @Transient val phase: TerminalPhase = TerminalPhase.DETACHED,
    @Transient val note: ChannelResult.Refused? = null,
)
