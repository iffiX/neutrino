package io.github.iffix.neutrino.channel

import io.github.iffix.neutrino.CHANNEL_STREAM_ID_BYTES
import io.github.iffix.neutrino.CLIENT_STREAM_CREDIT_BYTES
import io.github.iffix.neutrino.CLIENT_WS_CHUNK_BYTES
import io.github.iffix.neutrino.CLIENT_WS_CREDIT_TIMEOUT_S
import java.nio.ByteBuffer
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.json.JsonObject

/**
 * One stream this phone opened: its close, and on a byte stream its bytes both ways under credit.
 *
 * @property id The stream's id, odd.
 * @property kind The stream's kind.
 * @param socket The socket it runs on.
 * @param hasBytes Whether it carries bytes.
 * @param onClosedHere Called with the id when this side ends it.
 */
class ChannelStream internal constructor(
    val id: Int,
    val kind: String,
    private val socket: ChannelSocket,
    private val hasBytes: Boolean,
    private val onClosedHere: (Int) -> Unit,
) {
    private val incoming = Channel<ByteArray>(Channel.UNLIMITED)
    private val outcome = CompletableDeferred<ChannelResult<JsonObject>>()
    private val credit = MutableStateFlow(0L)
    private val isEnded = MutableStateFlow(false)
    private val creditLock = Mutex()
    private var consumed = 0L

    /** Whether the hub closed it, the socket ended, or this side closed it. */
    val isDone: Boolean
        get() = outcome.isCompleted

    /**
     * Wait for the hub's close.
     *
     * @param timeoutMillis How long to wait.
     * @return The close's params, or its refusal; `hub_unreachable` when the socket ended first
     *   or nothing came in time.
     */
    suspend fun awaitClose(timeoutMillis: Long): ChannelResult<JsonObject> = try {
        withTimeout(timeoutMillis) { outcome.await() }
    } catch (_: TimeoutCancellationException) {
        ChannelResult.refused("hub_unreachable", "detail" to "the hub did not close the $kind stream")
    }

    /**
     * The next bytes the hub sent; consuming half the window grants the hub more.
     *
     * @return The bytes, or null once the stream is over and nothing is left.
     */
    suspend fun read(): ByteArray? {
        val data = incoming.receiveCatching().getOrNull() ?: return null
        consumed += data.size
        if (consumed >= CLIENT_STREAM_CREDIT_BYTES / 2 && !isDone) {
            val grant = consumed.toInt()
            consumed = 0
            socket.sendText(ChannelFrames.credit(id, grant).toString())
        }
        return data
    }

    /**
     * Send bytes, no faster than the hub's credit, in frames of at most 64 KiB.
     *
     * @param data The bytes.
     * @return Ok, or `hub_unreachable` when the stream or the socket ended or no credit came in time.
     */
    suspend fun send(data: ByteArray): ChannelResult<Unit> {
        if (!hasBytes) return ChannelResult.refused("hub_unreachable", "detail" to "a $kind stream carries no bytes")
        var offset = 0
        while (offset < data.size) {
            val size = spendCredit(minOf(data.size - offset, CLIENT_WS_CHUNK_BYTES))
                ?: return ChannelResult.refused("hub_unreachable", "detail" to "the $kind stream has ended")
            val frame = ByteBuffer.allocate(CHANNEL_STREAM_ID_BYTES + size).putInt(id).put(data, offset, size).array()
            if (!socket.sendBytes(frame)) {
                return ChannelResult.refused(
                    "hub_unreachable",
                    "detail" to "the socket is gone",
                )
            }
            offset += size
        }
        return ChannelResult.Ok(Unit)
    }

    /** End the stream from this side; the hub sends no close back. */
    fun close() {
        if (!outcome.complete(ChannelResult.Ok(JsonObject(emptyMap())))) return
        incoming.close()
        isEnded.value = true
        socket.sendText(ChannelFrames.close(id).toString())
        onClosedHere(id)
    }

    internal fun takeBytes(data: ByteArray) {
        incoming.trySend(data)
    }

    internal fun takeCredit(bytes: Int) {
        credit.value += bytes.coerceAtLeast(0)
    }

    internal fun takeClose(code: String, params: JsonObject) {
        outcome.complete(if (code.isEmpty()) ChannelResult.Ok(params) else ChannelResult.Refused(code, params))
        incoming.close()
        isEnded.value = true
    }

    internal fun end() {
        outcome.complete(ChannelResult.refused("hub_unreachable", "detail" to "the hub socket closed"))
        incoming.close()
        isEnded.value = true
    }

    private suspend fun spendCredit(wanted: Int): Int? = try {
        withTimeout(CLIENT_WS_CREDIT_TIMEOUT_S * 1000) {
            creditLock.withLock {
                combine(credit, isEnded) { bytes, ended -> bytes > 0 || ended }.first { it }
                if (isDone) return@withLock null
                val size = minOf(wanted.toLong(), credit.value).toInt()
                credit.value -= size
                size
            }
        }
    } catch (_: TimeoutCancellationException) {
        null
    }
}
