package io.github.iffix.neutrino.remotedesktop

import io.github.iffix.neutrino.CLIENT_PLATFORM_OS_LINUX
import io.github.iffix.neutrino.RDP_ASCII_LAST
import io.github.iffix.neutrino.RDP_TYPE_PACE_MILLIS
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/**
 * The viewer's keys and text on their way to the core, with the key bar's modifiers held for one
 * key: Ctrl, Shift, Alt and Win stay down from their press until the next key or text is sent.
 * Every call joins one queue that one coroutine sends in order, and typed text goes one character
 * at a time, [RDP_TYPE_PACE_MILLIS] apart; text with any character outside ASCII goes to a Linux
 * host as a paste instead.
 *
 * @param core Where the keys and the text go.
 * @param platformOs The `platform_os` of the machine sharing the desktop, or empty when the entry
 *   names none.
 * @param scope Where the queue runs; it stops with the scope or on [close].
 * @param onHeld Called with the held modifiers each time they change.
 */
class RemoteDesktopInputSender(
    private val core: RemoteDesktopCore,
    private val platformOs: String,
    scope: CoroutineScope,
    private val onHeld: (Set<RemoteDesktopKey>) -> Unit,
) {
    private val queue = Channel<suspend () -> Unit>(Channel.UNLIMITED)

    /** The modifiers held for the next key. */
    var held: Set<RemoteDesktopKey> = emptySet()
        private set

    init {
        scope.launch { for (send in queue) send() }
    }

    /**
     * Press and release one key, then release the held modifiers.
     *
     * @param code RustDesk's name for the key.
     */
    fun press(code: String) {
        queue.trySend { sendPress(code) }
    }

    /**
     * A key of the key bar: a modifier is held or let go, any other key is pressed.
     *
     * @param key The key.
     */
    fun barKey(key: RemoteDesktopKey) {
        queue.trySend { sendBarKey(key) }
    }

    /**
     * Text the keyboard committed. A line break is Enter, a single letter or digit with a modifier
     * held is that key, and text with any character outside ASCII to a Linux host is put on its
     * clipboard and pasted with Shift+Insert; anything else is typed one character at a time.
     *
     * @param text The text.
     */
    fun type(text: String) {
        queue.trySend { sendText(text) }
    }

    /**
     * Put text on the remote machine's clipboard and press Ctrl+V there.
     *
     * @param text The text; nothing is sent when it is empty.
     */
    fun paste(text: String) {
        if (text.isEmpty()) return
        queue.trySend { sendPaste(text) }
    }

    /** Stop the queue: what is queued is still sent, later calls send nothing. */
    fun close() {
        queue.close()
    }

    private fun sendPress(code: String) {
        core.key(code, true)
        core.key(code, false)
        release()
    }

    private fun sendBarKey(key: RemoteDesktopKey) {
        when {
            !key.isModifier -> sendPress(key.code)

            key in held -> {
                core.key(key.code, false)
                hold(held - key)
            }

            else -> {
                core.key(key.code, true)
                hold(held + key)
            }
        }
    }

    private suspend fun sendText(text: String) {
        val code = text.singleOrNull()?.let { RemoteDesktopKey.codeOf(it) }
        when {
            text == "\n" -> sendPress(RemoteDesktopKey.ENTER)

            held.isNotEmpty() && code != null -> sendPress(code)

            platformOs == CLIENT_PLATFORM_OS_LINUX && text.any { it.code > RDP_ASCII_LAST } -> sendShiftInsert(text)

            else -> {
                var start = 0
                while (start < text.length) {
                    if (start > 0) delay(RDP_TYPE_PACE_MILLIS)
                    val end = text.offsetByCodePoints(start, 1)
                    core.type(text.substring(start, end))
                    start = end
                }
                release()
            }
        }
    }

    private fun sendPaste(text: String) {
        core.clipboard(text)
        core.key(RemoteDesktopKey.CTRL.code, true)
        core.key(RemoteDesktopKey.PASTE, true)
        core.key(RemoteDesktopKey.PASTE, false)
        core.key(RemoteDesktopKey.CTRL.code, false)
        release()
    }

    private fun sendShiftInsert(text: String) {
        release()
        core.clipboard(text)
        core.key(RemoteDesktopKey.SHIFT.code, true)
        core.key(RemoteDesktopKey.INSERT, true)
        core.key(RemoteDesktopKey.INSERT, false)
        core.key(RemoteDesktopKey.SHIFT.code, false)
    }

    private fun release() {
        for (key in held) core.key(key.code, false)
        hold(emptySet())
    }

    private fun hold(keys: Set<RemoteDesktopKey>) {
        if (keys == held) return
        held = keys
        onHeld(keys)
    }
}
