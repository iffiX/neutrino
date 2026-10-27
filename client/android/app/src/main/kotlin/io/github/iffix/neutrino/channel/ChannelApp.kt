package io.github.iffix.neutrino.channel

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * One app a hub publishes to this phone: one program on one machine, whose `web`, `port` and
 * `ssh` entries name it by [id].
 *
 * @property id The app's id, which its entries carry as `app_id`.
 * @property title The name a person reads.
 * @property source `module`, `declared` or `manual`, worded as `ui.app_source.<source>`.
 * @property deviceId The machine that provides it, empty when no managed machine does.
 * @property deviceName That machine's name, empty when the hub knows none.
 * @property localName The name its web entries open under on the loopback, `<app>.<machine>.localhost`.
 */
@Serializable
data class ChannelApp(
    val id: String,
    val title: String,
    val source: String = "",
    @SerialName("device_id") val deviceId: String = "",
    @SerialName("device_name") val deviceName: String = "",
    @SerialName("local_name") val localName: String = "",
)
