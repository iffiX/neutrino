package io.github.iffix.neutrino.terminal

/**
 * The key row's modifiers held for the next key: a press on one holds it or lets it go, and the
 * next key, from the row or the keyboard, spends them all.
 *
 * @property isCtrl Whether Ctrl is held.
 * @property isShift Whether Shift is held.
 * @property isAlt Whether Alt is held.
 */
data class TerminalModifiers(val isCtrl: Boolean = false, val isShift: Boolean = false, val isAlt: Boolean = false) {
    /** xterm's modifier parameter: 1, plus 1 for Shift, 2 for Alt and 4 for Ctrl. */
    val xtermParameter: Int
        get() = 1 + (if (isShift) 1 else 0) + (if (isAlt) 2 else 0) + (if (isCtrl) 4 else 0)

    /**
     * Whether one key of the row shows pressed.
     *
     * @param key The key.
     * @return True for a modifier that is held.
     */
    fun isHeld(key: TerminalKey): Boolean = when (key) {
        TerminalKey.CTRL -> isCtrl
        TerminalKey.SHIFT -> isShift
        TerminalKey.ALT -> isAlt
        else -> false
    }

    /**
     * The modifiers after a press on one key of the row.
     *
     * @param key The key; a key that is no modifier changes nothing.
     * @return The modifiers with that one held or let go.
     */
    fun toggled(key: TerminalKey): TerminalModifiers = when (key) {
        TerminalKey.CTRL -> copy(isCtrl = !isCtrl)
        TerminalKey.SHIFT -> copy(isShift = !isShift)
        TerminalKey.ALT -> copy(isAlt = !isAlt)
        else -> this
    }
}
