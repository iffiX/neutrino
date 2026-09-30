package io.github.iffix.neutrino.channel

import io.github.iffix.neutrino.CLIENT_ROLE
import io.github.iffix.neutrino.PROTOCOL
import io.github.iffix.neutrino.binding.HubBinding
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonObject

/** Every frame and body this phone writes on the channel, each with exactly the fields its protocol defines. */
object ChannelFrames {
    /** The `type` of each frame. */
    const val HELLO = "hello"

    /** The hub's identity card. */
    const val WELCOME = "welcome"

    /** A refusal, then close 4000. */
    const val REFUSED = "refused"

    /** What is to be true. */
    const val STATE = "state"

    /** What is true. */
    const val REPORT = "report"

    /** A stream begins. */
    const val OPEN = "open"

    /** A stream ends. */
    const val CLOSE = "close"

    /** The sender may send more. */
    const val CREDIT = "credit"

    /**
     * The first frame up: this phone's identity card with the binding's token.
     *
     * @param binding The binding the socket is for.
     * @param machine This phone.
     * @return The frame.
     */
    fun hello(binding: HubBinding, machine: ClientMachine): JsonObject = buildJsonObject {
        put("type", HELLO)
        put("protocol", PROTOCOL)
        put("role", CLIENT_ROLE)
        put("id", binding.id)
        put("name", binding.name.ifEmpty { machine.hostname })
        put("software", machine.software)
        put("token", binding.token)
    }

    /**
     * What is true of this phone, and the hash of the state held.
     *
     * @param stateHash The hash of the last state taken, empty before the first.
     * @param machine This phone.
     * @return The frame.
     */
    fun report(stateHash: String, machine: ClientMachine): JsonObject = buildJsonObject {
        put("type", REPORT)
        put("state_hash", stateHash)
        putJsonObject("machine") {
            put("hostname", machine.hostname)
            putJsonObject("platform") { machine.platform.forEach { (name, value) -> put(name, value) } }
        }
    }

    /**
     * A stream begins: the request, its arguments beside `stream` and `kind`.
     *
     * @param stream The stream's id.
     * @param kind The stream's kind.
     * @param args The kind's own arguments.
     * @return The frame.
     */
    fun open(stream: Int, kind: String, args: Map<String, JsonElement>): JsonObject = buildJsonObject {
        put("type", OPEN)
        put("stream", stream)
        put("kind", kind)
        args.forEach { (name, value) -> put(name, value) }
    }

    /**
     * A stream ends from this side.
     *
     * @param stream The stream's id.
     * @param code The refusal's code, empty for a result.
     * @param params The result or the refusal's parameters.
     * @return The frame.
     */
    fun close(stream: Int, code: String = "", params: JsonObject = JsonObject(emptyMap())): JsonObject =
        buildJsonObject {
            put("type", CLOSE)
            put("stream", stream)
            put("code", code)
            put("params", params)
        }

    /**
     * The hub may send this many more bytes on a stream.
     *
     * @param stream The stream's id.
     * @param bytes The grant.
     * @return The frame.
     */
    fun credit(stream: Int, bytes: Int): JsonObject = buildJsonObject {
        put("type", CREDIT)
        put("stream", stream)
        put("bytes", bytes)
    }

    /**
     * The body of `POST /api/channel/join`.
     *
     * @param ticket The link's ticket.
     * @param machine This phone.
     * @return The body.
     */
    fun joinRequest(ticket: String, machine: ClientMachine): JsonObject = buildJsonObject {
        put("ticket", ticket)
        put("role", CLIENT_ROLE)
        put("protocol", PROTOCOL)
        put("machine_id", machine.machineId)
        put("name", machine.hostname)
        put("software", machine.software)
        putJsonObject("platform") { machine.platform.forEach { (name, value) -> put(name, value) } }
    }

    /**
     * The body of `POST /api/channel/leave`.
     *
     * @param binding The binding being ended.
     * @return The body.
     */
    fun leaveRequest(binding: HubBinding): JsonObject = buildJsonObject {
        put("id", binding.id)
        put("token", binding.token)
    }

    /**
     * Text arguments as a stream's arguments.
     *
     * @param args The names and values.
     * @return The arguments as JSON values.
     */
    fun args(vararg args: Pair<String, Any>): Map<String, JsonElement> = args.associate { (name, value) ->
        name to when (value) {
            is Int -> JsonPrimitive(value)
            is Boolean -> JsonPrimitive(value)
            is JsonElement -> value
            else -> JsonPrimitive(value.toString())
        }
    }
}
