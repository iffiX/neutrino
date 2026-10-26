package io.github.iffix.neutrino.transport

import io.github.iffix.neutrino.TRANSPORT_RECORD_BYTES_MAX
import io.github.iffix.neutrino.TRANSPORT_RECORD_CLOSE
import io.github.iffix.neutrino.channel.ChannelResult
import java.io.DataInputStream
import java.io.EOFException
import java.io.IOException
import java.io.OutputStream
import java.nio.ByteBuffer
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * One record of a stream: `<u8 type><u32 length, big-endian><payload>`.
 *
 * @property type The record's type, one of the `TRANSPORT_RECORD_*` numbers.
 * @property payload Its bytes.
 */
class TransportRecord(val type: Int, val payload: ByteArray) {
    /** The payload read as one JSON object, empty when it is not one. */
    val json: JsonObject
        get() = try {
            Json.parseToJsonElement(String(payload, Charsets.UTF_8)) as? JsonObject
        } catch (_: SerializationException) {
            null
        } ?: JsonObject(emptyMap())

    /** A `close` record's refusal: its code and params, or null for a close that carries a result. */
    val refusal: ChannelResult.Refused?
        get() {
            if (type != TRANSPORT_RECORD_CLOSE) return null
            val body = json
            val code = (body["code"] as? JsonPrimitive)?.content.orEmpty()
            if (code.isEmpty()) return null
            return ChannelResult.Refused(code, body["params"] as? JsonObject ?: JsonObject(emptyMap()))
        }

    companion object {
        /**
         * Read the next record.
         *
         * @param input The stream's bytes.
         * @return The record, or null when the stream ended before a record began.
         * @throws IOException When the stream ends inside a record, or a length is past the largest record.
         */
        fun read(input: DataInputStream): TransportRecord? {
            val type = input.read()
            if (type < 0) return null
            val length = try {
                input.readInt()
            } catch (error: EOFException) {
                throw IOException("the stream ended inside a record's header", error)
            }
            if (length < 0 || length > TRANSPORT_RECORD_BYTES_MAX) throw IOException("a record of $length bytes")
            val payload = ByteArray(length)
            input.readFully(payload)
            return TransportRecord(type, payload)
        }

        /**
         * Write one record, cut into as many as the payload needs.
         *
         * @param output Where it goes.
         * @param type The record's type.
         * @param payload Its bytes.
         * @throws IOException When the stream is gone.
         */
        fun write(output: OutputStream, type: Int, payload: ByteArray) {
            var offset = 0
            do {
                val size = minOf(payload.size - offset, TRANSPORT_RECORD_BYTES_MAX)
                output.write(ByteBuffer.allocate(HEADER_BYTES).put(type.toByte()).putInt(size).array())
                output.write(payload, offset, size)
                offset += size
            } while (offset < payload.size)
            output.flush()
        }

        private const val HEADER_BYTES = 5
    }
}
