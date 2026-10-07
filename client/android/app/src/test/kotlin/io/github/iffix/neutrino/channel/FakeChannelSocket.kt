package io.github.iffix.neutrino.channel

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/** A socket that records what is sent on it. */
class FakeChannelSocket(private var isOpen: Boolean = true) : ChannelSocket {
    /** Every text frame sent, parsed. */
    val texts = mutableListOf<JsonObject>()

    /** Every binary frame sent. */
    val binaries = mutableListOf<ByteArray>()

    /** The close code, once closed from this side. */
    var closedWith: Int? = null

    /** How many pings were sent. */
    var pings = 0
        private set

    /**
     * The text frames of one type.
     *
     * @param type The frame's type.
     * @return The frames.
     */
    fun sent(type: String): List<JsonObject> = synchronized(this) {
        texts.filter { it["type"]?.jsonPrimitive?.content == type }
    }

    override fun sendText(text: String): Boolean = synchronized(this) {
        if (isOpen) texts += Json.parseToJsonElement(text).jsonObject
        isOpen
    }

    override fun sendBytes(bytes: ByteArray): Boolean = synchronized(this) {
        if (isOpen) binaries += bytes
        isOpen
    }

    override fun ping(): Boolean = synchronized(this) {
        if (isOpen) pings += 1
        isOpen
    }

    override fun close(code: Int, reason: String) {
        closedWith = code
        isOpen = false
    }
}
