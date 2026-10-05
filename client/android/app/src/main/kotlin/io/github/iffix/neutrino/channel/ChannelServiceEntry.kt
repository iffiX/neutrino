package io.github.iffix.neutrino.channel

import io.github.iffix.neutrino.PORT_PROTOCOL_TCP
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.intOrNull

/**
 * One service a hub publishes to this phone, as its `state` lists it.
 *
 * @property id What a `service` stream names.
 * @property type `web`, `port`, `ai`, `file` or `rdp`.
 * @property title The name a person reads.
 * @property payload The type's own fields.
 * @property isHealthy The last probe's word, null where nothing probed it.
 * @property source `module`, `declared` or `device`.
 * @property description The English provenance line.
 * @property descriptionCode The provenance as a code.
 * @property descriptionParams The values that sentence names.
 * @property deviceName The machine that provides it, empty when the hub knows none.
 * @property deviceId That machine's id, empty when no managed machine provides it.
 */
@Serializable
data class ChannelServiceEntry(
    val id: String,
    val type: String,
    val title: String,
    val payload: JsonObject = JsonObject(emptyMap()),
    @SerialName("is_healthy") val isHealthy: Boolean? = null,
    val source: String = "",
    val description: String = "",
    @SerialName("description_code") val descriptionCode: String = "",
    @SerialName("description_params") val descriptionParams: JsonObject = JsonObject(emptyMap()),
    @SerialName("device_name") val deviceName: String = "",
    @SerialName("device_id") val deviceId: String = "",
) {
    /** A `port` entry's protocol, `tcp` or `udp`, from the payload's `protocol`; `tcp` when it names none. */
    val portProtocol: String
        get() = text("protocol").ifEmpty { PORT_PROTOCOL_TCP }

    /**
     * One text field of the payload.
     *
     * @param name The field.
     * @return Its text, empty when it is absent or not a primitive.
     */
    fun text(name: String): String = (payload[name] as? JsonPrimitive)?.content.orEmpty()

    /**
     * One number field of the payload.
     *
     * @param name The field.
     * @return Its value, or null when it is absent or not a number.
     */
    fun number(name: String): Int? = (payload[name] as? JsonPrimitive)?.intOrNull

    /**
     * One boolean field of the payload.
     *
     * @param name The field.
     * @return Its value, false when it is absent or not a boolean.
     */
    fun flag(name: String): Boolean = (payload[name] as? JsonPrimitive)?.booleanOrNull ?: false
}
