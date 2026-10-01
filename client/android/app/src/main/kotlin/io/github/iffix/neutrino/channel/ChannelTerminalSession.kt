package io.github.iffix.neutrino.channel

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * One shell session as the hub lists it in a `terminals` entry: every session this phone owns,
 * and every shared session on a machine it has terminal rights on.
 *
 * @property sessionId What a `shell` stream and the `persist` and `stop_session` commands name.
 * @property deviceId The machine that holds it.
 * @property deviceName The machine's name.
 * @property account The account the shell runs as.
 * @property startedAt When it started, in unix seconds.
 * @property title What the shell last set as its title.
 * @property owner Who opened it: `hub` for the panel, `client:<id>` for a client.
 * @property isOwned Whether this phone opened it.
 * @property isAttached Whether a window shows it now.
 * @property isPersistent Whether it outlives every window.
 * @property isShared Whether every client with terminal rights on the machine lists it.
 * @property attachedCount How many windows show it now.
 */
@Serializable
data class ChannelTerminalSession(
    @SerialName("session_id") val sessionId: String,
    @SerialName("device_id") val deviceId: String = "",
    @SerialName("device_name") val deviceName: String = "",
    val account: String = "",
    @SerialName("started_at") val startedAt: Long = 0,
    val title: String = "",
    val owner: String = "",
    @SerialName("is_owned") val isOwned: Boolean = false,
    @SerialName("is_attached") val isAttached: Boolean = false,
    @SerialName("is_persistent") val isPersistent: Boolean = false,
    @SerialName("is_shared") val isShared: Boolean = false,
    @SerialName("attached_count") val attachedCount: Int = 0,
)
