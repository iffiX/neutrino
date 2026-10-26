package io.github.iffix.neutrino.transport

import io.github.iffix.neutrino.TRANSPORT_RECORD_ACCEPT
import io.github.iffix.neutrino.TRANSPORT_RECORD_CLOSE
import io.github.iffix.neutrino.channel.ChannelResult
import java.io.BufferedInputStream
import java.io.Closeable
import java.io.DataInputStream
import java.io.IOException
import java.io.InputStream
import java.io.OutputStream
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/**
 * One stream this app opened on a hub's session, carried by a local connection of its own. The
 * hub's `accept` has been read; a record stream then carries records both ways, and a TCP
 * `connect` stream its connection's raw bytes.
 *
 * @param connection The local connection.
 * @param reader The connection's input, buffered, past the `accept`.
 */
class TransportStream private constructor(
    private val connection: TransportConnection,
    private val reader: DataInputStream,
) : Closeable {
    private val writeLock = Any()

    @Volatile
    private var isClosed = false

    /** The raw bytes from the hub, for a `connect` stream. */
    val rawInput: InputStream
        get() = reader

    /** The raw bytes to the hub, for a `connect` stream. */
    val rawOutput: OutputStream
        get() = connection.output

    /**
     * Read the next record.
     *
     * @return The record, or null once the stream ended.
     * @throws IOException When the stream breaks inside a record.
     */
    fun read(): TransportRecord? = TransportRecord.read(reader)

    /**
     * Write one record.
     *
     * @param type The record's type.
     * @param payload Its bytes.
     * @return False when the stream is gone.
     */
    fun write(type: Int, payload: ByteArray): Boolean = synchronized(writeLock) {
        if (isClosed) return false
        try {
            TransportRecord.write(connection.output, type, payload)
            true
        } catch (_: IOException) {
            false
        }
    }

    /** End the stream from this side. */
    override fun close() {
        isClosed = true
        try {
            connection.close()
        } catch (_: IOException) {
            // The transport already ended it.
        }
    }

    companion object {
        /**
         * Open one stream on a hub's session: the line that names it, then the hub's answer.
         *
         * @param dialer Opens the local connection.
         * @param secret The transport's secret.
         * @param binding The hub, by the name its `dial` gave.
         * @param open The stream's `open` record, `{kind, ...args}`.
         * @return The stream once accepted; the hub's refusal from its `close`; `hub_unreachable`
         *   when the transport could not be reached or answered nothing.
         */
        fun open(
            dialer: TransportDialer,
            secret: String,
            binding: String,
            open: JsonObject,
        ): ChannelResult<TransportStream> {
            val connection = try {
                dialer.dial()
            } catch (error: IOException) {
                return ChannelResult.refused("hub_unreachable", "detail" to (error.message ?: "the transport is gone"))
            }
            val first = buildJsonObject {
                put("secret", secret)
                put("op", "open")
                put("binding", binding)
                put("open", open)
            }
            return try {
                connection.output.write((first.toString() + "\n").toByteArray(Charsets.UTF_8))
                connection.output.flush()
                val reader = DataInputStream(BufferedInputStream(connection.input))
                val answer = TransportRecord.read(reader)
                when {
                    answer?.type == TRANSPORT_RECORD_ACCEPT -> ChannelResult.Ok(TransportStream(connection, reader))

                    answer?.type == TRANSPORT_RECORD_CLOSE -> {
                        connection.close()
                        answer.refusal
                            ?: ChannelResult.refused("hub_unreachable", "detail" to "the stream closed at once")
                    }

                    else -> {
                        connection.close()
                        ChannelResult.refused("hub_unreachable", "detail" to "the stream was not accepted")
                    }
                }
            } catch (error: IOException) {
                connection.close()
                ChannelResult.refused("hub_unreachable", "detail" to (error.message ?: "the stream broke"))
            }
        }
    }
}
