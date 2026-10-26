package io.github.iffix.neutrino.terminal

import io.github.iffix.neutrino.CLIENT_STREAM_KIND_SHELL
import io.github.iffix.neutrino.CLIENT_TERMINAL_CLEAR_MAX_MS
import io.github.iffix.neutrino.CLIENT_TERMINAL_CLEAR_QUIET_MS
import io.github.iffix.neutrino.CLIENT_TERMINAL_KEPT_BYTES
import io.github.iffix.neutrino.TRANSPORT_RECORD_CLOSE
import io.github.iffix.neutrino.TRANSPORT_RECORD_DATA
import io.github.iffix.neutrino.TRANSPORT_RECORD_RESIZE
import io.github.iffix.neutrino.channel.ChannelResult
import io.github.iffix.neutrino.channel.HubView
import io.github.iffix.neutrino.transport.TransportStream
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.util.UUID
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/**
 * Every terminal tab of the app, outliving the screen that draws them: the tabs follow the
 * session lists of the connected hubs, and each tab keeps its shell stream and its last output
 * so a new view can draw it again.
 *
 * A new shell is opened with a session id this phone makes, as the account picked on its
 * machine; a listed one is attached with `is_resumed`, its kept output first. A later size is a
 * `resize` record on the shell's stream; `persist` and `stop_session` are frames naming only the session.
 *
 * What the person types joins one queue per tab that one coroutine sends in order.
 *
 * @param opener One hub's terminal questions, by binding id, or null while it is not connected.
 * @param scope Where the shells' readers, the tabs' senders and the lists' follower run.
 * @param clock The time in milliseconds that Clear's dropping is measured by.
 */
class TerminalTabs(
    private val opener: (String) -> TerminalHub?,
    private val scope: CoroutineScope,
    private val clock: () -> Long = System::currentTimeMillis,
) {
    private val current = MutableStateFlow<List<TerminalTab>>(emptyList())
    private val selected = MutableStateFlow("")
    private val machine = MutableStateFlow<Pair<String, String>?>(null)
    private val account = MutableStateFlow("")
    private val streams = mutableMapOf<String, TransportStream>()
    private val outputs = mutableMapOf<String, ByteArrayOutputStream>()
    private val sizes = mutableMapOf<String, Pair<Int, Int>>()
    private val dismissed = mutableSetOf<String>()
    private val senders = mutableMapOf<String, Channel<ByteArray>>()
    private val drops = mutableMapOf<String, Drop>()
    private val dropping = MutableStateFlow<Set<String>>(emptySet())
    private var sink: ((String, ByteArray) -> Unit)? = null

    /** Every tab, in the order made. */
    val tabs: StateFlow<List<TerminalTab>> = current.asStateFlow()

    /** The tab shown, empty for none. */
    val active: StateFlow<String> = selected.asStateFlow()

    /** The machine a new terminal opens on, as binding id and device id, or null for none picked. */
    val picked: StateFlow<Pair<String, String>?> = machine.asStateFlow()

    /** The account a new terminal runs as on the picked machine, empty for its first enabled one. */
    val pickedAccount: StateFlow<String> = account.asStateFlow()

    /** The tabs whose Clear is still dropping what arrives. */
    val clearing: StateFlow<Set<String>> = dropping.asStateFlow()

    /**
     * Follow the hubs' session lists from now on.
     *
     * @param hubs Every hub's view.
     */
    fun follow(hubs: Flow<List<HubView>>) {
        scope.launch { hubs.collect { take(it) } }
    }

    /**
     * Take one round of the hubs' session lists.
     *
     * @param hubs Every hub's view.
     */
    fun take(hubs: List<HubView>) {
        val (listings, listedHubs) = TerminalSessionMerge.listed(hubs)
        val gone = synchronized(dismissed) {
            val listedIds = listings.map { it.session.sessionId }.toSet()
            dismissed.retainAll { id -> id in listedIds }
            dismissed.toSet()
        }
        current.update { TerminalSessionMerge.merge(it, listings, listedHubs, gone) }
        settleActive()
    }

    /**
     * Pick the machine a new terminal opens on.
     *
     * @param bindingId The hub.
     * @param deviceId The machine.
     */
    fun pick(bindingId: String, deviceId: String) {
        if (machine.value != bindingId to deviceId) account.value = ""
        machine.value = bindingId to deviceId
    }

    /**
     * Pick the account a new terminal runs as on the picked machine.
     *
     * @param name One of the machine's enabled accounts.
     */
    fun pickAccount(name: String) {
        account.value = name
    }

    /**
     * Show one tab; its stream attaches at the first size its view reports.
     *
     * @param sessionId The tab.
     */
    fun select(sessionId: String) {
        if (tab(sessionId) != null) selected.value = sessionId
    }

    /**
     * Make a tab for a new shell and show it; its shell opens at the first size the view reports.
     *
     * @param bindingId The hub.
     * @param deviceId The machine.
     * @param name The machine's name.
     * @param account The account the shell runs as, empty for the machine's first enabled one.
     * @return The tab's session id.
     */
    fun create(bindingId: String, deviceId: String, name: String, account: String = ""): String {
        val tab = TerminalTab(
            UUID.randomUUID().toString(),
            bindingId,
            deviceId,
            name,
            account = account,
            phase = TerminalPhase.CONNECTING,
        )
        current.update { it + tab }
        selected.value = tab.sessionId
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
            stream != null -> {
                val size = buildJsonObject {
                    put("cols", cols)
                    put("rows", rows)
                }
                scope.launch(Dispatchers.IO) { stream.write(TRANSPORT_RECORD_RESIZE, size.toString().toByteArray()) }
            }

            tab.phase != TerminalPhase.ENDED && !tab.isOpening -> attach(tab, cols, rows)
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
        if (synchronized(streams) { streams[sessionId] } == null) return
        sender(sessionId).trySend(bytes)
    }

    /**
     * Clear a tab: Ctrl+C goes to the shell after what was typed before it, the kept output is
     * dropped, and so is what arrives until the stream has been quiet for
     * [CLIENT_TERMINAL_CLEAR_QUIET_MS], for [CLIENT_TERMINAL_CLEAR_MAX_MS] at most, or until the
     * shell ends. A tab with no open shell takes no Clear.
     *
     * @param sessionId The tab.
     * @return Whether the Clear was taken; the tab is then in [clearing] until its dropping ends.
     */
    fun clear(sessionId: String): Boolean {
        if (synchronized(streams) { streams[sessionId] } == null) return false
        val drop = synchronized(outputs) {
            outputs.remove(sessionId)
            val now = clock()
            Drop(since = now, last = now).also { drops[sessionId] = it }
        }
        dropping.update { it + sessionId }
        input(sessionId, byteArrayOf(CTRL_C))
        scope.launch { endDrop(sessionId, drop) }
        return true
    }

    /**
     * Set whether a tab's session outlives every window and whether others list it; the tab
     * shows the new values at once, and the next state frame confirms them.
     *
     * @param sessionId The tab.
     * @param isPersistent Whether the session outlives every window.
     * @param isShared Whether every client with terminal rights on the machine lists it.
     */
    fun persist(sessionId: String, isPersistent: Boolean, isShared: Boolean) {
        val tab = tab(sessionId)?.takeIf { it.canPersist } ?: return
        change(sessionId) { it.copy(isPersistent = isPersistent, isShared = isShared, note = null) }
        val hub = opener(tab.bindingId) ?: return
        scope.launch {
            val result = hub.persist(sessionId, isPersistent, isShared)
            if (result is ChannelResult.Refused) change(sessionId) { it.copy(note = result) }
        }
    }

    /**
     * Close a tab: an ended tab goes, a persistent or shared session is ended on its machine
     * with `stop_session` and its tab goes once the machine agrees, and any other closes with
     * its stream.
     *
     * @param sessionId The tab.
     */
    fun close(sessionId: String) {
        val tab = tab(sessionId) ?: return
        if (tab.phase != TerminalPhase.ENDED && tab.isKept) {
            stopSession(tab)
        } else {
            remove(sessionId)
        }
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

    private fun stopSession(tab: TerminalTab) {
        val hub = opener(tab.bindingId)
        if (hub == null) {
            change(tab.sessionId) { it.copy(note = ChannelResult.refused("hub_unreachable")) }
            return
        }
        scope.launch {
            when (val result = hub.stopSession(tab.sessionId)) {
                is ChannelResult.Refused -> change(tab.sessionId) { it.copy(note = result) }
                is ChannelResult.Ok -> remove(tab.sessionId)
            }
        }
    }

    private fun remove(sessionId: String) {
        synchronized(dismissed) { dismissed += sessionId }
        synchronized(streams) { streams.remove(sessionId) }?.close()
        synchronized(outputs) {
            outputs.remove(sessionId)
            stopDropping(sessionId)
        }
        synchronized(senders) { senders.remove(sessionId) }?.close()
        val before = current.value.indexOfFirst { it.sessionId == sessionId }
        current.update { list -> list.filterNot { it.sessionId == sessionId } }
        if (selected.value == sessionId) {
            val left = current.value
            selected.value = left.getOrNull(before.coerceAtMost(left.lastIndex))?.sessionId.orEmpty()
        }
    }

    private fun settleActive() {
        val list = current.value
        if (list.none { it.sessionId == selected.value }) selected.value = list.firstOrNull()?.sessionId.orEmpty()
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
        val open = buildJsonObject {
            put("kind", CLIENT_STREAM_KIND_SHELL)
            put("device_id", tab.deviceId)
            put("cols", cols)
            put("rows", rows)
            put("account", tab.account)
            put("session_id", tab.sessionId)
            put("is_resumed", isResumed)
            put("is_shared", tab.isShared)
        }
        change(tab.sessionId) { it.copy(phase = TerminalPhase.CONNECTING, isOpening = true) }
        scope.launch(Dispatchers.IO) {
            when (val opened = hub.open(open)) {
                is ChannelResult.Refused -> change(tab.sessionId) {
                    it.copy(phase = TerminalPhase.DETACHED, note = opened, isOpening = false)
                }

                is ChannelResult.Ok -> {
                    if (isResumed) synchronized(outputs) { outputs.remove(tab.sessionId) }
                    synchronized(streams) { streams[tab.sessionId] = opened.value }
                    change(tab.sessionId) { it.copy(phase = TerminalPhase.OPEN, note = null, isOpening = false) }
                    read(tab.sessionId, opened.value)
                }
            }
        }
    }

    private fun read(sessionId: String, stream: TransportStream) {
        var result: ChannelResult<JsonObject>? = null
        try {
            while (true) {
                val record = stream.read() ?: break
                when (record.type) {
                    TRANSPORT_RECORD_DATA -> keep(sessionId, record.payload)

                    TRANSPORT_RECORD_CLOSE -> {
                        result = record.refusal ?: ChannelResult.Ok(record.json)
                        break
                    }
                }
            }
        } catch (_: IOException) {
            result = null
        }
        stream.close()
        synchronized(streams) { if (streams[sessionId] === stream) streams.remove(sessionId) }
        synchronized(outputs) { if (drops.containsKey(sessionId)) stopDropping(sessionId) }
        change(sessionId) { tab ->
            when {
                result is ChannelResult.Refused && result.code == "session_unknown" -> tab.copy(
                    phase = TerminalPhase.ENDED,
                    note = result,
                    isPersistent = false,
                    isShared = false,
                )

                result is ChannelResult.Refused -> tab.copy(phase = TerminalPhase.DETACHED, note = result)

                result == null -> tab.copy(phase = TerminalPhase.DETACHED, note = null)

                else -> tab.copy(
                    phase = if (tab.isKept) TerminalPhase.DETACHED else TerminalPhase.ENDED,
                    note = null,
                )
            }
        }
    }

    private fun keep(sessionId: String, bytes: ByteArray) {
        synchronized(outputs) {
            if (isDropped(sessionId)) return
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

    private fun isDropped(sessionId: String): Boolean {
        val drop = drops[sessionId] ?: return false
        val now = clock()
        if (now < drop.endsAt()) {
            drop.last = now
            return true
        }
        stopDropping(sessionId)
        return false
    }

    private suspend fun endDrop(sessionId: String, drop: Drop) {
        while (true) {
            val left = synchronized(outputs) {
                if (drops[sessionId] !== drop) return
                drop.endsAt() - clock()
            }
            if (left <= 0) break
            delay(left)
        }
        synchronized(outputs) { if (drops[sessionId] === drop) stopDropping(sessionId) }
    }

    private fun stopDropping(sessionId: String) {
        drops.remove(sessionId)
        dropping.update { it - sessionId }
    }

    private fun sender(sessionId: String): Channel<ByteArray> = synchronized(senders) {
        senders.getOrPut(sessionId) {
            Channel<ByteArray>(Channel.UNLIMITED).also { queue ->
                scope.launch(Dispatchers.IO) { send(sessionId, queue) }
            }
        }
    }

    private suspend fun send(sessionId: String, queue: Channel<ByteArray>) {
        for (bytes in queue) synchronized(streams) { streams[sessionId] }?.write(TRANSPORT_RECORD_DATA, bytes)
    }

    private fun tab(sessionId: String): TerminalTab? = current.value.firstOrNull { it.sessionId == sessionId }

    private fun change(sessionId: String, transform: (TerminalTab) -> TerminalTab) {
        current.update { list -> list.map { if (it.sessionId == sessionId) transform(it) else it } }
    }

    private class Drop(val since: Long, var last: Long) {
        fun endsAt(): Long = minOf(last + CLIENT_TERMINAL_CLEAR_QUIET_MS, since + CLIENT_TERMINAL_CLEAR_MAX_MS)
    }

    private companion object {
        const val CTRL_C: Byte = 0x03
    }
}
