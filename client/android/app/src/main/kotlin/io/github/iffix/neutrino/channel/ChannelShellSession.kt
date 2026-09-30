package io.github.iffix.neutrino.channel

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * One shell session a machine holds, as its agent reports it.
 *
 * @property sessionId What a `shell` stream and the `persist` and `stop_session` commands name.
 * @property account The account the shell runs as.
 * @property startedAt When it started, in unix seconds.
 * @property title What the shell last set as its title.
 * @property isAttached Whether a window shows it now.
 * @property isPersistent Whether it outlives its window.
 */
@Serializable
data class ChannelShellSession(
    @SerialName("session_id") val sessionId: String,
    val account: String = "",
    @SerialName("started_at") val startedAt: Long = 0,
    val title: String = "",
    @SerialName("is_attached") val isAttached: Boolean = false,
    @SerialName("is_persistent") val isPersistent: Boolean = false,
)
