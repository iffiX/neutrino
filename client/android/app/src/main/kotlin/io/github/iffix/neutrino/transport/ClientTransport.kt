package io.github.iffix.neutrino.transport

import android.util.Log
import io.github.iffix.neutrino.CLIENT_LOG_TAG
import io.github.iffix.neutrino.TRANSPORT_COMMAND_TIMEOUT_S
import io.github.iffix.neutrino.TRANSPORT_RECONNECT_MILLIS
import io.github.iffix.neutrino.TRANSPORT_SECRET_BYTES
import io.github.iffix.neutrino.TransportMissingException
import io.github.iffix.neutrino.channel.ChannelResult
import java.io.BufferedReader
import java.io.IOException
import java.io.InputStreamReader
import java.security.SecureRandom
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicLong
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.channels.ReceiveChannel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/**
 * The client's end of the transport's local channel: the library started once in the app's
 * process, its one control connection with the commands, the events and the frames of every hub,
 * and the streams opened each on a connection of its own. A control connection that drops is
 * opened again, and every hub is then told [TransportEvent.Restarted] so it dials again.
 *
 * @param library The transport the app embeds.
 * @param directory The app's own data directory, where the library makes its local socket.
 * @param dialerOf Opens connections to the local socket at the path the library started on.
 * @param scope Where the control connection's reader runs.
 * @param secret The 64 hex characters every local connection opens with, made afresh at each start.
 * @param log Writes one line to the app's log.
 */
class ClientTransport(
    private val library: TransportLibrary,
    private val directory: String,
    private val dialerOf: (String) -> TransportDialer,
    private val scope: CoroutineScope,
    private val secret: String = freshSecret(),
    private val log: (String) -> Unit = { Log.i(CLIENT_LOG_TAG, it) },
) {
    private val subscribers = ConcurrentHashMap<String, Channel<TransportEvent>>()
    private val pending = ConcurrentHashMap<String, CompletableDeferred<JsonObject>>()
    private val ids = AtomicLong()
    private val control = MutableStateFlow<Control?>(null)
    private val ends = MutableSharedFlow<TransportForwardEnd>(extraBufferCapacity = FORWARD_ENDS_HELD)
    private var job: Job? = null

    @Volatile
    private var dialer: TransportDialer? = null

    @Volatile
    private var failure: ChannelResult.Refused? = null

    /** Every forward's listener that could not start or stopped. */
    val forwardEnds: SharedFlow<TransportForwardEnd> = ends.asSharedFlow()

    /** Start the library and keep its control connection open until [stop]. */
    fun start() {
        if (job != null) return
        job = scope.launch(Dispatchers.IO) { run() }
    }

    /** Stop the library: every session and every forward ends. */
    fun stop() {
        job?.cancel()
        job = null
        control.value?.close()
        library.stop()
    }

    /**
     * Take one hub's events from now on; a second subscription for the same hub replaces the first.
     *
     * @param binding The hub, by the name its `dial` gives.
     * @return Its events, in order.
     */
    fun subscribe(binding: String): ReceiveChannel<TransportEvent> {
        val events = Channel<TransportEvent>(Channel.UNLIMITED)
        subscribers.put(binding, events)?.close()
        return events
    }

    /**
     * Stop taking one hub's events.
     *
     * @param binding The hub.
     */
    fun unsubscribe(binding: String) {
        subscribers.remove(binding)?.close()
    }

    /**
     * Send one command and wait for the transport's answer.
     *
     * @param name The command, such as `dial` or `forward_start`.
     * @param fields Its fields.
     * @param timeoutMillis How long the answer may take.
     * @return The answer; its `{code, params}` as the refusal; `transport_missing` in a build with
     *   no transport; `hub_unreachable {detail}` while the transport does not answer.
     */
    suspend fun command(
        name: String,
        fields: JsonObject,
        timeoutMillis: Long = TRANSPORT_COMMAND_TIMEOUT_S * 1000,
    ): ChannelResult<JsonObject> {
        failure?.let { return it }
        val live = withTimeoutOrNull(timeoutMillis) { control.first { it != null } }
            ?: return failure ?: ChannelResult.refused("hub_unreachable", "detail" to "the transport does not answer")
        val id = "c${ids.incrementAndGet()}"
        val answer = CompletableDeferred<JsonObject>()
        pending[id] = answer
        val line = JsonObject(fields + mapOf("id" to JsonPrimitive(id), "command" to JsonPrimitive(name)))
        if (!live.write(line)) {
            pending.remove(id)
            return ChannelResult.refused("hub_unreachable", "detail" to "the transport is gone")
        }
        val got = withTimeoutOrNull(timeoutMillis) { answer.await() }
        pending.remove(id)
        got ?: return ChannelResult.refused("hub_unreachable", "detail" to "the transport did not answer $name")
        val code = (got["code"] as? JsonPrimitive)?.content.orEmpty()
        if (code.isNotEmpty()) {
            return ChannelResult.Refused(
                code,
                got["params"] as? JsonObject ?: JsonObject(emptyMap()),
            )
        }
        return ChannelResult.Ok(got)
    }

    /**
     * Write one frame on a hub's control stream.
     *
     * @param binding The hub.
     * @param frame The frame, with its `type`.
     * @return False while the transport has no control connection.
     */
    fun frame(binding: String, frame: JsonObject): Boolean {
        val line = buildJsonObject {
            put("frame", frame)
            put("binding", binding)
        }
        return control.value?.write(line) ?: false
    }

    /**
     * Open one stream on a hub's session, on a local connection of its own. Blocks until the hub answers.
     *
     * @param binding The hub.
     * @param open The stream's `open` record, `{kind, ...args}`.
     * @return The stream, or the refusal: the hub's, `transport_missing`, or `hub_unreachable`.
     */
    fun open(binding: String, open: JsonObject): ChannelResult<TransportStream> {
        failure?.let { return it }
        val started =
            dialer ?: return ChannelResult.refused("hub_unreachable", "detail" to "the transport has not started")
        return TransportStream.open(started, secret, binding, open)
    }

    private suspend fun run() {
        val started = try {
            dialerOf(library.start(directory, secret))
        } catch (error: TransportMissingException) {
            failure = ChannelResult.refused("transport_missing")
            log("this build carries no transport: ${error.message}")
            return
        } catch (error: IOException) {
            failure = ChannelResult.refused("transport_failed", "detail" to (error.message ?: "IOException"))
            log("the transport did not start: ${error.message}")
            return
        }
        dialer = started
        var isFirst = true
        while (scope.isActive) {
            val live = try {
                Control(started.dial()).also {
                    it.write(
                        buildJsonObject {
                            put("secret", secret)
                            put("op", "control")
                        },
                    )
                }
            } catch (error: IOException) {
                log("the transport's local channel did not open: ${error.message}")
                delay(TRANSPORT_RECONNECT_MILLIS)
                continue
            }
            control.value = live
            if (!isFirst) subscribers.values.forEach { it.trySend(TransportEvent.Restarted) }
            isFirst = false
            live.readUntilEnd(::take)
            control.value = null
            val gone = pending.values.toList()
            pending.clear()
            gone.forEach { it.complete(GONE) }
            log("the transport's local channel dropped; it opens again")
            delay(TRANSPORT_RECONNECT_MILLIS)
        }
    }

    private fun take(line: JsonObject) {
        val binding = text(line, "binding")
        val frame = line["frame"]
        if (frame is JsonObject) {
            route(binding, TransportEvent.Frame(frame))
            return
        }
        when (text(line, "event")) {
            "session_open" -> route(
                binding,
                TransportEvent.SessionOpen(
                    text(line, "address"),
                    text(line, "path"),
                    text(line, "handshake_ms").toDoubleOrNull()?.toLong() ?: 0,
                ),
            )

            "round_end" -> route(
                binding,
                TransportEvent.RoundEnd(refusalOf(line), text(line, "next_round_s").toDoubleOrNull()?.toLong() ?: 0),
            )

            "session_end" -> route(binding, TransportEvent.SessionEnd(refusalOf(line)))

            "forward_end" -> ends.tryEmit(
                TransportForwardEnd(text(line, "listen"), text(line, "protocol").ifEmpty { "tcp" }, refusalOf(line)),
            )

            "" -> if ("question" !in line) pending.remove(text(line, "id"))?.complete(line)

            else -> Unit
        }
    }

    private fun route(binding: String, event: TransportEvent) {
        subscribers[binding]?.trySend(event)
    }

    private fun refusalOf(line: JsonObject): ChannelResult.Refused? {
        val code = text(line, "code")
        if (code.isEmpty()) return null
        return ChannelResult.Refused(code, line["params"] as? JsonObject ?: JsonObject(emptyMap()))
    }

    private fun text(line: JsonObject, name: String): String = (line[name] as? JsonPrimitive)?.content.orEmpty()

    /** One control connection: JSON lines both ways. */
    private class Control(private val connection: TransportConnection) {
        private val writeLock = Any()

        fun write(line: JsonObject): Boolean = synchronized(writeLock) {
            try {
                connection.output.write((line.toString() + "\n").toByteArray(Charsets.UTF_8))
                connection.output.flush()
                true
            } catch (_: IOException) {
                false
            }
        }

        fun readUntilEnd(onLine: (JsonObject) -> Unit) {
            val reader = BufferedReader(InputStreamReader(connection.input, Charsets.UTF_8))
            try {
                while (true) {
                    val text = reader.readLine() ?: break
                    val line = try {
                        Json.parseToJsonElement(text) as? JsonObject
                    } catch (_: SerializationException) {
                        null
                    } ?: continue
                    onLine(line)
                }
            } catch (_: IOException) {
                // The connection ended; the caller opens another.
            } finally {
                close()
            }
        }

        fun close() {
            try {
                connection.close()
            } catch (_: IOException) {
                // Already closed.
            }
        }
    }

    companion object {
        private const val FORWARD_ENDS_HELD = 64
        private val GONE = buildJsonObject {
            put("code", "hub_unreachable")
            put("params", buildJsonObject { put("detail", "the transport's local channel dropped") })
        }

        /**
         * A fresh secret for the local channel.
         *
         * @return 32 random bytes in lowercase hex.
         */
        fun freshSecret(): String {
            val bytes = ByteArray(TRANSPORT_SECRET_BYTES)
            SecureRandom().nextBytes(bytes)
            return bytes.joinToString("") { "%02x".format(it) }
        }
    }
}
