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

/**
 * Every frame this phone writes on a hub's control stream, and the fields of the transport's
 * `join`, each with exactly the fields its protocol defines; a frame's `type` is its name.
 */
object ChannelFrames {
    /** This phone's identity card, the first frame of a session. */
    const val HELLO = "hello"

    /** The hub's identity card. */
    const val WELCOME = "welcome"

    /** A refusal; the hub ends the session after it. */
    const val REFUSED = "refused"

    /** What is to be true. */
    const val STATE = "state"

    /** What is true. */
    const val REPORT = "report"

    /** This phone's own round trip probe. */
    const val PING = "ping"

    /** The answer to a ping, with its nonce. */
    const val PONG = "pong"

    /** A question for one entry's material, or the panel's sign-in. */
    const val SERVICE = "service"

    /** Whether a kept shell stays and whether others can attach to it. */
    const val PERSIST = "persist"

    /** Ends a kept shell. */
    const val STOP_SESSION = "stop_session"

    /** The answer to a `service`, `persist` or `stop_session`. */
    const val REPLY = "reply"

    /**
     * The first frame of a session: this phone's identity card.
     *
     * @param binding The binding the session is for.
     * @param machine This phone.
     * @return The frame.
     */
    fun hello(binding: HubBinding, machine: ClientMachine): JsonObject = buildJsonObject {
        put("type", HELLO)
        put("protocol", PROTOCOL)
        put("role", CLIENT_ROLE)
        put("id", binding.boundId)
        put("name", binding.name.ifEmpty { machine.hostname })
        put("software", machine.software)
    }

    /**
     * What is true of this phone, and the hash of the state held.
     *
     * @param stateHash The hash of the last state taken, empty before the first.
     * @param machine This phone.
     * @param isRefresh Whether a person pressed refresh, which asks the hub for its whole state whatever its hash.
     * @return The frame.
     */
    fun report(stateHash: String, machine: ClientMachine, isRefresh: Boolean = false): JsonObject = buildJsonObject {
        put("type", REPORT)
        put("state_hash", stateHash)
        put("is_refresh", isRefresh)
        putJsonObject("machine") {
            put("hostname", machine.hostname)
            putJsonObject("platform") { machine.platform.forEach { (name, value) -> put(name, value) } }
            put("os_machine_id", "")
        }
    }

    /**
     * A round trip probe; the hub's transport echoes its nonce in a `pong`.
     *
     * @param nonce The mark of this ping, at most 64 characters.
     * @return The frame.
     */
    fun ping(nonce: String): JsonObject = buildJsonObject {
        put("type", PING)
        put("nonce", nonce)
    }

    /**
     * A question for the material one published entry takes, or for the panel's sign-in.
     *
     * @param request This phone's mark of the question, which the reply names.
     * @param args `{id}` for an entry, `{is_panel: true}` for the panel.
     * @return The frame.
     */
    fun service(request: String, args: Map<String, JsonElement>): JsonObject = buildJsonObject {
        put("type", SERVICE)
        put("request", request)
        args.forEach { (name, value) -> put(name, value) }
    }

    /**
     * Whether a kept shell stays when its last stream closes, and whether others can attach to it.
     *
     * @param request This phone's mark of the question.
     * @param sessionId The session.
     * @param isPersistent Whether it outlives every window.
     * @param isShared Whether every client with terminal rights on the machine lists it.
     * @return The frame.
     */
    fun persist(request: String, sessionId: String, isPersistent: Boolean, isShared: Boolean): JsonObject =
        buildJsonObject {
            put("type", PERSIST)
            put("request", request)
            put("session_id", sessionId)
            put("is_persistent", isPersistent)
            put("is_shared", isShared)
        }

    /**
     * Ends a kept shell and every program in it.
     *
     * @param request This phone's mark of the question.
     * @param sessionId The session.
     * @return The frame.
     */
    fun stopSession(request: String, sessionId: String): JsonObject = buildJsonObject {
        put("type", STOP_SESSION)
        put("request", request)
        put("session_id", sessionId)
    }

    /**
     * The `join` frame's body, which the transport sends on the round's winner.
     *
     * @param ticket The link's ticket.
     * @param machine This phone.
     * @return The body: `{ticket, role, protocol, machine_id, name, software, platform}`.
     */
    fun join(ticket: String, machine: ClientMachine): JsonObject = buildJsonObject {
        put("ticket", ticket)
        put("role", CLIENT_ROLE)
        put("protocol", PROTOCOL)
        put("machine_id", machine.machineId)
        put("name", machine.hostname)
        put("software", machine.software)
        putJsonObject("platform") { machine.platform.forEach { (name, value) -> put(name, value) } }
    }

    /**
     * Values as a stream's or a frame's arguments.
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
