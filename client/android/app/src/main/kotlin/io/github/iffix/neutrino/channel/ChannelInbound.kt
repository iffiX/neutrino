package io.github.iffix.neutrino.channel

import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.decodeFromJsonElement
import kotlinx.serialization.json.intOrNull

/** One text frame the hub sent, read tolerantly: an unknown field is ignored. */
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
     * The hub turned this binding away; close 4000 follows.
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
     * A stream this phone opened has ended.
     *
     * @property stream The stream's id.
     * @property code The refusal's code, empty for a result.
     * @property params The result, or the refusal's parameters.
     */
    data class Close(val stream: Int, val code: String, val params: JsonObject) : ChannelInbound

    /**
     * The hub takes this many more bytes on a stream.
     *
     * @property stream The stream's id.
     * @property bytes The grant.
     */
    data class Credit(val stream: Int, val bytes: Int) : ChannelInbound

    /**
     * The hub opened a stream; a client serves none.
     *
     * @property stream The stream's id.
     * @property kind Its kind.
     */
    data class Open(val stream: Int, val kind: String) : ChannelInbound

    /**
     * A frame this build does not read.
     *
     * @property type Its `type`.
     */
    data class Unknown(val type: String) : ChannelInbound

    companion object {
        private val json = Json { ignoreUnknownKeys = true }

        /**
         * Read one text frame.
         *
         * @param text The frame's text.
         * @return The frame.
         * @throws IllegalArgumentException When the text is not a JSON object, or a frame this
         *   build reads carries a field of the wrong shape.
         */
        fun decode(text: String): ChannelInbound {
            val frame = try {
                json.parseToJsonElement(text) as? JsonObject
            } catch (error: SerializationException) {
                throw IllegalArgumentException("a text frame is one JSON object", error)
            } ?: throw IllegalArgumentException("a text frame is one JSON object")
            return when (val type = frame.text("type")) {
                ChannelFrames.WELCOME -> Welcome(
                    protocol = frame.number("protocol") ?: 0,
                    role = frame.text("role"),
                    id = frame.text("id"),
                    name = frame.text("name"),
                    software = frame.text("software"),
                )

                ChannelFrames.REFUSED -> Refused(ChannelResult.Refused(frame.text("code"), frame.objectOf("params")))

                ChannelFrames.STATE -> State(decodeState(frame))

                ChannelFrames.CLOSE -> Close(frame.stream(), frame.text("code"), frame.objectOf("params"))

                ChannelFrames.CREDIT -> Credit(
                    frame.stream(),
                    frame.number("bytes") ?: throw IllegalArgumentException("a credit names its bytes"),
                )

                ChannelFrames.OPEN -> Open(frame.stream(), frame.text("kind"))

                else -> Unknown(type)
            }
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

        private fun JsonObject.number(name: String): Int? = (this[name] as? JsonPrimitive)?.intOrNull

        private fun JsonObject.objectOf(name: String): JsonObject = this[name] as? JsonObject ?: JsonObject(emptyMap())

        private fun JsonObject.stream(): Int =
            number("stream") ?: throw IllegalArgumentException("a stream frame names its stream by an integer")
    }
}
