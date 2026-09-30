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

    /**
     * The text frames of one type.
     *
     * @param type The frame's type.
     * @return The frames.
     */
    fun sent(type: String): List<JsonObject> = texts.filter { it["type"]?.jsonPrimitive?.content == type }

    override fun sendText(text: String): Boolean {
        if (isOpen) texts += Json.parseToJsonElement(text).jsonObject
        return isOpen
    }

    override fun sendBytes(bytes: ByteArray): Boolean {
        if (isOpen) binaries += bytes
        return isOpen
    }

    override fun close(code: Int, reason: String) {
        closedWith = code
        isOpen = false
    }
}
