package io.github.iffix.neutrino.remotedesktop

/**
 * The viewer's keys and text on their way to the core, with the key bar's modifiers held for one
 * key: Ctrl, Shift, Alt and Win stay down from their press until the next key or text is sent.
 *
 * @param core Where the keys and the text go.
 * @param onHeld Called with the held modifiers each time they change.
 */
class RemoteDesktopInputSender(
    private val core: RemoteDesktopCore,
    private val onHeld: (Set<RemoteDesktopKey>) -> Unit,
) {
    /** The modifiers held for the next key. */
    var held: Set<RemoteDesktopKey> = emptySet()
        private set

    /**
     * Press and release one key, then release the held modifiers.
     *
     * @param code RustDesk's name for the key.
     */
    fun press(code: String) {
        core.key(code, true)
        core.key(code, false)
        release()
    }

    /**
     * A key of the key bar: a modifier is held or let go, any other key is pressed.
     *
     * @param key The key.
     */
    fun barKey(key: RemoteDesktopKey) {
        when {
            !key.isModifier -> press(key.code)

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

    /**
     * Text the keyboard committed. A line break is Enter, and a single letter or digit with a
     * modifier held is that key; anything else is sent as text.
     *
     * @param text The text.
     */
    fun type(text: String) {
        val code = text.singleOrNull()?.let { RemoteDesktopKey.codeOf(it) }
        when {
            text == "\n" -> press(RemoteDesktopKey.ENTER)

            held.isNotEmpty() && code != null -> press(code)

            else -> {
                core.type(text)
                release()
            }
        }
    }

    /**
     * Put text on the remote machine's clipboard and press Ctrl+V there.
     *
     * @param text The text; nothing is sent when it is empty.
     */
    fun paste(text: String) {
        if (text.isEmpty()) return
        core.clipboard(text)
        core.key(RemoteDesktopKey.CTRL.code, true)
        core.key(RemoteDesktopKey.PASTE, true)
        core.key(RemoteDesktopKey.PASTE, false)
        core.key(RemoteDesktopKey.CTRL.code, false)
        release()
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
