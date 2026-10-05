package io.github.iffix.neutrino.forward

import io.github.iffix.neutrino.PORT_PROTOCOL_TCP
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * One forwardable entry's local port, as the table keeps it.
 *
 * @property isFixed Whether the person fixed the number; otherwise the app picks it.
 * @property port The fixed number, or the app's pick once made; 0 for an automatic entry not yet forwarded.
 * @property protocol `tcp` or `udp`; a stored choice with none is TCP.
 */
@Serializable
data class LocalPortChoice(
    @SerialName("is_fixed") val isFixed: Boolean = false,
    val port: Int = 0,
    val protocol: String = PORT_PROTOCOL_TCP,
)
