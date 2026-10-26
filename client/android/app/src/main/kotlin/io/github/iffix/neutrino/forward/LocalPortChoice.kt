package io.github.iffix.neutrino.forward

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * One entry's local port, as the table keeps it.
 *
 * @property isFixed Whether the person set the number, in place of the hub's; otherwise it is the
 *   app's pick for a forward of no app.
 * @property port The number.
 * @property protocol `tcp` or `udp`; a kept entry with none reads as `tcp`.
 */
@Serializable
data class LocalPortChoice(
    @SerialName("is_fixed") val isFixed: Boolean = false,
    val port: Int = 0,
    val protocol: String = "tcp",
)
