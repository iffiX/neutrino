package io.github.iffix.neutrino.channel

import io.github.iffix.neutrino.CHANNEL_STREAM_ID_BYTES
import io.github.iffix.neutrino.CLIENT_STREAM_CREDIT_BYTES
import io.github.iffix.neutrino.CLIENT_STREAM_KIND_CONNECT
import java.nio.ByteBuffer
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/**
 * The hub's end of `connect` streams, over one real stream registry: every open is granted a
 * window and every byte sent is written back and granted again, unless the hub refuses every
 * open with [refusal] or grants nothing by itself.
 *
 * @param refusal The close every open gets at once, or null to serve it.
 * @param isGranting Whether the hub grants credit by itself.
 */
class FakeConnectHub(private val refusal: ChannelResult.Refused? = null, private val isGranting: Boolean = true) :
    ChannelSocket {
    /** The registry the phone's side opens streams on. */
    val registry = ChannelStreamRegistry(this)

    /** Every `open` frame, parsed. */
    val opens = mutableListOf<JsonObject>()

    /** The ids of the streams the phone closed. */
    val closed = mutableListOf<Int>()

    /** Every credit the phone granted, as `(stream, bytes)`. */
    val credits = mutableListOf<Pair<Int, Int>>()

    /** Every binary frame's payload the phone sent, in order. */
    val frames = mutableListOf<ByteArray>()

    /**
     * Open one `connect` stream from the phone's side.
     *
     * @param args The stream's arguments.
     * @return What the registry returns.
     */
    fun open(args: Map<String, JsonElement>): ChannelResult<ChannelStream> =
        registry.open(CLIENT_STREAM_KIND_CONNECT, args, hasBytes = true)

    /**
     * The hub sends bytes on a stream.
     *
     * @param stream The stream's id.
     * @param data The bytes.
     */
    fun send(stream: Int, data: ByteArray) =
        registry.takeBinary(ByteBuffer.allocate(CHANNEL_STREAM_ID_BYTES + data.size).putInt(stream).put(data).array())

    /**
     * The hub grants the phone more bytes on a stream.
     *
     * @param stream The stream's id.
     * @param bytes The grant.
     */
    fun grant(stream: Int, bytes: Int) = registry.takeCredit(ChannelInbound.Credit(stream, bytes))

    /**
     * The hub closes a stream.
     *
     * @param stream The stream's id.
     * @param code The refusal's code, empty for an end of file.
     */
    fun end(stream: Int, code: String = "") =
        registry.takeClose(ChannelInbound.Close(stream, code, JsonObject(emptyMap())))

    override fun sendText(text: String): Boolean {
        val frame = Json.parseToJsonElement(text).jsonObject
        val stream = frame["stream"]?.jsonPrimitive?.int ?: return true
        when (frame["type"]?.jsonPrimitive?.content) {
            ChannelFrames.OPEN -> synchronized(this) { opens += frame }.also {
                if (refusal != null) {
                    registry.takeClose(ChannelInbound.Close(stream, refusal.code, refusal.params))
                } else if (isGranting) {
                    grant(stream, CLIENT_STREAM_CREDIT_BYTES)
                }
            }

            ChannelFrames.CLOSE -> synchronized(this) { closed += stream }

            ChannelFrames.CREDIT -> synchronized(this) {
                credits += stream to (frame["bytes"]?.jsonPrimitive?.int ?: 0)
            }
        }
        return true
    }

    override fun sendBytes(bytes: ByteArray): Boolean {
        val stream = ByteBuffer.wrap(bytes, 0, CHANNEL_STREAM_ID_BYTES).int
        val data = bytes.copyOfRange(CHANNEL_STREAM_ID_BYTES, bytes.size)
        synchronized(this) { frames += data }
        if (isGranting) {
            send(stream, data)
            grant(stream, data.size)
        }
        return true
    }

    override fun close(code: Int, reason: String) = registry.endAll()
}
