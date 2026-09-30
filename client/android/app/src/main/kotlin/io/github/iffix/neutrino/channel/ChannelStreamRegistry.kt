package io.github.iffix.neutrino.channel

import io.github.iffix.neutrino.CHANNEL_FIRST_STREAM_ID
import io.github.iffix.neutrino.CHANNEL_STREAM_ID_BYTES
import io.github.iffix.neutrino.CHANNEL_STREAM_ID_STEP
import io.github.iffix.neutrino.CLIENT_STREAM_CODE_KIND_UNKNOWN
import io.github.iffix.neutrino.CLIENT_STREAM_CREDIT_BYTES
import java.nio.ByteBuffer
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * The streams open on one socket, by id: this side opens odd ids counting up from 1.
 *
 * @param socket The socket.
 */
class ChannelStreamRegistry(private val socket: ChannelSocket) {
    private val streams = mutableMapOf<Int, ChannelStream>()
    private var nextId = CHANNEL_FIRST_STREAM_ID
    private var isEnded = false

    /**
     * Open one stream: the next odd id, the open sent, and a byte stream granted a window at once.
     *
     * @param kind The stream's kind.
     * @param args The kind's own arguments.
     * @param hasBytes Whether it carries bytes both ways.
     * @return The stream, or `hub_unreachable` when the socket is gone.
     */
    fun open(kind: String, args: Map<String, JsonElement>, hasBytes: Boolean = false): ChannelResult<ChannelStream> {
        val stream = synchronized(streams) {
            if (isEnded) return ChannelResult.refused("hub_unreachable", "detail" to "the socket is closed")
            val id = nextId
            nextId += CHANNEL_STREAM_ID_STEP
            ChannelStream(id, kind, socket, hasBytes, ::forget).also { streams[id] = it }
        }
        val isSent = socket.sendText(ChannelFrames.open(stream.id, kind, args).toString()) &&
            (!hasBytes || socket.sendText(ChannelFrames.credit(stream.id, CLIENT_STREAM_CREDIT_BYTES).toString()))
        if (!isSent) {
            forget(stream.id)
            return ChannelResult.refused("hub_unreachable", "detail" to "the socket is closed")
        }
        return ChannelResult.Ok(stream)
    }

    /**
     * Hand one binary frame to its stream.
     *
     * @param frame The frame: a big-endian u32 stream id, then the bytes.
     * @throws IllegalArgumentException When the frame is shorter than a stream id.
     */
    fun takeBinary(frame: ByteArray) {
        require(frame.size >= CHANNEL_STREAM_ID_BYTES) { "a binary frame starts with a four-byte stream id" }
        val id = ByteBuffer.wrap(frame, 0, CHANNEL_STREAM_ID_BYTES).int
        synchronized(streams) { streams[id] }?.takeBytes(frame.copyOfRange(CHANNEL_STREAM_ID_BYTES, frame.size))
    }

    /**
     * Hand one credit to its stream.
     *
     * @param credit The frame.
     */
    fun takeCredit(credit: ChannelInbound.Credit) {
        synchronized(streams) { streams[credit.stream] }?.takeCredit(credit.bytes)
    }

    /**
     * Hand one close to its stream, which is then forgotten.
     *
     * @param close The frame.
     */
    fun takeClose(close: ChannelInbound.Close) {
        synchronized(streams) { streams.remove(close.stream) }?.takeClose(close.code, close.params)
    }

    /**
     * Close a stream the hub opened: a client serves no kind.
     *
     * @param open The frame.
     */
    fun refuse(open: ChannelInbound.Open) {
        val params = JsonObject(mapOf("kind" to JsonPrimitive(open.kind)))
        socket.sendText(ChannelFrames.close(open.stream, CLIENT_STREAM_CODE_KIND_UNKNOWN, params).toString())
    }

    /** The socket ended: every stream waiting on it is woken with no close. */
    fun endAll() {
        val ended = synchronized(streams) {
            isEnded = true
            streams.values.toList().also { streams.clear() }
        }
        ended.forEach { it.end() }
    }

    private fun forget(id: Int) {
        synchronized(streams) { streams.remove(id) }
    }
}
