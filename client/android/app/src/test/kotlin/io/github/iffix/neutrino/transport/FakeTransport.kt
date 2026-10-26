package io.github.iffix.neutrino.transport

import io.github.iffix.neutrino.TRANSPORT_RECORD_ACCEPT
import io.github.iffix.neutrino.TRANSPORT_RECORD_CLOSE
import io.github.iffix.neutrino.TransportMissingException
import java.io.BufferedInputStream
import java.io.DataInputStream
import java.io.IOException
import java.io.InputStream
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/**
 * A transport faked at its local channel: it takes the library's start, serves the control
 * connection's lines and every stream connection in memory, answers each command by [answer],
 * and records what the app wrote.
 *
 * @param isMissing Whether it plays a build with no transport library.
 */
class FakeTransport(private val isMissing: Boolean = false) :
    TransportLibrary,
    TransportDialer {
    /** The secret the library was started with. */
    @Volatile
    var secret = ""

    /** Every command the app sent, in order, with its fields. */
    val commands = LinkedBlockingQueue<JsonObject>()

    /** Every frame line the app wrote: the binding and the frame. */
    val frames = LinkedBlockingQueue<Pair<String, JsonObject>>()

    /** Every stream the app opened: its first line. */
    val opens = CopyOnWriteArrayList<JsonObject>()

    /** The answer to each command, as the transport writes it, without its `id`. */
    @Volatile
    var answer: (JsonObject) -> JsonObject = { JsonObject(emptyMap()) }

    /** How a stream the app opens is served, with its `open` record and the transport's end. */
    @Volatile
    var serve: (JsonObject, MemoryConnection) -> Unit = { _, end -> refuse(end, "kind_unknown") }

    @Volatile
    private var control: MemoryConnection? = null

    override fun start(directory: String, secret: String): String {
        if (isMissing) throw TransportMissingException("mobile.Mobile")
        this.secret = secret
        return "$directory/transport.sock"
    }

    override fun stop() = Unit

    override fun dial(): TransportConnection {
        val (app, transport) = MemoryConnection.pair()
        Thread { take(transport) }.apply { isDaemon = true }.start()
        return app
    }

    /**
     * Send one line on the control connection.
     *
     * @param line The line: an event or a frame.
     */
    fun send(line: JsonObject) {
        val end = waitFor { control } ?: throw IOException("the app opened no control connection")
        end.output.write((line.toString() + "\n").toByteArray())
    }

    /**
     * Send one event about a hub.
     *
     * @param name The event.
     * @param binding The hub.
     * @param fields Its other fields.
     */
    fun event(name: String, binding: String, vararg fields: Pair<String, Any>) {
        send(
            JsonObject(
                mapOf("event" to JsonPrimitive(name), "binding" to JsonPrimitive(binding)) +
                    fields.associate { (key, value) ->
                        key to when (value) {
                            is JsonElement -> value
                            is Number -> JsonPrimitive(value)
                            is Boolean -> JsonPrimitive(value)
                            else -> JsonPrimitive(value.toString())
                        }
                    },
            ),
        )
    }

    /**
     * Send one frame from the hub.
     *
     * @param binding The hub.
     * @param frame The frame.
     */
    fun frame(binding: String, frame: JsonObject) = send(
        buildJsonObject {
            put("frame", frame)
            put("binding", binding)
        },
    )

    /**
     * Open a `connect` stream to one entry on this fake, as the app's session would.
     *
     * @param entryId The entry.
     * @return The stream, or the refusal [serve] answered with.
     */
    fun connect(entryId: String): io.github.iffix.neutrino.channel.ChannelResult<TransportStream> {
        if (secret.isEmpty()) start("/data", "aa".repeat(32))
        val open = buildJsonObject {
            put("kind", "connect")
            put("id", entryId)
        }
        return TransportStream.open(this, secret, "b1", open)
    }

    /** Drop the control connection, as a transport that ended would. */
    fun dropControl() {
        control?.close()
        control = null
    }

    /**
     * The next command of a name the app sends.
     *
     * @param name The command.
     * @param seconds How long to wait.
     * @return Its line, or null when none came in time.
     */
    fun nextCommand(name: String, seconds: Long = 5): JsonObject? {
        val until = System.currentTimeMillis() + seconds * 1000
        while (System.currentTimeMillis() < until) {
            val line = commands.poll(50, TimeUnit.MILLISECONDS) ?: continue
            if (text(line, "command") == name) return line
        }
        return null
    }

    /**
     * The next frame of a type the app writes.
     *
     * @param type The frame's `type`.
     * @param seconds How long to wait.
     * @return The binding and the frame, or null when none came in time.
     */
    fun nextFrame(type: String, seconds: Long = 5): Pair<String, JsonObject>? {
        val until = System.currentTimeMillis() + seconds * 1000
        while (System.currentTimeMillis() < until) {
            val line = frames.poll(50, TimeUnit.MILLISECONDS) ?: continue
            if (text(line.second, "type") == type) return line
        }
        return null
    }

    private fun take(end: MemoryConnection) {
        val reader = BufferedInputStream(end.input)
        val first = readLine(reader) ?: return
        val line = Json.parseToJsonElement(first) as JsonObject
        if (text(line, "secret") != secret) {
            end.close()
            return
        }
        when (text(line, "op")) {
            "control" -> {
                control = end
                while (true) {
                    val next = readLine(reader) ?: break
                    val parsed = Json.parseToJsonElement(next) as JsonObject
                    val frame = parsed["frame"]
                    if (frame is JsonObject) {
                        frames.put(text(parsed, "binding") to frame)
                        continue
                    }
                    commands.put(parsed)
                    val reply = JsonObject(answer(parsed) + ("id" to JsonPrimitive(text(parsed, "id"))))
                    end.output.write((reply.toString() + "\n").toByteArray())
                }
            }

            "open" -> {
                opens.add(line)
                serve(line["open"] as? JsonObject ?: JsonObject(emptyMap()), end)
            }
        }
    }

    private fun readLine(input: InputStream): String? {
        val bytes = java.io.ByteArrayOutputStream()
        while (true) {
            val next = input.read()
            if (next < 0) return null
            if (next == '\n'.code) return String(bytes.toByteArray(), Charsets.UTF_8)
            bytes.write(next)
        }
    }

    private fun <T> waitFor(read: () -> T?): T? {
        val until = System.currentTimeMillis() + 5000
        while (System.currentTimeMillis() < until) {
            read()?.let { return it }
            Thread.sleep(10)
        }
        return null
    }

    companion object {
        /**
         * One field of a line as text.
         *
         * @param line The line.
         * @param name The field.
         * @return Its text, empty when absent.
         */
        fun text(line: JsonObject, name: String): String = (line[name] as? JsonPrimitive)?.content.orEmpty()

        /**
         * Accept a stream on the transport's end.
         *
         * @param end The transport's end.
         */
        fun accept(end: MemoryConnection) = TransportRecord.write(end.output, TRANSPORT_RECORD_ACCEPT, ByteArray(0))

        /**
         * Refuse a stream on the transport's end with a code.
         *
         * @param end The transport's end.
         * @param code The code.
         * @param params Its params.
         */
        fun refuse(end: MemoryConnection, code: String, params: JsonObject = JsonObject(emptyMap())) {
            val close = buildJsonObject {
                put("code", code)
                put("params", params)
            }
            TransportRecord.write(end.output, TRANSPORT_RECORD_CLOSE, close.toString().toByteArray())
            end.close()
        }

        /**
         * Accept a stream and send back every byte it carries until it ends.
         *
         * @param end The transport's end.
         */
        fun echo(end: MemoryConnection) {
            accept(end)
            val chunk = ByteArray(4096)
            while (true) {
                val count = end.input.read(chunk)
                if (count < 0) break
                end.output.write(chunk, 0, count)
            }
        }

        /**
         * The records the app writes on a stream, read on the transport's end.
         *
         * @param end The transport's end.
         * @return A reader of its records.
         */
        fun records(end: MemoryConnection): DataInputStream = DataInputStream(BufferedInputStream(end.input))
    }
}
