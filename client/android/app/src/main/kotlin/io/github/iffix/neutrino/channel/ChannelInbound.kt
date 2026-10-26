package io.github.iffix.neutrino.channel

import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.decodeFromJsonElement
import kotlinx.serialization.json.intOrNull

/** One frame the hub sent on the control stream, read tolerantly: an unknown field is ignored. */
sealed interface ChannelInbound {
    /**
     * The hub's identity card.
     *
     * @property protocol The hub's protocol number.
     * @property role `hub`.
     * @property id The hub's id.
     * @property name The hub's name.
     * @property software `neutrino_hub/<version>`.
     */
    data class Welcome(val protocol: Int, val role: String, val id: String, val name: String, val software: String) :
        ChannelInbound

    /**
     * The hub turned this binding away; the session ends after it.
     *
     * @property refusal The code and its parameters.
     */
    data class Refused(val refusal: ChannelResult.Refused) : ChannelInbound

    /**
     * What is to be true for this phone.
     *
     * @property state The sections.
     */
    data class State(val state: ChannelClientState) : ChannelInbound

    /**
     * The answer to a question this phone asked with a frame.
     *
     * @property request The question's mark.
     * @property result The params as the answer, or the refusal.
     */
    data class Reply(val request: String, val result: ChannelResult<JsonObject>) : ChannelInbound

    /**
     * The answer to a ping of this phone's.
     *
     * @property nonce The ping's nonce, as the transport echoed it.
     */
    data class Pong(val nonce: String) : ChannelInbound

    /**
     * A frame this build does not read.
     *
     * @property type Its `type`.
     */
    data class Unknown(val type: String) : ChannelInbound

    companion object {
        private val json = Json { ignoreUnknownKeys = true }

        /**
         * Read one frame.
         *
         * @param frame The frame as the transport passed it on.
         * @return The frame.
         * @throws IllegalArgumentException When a frame this build reads carries a field of the wrong shape.
         */
        fun decode(frame: JsonObject): ChannelInbound = when (val type = frame.text("type")) {
            ChannelFrames.WELCOME -> Welcome(
                protocol = (frame["protocol"] as? JsonPrimitive)?.intOrNull ?: 0,
                role = frame.text("role"),
                id = frame.text("id"),
                name = frame.text("name"),
                software = frame.text("software"),
            )

            ChannelFrames.REFUSED -> Refused(ChannelResult.Refused(frame.text("code"), frame.objectOf("params")))

            ChannelFrames.STATE -> State(decodeState(frame))

            ChannelFrames.REPLY -> {
                val code = frame.text("code")
                val params = frame.objectOf("params")
                Reply(
                    frame.text("request"),
                    if (code.isEmpty()) ChannelResult.Ok(params) else ChannelResult.Refused(code, params),
                )
            }

            ChannelFrames.PONG -> Pong(frame.text("nonce"))

            else -> Unknown(type)
        }

        private fun decodeState(frame: JsonObject): ChannelClientState {
            val state = try {
                json.decodeFromJsonElement<ChannelClientState>(JsonObject(frame - "overlays" - "urls"))
            } catch (error: SerializationException) {
                throw IllegalArgumentException("a state frame's sections are malformed", error)
            }
            return state.copy(
                urls = EnrollmentLink.cleanUrls(frame["urls"]),
                overlays = EnrollmentLink.cleanOverlays(frame["overlays"]),
            )
        }

        private fun JsonObject.text(name: String): String = (this[name] as? JsonPrimitive)?.content.orEmpty()

        private fun JsonObject.objectOf(name: String): JsonObject = this[name] as? JsonObject ?: JsonObject(emptyMap())
    }
}
