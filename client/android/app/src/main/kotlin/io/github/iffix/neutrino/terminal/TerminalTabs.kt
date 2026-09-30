package io.github.iffix.neutrino.terminal

import android.content.SharedPreferences
import androidx.core.content.edit
import io.github.iffix.neutrino.CLIENT_STREAM_KIND_COMMAND
import io.github.iffix.neutrino.CLIENT_STREAM_KIND_SHELL
import io.github.iffix.neutrino.CLIENT_STREAM_TIMEOUT_S
import io.github.iffix.neutrino.CLIENT_TERMINAL_KEPT_BYTES
import io.github.iffix.neutrino.CLIENT_TERMINAL_SESSIONS_KEY
import io.github.iffix.neutrino.channel.ChannelFrames
import io.github.iffix.neutrino.channel.ChannelResult
import io.github.iffix.neutrino.channel.ChannelStream
import java.io.ByteArrayOutputStream
import java.util.UUID
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.serialization.SerializationException
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json

/**
 * Every terminal tab of the app, outliving the screen that draws them: each tab's shell stream,
 * the last output it wrote so a new view can draw it again, and the kept sessions, restored
 * detached on the next start.
 *
 * A shell is opened with a session id this phone makes; a kept one is attached again with
 * `is_resumed`. `persist` and `stop_session` name the machine and the session.
 *
 * @param preferences Where the kept sessions are listed.
 * @param opener The stream opener of one hub, by binding id, or null while it is not connected.
 * @param scope Where the shells' readers run.
 */
class TerminalTabs(
    private val preferences: SharedPreferences,
    private val opener: (String) -> StreamOpener?,
    private val scope: CoroutineScope,
) {
    private val json = Json { ignoreUnknownKeys = true }
    private val current = MutableStateFlow(restore())
    private val streams = mutableMapOf<String, ChannelStream>()
    private val outputs = mutableMapOf<String, ByteArrayOutputStream>()
    private val sizes = mutableMapOf<String, Pair<Int, Int>>()
    private var sink: ((String, ByteArray) -> Unit)? = null

    /** Every tab, in the order opened. */
    val tabs: StateFlow<List<TerminalTab>> = current.asStateFlow()

    /**
     * Make a tab for a new shell; its shell opens at the first size the view reports.
     *
     * @param bindingId The hub.
     * @param deviceId The machine.
     * @param name The machine's name.
     * @return The tab's session id.
     */
    fun create(bindingId: String, deviceId: String, name: String): String {
        val tab = TerminalTab(UUID.randomUUID().toString(), bindingId, deviceId, name, phase = TerminalPhase.CONNECTING)
        current.update { it + tab }
        return tab.sessionId
    }

    /**
     * Take a view's size: the first opens or attaches the shell, a later one resizes it.
     *
     * @param sessionId The tab.
     * @param cols The width in columns.
     * @param rows The height in rows.
     */
    fun sized(sessionId: String, cols: Int, rows: Int) {
        val tab = tab(sessionId) ?: return
        synchronized(sizes) { sizes[sessionId] = cols to rows }
        val stream = synchronized(streams) { streams[sessionId] }
        when {
            stream != null && !stream.isDone -> command(
                tab,
                "resize",
                "shell" to stream.id,
                "cols" to cols,
                "rows" to rows,
            )

            tab.phase != TerminalPhase.ENDED -> attach(tab, cols, rows)
        }
    }

    /**
     * Attach a detached tab's shell again at its last size, as once its hub answers again.
     *
     * @param sessionId The tab.
     */
    fun reattach(sessionId: String) {
        val tab = tab(sessionId)?.takeIf { it.phase == TerminalPhase.DETACHED } ?: return
        val (cols, rows) = synchronized(sizes) { sizes[sessionId] } ?: return
        attach(tab, cols, rows)
    }

    /**
     * Send what the person typed.
     *
     * @param sessionId The tab.
     * @param bytes The bytes.
     */
    fun input(sessionId: String, bytes: ByteArray) {
        val stream = synchronized(streams) { streams[sessionId] } ?: return
        scope.launch { stream.send(bytes) }
    }

    /**
     * Keep, or stop keeping, a tab's shell when its stream closes.
     *
     * @param sessionId The tab.
     * @param isPersistent The wish.
     */
    fun setPersistent(sessionId: String, isPersistent: Boolean) {
        val tab = tab(sessionId) ?: return
        change(sessionId) { it.copy(isPersistent = isPersistent) }
        command(tab, "persist", "device_id" to tab.deviceId, "session_id" to sessionId, "is_persistent" to isPersistent)
    }

    /**
     * Close a tab: a kept shell is ended on its machine, any other closes with its stream.
     *
     * @param sessionId The tab.
     */
    fun close(sessionId: String) {
        val tab = tab(sessionId) ?: return
        if (tab.isPersistent) command(tab, "stop_session", "device_id" to tab.deviceId, "session_id" to sessionId)
        synchronized(streams) { streams.remove(sessionId) }?.close()
        synchronized(outputs) { outputs.remove(sessionId) }
        current.update { list -> list.filterNot { it.sessionId == sessionId } }
        keep()
    }

    /**
     * Watch every tab's output: what each wrote so far first, then what it writes.
     *
     * @param onOutput Called with a tab and its bytes, on the reader's thread; null stops watching.
     */
    fun watch(onOutput: ((String, ByteArray) -> Unit)?) {
        synchronized(outputs) {
            sink = onOutput
            if (onOutput != null) outputs.forEach { (id, bytes) -> onOutput(id, bytes.toByteArray()) }
        }
    }

    private fun attach(tab: TerminalTab, cols: Int, rows: Int) {
        val hub = opener(tab.bindingId)
        if (hub == null) {
            change(tab.sessionId) {
                it.copy(phase = TerminalPhase.DETACHED, note = ChannelResult.refused("hub_unreachable"))
            }
            return
        }
        val isResumed = tab.phase == TerminalPhase.DETACHED
        val args = ChannelFrames.args(
            "device_id" to tab.deviceId,
            "cols" to cols,
            "rows" to rows,
            "session_id" to tab.sessionId,
            "is_resumed" to isResumed,
        )
        when (val opened = hub.open(CLIENT_STREAM_KIND_SHELL, args, true)) {
            is ChannelResult.Refused -> change(tab.sessionId) { it.copy(phase = TerminalPhase.DETACHED, note = opened) }

            is ChannelResult.Ok -> {
                if (isResumed) synchronized(outputs) { outputs.remove(tab.sessionId) }
                synchronized(streams) { streams[tab.sessionId] = opened.value }
                change(tab.sessionId) { it.copy(phase = TerminalPhase.OPEN, note = null) }
                scope.launch { read(tab.sessionId, opened.value) }
            }
        }
    }

    private suspend fun read(sessionId: String, stream: ChannelStream) {
        while (true) {
            val bytes = stream.read() ?: break
            synchronized(outputs) {
                val kept = outputs.getOrPut(sessionId) { ByteArrayOutputStream() }
                kept.write(bytes)
                if (kept.size() > CLIENT_TERMINAL_KEPT_BYTES) {
                    val tail = kept.toByteArray().takeLast(CLIENT_TERMINAL_KEPT_BYTES).toByteArray()
                    kept.reset()
                    kept.write(tail)
                }
                sink?.invoke(sessionId, bytes)
            }
        }
        synchronized(streams) { if (streams[sessionId] === stream) streams.remove(sessionId) }
        val result = stream.awaitClose(CLIENT_STREAM_TIMEOUT_S * 1000)
        change(sessionId) { tab ->
            when {
                result is ChannelResult.Refused && result.code == "session_unknown" -> tab.copy(
                    phase = TerminalPhase.ENDED,
                    note = result,
                )

                result is ChannelResult.Refused -> tab.copy(phase = TerminalPhase.DETACHED, note = result)

                else -> tab.copy(
                    phase = if (tab.isPersistent) TerminalPhase.DETACHED else TerminalPhase.ENDED,
                    note = null,
                )
            }
        }
    }

    private fun command(tab: TerminalTab, verb: String, vararg args: Pair<String, Any>) {
        val hub = opener(tab.bindingId) ?: return
        val all = ChannelFrames.args("module" to "agent", "verb" to verb, *args)
        val opened = hub.open(CLIENT_STREAM_KIND_COMMAND, all, false) as? ChannelResult.Ok ?: return
        scope.launch {
            val result = opened.value.awaitClose(CLIENT_STREAM_TIMEOUT_S * 1000)
            if (result is ChannelResult.Refused && verb != "resize") change(tab.sessionId) { it.copy(note = result) }
        }
    }

    private fun tab(sessionId: String): TerminalTab? = current.value.firstOrNull { it.sessionId == sessionId }

    private fun change(sessionId: String, transform: (TerminalTab) -> TerminalTab) {
        current.update { list -> list.map { if (it.sessionId == sessionId) transform(it) else it } }
        keep()
    }

    private fun keep() {
        val kept = current.value.filter { it.isPersistent }
        preferences.edit {
            putString(CLIENT_TERMINAL_SESSIONS_KEY, json.encodeToString(ListSerializer(TerminalTab.serializer()), kept))
        }
    }

    private fun restore(): List<TerminalTab> {
        val text = preferences.getString(CLIENT_TERMINAL_SESSIONS_KEY, null) ?: return emptyList()
        return try {
            json.decodeFromString(ListSerializer(TerminalTab.serializer()), text)
        } catch (_: SerializationException) {
            emptyList()
        } catch (_: IllegalArgumentException) {
            emptyList()
        }
    }
}
