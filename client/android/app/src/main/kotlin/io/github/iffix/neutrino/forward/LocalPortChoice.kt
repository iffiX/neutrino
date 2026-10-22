package io.github.iffix.neutrino.forward

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * One forwardable entry's local port, as the table keeps it.
 *
 * @property isFixed Whether the person fixed the number; otherwise the app picks it.
 * @property port The fixed number, or the app's pick once made; 0 for an automatic entry not yet forwarded.
 */
@Serializable
data class LocalPortChoice(@SerialName("is_fixed") val isFixed: Boolean = false, val port: Int = 0)
